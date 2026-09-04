# NOX Hummer H-200 LCD - USB Protocol Capture Plan

## Objective
Reverse engineer the USB HID protocol of the NOX Hummer H-200 LCD display to create a native Linux driver/daemon.

## Current Status (updated 2026-09-04, round 3 — **protocol decoded**)

> **The protocol is documented in [`PROTOCOL.md`](PROTOCOL.md); the capture rig
> and its pitfalls are in [`METHOD.md`](METHOD.md).** Everything in the
> "Blocked" section below was resolved in round 3 — see those two documents
> first. [`FINDINGS_CAPTURE.md`](FINDINGS_CAPTURE.md) is kept as the round-2
> investigation history (with corrections marked).

Round 3 outcome:
- USBPcap uninstalled → the guest's HID stack recovered; `hid_enumerate()`
  returns the H-200 normally (the round-2 "app skips the device" conclusion was
  a test bug, see `METHOD.md`).
- A logging `hidapi.dll` proxy + a fake `HWiNFO32.dll` (`tools/windows-proxy/`)
  made the app talk to the real device with **sensor values chosen by us**, so
  every field of the `0x20` frame is confirmed, not inferred.
- Remaining work: implement and validate the Linux daemon against the hardware.

### Completed ✅
- Hardware identification (VID:PID = 2E3C:0A12, KIMTECH Tuner)
- HID Report Descriptor extracted (128 bytes, vendor-defined)
- Windows VM created with SSH access
- USBPcap 1.5.4.0 installed in VM
- **USB passthrough FIXED** (udev rule, see below)
- **First live captures obtained** (30 Hz auto-streaming of the display)
- Input report format decoded (device → host)
- Windows app disassembled: hidapi IAT mapped, `recognize()` and `sendDataToHIDDevice()` command builders decoded
- **`recognize()` call sites fully traced**: one-shot `hid_enumerate(0,0)` loop at app startup (filter: `serial_number != NULL`) + one UI handler; **no hotplug handling exists** in the app
- **hidapi filter decoded**: compares a device property to `"HIDClass"`; live P/Invoke test proves the H-200 is **absent** from `hid_enumerate` results when its HID interface has no `Service` bound
- QMP hotplumbing built and verified (device_del/device_add on emulated xhci; PnP GONE→OK)
- USBPcapCMD quoting bug found and fixed (argument arrays, not escaped strings)

### Blocked 🔴
- **VM USB stack is broken for the H-200**: after the QMP hotplug experiments the
  device's HID interface comes up with PnP status "OK" but **hidclass never binds**
  (no `Service` in registry, no `GET HID REPORT DESCRIPTOR` on the bus, no
  streaming). Failed fixes: QMP re-add, `pnputil /remove-device`, full reboot,
  **real host power cycle** (`authorized=0/1`).
- **USBPcap service is unstoppable** (even on fresh boot) and produces 24-byte
  captures — its filter driver is the prime suspect for wedging the device stack.
- **App HID writes never captured**: root cause now identified — the app only
  enumerates once, at startup, and skips the device (see above). The `0x10`
  handshake / `0x20` reports have not been seen in any capture.

### Next (see FINDINGS_CAPTURE.md §7 for details)
1. Uninstall USBPcap in VM → reboot → check if device streams again (isolates the
   filter driver).
2. If healthy: run the winning sequence — device fully ready (registry `Service`
   present) → start capture → kill app → start app fresh → capture the handshake.
3. Fallback capture path if USBPcap stays broken: USB/IP + host-side usbmon.
4. If the VM path stays broken: per agreement, **abandon the VM** and drive the
   device directly from the host (it is fully accessible there: send candidate
   OUT reports, watch the 6-byte IN stream + the LCD).

## Device Identification

| Property | Value |
|---|---|
| VID:PID | 2E3C:0A12 |
| Interface | HID, 1 endpoint (IN 0x81) |
| Report descriptor | 128 bytes, vendor-defined |
| Behavior | Auto-cycles metrics (CPU → GPU → RPM), ~22 refreshes each; 6-byte IN reports @ ~30 ms |

## Routes Identified

### Host (Linux, H200 box)
| Item | Value |
|---|---|
| USB location | Bus 001, Port 11 → sysfs `1-11` |
| Host device node | `/dev/bus/usb/001/005` (device number changes on replug) |
| Sysfs | `/sys/bus/usb/devices/1-11` (interface `1-11:1.0`) |
| Driver state on host | unbound (`[none]`) — device is exclusively grabbed by QEMU (fd 24 of qemu pid) |
| Udev rule | `/etc/udev/rules.d/70-hummer-h200-udev.rules` |

