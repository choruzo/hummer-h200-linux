# H-200 USB Capture - Findings (2026-09-04, round 2)

> **Superseded by [`PROTOCOL.md`](PROTOCOL.md) + [`METHOD.md`](METHOD.md)
> (round 3).** Two conclusions below turned out to be wrong:
> - §2 "the H-200 never appears in `hid_enumerate`" — the live test walked the
>   linked list with a 44-byte struct while hidapi 0.8 allocates 36
>   (`next` at offset 32). With the correct layout the device is returned
>   normally, with a valid serial number.
> - §3 "`Service` absent means hidclass never bound" — a vendor-defined HID
>   collection legitimately has no upper function driver, so an empty `Service`
>   is normal. The real wedge was USBPcap's class filter; uninstalling it and
>   re-enumerating the device fixed everything.
>
> §1 (the app's one-shot enumeration and lack of hotplug handling) and §4
> (tooling notes) still hold.

Detailed findings from the USBPcap capture + app reverse-engineering session.
Status snapshot at end of session: **VM USB stack is broken for the H-200** (USBPcap
service stuck even after full reboot + real host power cycle). See "Current state" below.

## 1. App device-detection logic (fully decoded)

`recognize()` at VA `0x409cd0` (handshake: `hid_write [0x10,0x01,0x00...]` 65 B + `hid_read` 65 B)
is called from exactly **two** sites:

### 1.1 One-shot enumeration (the main path)
Function at `0x409880`:
```
list = hid_enumerate(0, 0)
for dev in list:
    if dev->serial_number == NULL:   // check at [dev+0x8]
        continue
    recognize(dev->path, dev->vid, dev->pid)   // call at 0x4098aa
```
- `[dev+0x8]` = `serial_number` in the standard hidapi `hid_device_info` struct
  (confirmed: the loop's `next` pointer is read at `[dev+0x20]`, which matches the
  standard layout only when offset 8 is serial_number).
- This function has a **single caller**: `0x40bef5`, inside a large class setup/
  constructor (object allocations + log calls around it). It runs **once, at app
  startup**. There is **no polling loop**.
- **No hotplug handling exists**: the app imports no `RegisterDeviceNotification`,
  `CM_Register_Device_Notification`, or any device-event API. If the device is not
  (fully) present at the moment the app starts, it is never picked up — not even
  if it arrives later.

### 1.2 Single-device handler
`0x409c54` (inside a `ret 0xc` function at ~`0x409b80`): builds a few C++ string/
object locals, then `recognize([ebp-0x38], esi, [ebp-0x14])`. Likely the
UI/user-triggered path (device selected in the interface).

### 1.3 Consequences
- App is **single-instance** and auto-starts via Task Scheduler task
  `DeviceMonitorStartTask` (at logon). The scheduler-started instance does its
  one-shot enumerate at boot — before the USB device is ready — and a manual
  `Start-Process` afterwards is a no-op (second instance exits).
- **Required condition for a capture**: the H-200 must be fully enumerated by
  Windows (hidclass bound) **before** the app process starts; then kill all
  instances and start the app fresh.

## 2. hidapi.dll (the app's, pre-0.9)

- PE32, 14,336 B, ImageBase 0x10000000. Imports (full list extracted):
  `SetupDiGetClassDevsA, SetupDiEnumDeviceInterfaces, SetupDiGetDeviceInterfaceDetailA,
  SetupDiEnumDeviceInfo, SetupDiGetDeviceRegistryPropertyA, SetupDiDestroyDeviceInfoList,
  CreateFileA, ReadFile, WriteFile, DeviceIoControl` — **no HidD_*** (old backend).
- `hid_enumerate` (at 0x1210) reads a device property via
  `SetupDiGetDeviceRegistryPropertyA` and **case-sensitively compares it to the
  string "HIDClass"** (string at DLL RVA 0x3220). Non-match => device is skipped.
  (Exact property index not yet pinned down; the QEMU tablet passes the filter
  with registry `Service=mouhid`, so the compared property is not the plain
  `Service` value.)
- **Live test** (P/Invoke from SysWOW64 PowerShell using the app's own DLL —
  64-bit PowerShell fails with BadImageFormat, the DLL is 32-bit):
  `hid_enumerate(0,0)` returns **only the QEMU tablet**
  (`VID=0627 PID=0001 serial=28754-0000:00:04.0-2 prod=QEMU`).
  **The H-200 never appears** => the app's enumerate loop never reaches it =>
  `recognize()` is never called. This is the root cause of "no writes in any
  capture".

## 3. Windows-side state of the H-200 (why hidapi skips it)

Healthy (first boot, 12:04 — device streamed at 30 Hz): HID interface fully
initialized, USBPcap captured the interrupt stream.

Broken state (all subsequent boots, identical):
```
HID\VID_2E3C&PID_0A12\<instance>
  ClassGUID = {745a17a0-74d3-11d0-b6fe-00a0c90f57da}   (HID class)
  Driver    = {745a17a0-...}\0004                       (generic HID driver SELECTED)
  Service   = (ABSENT)                                  (driver never installed/started)
  Device Parameters = (key ABSENT)
```
- PnP status says "OK", but **hidclass never runs StartDevice**: no
  `GET DESCRIPTOR (HID Report)` on the bus (visible in captures), no streaming,
  no `Service`/`Device Parameters` in the registry.
- The tablet on the same xhci controller works fine (mouhid bound, interrupt
  traffic present) => the xhci emulation and USBPcap's global attachment are not
  uniformly broken; the failure is specific to this device's HID stack.

### Attempted fixes (all failed)
1. QMP `device_del`/`device_add` hotplug (works at PnP level: instance goes
   GONE -> OK, verified in registry) — leaves the device half-initialized as above.
2. `pnputil /remove-device` on all 4 contaminated instances (2E3C USB + HID,
   old + new) + QMP re-add — new instance (`...&1&0000`) came up with the same
   missing-Service state.
3. **Real power cycle** from the host: `echo 0/1 > /sys/bus/usb/devices/1-11/authorized`
   (full QEMU stop between) — same broken state after reboot.
4. Stopping/restarting the USBPcap service — **the service cannot be stopped,
   even on a fresh boot** ("No se puede detener el servicio USBPcap"). After the
   latest reboot, USBPcapCMD produces 24-byte captures (not even the 711-byte
   descriptor baseline) => the USBPcap **filter driver is the prime suspect** for
   wedging this device's stack; its persisted state survives reboots.

## 4. USBPcap / QMP / tooling notes

- **QMP (QEMU 8.2)**: client handshake is `{"execute": "qmp_capabilities"}`
  (no `"QMP"` wrapper — that's only the server greeting). Helper:
  `/tmp/opencode/qmp.py {del|add}` on socket `/tmp/h200-qmp.sock`
  (QEMU started with `-qmp unix:/tmp/h200-qmp.sock,server,nowait` and
  `-device usb-host,id=h200,hostbus=1,hostport=11` — see `start-windows-vm.sh`).
- **USBPcapCMD quoting bug** (cost an hour): in PowerShell, backslash is NOT an
  escape character, so `-ArgumentList "-d \\\\.\\USBPcap1 ..."` passed a garbage
  device name; the CLI exited instantly ("Couldn't open device - 161").
  **Use an argument array**:
  `$a = @("-d", "\\.\USBPcap1", "-A", "--inject-descriptors", "-o", "C:\x.pcapng");
  Start-Process USBPcapCMD.exe -ArgumentList $a -PassThru -WindowStyle Hidden`
- Foreground (console-attached) USBPcapCMD runs fine; the failures were the
  bad argument, not the hidden-process mode.
- 711-byte capture = `--inject-descriptors` baseline only (no live traffic).
  >~2 KB in 5 s => the 30 Hz device stream is present.
- USBPcap packet format (tshark decodes it): 27-byte URBs with no payload are
  interrupt-URB submissions/completions; real 6-byte HID data frames are ~33 B.
- App log (`C:\Program Files (x86)\Hummer_Digital\logs\Log_YYYY-MM-DD.txt`):
  **only Task Scheduler bookkeeping** (AddTaskToScheduler/SetTaskEnabledState).
  No device/HID messages — useless for diagnosing the HID path.
- VM clock runs ~2 h behind host clock; correlate via event-log timestamps.
- `Get-PnpProperty` does not exist on this Win10 build; query
  `HKLM:\SYSTEM\CurrentControlSet\Enum\<instance>` (+ `Device Parameters`) directly.
- Remote PowerShell: always via scp'd `.ps1` files (`powershell -File C:\x.ps1`);
  inline commands break under cmd.exe quoting. Use 32-bit
  `C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe` for anything that
  loads the app's 32-bit DLLs.

## 5. Captures taken this session

| File | Content |
|---|---|
| `captures/cap5.pcapng` (1,764 B, 30 frames) | QMP hotplug round: injected descriptors + device arrival (SET_IDLE at t=17.55, tablet re-enumeration, 2 empty interrupt URBs). **No HID data, no app writes.** |
| (older) `h200_win_20260904_120457.pcapng` | Only capture with the live 30 Hz stream (healthy first boot). |

## 6. Current state (session end)

- QEMU running (see `pgrep -f qemu-system-x86_64`), QMP socket live, device
  grabbed by QEMU.
- In-VM: H-200 PnP "OK" but **no streaming, no hidclass Service**; USBPcap
  service Running but **unstoppable** and producing 24-byte captures.
- App: not running.

## 7. Next steps (ranked)

1. **Uninstall USBPcap in the VM** (Add/MRemove programs or `pnputil`), reboot,
   verify the device streams again (5 s USBPcap-less test: watch PnP +
   `hid_enumerate` P/Invoke). If fixed => USBPcap filter was the wedge; then
   choose capture path:
   a. Reinstall USBPcap fresh and hope it stays well-behaved, or
   b. **USB/IP**: export the device from the host (`usbipd`) and attach in the
      VM; capture on the **host with usbmon** (`tshark -i usbmon1`) — the host
      kernel performs all USB traffic for the guest, so nothing is missed.
2. Once streaming + hidclass are healthy: run the **winning sequence** —
   device fully ready (verify `Service` in registry) => start capture =>
   `Stop-Process Hummer_Digital` => start app fresh => watch for the
   `[0x10,0x01]` 65-byte write + response, then periodic 64-byte `0x20` reports.
3. Fallback if the VM path stays broken: per the agreed condition, abandon the
   VM and pursue direct host-side reverse engineering (the device is already
   fully accessible on the host: `/dev/bus/usb/001/005`, 6-byte IN reports
   decoded, and we can send candidate OUT reports directly and observe the LCD).
