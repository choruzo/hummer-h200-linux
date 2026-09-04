#!/bin/bash
# Install h200d: the daemon, its udev rule and a systemd service.
#
#   sudo ./install.sh            install and enable the service
#   sudo ./install.sh --uninstall remove everything this script installed
set -euo pipefail

PREFIX=${PREFIX:-/usr/local}
BIN="$PREFIX/bin/h200d"
DOC="$PREFIX/share/doc/h200d"
RULE=/etc/udev/rules.d/70-hummer-h200.rules
UNIT=/etc/systemd/system/h200d.service
SRC=$(cd "$(dirname "$0")" && pwd)

if [ "$(id -u)" -ne 0 ]; then
    echo "install.sh: run me as root (sudo ./install.sh)" >&2
    exit 1
fi

uninstall() {
    systemctl disable --now h200d.service 2>/dev/null || true
    rm -f "$UNIT" "$RULE" "$BIN"
    rm -rf "$DOC"
    systemctl daemon-reload
    udevadm control --reload-rules && udevadm trigger
    echo "Removed. The 'h200' group was left in place; delete it with:"
    echo "  groupdel h200"
}

if [ "${1:-}" = "--uninstall" ]; then
    uninstall
    exit 0
fi

getent group h200 >/dev/null || { groupadd --system h200; echo "created group h200"; }
id -u h200 >/dev/null 2>&1 || {
    useradd --system --gid h200 --no-create-home --shell /usr/sbin/nologin h200
    echo "created user h200"
}

install -Dm755 "$SRC/h200d.py" "$BIN"
install -Dm644 "$SRC/packaging/70-hummer-h200.rules" "$RULE"
install -Dm644 "$SRC/packaging/h200d.service" "$UNIT"
install -Dm644 "$SRC/research/PROTOCOL.md" "$DOC/PROTOCOL.md"
install -Dm644 "$SRC/research/METHOD.md" "$DOC/METHOD.md"

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
echo "To drive the display by hand instead, stop the service and run '$BIN -v'."
echo "Add yourself to the h200 group (or rely on uaccess at your seat) first:"
echo "  sudo usermod -aG h200 \$USER"
