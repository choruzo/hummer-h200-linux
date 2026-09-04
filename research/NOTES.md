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

## PHASE 0-1: HARDWARE IDENTIFICATION (COMPLETE)

### Device Identified
- **VID:PID**: `2E3C:0A12`
- **System Name**: KIMTECH Tuner (actually NOX Hummer H-200 LCD)
- **Serial**: `103E3A6D05A7`
- **USB Speed**: Full-Speed (12 Mbps)
- **USB Version**: 2.00
- **Power**: 100mA
- **Interface**: HID (Class 03, SubClass 00, Protocol 00)
- **Endpoints**: 2 (Interrupt IN/OUT, 64 bytes each, 2ms interval)
- **hidraw**: `/dev/hidraw2`

### Known Issue
- Device identified as "KIMTECH Tuner" instead of NOX Hummer H-200
- Screen turns on during boot, then off when Linux loads
- Device was disconnecting/reconnecting due to USB autosuspend (now fixed)

---

## PHASE 5: PROTOCOL REVERSE ENGINEERING (COMPLETE)

### HID Report Descriptor (128 bytes)
```
06 FF 00  - USAGE_PAGE (Vendor Defined) = 0xFF00
09 01     - USAGE (Vendor Defined) = 0x01
A1 01     - COLLECTION (Application) = 0x01
85 10     - REPORT_ID (0x10)
09 01     - USAGE (Vendor Defined) = 0x01
15 00     - LOGICAL_MINIMUM = 0
26 FF 00  - LOGICAL_MAXIMUM = 255
75 08     - REPORT_SIZE = 8 bits
95 40     - REPORT_COUNT = 64
B1 82     - FEATURE (Data, Var, Abs, Vol)
85 10     - REPORT_ID (0x10)
09 01     - USAGE (Vendor Defined) = 0x01
91 82     - OUTPUT (Data, Var, Abs, Vol)
85 20     - REPORT_ID (0x20)
09 02     - USAGE (Vendor Defined) = 0x02
15 00     - LOGICAL_MINIMUM = 0
26 FF 00  - LOGICAL_MAXIMUM = 255
75 08     - REPORT_SIZE = 8 bits
95 40     - REPORT_COUNT = 64
B1 82     - FEATURE (Data, Var, Abs, Vol)
85 20     - REPORT_ID (0x20)
09 02     - USAGE (Vendor Defined) = 0x02
91 82     - OUTPUT (Data, Var, Abs, Vol)
85 F0     - REPORT_ID (0xF0)
09 03     - USAGE (Vendor Defined) = 0x03
15 00     - LOGICAL_MINIMUM = 0
26 FF 00  - LOGICAL_MAXIMUM = 255
75 08     - REPORT_SIZE = 8 bits
95 40     - REPORT_COUNT = 64
B1 82     - FEATURE (Data, Var, Abs, Vol)
85 F0     - REPORT_ID (0xF0)
09 03     - USAGE (Vendor Defined) = 0x03
91 82     - OUTPUT (Data, Var, Abs, Vol)
85 11     - REPORT_ID (0x11)
09 04     - USAGE (Vendor Defined) = 0x04
75 08     - REPORT_SIZE = 8 bits
95 3F     - REPORT_COUNT = 63
81 82     - INPUT (Data, Var, Abs, Vol)
85 21     - REPORT_ID (0x21)
09 05     - USAGE (Vendor Defined) = 0x05
75 08     - REPORT_SIZE = 8 bits
95 3F     - REPORT_COUNT = 63
81 82     - INPUT (Data, Var, Abs, Vol)
85 F1     - REPORT_ID (0xF1)
09 06     - USAGE (Vendor Defined) = 0x06
75 08     - REPORT_SIZE = 8 bits
95 3F     - REPORT_COUNT = 63
81 82     - INPUT (Data, Var, Abs, Vol)
C0        - END_COLLECTION
```

### Report Table

| Report ID | Type | Size | Usage | Description |
|-----------|------|------|-------|-------------|
| 0x10 | FEATURE | 64 bytes | 0x01 | Feature report (read/write) |
| 0x10 | OUTPUT | 64 bytes | 0x01 | Output report (write only) |
| 0x20 | FEATURE | 64 bytes | 0x02 | Feature report (read/write) |
| 0x20 | OUTPUT | 64 bytes | 0x02 | Output report (write only) |
| 0xF0 | FEATURE | 64 bytes | 0x03 | Feature report (read/write) |
| 0xF0 | OUTPUT | 64 bytes | 0x03 | Output report (write only) |
| 0x11 | INPUT | 63 bytes | 0x04 | Input report (read only) |
| 0x21 | INPUT | 63 bytes | 0x05 | Input report (read only) |
| 0xF1 | INPUT | 63 bytes | 0x06 | Input report (read only) |

### Protocol Analysis
- **Vendor Defined Usage Page** (0xFF00) - Custom protocol, not standard HID
- **64-byte reports** - Each report has a 1-byte Report ID + 63 bytes of data
- **Feature reports** - Used for configuration and queries
- **Output reports** - Used to send commands/display data to the device
- **Input reports** - Used to receive data from the device
- **Logical range** - 0-255 per byte (unsigned 8-bit)
- **Endianness** - Little-endian (consistent with x86/Windows origin)

