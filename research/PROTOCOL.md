# NOX Hummer H-200 — USB HID protocol

Reverse engineered from `Hummer_Digital.exe` (Windows app) by instrumenting its
`hidapi.dll` with a logging proxy while feeding it synthetic sensor values through
a fake `HWiNFO32.dll`. Every frame below was captured live from the real device
(VID:PID `2E3C:0A12`, "KIMTECH Tuner", firmware 1.0).

See [`METHOD.md`](METHOD.md) for how the capture rig works and
[`FINDINGS_CAPTURE.md`](FINDINGS_CAPTURE.md) for the investigation history.

## Transport

Plain HID, one interface, numbered reports. From the 128-byte report descriptor:

| Report ID | Direction | Payload | Purpose |
|---|---|---|---|
| `0x10` | OUTPUT + FEATURE | 64 B | host → device: identify / handshake |
| `0x11` | INPUT | 63 B | device → host: reply to `0x10` |
| `0x20` | OUTPUT + FEATURE | 64 B | host → device: sensor values (periodic) |
| `0x21` | INPUT | 63 B | device → host: ACK for `0x20` |
| `0xF0` | OUTPUT + FEATURE | 64 B | host → device: unused by the app (firmware upgrade path) |
| `0xF1` | INPUT | 63 B | device → host: unused by the app |

On the wire hidapi sends 65 bytes (1 report-ID byte + 64) and reads 64 bytes
(1 report-ID byte + 63). All multi-byte values are **big-endian**.

The app opens the device, writes one report, reads the reply, and **closes the
device again for every single exchange** — roughly twice per second.

## 1. Handshake (report `0x10`)

Sent once by `HIDDevicesManager::recognize()` right after `hid_open_path()`.

```
host -> 10 01 <62 bytes: ignored>
```

Only bytes 0 and 1 matter — the app leaves the rest of the stack buffer
uninitialised and the device does not care. Captured example:

```
10 01 3D 77 D5 DD 0E 9D FE FF FF FF 44 A1 F1 73 ... (garbage)
```

Reply:

```
device -> 11 01 01 00 01 00 00 C5 B3 63 05 A7 00 00 0F 78 87 0A 00 00 ...
          ^^ ^^ ^^ ^^
          |  |  |  +-- firmware minor
          |  |  +----- firmware major
          |  +-------- echo of the command byte (0x01)
          +----------- report ID 0x11
```

The app requires `reply[0] == 0x11` and formats the version as
`"<reply[2]>.<reply[3]>"` — this unit reports **1.0**. Bytes 7..17
(`C5 B3 63 05 A7 00 00 0F 78 87 0A`) are constant per unit and unused by the
app; they are probably a device/serial blob.

## 2. Sensor push (report `0x20`)

Built by `sendDataToHIDDevice` (VA `0x40fec0`…`0x4101a2`) and sent every ~550 ms
per detected device. Buffer is `memset` to 0 first, so every byte not listed is `0x00`.

```
off  0   0x20            report ID
off  1   type            which metric the display is currently showing (see below)
off  2   unit            0 = Celsius, 1 = Fahrenheit
off  3   alarm           alarm bit for the metric in off 1 (see below), else 0
off  4   0x00
off  5-6 cpu_temp        int16 BE, in the unit from off 2
off  7   cpu_usage       uint8, percent
off  8-9 gpu_temp        int16 BE, in the unit from off 2
off 10   gpu_usage       uint8, percent
off 11-12 fan_rpm        uint16 BE
off 13-63 0x00
```

Negative temperatures are encoded as a sign-extended 16-bit value: the app emits
`hi = (v + (v<0 ? 0xff : 0)) >> 8` and `lo = v & 0xff`, i.e. plain two's complement.

### `type` / `alarm` bit values

`type` is a single bit naming the metric the LCD is currently cycling through;
`alarm` carries the **same** bit when that metric is past its configured threshold
(the fan is inverted: the alarm trips when the RPM falls *to or below* the limit).

| bit | metric | frame field |
|---|---|---|
| `0x01` | CPU temperature | off 5-6 |
| `0x02` | CPU usage | off 7 |
| `0x04` | GPU temperature | off 8-9 |
| `0x08` | GPU usage | off 10 |
| `0x10` | Fan speed | off 11-12 |

Only the metrics enabled in *Display Options* are cycled; the app rotates through
them at the *Data Change Interval* (default 3 s) while still sending **all**
values in every frame.

### ACK

```
device -> 21 <type> 01 00 00 ...
          ^^ ^^^^^^ ^^
          |  |      +-- ACK: non-zero = accepted (0 = the app logs a write failure)
          |  +--------- echo of the type byte from the request
          +------------ report ID 0x21
```

### Verified captures

Sensor values were injected through the fake `HWiNFO32.dll`, so the mapping is
confirmed rather than inferred:

| injected (CPU °C / GPU °C / RPM) | unit setting | frame (first 13 bytes) |
|---|---|---|
| 61 / 77 / 3333 | Celsius | `20 04 00 00 00  00 3D  00  00 4D  00  0D 05` |
| 61 / 77 / 3333 | Fahrenheit | `20 04 01 00 00  00 8D  00  00 AA  00  0D 05` |
| 95 / 88 / 9999 | Celsius | `20 01 00 00 00  00 5F  00  00 58  00  27 0F` |
| 120 / 110 / 12000 | Celsius | `20 10 00 00 00  00 78  00  00 6E  00  2E E0` |

`0x3D`=61, `0x4D`=77, `0x0D05`=3333, `0x8D`=141 (=61 °C in °F), `0xAA`=170
(=77 °C in °F), `0x270F`=9999, `0x2EE0`=12000 — all exact.

The `type` byte tracked the *Display Options* checkboxes exactly: with only GPU
temperature and fan speed enabled it alternated `0x04`/`0x10`; enabling CPU
temperature added `0x01` to the rotation.

## 3. What the host must do

1. Open the HID device (`hidraw` / libusb) for `2E3C:0A12`.
2. Write report `0x10` with `[0x10, 0x01, 0x00 × 63]`, read the `0x11` reply,
   check `reply[0] == 0x11`.
3. Every ~0.5–3 s write a `0x20` frame with the current sensor values and read
   the `0x21` ACK.
4. Rotate the `type` byte across the metrics you want the LCD to cycle through.

## Open points

- The alarm thresholds live in the app's settings; the defaults are above 120 °C
  and 12000 RPM, so `alarm` stayed `0x00` in every capture. The bit layout above
  comes from the jump table at `0x410040`–`0x4100f5`, not from a live trigger.
- `0xF0`/`0xF1` are declared by the device but never used by the app's monitoring
  path; the app does contain a `CUpgradeDialog`, so they are most likely firmware
  update reports.
- Earlier sessions recorded a 6-byte interrupt IN stream at ~30 Hz. The report
  descriptor declares no 6-byte input report, so that reading needs to be
  re-checked against a fresh capture before it is trusted.
