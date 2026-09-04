#!/usr/bin/env python3
"""Minimal RFB (VNC) client for the QEMU console: screenshot + mouse/keyboard.

Usage:
  vnc.py shot out.png
  vnc.py click X Y [out.png]
  vnc.py dblclick X Y [out.png]
  vnc.py key <keysym-hex-or-name> [out.png]
  vnc.py type "text" [out.png]
"""
import socket, struct, sys, time
from PIL import Image

HOST, PORT = "127.0.0.1", 5901


class VNC:
    def __init__(self, host=HOST, port=PORT):
        self.s = socket.create_connection((host, port), timeout=10)
        self.s.settimeout(10)
        ver = self.recv(12)
        self.s.sendall(b"RFB 003.008\n")
        n = self.recv(1)[0]
        types = self.recv(n)
        if 1 not in types:
            raise SystemExit("no 'None' security type: %r" % types)
        self.s.sendall(b"\x01")
        res = struct.unpack(">I", self.recv(4))[0]
        if res != 0:
            raise SystemExit("auth failed: %d" % res)
        self.s.sendall(b"\x01")  # shared
        hdr = self.recv(24)
        self.w, self.h = struct.unpack(">HH", hdr[:4])
        (self.bpp, self.depth, self.big, self.true,
         self.rmax, self.gmax, self.bmax,
         self.rsh, self.gsh, self.bsh) = struct.unpack(">BBBBHHHBBB", hdr[4:17])
        nlen = struct.unpack(">I", hdr[20:24])[0]
        self.name = self.recv(nlen).decode("latin1")
        # QEMU already offers 32bpp true colour BGRA little-endian; sending a
        # SetPixelFormat here makes it stop answering, so keep the server format.
        if not (self.bpp == 32 and self.true and not self.big):
            raise SystemExit("unexpected pixel format bpp=%d true=%d big=%d"
                             % (self.bpp, self.true, self.big))
        # encodings: RAW(0), CopyRect(1), DesktopSize(-223)
        self.s.sendall(struct.pack(">BxH", 2, 3) +
                       struct.pack(">iii", 0, 1, -223))
        self.fb = Image.new("RGB", (self.w, self.h), (0, 0, 0))

    def recv(self, n):
        buf = b""
        while len(buf) < n:
            d = self.s.recv(n - len(buf))
            if not d:
                raise EOFError("connection closed")
            buf += d
        return buf

    def refresh(self, incremental=0):
        self.s.sendall(struct.pack(">BBHHHH", 3, incremental, 0, 0, self.w, self.h))
        deadline = time.time() + 8
        while time.time() < deadline:
            t = self.recv(1)[0]
            if t == 0:
                self._framebuffer_update()
                return
            elif t == 1:                       # SetColourMapEntries
                self.recv(5)
                n = struct.unpack(">H", self.recv(2))[0]
                self.recv(n * 6)
            elif t == 2:                       # Bell
                pass
            elif t == 3:                       # ServerCutText
                self.recv(3)
                n = struct.unpack(">I", self.recv(4))[0]
                self.recv(n)
            else:
                raise SystemExit("unknown server msg %d" % t)

    def _framebuffer_update(self):
        self.recv(1)
        nrect = struct.unpack(">H", self.recv(2))[0]
        for _ in range(nrect):
            x, y, w, h, enc = struct.unpack(">HHHHi", self.recv(12))
            if enc == 0:
                data = self.recv(w * h * 4)
                img = Image.frombytes("RGBA", (w, h), data, "raw", "BGRA")
                self.fb.paste(img.convert("RGB"), (x, y))
            elif enc == 1:
                sx, sy = struct.unpack(">HH", self.recv(4))
                self.fb.paste(self.fb.crop((sx, sy, sx + w, sy + h)), (x, y))
            elif enc == -223:
                self.w, self.h = w, h
                new = Image.new("RGB", (w, h), (0, 0, 0))
                new.paste(self.fb, (0, 0))
                self.fb = new
            else:
                raise SystemExit("unsupported encoding %d" % enc)

    def pointer(self, x, y, mask=0):
        self.s.sendall(struct.pack(">BBHH", 5, mask, x, y))

    def click(self, x, y, button=1, double=False):
        m = 1 << (button - 1)
        self.pointer(x, y, 0); time.sleep(0.1)
        for _ in range(2 if double else 1):
            self.pointer(x, y, m); time.sleep(0.06)
            self.pointer(x, y, 0); time.sleep(0.06)

    def key(self, sym, down=1):
        self.s.sendall(struct.pack(">BBxxI", 4, down, sym))

    def tap(self, sym):
        self.key(sym, 1); time.sleep(0.03); self.key(sym, 0); time.sleep(0.03)

    def type_text(self, text):
        for ch in text:
            self.tap(ord(ch))


KEYS = {"enter": 0xFF0D, "esc": 0xFF1B, "tab": 0xFF09, "space": 0x20,
        "left": 0xFF51, "up": 0xFF52, "right": 0xFF53, "down": 0xFF54,
        "backspace": 0xFF08, "delete": 0xFFFF, "f5": 0xFFC2}


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return
    v = VNC()
    cmd = a[0]
    out = None
    if cmd == "shot":
        out = a[1] if len(a) > 1 else "shot.png"
    elif cmd in ("click", "dblclick", "rclick"):
        x, y = int(a[1]), int(a[2])
        v.refresh(0)
        v.click(x, y, button=3 if cmd == "rclick" else 1, double=(cmd == "dblclick"))
        time.sleep(0.8)
        out = a[3] if len(a) > 3 else "shot.png"
    elif cmd == "key":
        v.refresh(0)
        sym = KEYS.get(a[1].lower(), None)
        if sym is None:
            sym = int(a[1], 16) if a[1].startswith("0x") else ord(a[1])
        v.tap(sym); time.sleep(0.8)
        out = a[2] if len(a) > 2 else "shot.png"
    elif cmd == "type":
        v.refresh(0)
        v.type_text(a[1]); time.sleep(0.8)
        out = a[2] if len(a) > 2 else "shot.png"
    else:
        print(__doc__); return
    v.refresh(0)
    v.fb.save(out)
    print("%s %dx%d -> %s" % (v.name, v.w, v.h, out))


if __name__ == "__main__":
    main()