Udev rule (fix for "cannot open /dev/bus/usb" from non-root QEMU):
```
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="2e3c", ATTRS{idProduct}=="0a12", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="2e3c", ATTR{idProduct}=="0a12", MODE="0666"
```
Apply: `sudo udevadm control --reload-rules && sudo udevadm trigger`, then restart QEMU.

### VM (Windows 10)
| Item | Value |
|---|---|
| QEMU device | `-device qemu-xhci -device usb-host,hostbus=1,hostport=11` (via `start-windows-vm.sh`) |
| USB bus/device in VM | bus 1, addr 2 → USBPcap device id **`1.2.0`** (`1.1.0` is the qemu-xhci tablet) |
| PnP instance (USB) | `USB\VID_2E3C&PID_0A12\103E3A6D05A7` (Status OK) |
| PnP instance (HID) | `HID\VID_2E3C&PID_0A12\6&DB5E56B&0&0000` (Status OK) |
| Legacy instances (stale) | `USB\...\5&134707B&0&5`, `HID\...\6&34FB57CB&0&0000` (Unknown) |
| USBPcap interface | **`\\.\USBPcap1`** (hub containing the device) |
| Windows driver stack | hidusb + hidclass (no vendor driver) |

## Capture Setup

USBPcap CLI (no GUI needed):
```
"C:\Program Files\USBPcap\USBPcapCMD.exe" -d \\.\USBPcap1 -A --inject-descriptors -o <out.pcapng>
```
- `-A` = all endpoints. `--inject-descriptors` prepends descriptor dumps (711 B baseline = descriptors only, no live traffic).
- The USBPcap service must be **Running**; after VM reboot the service starts with the device present and captures work.
- If a capture contains only 711 B: the device was (re)grabbed by QEMU after the service bound — reboot the VM or restart the service **after** QEMU grabbed the device.

Analyze on host: `tshark -r <pcapng> -Y "usb" -T fields -e frame.number -e usbpid.device_address -e usbpid.endpoint -e usbhid.report` (tshark 4.2.2 installed).

## Capture Results

| File | Size | Frames | Content |
|---|---|---|---|
| `captures/h200_win_20260904_120457.pcapng` | 18,270 B | 388 / ~25 s | Device auto-streaming only (best sample) |
| `captures/h200_hotplug_20260904_121748.pcapng` | 11,265 B | — | PnP disable/enable cycle + streaming |
| `captures/h200_app_20260904_124447.pcapng` | 1,351 B | 24 | App start: SET_IDLE (open) + 3× string reads (enumerate), **no writes** |

### Decoded IN reports (device → host, EP 0x81, 6 bytes, ~30 ms)
Layout `B0 B1 B2 B3 B4 B5`:
- `B0` ≈ 0x00 (one 0x01 seen)
- `B1` low nibble always 0xF, high nibble varies
- `B2` slow sawtooth (rises, falls) — likely metric value/level
- `B3` LCD segment patterns: 0xAA, 0x55, 0x2A, 0xFF, 0x7F, 0xD5
- `B4` fast sawtooth countdown — refresh/blink counter
- `B5` always 0x00

This stream is the **device's internal display state** (it drives its own LCD from the values it holds). The app's job is to feed it sensor values.

## Windows App Analysis (`Hummer_Digital.exe`, PE32, ImageBase 0x400000)

App location in VM: `C:\Program Files (x86)\Hummer_Digital\Hummer_Digital.exe`
- Single instance; auto-starts via Task Scheduler `DeviceMonitorStartTask`
- Uses local `hidapi.dll` (pre-0.9: SetupAPI + `CreateFile` + `ReadFile`/`WriteFile`, no `HidD_*`)
- Full disassembly: `/tmp/opencode/hummer_disasm.txt`, `/tmp/opencode/hidapi_disasm.txt`

### hidapi IAT (VA / thunk)
| Import | IAT VA | Thunk |
|---|---|---|
| hid_free_enumeration | 0x425010 | 0x41bf54 |
| hid_open_path | 0x425014 | 0x41bf5a |
| hid_enumerate | 0x425018 | 0x41bf4e |
| hid_close | 0x42501c | 0x41bf78 |
| hid_error | 0x425020 | 0x41bf72 |
| hid_set_nonblocking | 0x425024 | 0x41bf6c |
| hid_read | 0x425028 | 0x41bf66 |
| hid_write | 0x42502c | 0x41bf60 |

