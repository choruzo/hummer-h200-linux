# How the H-200 protocol was captured

Bus sniffing (USBPcap in the Windows VM) never produced a single application
write and eventually wedged the guest's USB stack. The working approach was to
instrument the app at the API boundary instead. Nothing here needs USBPcap.

## The rig

```
Linux host                                   Windows 10 guest (QEMU)
-----------                                  -----------------------
tools/qmp.py  --- /tmp/h200-qmp.sock ------> QEMU monitor (screendump, mouse, keys)
ssh -p 2222 capturer@127.0.0.1 -----------> guest shell (run .ps1 files)
                                             Hummer_Digital.exe
                                               |-> hidapi.dll      == logging proxy
                                               |     writes C:\hidlog.txt
                                               `-> HWiNFO32.dll    == fake sensors
                                                     reads  C:\hwi_fake.txt
usb-host passthrough  ---------------------> the real H-200 (bus 1, port 11)
```

## 1. Un-wedge the guest USB stack

USBPcap's class filter left the H-200's HID interface half-initialised
(`Service` empty, no `Device Parameters`, no streaming) across reboots and even a
real power cycle. Fix:

1. `"C:\Program Files\USBPcap\Uninstall.exe" /S`
2. Delete `USBPcap` from `UpperFilters` under
   `HKLM:\SYSTEM\CurrentControlSet\Control\Class\{36fc9e60-c465-11cf-8056-444553540000}`
3. Reboot.
4. `pnputil /remove-device` on both the `HID\VID_2E3C…` and `USB\VID_2E3C…`
   instances, then `pnputil /scan-devices`.

After that the HID interface reports `SPDRP_CLASS = HIDClass`, has a bound
driver and opens read/write — and `hid_enumerate()` returns it with
`serial=103E3A6D05A7`, `mfg=KIMTECH`, `prod=Tuner`, `usage_page=0xFF00`.

> The previous session concluded the app "skipped" the device because
> `hid_enumerate` never returned it. That conclusion came from a **buggy test**:
> the P/Invoke struct read `next` at offset 40, but hidapi 0.8's
> `hid_device_info` is 36 bytes (`malloc(0x24)`, `next` at `[eax+0x20]`), so the
> walk always stopped after the first device. The correct layout is
> `path 0, vid 4, pid 6, serial 8, release 12, mfg 16, product 20, usage_page 24,
> usage 26, interface_number 28, next 32`.

## 2. `hidapi.dll` logging proxy

`tools/windows-proxy/proxy.c` re-exports the 17 hidapi entry points, forwards
each to the renamed original and appends every call — with full report hex — to
`C:\hidlog.txt`.

Install:

```
copy hidapi.dll hidapi_real.dll
copy hidapi_proxy.dll hidapi.dll
```

## 3. Fake `HWiNFO32.dll`

The app reads CPU/GPU temperature and fan RPM through `HWiNFO32.dll`, which is
`LoadLibrary`'d and called **by ordinal**. In a VM it finds no sensors, so the app
never sends a `0x20` report at all. `tools/windows-proxy/hwi.c` replaces it.

API, recovered from `HardwareInfoReader::InitHWi32Dll` (`0x40a7ae`) and
`ReadHWInfoByHWi32Dll` (`0x40b1d6`), all `__cdecl`:

| ordinal | signature | notes |
|---|---|---|
| `@127` | `int init(int)` | app calls `init(0x40)`; **0 means success** |
| `@466` | `int (int)` | only checked for non-NULL |
| `@781` | `int device_count(void)` | |
| `@617` | `void select_device(int idx)` | |
| `@168` | `int device_name(int idx, char *buf, int len)` | `len` = 256 |
| `@570` | `int sensor(int type, int dev, int idx, char buf[0x1d0])` | 0 = no more sensors |

`type` is `1` for temperatures and `3` for fans. The 464-byte struct the app
reads back:

| offset | content |
|---|---|
| `0x000` | dword, non-zero = reading is valid |
| `0x008` | double, the value |
| `0x010` | char[], unit string |
| `0x148` | char[], sensor label |

Sensor selection is by string matching, so the stub only has to name things
plausibly:

- CPU temperature: label scored against `CPU`, `Core`, `Cores`, `Average`,
  `Tdie`, `Die`, `Package`, `Tctl`, `DTS`, `Enhanced` — the stub uses
  `"CPU Package"`.
- GPU temperature: label `"GPU Temperature"`.
- Fan: matched on the **unit** string containing `RPM`.

Two traps found the hard way:

- If the unit string contains `"F"` at index > 0, the app converts the reading
  with `(v - 32) * 5 / 9` before sending it (`0x40b670` → `0x407730`). Use an
  empty unit for temperatures to get the value through untouched.
- Temperature readings are slew-limited to ±8.8 per read against a static
  previous value (`0x447d78`), so a large step takes a few seconds to settle.

Install:

```
copy HWiNFO32.dll HWiNFO32_orig.dll
copy HWiNFO32_fake.dll HWiNFO32.dll
echo 61.0 77.0 3333.0 > C:\hwi_fake.txt
```

Changing `C:\hwi_fake.txt` takes effect on the next read — no restart needed.

## 4. Driving the app

- The app is **single instance**, needs **elevation** (UAC), and auto-starts from
  the Task Scheduler task `DeviceMonitorStartTask` ("interactive only") at logon.
- Autologon (`HKLM\…\Winlogon`: `AutoAdminLogon=1`, `DefaultUserName`,
  `DefaultPassword`) gets a desktop session up after a reboot so the task fires.
- Starting it over SSH works for HID traffic but the window lands in the wrong
  session and is invisible on the console. To reach the GUI, double-click the
  desktop icon over QMP and accept the UAC prompt.
- `tools/qmp.py` does screenshots (`shot`), absolute mouse (`click`, `dblclick`)
  and keys (`key`) through the QEMU monitor — no VNC client needed, and it works
  while someone else is already attached to `-vnc :1`.

## 5. Gotchas that cost time

- Remote PowerShell: always `scp` a `.ps1` and run
  `powershell -NoProfile -ExecutionPolicy Bypass -File C:\x.ps1`. Inline commands
  get mangled by cmd.exe quoting — including string arguments, which is how
  `C:\hwi_fake.txt` once ended up containing `'61`. Write data files with `scp`.
- Anything loading the app's DLLs must run under
  `C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe` (they are 32-bit).
- QEMU's VNC `SetPixelFormat` makes the server stop responding; use the format it
  advertises (it is already 32bpp BGRA). `tools/vnc.py` does this, but `qmp.py` is
  the better tool for this VM.
- The guest clock runs ~2 h behind the host clock.
- The app's own log (`…\Hummer_Digital\logs\Log_*.txt`) only records Task
  Scheduler bookkeeping — useless for the HID path.
