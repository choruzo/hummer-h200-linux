#!/bin/bash
# Build the distributable tarball: extract it anywhere, run install.sh, done.
# The git tree carries a venv, the extracted Windows app and the capture rig;
# none of that belongs in a release, so this picks the files by hand.
set -euo pipefail

SRC=$(cd "$(dirname "$0")/.." && pwd)
# Single source of truth: h200d.py. A tarball named differently from what
# `h200d --version` reports is exactly the kind of thing nobody notices.
VERSION=${VERSION:-$(python3 -c "import re,io; print(re.search(r'__version__ = \"([^\"]+)\"', io.open('$SRC/h200d.py').read()).group(1))")}
NAME="h200d-$VERSION"
OUT="$SRC/dist"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

# Nothing gets built out of a tree that fails its own tests. SKIP_TESTS=1 is
# for debugging the packaging itself, not for cutting a release.
if [ "${SKIP_TESTS:-0}" != "1" ] && [ -d "$SRC/tests" ]; then
    echo "running the test suite"
    ( cd "$SRC" && python3 -m unittest discover -s tests -q )
fi

mkdir -p "$STAGE/$NAME/packaging" "$STAGE/$NAME/docs"
install -m755 "$SRC/h200d.py"                        "$STAGE/$NAME/"
install -m755 "$SRC/install.sh"                      "$STAGE/$NAME/"
install -m644 "$SRC/packaging/70-hummer-h200.rules"  "$STAGE/$NAME/packaging/"
install -m644 "$SRC/packaging/h200d.service"         "$STAGE/$NAME/packaging/"
install -m644 "$SRC/research/PROTOCOL.md"            "$STAGE/$NAME/docs/"
install -m644 "$SRC/research/METHOD.md"              "$STAGE/$NAME/docs/"

cat > "$STAGE/$NAME/README.md" <<EOF
# h200d $VERSION — NOX Hummer H-200 LCD for Linux

Feeds the display with CPU/GPU temperature, CPU/GPU usage and fan RPM read from
sysfs. Pure Python 3, no third-party modules. Needs systemd and a kernel with
hidraw (any modern distro).

## Install

    sudo ./install.sh

That installs \`h200d\` into /usr/local/bin, adds a udev rule so the display's
hidraw node belongs to a new \`h200\` system group, installs and enables
\`h200d.service\`, and drops these docs into /usr/local/share/doc/h200d.

Check it:

    systemctl status h200d
    journalctl -u h200d -f

Uninstall:

    sudo ./install.sh --uninstall

## Running it by hand

    sudo systemctl stop h200d
    sudo usermod -aG h200 \$USER      # then log out and back in
    h200d --list                     # detected device + the sensors it will use
    h200d -v                         # run in the foreground

Options: \`--metrics cpu-temp,cpu-usage,gpu-temp,gpu-usage,fan\`, \`--fahrenheit\`,
\`--interval\`, \`--rotate\`, \`--device\`, \`--retry\`, \`--once\`.

To change what the service shows, edit \`ExecStart=\` in
/etc/systemd/system/h200d.service (or drop in an override with
\`systemctl edit h200d\`) and \`systemctl restart h200d\`.

## Docs

- \`docs/PROTOCOL.md\` — the HID protocol (reports 0x10/0x11 and 0x20/0x21)
- \`docs/METHOD.md\` — how it was reverse engineered
EOF

mkdir -p "$OUT"
tar -czf "$OUT/$NAME.tar.gz" -C "$STAGE" "$NAME"

# A release that does not install is worse than no release: smoke-test the
# tarball the way a user would unpack it.
CHECK=$(mktemp -d)
tar -xzf "$OUT/$NAME.tar.gz" -C "$CHECK"
( cd "$CHECK/$NAME"
  bash -n install.sh
  python3 -m py_compile h200d.py
  for f in install.sh h200d.py packaging/70-hummer-h200.rules \
           packaging/h200d.service docs/PROTOCOL.md docs/METHOD.md README.md; do
      [ -f "$f" ] || { echo "missing from tarball: $f" >&2; exit 1; }
  done
  [ -x install.sh ] && [ -x h200d.py ] || { echo "lost the exec bits" >&2; exit 1; }

  # Run the real installer against a staging root: catches a broken install
  # line or a renamed file, without needing root or touching the system.
  root="$CHECK/root"
  DESTDIR="$root" ./install.sh >/dev/null
  for f in "$root/usr/local/bin/h200d" \
           "$root/etc/udev/rules.d/70-hummer-h200.rules" \
           "$root/etc/systemd/system/h200d.service" \
           "$root/usr/local/share/doc/h200d/PROTOCOL.md" \
           "$root/usr/local/share/doc/h200d/METHOD.md"; do
      [ -f "$f" ] || { echo "install.sh did not produce $f" >&2; exit 1; }
  done
  [ -x "$root/usr/local/bin/h200d" ] || { echo "h200d not executable" >&2; exit 1; }
  DESTDIR="$root" ./install.sh --uninstall
  [ -e "$root/usr/local/bin/h200d" ] && { echo "--uninstall left files behind" >&2; exit 1; }
  true
)
rm -rf "$CHECK"

# Checksums, so a downloaded tarball can be verified: sha256sum -c SHA256SUMS
( cd "$OUT" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256" \
    && cat ./*.tar.gz.sha256 > SHA256SUMS )

echo "$OUT/$NAME.tar.gz"
tar -tzf "$OUT/$NAME.tar.gz"
