# research/windows-app/ — not in this repository

The Windows application this project was reverse engineered from
(`Hummer_Digital.exe`, `hidapi.dll`, `HWiNFO32.dll`, the bundled Qt 5 and
Microsoft runtime DLLs) is NOX/KIMTECH and third-party property. It is not ours
to redistribute, so it is deliberately untracked — the rest of `research/`
documents everything that was learned from it.

## Getting the files

Download the vendor package for the H-200 (NOX's support page, "Hummer H-200
LCD") and unpack the installer without running it:

```bash
unzip hummer_h-200_lcd-*.zip
innoextract -d research/windows-app <the .exe from the zip>
```

The interesting files end up in `app/`; move them here so the paths in
`METHOD.md` line up:

| File | Why it matters |
|---|---|
| `Hummer_Digital.exe` | PE32, ImageBase `0x400000`. All the VAs quoted in `PROTOCOL.md` and `METHOD.md` refer to this binary. |
| `hidapi.dll` | hidapi 0.8-era build (SetupAPI + `CreateFile`, `HidD_*` loaded lazily from `hid.dll`). Replaced by the logging shim in `tools/windows-proxy/`. |
| `HWiNFO32.dll` | Sensor backend, exports by ordinal only. Replaced by the fake in `tools/windows-proxy/`. |

## Reproducing the disassembly

```bash
objdump -D -b binary -m i386 --adjust-vma=0x400000 Hummer_Digital.exe > hummer_disasm.txt
objdump -D -b binary -m i386 --adjust-vma=0x10000000 hidapi.dll > hidapi_disasm.txt
```

None of this is needed to build or run `h200d` — the protocol is already
documented in [`../PROTOCOL.md`](../PROTOCOL.md).
