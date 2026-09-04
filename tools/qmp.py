#!/usr/bin/env python3
"""QMP helper for the H-200 capture VM.

  qmp.py shot out.png            screendump the guest console
  qmp.py move X Y                move the absolute pointer
  qmp.py click X Y [btn]         move + click (btn: left/right/middle)
  qmp.py dblclick X Y
  qmp.py key K [K ...]           send-key (qcode names, e.g. ret, tab, esc)
  qmp.py cmd '<json>'            raw QMP command
  qmp.py del | add               detach / re-attach the H-200 usb-host device
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

SOCK = "/tmp/h200-qmp.sock"
# The guest console is 1024x768; absolute axes are reported in 0..32767.
GW, GH = 1024, 768
ABS = 32767


class Qmp:
    def __init__(self, path=SOCK):
        self.c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.c.settimeout(15)
        self.c.connect(path)
        self.f = self.c.makefile("rw")
        self.f.readline()                      # greeting
        self.cmd({"execute": "qmp_capabilities"})

    def cmd(self, obj):
        self.f.write(json.dumps(obj) + "\n")
        self.f.flush()
        while True:
            line = self.f.readline()
            if not line:
                raise SystemExit("qmp closed")
            r = json.loads(line)
            if "event" in r:                   # ignore async events
                continue
            return r

    def events(self, *evs):
        self.cmd({"execute": "input-send-event", "arguments": {"events": list(evs)}})

    def move(self, x, y):
        self.events(
            {"type": "abs", "data": {"axis": "x", "value": int(x * ABS / GW)}},
            {"type": "abs", "data": {"axis": "y", "value": int(y * ABS / GH)}},
        )

    def click(self, x, y, button="left", double=False):
        self.move(x, y)
        time.sleep(0.15)
        for _ in range(2 if double else 1):
            self.events({"type": "btn", "data": {"down": True, "button": button}})
            time.sleep(0.05)
            self.events({"type": "btn", "data": {"down": False, "button": button}})
            time.sleep(0.08)

    def keys(self, names):
        self.cmd({"execute": "send-key", "arguments": {
            "keys": [{"type": "qcode", "data": n} for n in names]}})

    def shot(self, out):
        ppm = tempfile.mktemp(suffix=".ppm", dir="/tmp")
        r = self.cmd({"execute": "screendump", "arguments": {"filename": ppm}})
        if "error" in r:
            raise SystemExit(r["error"])
        if out.lower().endswith(".png"):
            from PIL import Image
            Image.open(ppm).save(out)
            os.unlink(ppm)
        else:
            os.replace(ppm, out)
        return out


USB_DEV = {"driver": "usb-host", "id": "h200", "hostbus": 1, "hostport": "11"}


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    q = Qmp()
    op = a[0]
    if op == "shot":
        out = a[1] if len(a) > 1 else "shot.png"
        print(q.shot(out))
    elif op == "move":
        q.move(int(a[1]), int(a[2]))
    elif op in ("click", "dblclick"):
        btn = a[3] if len(a) > 3 else "left"
        q.click(int(a[1]), int(a[2]), btn, double=(op == "dblclick"))
    elif op == "key":
        q.keys(a[1:])
    elif op == "cmd":
        print(json.dumps(q.cmd(json.loads(a[1])), indent=2))
    elif op == "del":
        print(q.cmd({"execute": "device_del", "arguments": {"id": "h200"}}))
    elif op == "add":
        print(q.cmd({"execute": "device_add", "arguments": USB_DEV}))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
