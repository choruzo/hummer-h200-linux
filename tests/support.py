"""Fakes for the h200d test suite: a sysfs tree and an LCD that answers.

Everything here is stdlib-only, like the daemon itself, and nothing touches the
real machine: no /sys, no /dev, no hardware. The one thing we do use is a real
socketpair, so H200 exercises its actual os.write/select/os.read path instead of
a mock that would happily agree with a broken implementation.
"""

import os
import socket
import struct
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import h200d  # noqa: E402


# --------------------------------------------------------------------------- #
# fake sysfs / proc
# --------------------------------------------------------------------------- #

class FakeSysfs:
    """A throwaway /sys + /proc tree; point h200d at it with install()."""

    def __init__(self, root):
        self.root = root
        self.sys = os.path.join(root, "sys")
        self.proc = os.path.join(root, "proc")
        self._hwmon = 0
        os.makedirs(self.proc)
        self.write_proc_stat(0, 0, 0, 0, 0)

    # -- installation ----------------------------------------------------- #

    def install(self, test):
        """Redirect h200d at this tree for the duration of `test`."""
        old_sys, old_proc = h200d.SYSFS, h200d.PROC
        h200d.SYSFS, h200d.PROC = self.sys, self.proc

        def restore():
            h200d.SYSFS, h200d.PROC = old_sys, old_proc

        test.addCleanup(restore)
        return self

    # -- builders --------------------------------------------------------- #

    def _write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        return path

    def add_hidraw(self, index, vid=h200d.VID, pid=h200d.PID, bus="0003",
                   uevent=None):
        """Create /sys/class/hidraw/hidrawN with the kernel's HID_ID line."""
        node = os.path.join(self.sys, "class", "hidraw", "hidraw%d" % index)
        if uevent is None:
            uevent = ("DRIVER=hid-generic\n"
                      "HID_ID=%s:%08X:%08X\n"
                      "HID_NAME=NOX Hummer H-200\n" % (bus, vid, pid))
        self._write(os.path.join(node, "device", "uevent"), uevent)
        return "/dev/hidraw%d" % index

    def add_bare_hidraw(self, index):
        """A hidraw node whose uevent cannot be read (unbound/racing device)."""
        os.makedirs(os.path.join(self.sys, "class", "hidraw",
                                 "hidraw%d" % index, "device"))

    def remove_hidraw(self, index):
        node = os.path.join(self.sys, "class", "hidraw", "hidraw%d" % index)
        for dirpath, _, files in os.walk(node, topdown=False):
            for name in files:
                os.unlink(os.path.join(dirpath, name))
            os.rmdir(dirpath)

    def add_hwmon(self, name, temps=(), fans=()):
        """temps: ((label|None, millidegrees), ...); fans: (rpm, ...)."""
        node = os.path.join(self.sys, "class", "hwmon", "hwmon%d" % self._hwmon)
        self._hwmon += 1
        self._write(os.path.join(node, "name"), name + "\n")
        for i, (label, value) in enumerate(temps, start=1):
            self._write(os.path.join(node, "temp%d_input" % i), "%d\n" % value)
            if label is not None:
                self._write(os.path.join(node, "temp%d_label" % i), label + "\n")
        for i, rpm in enumerate(fans, start=1):
            self._write(os.path.join(node, "fan%d_input" % i), "%d\n" % rpm)
        return node

    def add_drm_card(self, index, busy=None):
        card = os.path.join(self.sys, "class", "drm", "card%d" % index, "device")
        os.makedirs(card, exist_ok=True)
        if busy is not None:
            self._write(os.path.join(card, "gpu_busy_percent"), "%d\n" % busy)
        return card

    def write_proc_stat(self, user, nice, system, idle, iowait, extra=()):
        fields = [user, nice, system, idle, iowait] + list(extra)
        self._write(os.path.join(self.proc, "stat"),
                    "cpu  " + " ".join(str(x) for x in fields) + "\n"
                    "cpu0 " + " ".join(str(x) for x in fields) + "\n")


# --------------------------------------------------------------------------- #
# fake display
# --------------------------------------------------------------------------- #

