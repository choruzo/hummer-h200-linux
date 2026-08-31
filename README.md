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

> **VID/PID**: To be discovered. The device must be connected to an Ubuntu system and identified via `lsusb`.

## What This Project Does

- Reads system sensors (CPU temperature, GPU temperature, fan RPM)
- Sends display data to the H-200 LCD via USB HID
- Runs as a systemd service, auto-starting on boot
- Replaces the official Windows "Hummer Digital" software

## Current Status

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Hardware identification | Pending |
| 1 | USB device enumeration | Pending |
| 2 | Windows software extraction | Complete |
| 3 | Static binary analysis | Complete |
| 4 | Passive traffic capture | Pending |
| 5 | Protocol reverse engineering | Pending |
| 6 | Linux prototype (`h200ctl`) | Pending |
| 7 | Systemd daemon | Pending |
| 8 | Linux sensor integration | Pending |
| 9 | Configuration system | Pending |
| 10 | udev rules | Pending |
| 11 | Systemd service | Pending |
| 12 | Tests | Pending |
| 13 | Documentation | In progress |

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

## Installation

Not yet available. This project is in the research/reverse engineering phase.

When complete, installation will be:

```bash
sudo ./install.sh
sudo systemctl enable --now hummer-h200
```

## Project Structure

```
hummer-h200-linux/
├── docs/                  # Project documentation
├── research/
│   ├── windows-app/       # Extracted Windows app binaries
│   └── NOTES.md           # Research diary
├── captures/              # USB traffic captures (pending)
├── src/                   # Linux implementation (pending)
│   └── hummer_h200/       # Python package (pending)
├── tools/                 # CLI tools (pending)
│   └── h200ctl.py         # Manual control tool (pending)
├── packaging/             # Systemd, udev, packaging (pending)
└── README.md
```

## Reverse Engineering Approach

The project follows a phased, safe approach:

1. **Passive discovery only** — no arbitrary USB writes
2. **VID/PID verification** before any write operation
3. **Protocol specification** derived from traffic capture
4. **Incremental implementation** with tests at each stage

See `research/NOTES.md` for detailed findings.

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

Not yet applicable — no working implementation exists yet.

## Contributing

This is a personal reverse engineering project. Feel free to open issues or PRs if you find this useful.

## License

To be determined.

## Credits

- NOX for the Hummer H-200 LCD hardware
- Hummer Digital Windows software (reverse engineered)
- Qt, hidapi, and the open source community
