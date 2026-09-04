#!/bin/bash
# Install h200d: the daemon, its udev rule and a systemd service.
#
#   sudo ./install.sh             install and enable the service
#   sudo ./install.sh --uninstall remove everything this script installed
#
# DESTDIR=/tmp/x ./install.sh     stage the files under /tmp/x without touching
#                                 the system: no user is created, no udev or
#                                 systemd command runs, root is not required.
#                                 Used by packaging/make-release.sh to test.
set -euo pipefail

DESTDIR=${DESTDIR:-}
PREFIX=${PREFIX:-/usr/local}
BIN="$DESTDIR$PREFIX/bin/h200d"
DOC="$DESTDIR$PREFIX/share/doc/h200d"
RULE="$DESTDIR/etc/udev/rules.d/70-hummer-h200.rules"
UNIT="$DESTDIR/etc/systemd/system/h200d.service"
SRC=$(cd "$(dirname "$0")" && pwd)

if [ -z "$DESTDIR" ] && [ "$(id -u)" -ne 0 ]; then
    echo "install.sh: run me as root (sudo ./install.sh)" >&2
    exit 1
fi

uninstall() {
    systemctl disable --now h200d.service 2>/dev/null || true
    rm -f "$UNIT" "$RULE" "$BIN"
    rm -rf "$DOC"
    systemctl daemon-reload
    udevadm control --reload-rules && udevadm trigger
    echo "Removed. The 'h200' user and group were left in place; delete them with:"
    echo "  userdel h200 && groupdel h200"
}

if [ "${1:-}" = "--uninstall" ]; then
    [ -n "$DESTDIR" ] && { rm -f "$UNIT" "$RULE" "$BIN"; rm -rf "$DOC"; exit 0; }
    uninstall
    exit 0
fi

for f in h200d.py packaging/70-hummer-h200.rules packaging/h200d.service; do
    [ -f "$SRC/$f" ] || { echo "install.sh: missing $f next to this script" >&2; exit 1; }
done

python3 -c 'import sys; sys.exit(sys.version_info < (3, 6))' \
    || { echo "install.sh: python3 >= 3.6 required" >&2; exit 1; }

if [ -z "$DESTDIR" ]; then
    command -v systemctl >/dev/null || { echo "install.sh: systemd required" >&2; exit 1; }
    getent group h200 >/dev/null || { groupadd --system h200; echo "created group h200"; }
    id -u h200 >/dev/null 2>&1 || {
        useradd --system --gid h200 --no-create-home --shell /usr/sbin/nologin h200
        echo "created user h200"
    }
fi

install -Dm755 "$SRC/h200d.py" "$BIN"
install -Dm644 "$SRC/packaging/70-hummer-h200.rules" "$RULE"
install -Dm644 "$SRC/packaging/h200d.service" "$UNIT"

# Docs live in research/ in the git tree and in docs/ in the release tarball.
for doc in PROTOCOL.md METHOD.md; do
    for dir in research docs; do
        [ -f "$SRC/$dir/$doc" ] && install -Dm644 "$SRC/$dir/$doc" "$DOC/$doc" && break
    done
done

if [ -n "$DESTDIR" ]; then
    echo "Staged under $DESTDIR (nothing on this system was touched)."
    exit 0
fi

# The old rule from the research phase made the node world-writable; the new one
# supersedes it and leaving both would keep MODE 0666 in effect.
if [ -f /etc/udev/rules.d/70-hummer-h200-udev.rules ]; then
    rm -f /etc/udev/rules.d/70-hummer-h200-udev.rules
    echo "removed the old 70-hummer-h200-udev.rules (MODE 0666)"
fi

udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw --subsystem-match=usb
systemctl daemon-reload
systemctl enable --now h200d.service

echo
echo "Installed. Check it with:"
echo "  systemctl status h200d"
echo "  journalctl -u h200d -f"
echo
echo "To drive the display by hand instead, stop the service and run '$PREFIX/bin/h200d -v'."
echo "Add yourself to the h200 group (or rely on uaccess at your seat) first:"
echo "  sudo usermod -aG h200 \$USER"