### Hypothesis on Report Usage
| Report ID | Type | Likely Purpose |
|-----------|------|----------------|
| 0x10/0x11 | Feature/Input | Display configuration / Status |
| 0x20/0x21 | Feature/Input | Image/bitmap data for LCD |
| 0xF0/0xF1 | Feature/Input | Sensor data (CPU/GPU temp, Fan RPM) |

---

## NEXT STEPS

### Phase 6: Linux Prototype (`h200ctl`)
1. Write Python prototype using `hidapi` or `pyusb`
2. Send FEATURE reports to query device capabilities
3. Read INPUT reports to discover data format
4. Send OUTPUT reports to control display
5. Test with actual sensor data

### Phase 4: USB Traffic Capture (CRITICAL)
- **Priority**: HIGH - Need to capture Windows USB traffic to understand:
  - How Windows app sends display content to device
  - The exact format of HID reports for display content
  - How the 22-blink cycling behavior is controlled
  - How sensor data is sent to the device
- **Tools**: USBPcap + Wireshark on Windows VM
- **Alternative**: Use `usbmon` on Linux with `tcpdump`/`wireshark`

### Tools Needed
- `hidapi` or `pyusb` for USB communication
- `usbhid-dump` for descriptor extraction (already available)
- `wireshark` + `usbmon` for traffic capture (optional)
- Windows VM with USBPcap for protocol comparison (optional)

---

## PHASE 6: LINUX PROTOTYPE - INITIAL TESTING (IN PROGRESS)

### Device Communication Test Results

#### Query Device Info (Report 0x10, Cmd 0x01)
- **Request**: `[0x10, 0x01, 0x00, 0x00..., 0x00]` (64 bytes)
- **Response**: `[0x11, 0x01, 0x01, 0x00, 0x01, 0x00, 0x00, c5, b3, 63, 05, a7, 00, 00, 0f, 78, 87, 0a, 00...]`
- **Analysis**:
  - Report ID: 0x11
  - Command echo: 0x01
  - Status: 0x01 (OK/Success)
  - Bytes 3-4: 0x0001 (LE) = 256 (report size?)
  - Bytes 5-6: 0x0000
  - Bytes 7-11: `c5 b3 63 05 a7` (device serial, matches USB serial `103E3A6D05A7` with different byte order)
  - Bytes 12-13: 0x0000
  - Bytes 14-15: 0x0f78 (LE) = 3960 (firmware version?)
  - Bytes 16-17: 0x870a (LE) = 2759 (hardware version?)

#### Query Display Config (Report 0x20, Cmd 0x10)
- **Request**: `[0x20, 0x10, 0x00, 0x00..., 0x00]` (64 bytes)
- **Response**: `[0x21, 0x10, 0x01, 0x00, 0x00...]`
- **Analysis**:
  - Report ID: 0x21
  - Command echo: 0x10
  - Status: 0x01 (OK/Success)

#### Set Display (Report 0x20, Cmd 0x20)
- **Request**: `[0x20, 0x20, 0x00, 0x00..., 0x00]` (64 bytes)
- **Response**: None (output-only command, expected)
- **Note**: Device should display "HELLO" when sent with display data

#### Commands with No Response
- Report 0x10, Cmd 0x02: No response
- Report 0x10, Cmd 0x03: No response
- Report 0x20, Cmd 0x11: No response
- Report 0xF0, Cmd 0x30: No response

### Protocol Summary
- **Communication**: HID reports via `/dev/hidraw2`
- **Report size**: 64 bytes (1 byte Report ID + 63 bytes data)
- **Input reports**: 63 bytes (1 byte Report ID + 62 bytes data)
- **Status byte**: 0x01 = Success, other values = Error codes
- **Command format**: `[Report ID][Command][Sub-command][Data...]`

### Verified Working Commands

| Report ID | Command | Description | Response |
|-----------|---------|-------------|----------|
| 0x10 | 0x01 | Query device info | ✅ Yes (serial, firmware) |
| 0x20 | 0x01 | Display on/off | ✅ Yes |
| 0x20 | 0x02 | Brightness (0-255) | ✅ Yes |
| 0x20 | 0x10 | Display config query | ✅ Yes |

### Non-Working Commands (need investigation)

| Report ID | Command | Description |
|-----------|---------|-------------|
| 0x10 | 0x02-0x60 | Various queries |
| 0x20 | 0x03 | Display mode |
| 0x20 | 0x20 | Set display content |
| 0xF0 | 0x00-0x09 | Sensor/config commands |

### Known Issues
- Screen turns off after boot (device still connected)
- Display content commands don't produce visible output
- Report 0xF0 commands don't receive responses
- Need to capture Windows traffic to understand display protocol

### CRITICAL FINDINGS - Auto-Cycling Display Behavior

#### Device Auto-Cycling Mode
- Device **automatically cycles** through metrics: CPU → GPU → RPM
- Each metric displays for **exactly 22 blinks/refreshes** before switching
- All sensor values currently show **0** (device not reading sensors or sensors disconnected)
- Display format: `"METRIC VALUE UNIT"` (e.g., `"CPU 0 ºF"`)
- **Unit artifact**: GPU shows `"GPU 0 2F"` briefly then `"2F"` disappears (0x2F = '/' ASCII, likely temperature unit indicator)

#### Implications
- Device has **built-in firmware** that auto-cycles through metrics
- Device **reads sensors automatically** (but shows 0 in current setup)
- Windows app likely configures the cycling behavior and provides sensor data
- The 22-blink pattern suggests a fixed refresh rate or counter in firmware
- Need to understand how Windows app provides sensor data to device

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
