# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A native Linux daemon (`h200d.py`) that replaces the vendor's Windows-only
"Hummer Digital" app for the NOX Hummer H-200 liquid cooler's LCD. It reads
CPU/GPU temperature, CPU/GPU usage and fan RPM from sysfs/`/proc` and pushes
them to the display over a reverse-engineered USB HID protocol
(`VID:PID = 2E3C:0A12`, `/dev/hidraw*`). Pure Python 3 standard library, no
third-party dependencies, single file.

## Commands

```bash
./h200d.py --list          # show detected device + sensor sources, then exit
./h200d.py --once          # handshake, send one frame, print it, exit
./h200d.py -v              # run in foreground, verbose, cycling metrics
python3 -m py_compile h200d.py   # syntax check

python3 -m unittest discover -s tests      # the whole suite (~3 s, no hardware)
python3 -m unittest discover -s tests -v   # one line per test
python3 -m unittest tests.test_protocol    # a single module

sudo ./install.sh           # install daemon + udev rule + systemd unit, enable+restart it
sudo ./install.sh --uninstall
DESTDIR=/tmp/x ./install.sh # stage install under a fake root, no system changes, no root needed

./packaging/make-release.sh # build dist/h200d-<version>.tar.gz and smoke-test it
                             # (extracts the tarball, py_compiles it, runs install.sh
                             #  against a staging DESTDIR, checks uninstall cleans up)
```

Tests are plain `unittest`, stdlib only, and never touch real hardware: they
fake `/sys` and `/proc` (via the `h200d.SYSFS`/`h200d.PROC` constants) and stand
in for the LCD with a socketpair that speaks the real HID protocol
(`tests/support.py`). Run them after any change; `make-release.sh` runs them too
and refuses to build if they fail (`SKIP_TESTS=1` bypasses that, for debugging
the packaging only). There is no linter configured beyond ShellCheck in CI.

The release version is a single source of truth: `__version__` in `h200d.py`.
`make-release.sh` reads it to name the tarball, and
`.github/workflows/release.yml` refuses to publish a `v*` tag that does not
match it — bump `__version__` in the commit before tagging.

CI (`.github/workflows/ci.yml`, also reused by the release workflow) runs the
suite on Python 3.9/3.11/3.13, ShellCheck, `systemd-analyze verify`, `udevadm
verify`, the tarball build, and a real `sudo ./install.sh` + `--uninstall` on
the runner's live systemd. Anything that must hold before a release goes there,
not into a separate release-only step.

## Architecture

- **`h200d.py`** — everything: HID transport (`H200` class, raw `os.open`/
  `os.write`/`select`/`os.read` on the hidraw node, no hidapi), sensor
  discovery (`Sensors`, autodetected via `/sys/class/hwmon` chip names +
  labels, `/sys/class/drm/*/gpu_busy_percent`, `/proc/stat`), and the CLI/main
  loop. No internal module boundaries — it's meant to stay a single
  dependency-free script that `install.sh` copies verbatim into
  `/usr/local/bin`.
- **Protocol**: 65-byte HID reports. `0x10`→`0x11` is the hello/handshake
  (returns firmware version), `0x20`→`0x21` carries a sensor frame (metric
  flags, unit, temps/usages/fan RPM, ack byte). Full byte layout and how it
  was reverse-engineered from the Windows binary lives in
  `research/PROTOCOL.md` and `research/METHOD.md` — read those before
  changing anything in `H200._exchange`/`handshake`/`send`.
- **Reconnect behavior**: `open_device()`/`run()` in `h200d.py` block waiting
  for the device, survive unplug/replug (including the hidraw node number
  changing), and retry on I/O errors; `--retry 0` restores fail-fast
  behavior. Any protocol change must preserve this — the daemon runs unattended
  as a systemd service across suspend/resume and USB hiccups.
- **`install.sh`** supports two modes: real install (root, creates `h200`
  system user/group, udev rule, systemd unit, `systemctl restart` — never
  `enable --now`, since an upgrade must reload code even though the unit is
  already running) and `DESTDIR=` staging (no root, no system mutation) used
  by `make-release.sh` for smoke testing.
- **`packaging/make-release.sh`** hand-picks release contents (daemon +
  install.sh + packaging/ + research docs renamed to docs/) — deliberately
  excludes `venv/`, the extracted Windows app, and the capture rig. Docs
  install from `research/` in the git tree but from `docs/` in the extracted
  tarball; `install.sh` checks both locations.
- **`research/`** — the reverse-engineering trail: `NOTES.md` (diary),
  `METHOD.md` (Windows instrumentation rig used to capture traffic),
  `PROTOCOL.md` (decoded HID protocol spec), `FINDINGS_CAPTURE.md`,
  `USB_CAPTURE_PLAN.md`. Consult these before guessing at undocumented report
  IDs (`0xF0`/`0xF1` are known-unimplemented, see README "Known Issues").
- **`tests/`** — `support.py` holds the fakes (`FakeSysfs`, `FakeLcd`,
  `FakeSensors`); the rest are one module per concern: discovery, protocol,
  sensors, daemon flow, packaging. `FakeLcd.install()` swaps `os.open` so the
  daemon's real write/select/read path runs against a socketpair — do not
  replace it with mocks of `H200`, the point is to exercise the transport.
- **`tools/`** — helpers used only during reverse engineering (QEMU monitor
  client, minimal RFB/VNC client, a Windows-side hidapi logging proxy under
  `tools/windows-proxy/`), not part of the shipped daemon.

## Working in this repo

- Keep `h200d.py` dependency-free (stdlib only) and a single file — that's
  the point of the project (drop-in replacement, trivial to audit/install).
- The repo's working tree contains large local artifacts not meant for
  commits or releases: `venv/`, `windows10.qcow2`, `Windows.iso`,
  `captures/*.pcapng`, `research/windows-app/` (vendor binaries, not
  redistributable — see its own README), and secrets (`root_passwd.txt`,
  `vm_passwd.txt`, `/etc/sudoers.d/99-javi-nopasswd`). Never include these in
  a release tarball or commit; `.gitignore` and `make-release.sh` already
  exclude them — check both if adding new local-only files.
