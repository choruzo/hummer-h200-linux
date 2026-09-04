#!/bin/bash
# Start Windows VM with IDE disk, USB passthrough, and network

ISO="/mnt/datos/Datos/hummer-h200-linux/Windows.iso"
DISK="/mnt/datos/Datos/hummer-h200-linux/windows10.qcow2"

qemu-system-x86_64 \
  -enable-kvm \
  -m 4096 \
  -smp 4 \
  -cpu host \
  -drive file=$DISK,format=qcow2,if=ide \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device e1000,netdev=net0 \
  -device qemu-xhci \
  -device usb-host,id=h200,hostbus=1,hostport=11 \
  -device usb-tablet \
  -boot d \
  -vnc :1 \
  -display none \
  -qmp unix:/tmp/h200-qmp.sock,server,nowait \
  -daemonize

echo "VM started."
echo "VNC: vncviewer <IP-DEL-SERVIDOR>:5901"
echo "SSH: ssh -p 2222 capturer@<IP-DEL-SERVIDOR>"
