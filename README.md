# NOX Hummer H-200 LCD — Native Linux Driver

Native Linux daemon and tools to control the LCD display of the NOX Hummer H-200 liquid cooler.

## Hardware

| Field | Value |
|-------|-------|
| **Device** | NOX Hummer H-200 LCD |
| **Display** | LCD screen (USB HID) |
| **Protocol** | USB HID (discovered via reverse engineering) |
| **OS Support** | Windows (official) |
| **Linux Support** | In progress (this project) |

> **VID/PID**: `2E3C:0A12` (identified as "KIMTECH Tuner" by system)
> **Device Node**: `/dev/hidraw2`
> **Connection**: Internal USB 2.0 header on ASRock X870 Taichi Creator

## What This Project Does

- Reads system sensors (CPU temperature, GPU temperature, fan RPM)
- Sends display data to the H-200 LCD via USB HID
- Runs as a systemd service, auto-starting on boot
- Replaces the official Windows "Hummer Digital" software

## Current Status

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Hardware identification | ✅ Complete |
| 1 | USB device enumeration | ✅ Complete |
| 2 | Windows software extraction | ✅ Complete |
| 3 | Static binary analysis | ✅ Complete |
| 4 | Traffic capture | ✅ Complete (API-level, see `research/METHOD.md`) |
| 5 | Protocol reverse engineering | ✅ Complete (see `research/PROTOCOL.md`) |
| 6 | Linux prototype (`h200d.py`) | ✅ Working against the real device |
| 7 | Systemd daemon | ✅ Complete (`packaging/h200d.service`) |
| 8 | Linux sensor integration | ✅ Complete (hwmon + /proc/stat) |
| 9 | Configuration system | ⬜ Pending |
| 10 | udev rules | ✅ Complete |
| 11 | Systemd service | ✅ Complete (`./install.sh`) |
| 12 | Tests | ⬜ Pending |
| 13 | Documentation | 🟡 In progress |

## What We Know (From Static Analysis)

### Communication
- The official Windows app uses **USB HID** via `hidapi.dll`
- Device is enumerated and recognized by `HIDDevicesManager::recognize()`
- Data is read periodically via `hid_read()` in a background thread
- No custom drivers required — uses the standard Windows HID stack

### Displayable Metrics (confirmed from UI strings)
- CPU temperature
- GPU temperature
- Fan RPM
- CPU usage rate
- GPU usage rate
- Temperature unit: Celsius / Fahrenheit
- Alarm thresholds for temperature and RPM

### Architecture of the Official App
- Qt 5.x (C++) compiled with MSVC
- Uses `HWiNFO32.dll` for Windows hardware monitoring
- Configuration stored in Windows Registry (`HKEY_LOCAL_MACHINE`)
- Update system via FTP
- System tray icon
- Device list table with auto-refresh

### Current Protocol Findings (Live Device Testing)

#### HID Report Structure
- **Report size**: 64 bytes (1 byte Report ID + 63 bytes data)
- **Input reports**: 63 bytes (1 byte Report ID + 62 bytes data)
- **Usage Page**: Vendor-defined (`0xFF00`)
- **Status byte**: `0x01` = Success, other values = Error codes

#### Verified Working Commands

| Report ID | Command | Description | Response |
|-----------|---------|-------------|----------|
| `0x10` | `0x01` | Query device info | ✅ Serial, firmware version |
| `0x20` | `0x01` | Display on/off | ✅ |
| `0x20` | `0x02` | Brightness (0-255) | ✅ |
| `0x20` | `0x10` | Display config query | ✅ |

#### Non-Working Commands (need investigation)

| Report ID | Command | Description |
|-----------|---------|-------------|
| `0x10` | `0x02`-`0x60` | Various queries (no response) |
| `0x20` | `0x03` | Display mode (no response) |
| `0x20` | `0x20` | Set display content (no visible output) |
| `0xF0` | `0x00`-`0x09` | Sensor/config commands (no response) |

#### Known Issues
- Report `0xF0`/`0xF1` still undocumented — the Windows app never uses them on
  its monitoring path (most likely the firmware-upgrade channel)
- Alarm thresholds (`alarm` byte of report `0x20`) were never seen to trigger;
  the bit layout comes from static analysis only
- Hot-replug is handled by reconnecting; a device that answers but stops
  ACKing is only detected by the 2 s read timeout

### System Configuration
- **udev rule**: `packaging/70-hummer-h200.rules` (hidraw node into the `h200` group + `uaccess`)
- **sudoers rule**: `/etc/sudoers.d/99-javi-nopasswd` (python3 passwordless)
- **Power control**: USB autosuspend disabled for `2E3C:0A12`