`hid_write` call sites: RVA 0x1cdc7 (VA 0x409dc7) and RVA 0x211a2 (VA 0x4101a2).

### `HIDDevicesManager::recognize` (VA 0x409cd0; name string at 0x426650)
Handshake on (re)connect:
1. `hid_open_path`
2. `hid_write(dev, buf, 0x41)` where `buf[0]=0x10, buf[1]=0x01`, rest 0x00
3. `hid_read(dev, buf, 0x41)` → parses firmware version, string `"%1.%2"`
- Error strings: "Write data to device fail: %1, device path: %2!", "Read HID device data fail: %1, device path: %2!"

### `sendDataToHIDDevice` (builder at ~0x410000, write at 0x4101a2)
Periodic sensor push — 64-byte output report:
```
off 0: 0x20            ; report/command ID
off 1: type/metric flag
off 2: mode
off 3: flag (jump table)
off 4: 0x00
off 5-6: value A (hi, lo signed)
off 7: struct byte
off 8-9: value B (hi, lo)
off 10: struct byte
off 11-12: value C (hi, lo)
... (more values follow)
```
After `hid_write(dev, buf, 0x40)`: `hid_read(dev, buf, 0x40)` and checks response `buf[2] == 0` (ACK).

## Open Questions
1. Why does the app stop at `hid_enumerate` (3 string reads) and never reach `recognize()` in the captures? Hypotheses:
   - `hid_open_path` succeeds (SET_IDLE observed) but a later hidapi step fails for this device (e.g., usage_page 0xFF00 vs the enumeration filter `cmp [eax+0x1c], 0x2` at VA 0x409d70)
   - the app waits for a true `DBT_DEVICEARRIVAL` hotplug event that PnP enable doesn't produce
   - the scheduler-started instance opens, fails, and exits before capture begins
2. QEMU VNC with empty password: after selecting security type 1, server sends 4 zero bytes (not a 16-byte challenge) — need to confirm whether to skip the DES step and read ServerInit directly.

## Next Steps
1. Fix VNC screenshot (`/tmp/opencode/vnc_shot.py`) to verify whether the app UI shows the device as connected.
2. Trigger a real hotplug while capturing: stop QEMU → `echo 0/1 > /sys/bus/usb/devices/1-11/authorized` (or unplug/replug) → start QEMU + USBPcap capture → start app manually (not via scheduler) and operate it (change metrics/brightness) to force `0x20` writes.
3. Alternative: hook `hid_write`/`hid_read` (e.g., API monitor or a small DLL proxy of `hidapi.dll`) to log exact report bytes even if USBPcap misses them.
4. Once a `0x10`/`0x20` write+response pair is captured: document the full protocol table, then implement the Linux daemon (libusb/hidapi) + systemd service.

## Access
- **Host SSH to VM**: `sshpass -p "$(cat vm_passwd.txt)" ssh -p 2222 capturer@127.0.0.1` (hostfwd; remote shell is cmd — use `.ps1` files, inline `$_` breaks under cmd). `vm_passwd.txt` is gitignored.
- **VNC**: QEMU `-vnc :1` → `127.0.0.1:5901` (empty password)
- **Host root**: password in `root_passwd.txt` (`echo 2001 | sudo -S ...`)
- **VM scripts**: scp `.ps1` to `C:\` and run `powershell -NoProfile -ExecutionPolicy Bypass -File C:\x.ps1`

## Key Files
| File | Purpose |
|---|---|
| `research/USB_CAPTURE_PLAN.md` | this document |
| `research/FINDINGS_CAPTURE.md` | round-2 findings: app detection logic, hidapi filter, PnP state, tooling |
| `research/NOTES.md` | Phase 0–3 notes, app strings |
| `start-windows-vm.sh` | QEMU startup (usb-host bus 1 port 11, VNC :1) |
| `captures/*.pcapng` | captures; `frames.tsv` = extracted HID reports |
| `research/windows-app/README.md` | how to obtain the vendor binaries (untracked) |
| `research/windows-app/Hummer_Digital.exe` | app binary (untracked) |
| `research/windows-app/hidapi.dll` | app's hidapi (pre-0.9, untracked) |
| `/etc/udev/rules.d/70-hummer-h200-udev.rules` | host udev rule (fix) |
| `/tmp/opencode/hummer_disasm.txt` | objdump of app (45,992 lines) |
| `/tmp/opencode/hidapi_disasm.txt` | objdump of hidapi.dll |
| `/tmp/opencode/vnc_shot.py` | WIP VNC framebuffer grabber |
