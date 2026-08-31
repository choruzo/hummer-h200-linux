# Research Notes - NOX Hummer H-200 LCD

## STATUS: Phase 0-3 Complete (Initial Analysis)

---

## PHASE 0 & 1: Hardware Identification (TODO - run on Ubuntu)

Need to execute on Ubuntu:
- `lsusb` - identify device VID/PID
- `lsusb -t` - bus topology
- `ls -l /dev/hidraw*` - HID devices
- `udevadm info --attribute-walk --name=/dev/hidrawX` - device attributes
- Check `/sys/bus/usb/devices/`
- Check `/sys/class/hwmon/`

---

## PHASE 2: Windows Software Extraction

### Extracted from Inno Setup installer
- **Installer**: `Hummer_DigitalSetup_H-200 LCD.exe` (Inno Setup 6.1.0 Unicode)
- **Output**: `research/windows-app/`

### Package structure
```
Hummer_DigitalSetup_H-200 LCD.exe
└── app/
    ├── Hummer_Digital.exe     (310 KiB) - main application
    ├── hidapi.dll             (14 KiB)  - USB HID communication
    ├── HWiNFO32.dll           (1.88 MiB) - hardware monitoring (AMD/Intel sensors)
    ├── Qt5Core.dll            (5.05 MiB)
    ├── Qt5Gui.dll             (5.7 MiB)
    ├── Qt5Widgets.dll         (4.38 MiB)
    ├── Qt5Network.dll         (1.06 MiB)
    ├── Qt5Svg.dll             (265 KiB)
    ├── msvcp140.dll           (432 KiB) - MSVC runtime
    ├── ucrtbase.dll           (895 KiB)
    ├── vcruntime140.dll       (74 KiB)
    ├── imageformats/          (Qt image plugins)
    │   ├── qgif.dll, qjpeg.dll, qsvg.dll, qwebp.dll, ...
    ├── platforms/
    │   └── qwindows.dll       (Windows platform plugin)
    ├── styles/
    │   └── qwindowsvistastyle.dll
    └── logs/                  (empty in installer)
```

### No drivers, .sys, .inf files
- No kernel drivers
- No WinUSB drivers
- No custom INF files
- Uses standard Windows HID stack

---

## PHASE 3: Static Analysis

### Application Info
- **Project name**: DeviceMonitorXtr (from PDB path)
- **PDB path**: `G:\Documents\Projects\DeviceMonitorXtr\release\Hummer_Digital.pdb`
- **Build**: Release mode, Unicode
- **Framework**: Qt 5.x (C++)
- **Compiler**: MSVC (Visual Studio 2015+)
- **Architecture**: 32-bit (Qt5 plugins, 32-bit DLLs)

### Communication Methods (CONFIRMED by imports)

#### 1. USB HID (PRIMARY)
- **Library**: `hidapi.dll` (bundled)
- **Functions used**:
  - `hid_enumerate` - enumerate USB HID devices
  - `hid_open_path` - open by device path
  - `hid_read` - read data from device
  - `hid_write` - write data to device
  - `hid_close` - close device
  - `hid_error` - get error string
  - `hid_set_nonblocking` - non-blocking mode
  - `hid_free_enumeration` - free enumeration result

#### 2. Network (SECONDARY)
- **QTcpSocket / QTcpServer** - TCP client/server
- **QLocalSocket / QLocalServer** - local IPC (named pipes on Windows)
- **QNetworkAccessManager** - HTTP/HTTPS requests (update checking)
- **QFtpPrivate** - FTP protocol (update downloads)

#### 3. Hardware Sensors (via HWiNFO32.dll)
- `HardwareInfoReader::InitHWi32Dll`
- `Get cpu temp from hwi32 error/invalid`
- `Get gpu temp from hwi32 error/invalid`
- `Get cpu fan speed from hwi32 error/invalid`

#### 4. Configuration
- **QSettings** with `HKEY_LOCAL_MACHINE` (Windows Registry)
- Also supports INI files (QSettings::IniFormat)

### UI Components (CONFIRMED by imports + strings)

| Component | Purpose |
|-----------|---------|
| `QMainWindow` | Main window |
| `QTableWidget` | Device list table (`tableWidget_HIDDevicesTable`) |
| `QComboBox` | Temperature unit selector (`cmb_temperature_unit`) |
| `QCheckBox` | Toggle display items (CPU temp, GPU temp, Fan RPM) |
| `QLineEdit` | Display readouts (CPU temp, GPU temp, Fan RPM, CPU/GPU usage) |
| `QLabel` | Static text (firmware version, hardware version, etc.) |
| `QProgressBar` | Download progress |
| `QSystemTrayIcon` | System tray icon |
| `QMenuBar` / `QMenu` | Menu (Settings, Help, Exit, etc.) |

### UI Labels (Chinese strings decoded)

| Chinese | English |
|---------|---------|
| 设备检测软件 | Device Monitor Software |
| 软件版本 | Software Version |
| 硬件版本 | Hardware Version |
| 固件版本 | Firmware Version |
| 风扇转速 | Fan Speed (RPM) |
| 温度 | Temperature |
| 使用率 | Usage Rate |
| 温度单位 | Temperature Unit |
| 摄氏度 | Celsius |
| 华氏度 | Fahrenheit |
| 设置 | Settings |
| 通用设置 | General Settings |
| 数据切换间隔 | Data Switch Interval |
| 语言 | Language |
| 开机启动 | Start on Boot |
| 报警阈值 | Alarm Threshold |
| 设备列表 | Device List |
| 检查更新 | Check for Updates |
| 帮助 | Help |
| 退出 | Exit |
| 关于 | About |
| 设备显示项 | Display Items |
| 简体中文 | Simplified Chinese |
| 繁体中文 | Traditional Chinese |