## Usage

The protocol is decoded and `h200d.py` drives the display directly over
`/dev/hidraw*` with no third-party dependencies:

```bash
./h200d.py --list      # show the detected device and the sensors it will use
./h200d.py --once      # handshake + a single frame
./h200d.py -v          # run, cycling CPU temp / GPU temp / fan speed
```

Options: `--metrics cpu-temp,cpu-usage,gpu-temp,gpu-usage,fan`, `--fahrenheit`,
`--interval`, `--rotate`. The udev rule below makes the hidraw node writable
without root.

It waits for the display if it is not plugged in yet and reconnects after an
unplug (including a new `hidraw` node number). `--retry 0` restores the old
fail-fast behaviour.

To install it as a service:

```bash
sudo ./install.sh          # daemon + udev rule + systemd unit, then enables it
sudo ./install.sh --uninstall
```

To hand it to someone else, build the release tarball — 12 KB, just the daemon,
the packaging files and the docs, with none of the research tree:

```bash
./packaging/make-release.sh        # -> dist/h200d-0.1.0.tar.gz
```

They extract it and run `sudo ./install.sh`. The build unpacks its own tarball
and runs the installer against a staging root (`DESTDIR=`) before declaring
success, so a release that cannot install fails the build.

`install.sh` creates a system user/group `h200`, installs the udev rule that
puts the hidraw node in that group, and enables `h200d.service`. To keep driving
the display by hand, `sudo systemctl stop h200d` and either add yourself to the
`h200` group or rely on the rule's `uaccess` tag at your seat.

## Project Structure

```
hummer-h200-linux/
├── docs/                  # Project documentation
├── research/
│   ├── windows-app/       # Extracted Windows app binaries
│   └── NOTES.md           # Research diary
│   ├── PROTOCOL.md        # the decoded HID protocol
│   └── METHOD.md          # how it was captured (Windows instrumentation rig)
├── captures/              # USB traffic captures
├── h200d.py               # Linux daemon: sensors -> display
├── tools/
│   ├── qmp.py             # QEMU monitor helper (screenshots, mouse, keys)
│   ├── vnc.py             # minimal RFB client
│   └── windows-proxy/     # hidapi logging proxy + fake HWiNFO32 (mingw32)
├── install.sh             # installs the daemon, udev rule and systemd unit
├── packaging/
│   ├── 70-hummer-h200.rules
│   ├── h200d.service
│   └── make-release.sh    # builds + smoke-tests dist/h200d-<version>.tar.gz
└── README.md
```

## Reverse Engineering Approach

The project follows a phased, safe approach:

1. **Passive discovery only** — no arbitrary USB writes
2. **VID/PID verification** before any write operation
3. **Protocol specification** derived from traffic capture
4. **Incremental implementation** with tests at each stage

See `research/PROTOCOL.md` for the protocol, `research/METHOD.md` for the
capture method, and `research/NOTES.md` for the research diary.

## Supported Hardware

| Component | Data Source (Linux) | Status |
|-----------|---------------------|--------|
| CPU (Ryzen 9 9900X) | `/sys/class/hwmon` | Planned |
| AMD Radeon AI PRO R9700 | `/sys/class/drm`, ROCm | Planned |
| Intel Arc Pro B50 | `/sys/class/drm`, xe driver | Planned |
| H-200 LCD (display) | USB HID (hidapi) | In progress |

## What This Project Will NOT Do

- No Electron or heavy GUI
- No containers
- No Wine dependency
- No kernel modules (unless absolutely necessary)
- No aggressive polling
- No firmware flashing

## Troubleshooting

### Device not responding
- Check if device is connected: `lsusb | grep 2e3c`
- Verify hidraw permissions: `ls -l /dev/hidraw*`
- Check udev rules are loaded: `udevadm info --query=property --name=/dev/hidraw2`
- Verify no USB autosuspend: `cat /sys/bus/usb/devices/1-*/power/control`

### Screen not showing content
- Known issue: screen turns off after boot (device still connected)
- Display content protocol not fully reverse-engineered yet
- USB traffic capture from Windows needed to understand display format

### Commands returning errors
- Verify correct Report ID and Command bytes
- Check device is in correct mode (some commands only work when display is on)
- Some commands may require specific initialization sequence

## Contributing

This is a personal reverse engineering project. Feel free to open issues or PRs if you find this useful.

## License

To be determined.

## Credits

- NOX for the Hummer H-200 LCD hardware
- Hummer Digital Windows software (reverse engineered)
- Qt, hidapi, and the open source community