class Frame:
    """One decoded 0x20 sensor report, as the display would see it."""

    FIELDS = ("metric", "unit", "alarm", "pad", "cpu_temp", "cpu_usage",
              "gpu_temp", "gpu_usage", "fan_rpm")

    def __init__(self, report):
        self.raw = report
        values = struct.unpack(">BBBBhBhBH", report[1:13])
        for name, value in zip(self.FIELDS, values):
            setattr(self, name, value)

    def __repr__(self):
        return "Frame(%s)" % ", ".join(
            "%s=%r" % (f, getattr(self, f)) for f in self.FIELDS)


class FakeLcd:
    """An H-200 that speaks the real protocol over a socketpair.

    Knobs for the failure paths: `ack` (0 makes the device reject frames),
    `mute` (answers nothing, so H200 must time out), `bad_reply` (wrong report
    id) and unplug() (peer close, i.e. the cable comes out mid-frame).
    """

    def __init__(self, firmware=(1, 3), ack=1, mute=False, bad_reply=False):
        self.firmware = firmware
        self.ack = ack
        self.mute = mute
        self.bad_reply = bad_reply
        self.requests = []          # every 65-byte report we received
        self.frames = []            # the 0x20 ones, decoded
        self.opens = 0              # how many times the node was opened
        self._host, self._dev = socket.socketpair(socket.AF_UNIX,
                                                  socket.SOCK_DGRAM)
        self._client_fd = self._host.detach()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    # -- plumbing --------------------------------------------------------- #

    def install(self, test, path="/dev/hidraw0"):
        """Make h200d's os.open(path) hand out a connection to this display."""
        self.path = path
        real_open = os.open

        def fake_open(name, *a, **kw):
            if name == path:
                if self._client_fd is None:
                    raise OSError(19, "No such device")
                self.opens += 1
                return os.dup(self._client_fd)
            return real_open(name, *a, **kw)

        h200d.os.open = fake_open
        test.addCleanup(setattr, h200d.os, "open", real_open)
        test.addCleanup(self.close)
        return self

    def close(self):
        self.unplug()
        if self._client_fd is not None:
            os.close(self._client_fd)
            self._client_fd = None

    def unplug(self):
        """Yank the cable: reads return EOF, further opens fail with ENODEV."""
        with self._lock:
            if self._dev is not None:
                self._dev.close()
                self._dev = None

    # -- the firmware ----------------------------------------------------- #

    def _serve(self):
        while True:
            with self._lock:
                dev = self._dev
            if dev is None:
                return
            try:
                request = dev.recv(4096)
            except OSError:
                return
            if not request:
                return
            self.requests.append(request)
            reply = self._reply_to(request)
            if reply is None:
                continue
            try:
                with self._lock:
                    if self._dev is not None:
                        self._dev.send(reply)
            except OSError:
                return

    def _reply_to(self, request):
        if self.mute:
            return None
        reply = bytearray(64)
        if request[0] == h200d.REPORT_HELLO:
            reply[0] = 0x99 if self.bad_reply else h200d.REPLY_HELLO
            reply[1] = request[1]
            reply[2], reply[3] = self.firmware
        elif request[0] == h200d.REPORT_DATA:
            self.frames.append(Frame(request))
            reply[0] = 0x99 if self.bad_reply else h200d.REPLY_DATA
            reply[1] = request[1]
            reply[2] = self.ack
        else:
            return None
        return bytes(reply)


class FakeSensors:
    """Stands in for h200d.Sensors with values the test picks."""

    def __init__(self, **values):
        self.values = {"cpu_temp": 0.0, "gpu_temp": 0.0, "fan_rpm": 0,
                       "cpu_usage": 0.0, "gpu_usage": 0}
        self.values.update(values)
        self.reads = 0

    def read(self):
        self.reads += 1
        return dict(self.values)

    def describe(self):
        return [(k, "fake") for k in sorted(self.values)]


class Args:
    """A stand-in for the argparse namespace run() consumes."""

    def __init__(self, **kw):
        self.rotate = 3.0
        self.interval = 0.0
        self.once = False
        self.verbose = False
        self.device = None
        self.retry = 5.0
        self.__dict__.update(kw)