### Display Items (checkboxes)
- `checkBox_displayCPUTemp` - CPU Temperature
- `checkBox_displayGPUTemp` - GPU Temperature  
- `checkBox_displayFanSpeed` - Fan RPM

### Input Fields
- `lineEdit_CPUTemperature` - CPU temp display
- `lineEdit_CPUUsageRate` - CPU usage display
- `lineEdit_GPUTemperature` - GPU temp display
- `lineEdit_GPUUsageRate` - GPU usage display
- `lineEdit_FanRpm` - Fan RPM display

### Alarm Settings
- `spinBox_cpu_temp_alarm` - CPU temperature alarm threshold
- `spinBox_gpu_temp_alarm` - GPU temperature alarm threshold
- `spinBox_fanRpm_alarm` - Fan RPM alarm threshold
- `nTemperatureAlarm` - temperature alarm flag
- `nFanRpmAlarm` - fan RPM alarm flag

### Update System
- `UpgradeDialog` - update dialog
- `signalNeedUpdate(QString)` - signal for new version
- `downloadProgress(qint64, qint64)` - download progress
- `downloadFinished(bool, QString, QString)` - download complete
- `ftpConnected(bool, QString)` - FTP connection status
- `signalFtpConnect` - FTP connection signal
- "软件升级服务器连接失败" - "Software upgrade server connection failed"

### Key Classes (from mangled names + PDB)
- `HIDDevicesManager` - manages HID device enumeration and connection
  - `recognize()` - device recognition
  - `registerNotify()` - register for device arrival notifications
- `SendHIDDataThread` - background thread for HID communication
  - `sendDataToHIDDevice()` - send data to HID device
- `CircularDisplayTimer` - rotates display items
- `CircularDisplayTimer` - manages display cycling
- `HardwareInfoReader` - reads hardware info via HWiNFO32
- `FtpManager` - FTP download manager for updates
- `UpgradeDialog` - update dialog

### Error Messages (CONFIRMED)
- "Open HID device fail, path: %1"
- "Send data to HID device fail! reply error."
- "Send data to HID device fail. [%1]!"
- "Read HID device data fail: %1, device path: %2!"
- "Invalid HID device"
- "Write data to device fail: %1, device path: %2!"
- "VID: %2, PID: %3, Device Path: %4!"

### VID/PID Discovery
- VID/PID are NOT hardcoded as string literals
- They are loaded dynamically (likely from registry or config)
- The format string "VID: %2, PID: %3, Device Path: %4!" confirms they are variables
- **Must be discovered via `lsusb` on Ubuntu with device connected**

### Translation Files (Qt .qm)
- `:/zh_CN.qm` - Simplified Chinese
- `:/zh_TW.qm` - Traditional Chinese
- `:/eg_EN.qm` - English

### Embedded Resources (Qt .qrc)
- `:/Resource/QssConfig/Application.qss` - Qt stylesheet
- `:/Resource/favicon.ico` - Application icon
- `:/Resource/devicelist.png` - Device list icon
- `:/Resource/setting.png` - Settings icon
- `:/Resource/about.png` - About icon
- `:/Resource/quit.png` - Quit icon
- `:/Resource/online.png` - Online/connected icon

### Threading Model
- `SendHIDDataThread` - dedicated thread for HID communication
- Uses Qt signals/slots for IPC
- QTimer for periodic polling (CircularDisplayTimer)

---

## PROTOCOL ANALYSIS (PENDING)

### CONFIRMED
- Device communicates via **USB HID** (not CDC-ACM, not WinUSB)
- Uses **hidapi** (libusb-backed on Linux, Windows HID API on Windows)
- **HID Report protocol** - needs reverse engineering
- Device is enumerated and recognized by `HIDDevicesManager::recognize()`
- Data is read periodically via `hid_read()` in `SendHIDDataThread`

### NEEDS DISCOVERY
- VID / PID (dynamic, not hardcoded)
- Report ID(s)
- Report size (input/output)
- Command structure / byte layout
- Endianness
- Checksum algorithm (if any)
- What commands does the display support?
- What data can the display show?

### LIKELY PROTOCOL STRUCTURE (HYPOTHESIS)
```
[Report ID][Command][Data...][Checksum?]
```
- The display likely supports:
  - Read sensor data (CPU temp, GPU temp, Fan RPM)
  - Set display content
  - Set alarm thresholds
  - Query firmware version

---

## NEXT STEPS

### Immediate (on Ubuntu):
1. Connect H-200 LCD via USB
2. Run `lsusb` to find VID/PID
3. Run `ls -l /dev/hidraw*` to find HID device node
4. Run `udevadm info` for full device descriptor
5. Extract HID Report Descriptor if available
6. Try passive sniffing with `usbmon`

### Then:
7. Capture traffic from Windows app (Wireshark + USBPcap or VM)
8. Reverse engineer HID protocol
9. Create protocol specification
10. Build Linux prototype with hidapi

---

## IMPORTANT NOTES

- The app uses **HWiNFO32.dll** to read CPU/GPU temps on Windows
- On Linux, we'll use `/sys/class/hwmon` and `sensors` instead
- The H-200 LCD is a **standalone display** - it reads thermal data itself
- The USB connection sends display content TO the device, not sensor data FROM it
- The device likely has its own firmware that reads thermal sensors via internal I2C/SMBus

## RISK ASSESSMENT

- **Low risk**: HID is a standard protocol, read-only discovery is safe
- **Medium risk**: Writing to HID could change display behavior (not permanent)
- **High risk**: Writing unknown data could potentially cause display corruption
- **NO firmware flashing** - could brick the device
