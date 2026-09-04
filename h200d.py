#!/usr/bin/env python3
"""h200d - feed a NOX Hummer H-200 LCD with host sensor readings.

Speaks the HID protocol documented in research/PROTOCOL.md over /dev/hidrawN.
No third-party dependencies: it reads sensors from sysfs and /proc and writes
raw numbered HID reports.

  ./h200d.py --list                 show the sensors it would use and exit
  ./h200d.py --once                 handshake, send one frame, print the ACK
  ./h200d.py                        run until interrupted
"""

import argparse
import glob
import os
import re
import select
import struct
import sys
import time

VID, PID = 0x2E3C, 0x0A12

REPORT_HELLO = 0x10
REPORT_DATA = 0x20
REPLY_HELLO = 0x11
REPLY_DATA = 0x21

# `type` bits: which metric the LCD shows, and which alarm bit belongs to it.
M_CPU_TEMP = 0x01
M_CPU_USAGE = 0x02
M_GPU_TEMP = 0x04
M_GPU_USAGE = 0x08
M_FAN = 0x10

UNIT_CELSIUS = 0
UNIT_FAHRENHEIT = 1


# --------------------------------------------------------------------------- #
# device
# --------------------------------------------------------------------------- #

def find_hidraw():
    """Return the /dev/hidrawN path of the H-200, or None."""
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        uevent = os.path.join(node, "device", "uevent")
        try:
            with open(uevent) as f:
                text = f.read()
        except OSError:
            continue
        m = re.search(r"^HID_ID=\w+:0*([0-9A-Fa-f]+):0*([0-9A-Fa-f]+)$",
                      text, re.M)
        if m and (int(m.group(1), 16), int(m.group(2), 16)) == (VID, PID):
            return "/dev/" + os.path.basename(node)
    return None


class H200:
    #: seconds to wait for the device's reply before giving up on the exchange
    READ_TIMEOUT = 2.0

    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR)
        self.path = path

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass

    def _exchange(self, report_id, payload, expect):
        """Write a 65-byte report and read the device's reply."""
        buf = bytearray(65)
        buf[0] = report_id
        buf[1:1 + len(payload)] = payload
        os.write(self.fd, bytes(buf))
        # A wedged or half-unplugged device would block os.read() forever.
        if not select.select([self.fd], [], [], self.READ_TIMEOUT)[0]:
            raise IOError("timed out waiting for a reply to report 0x%02X"
                          % report_id)
        reply = os.read(self.fd, 64)
        if not reply or reply[0] != expect:
            raise IOError("unexpected reply %s to report 0x%02X"
                          % (reply[:4].hex() if reply else "(empty)", report_id))
        return reply

    def handshake(self):
        """Identify the device; returns the firmware version string."""
        reply = self._exchange(REPORT_HELLO, b"\x01", REPLY_HELLO)
        return "%d.%d" % (reply[2], reply[3])

    def send(self, metric, unit, cpu_temp, cpu_usage, gpu_temp, gpu_usage,
             fan_rpm, alarm=0):
        payload = struct.pack(
            ">BBBBhBhBH",
            metric, unit, alarm, 0,
            clamp16(cpu_temp), clamp8(cpu_usage),
            clamp16(gpu_temp), clamp8(gpu_usage),
            clampu16(fan_rpm),
        )
        reply = self._exchange(REPORT_DATA, payload, REPLY_DATA)
        if reply[2] == 0:
            raise IOError("device rejected the frame (ack=0)")
        return reply


def clamp16(v):
    return max(-32768, min(32767, int(round(v))))


def clampu16(v):
    return max(0, min(65535, int(round(v))))


def clamp8(v):
    return max(0, min(255, int(round(v))))


# --------------------------------------------------------------------------- #
# sensors
# --------------------------------------------------------------------------- #

def read_int(path):
    with open(path) as f:
        return int(f.read().strip())


def hwmon_chips():
    for node in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        try:
            with open(os.path.join(node, "name")) as f:
                yield node, f.read().strip()
        except OSError:
            continue


def find_temp(chip_names, labels=None):
    """First tempN_input of a chip in `chip_names` whose label matches."""
    for node, name in hwmon_chips():
        if name not in chip_names:
            continue
        for inp in sorted(glob.glob(os.path.join(node, "temp*_input"))):
            if labels:
                label_path = inp.replace("_input", "_label")
                try:
                    with open(label_path) as f:
                        if f.read().strip() not in labels:
                            continue
                except OSError:
                    continue
            return inp
    return None


def find_fan(chip_names):
    for node, name in hwmon_chips():
        if name not in chip_names:
            continue
        fans = sorted(glob.glob(os.path.join(node, "fan*_input")))
        if fans:
            return fans[0]
    return None


def find_gpu_busy():
    for path in sorted(glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")):
        return path
    return None


class CpuUsage:
    """Percentage busy since the previous call, from /proc/stat."""

    def __init__(self):
        self.prev = self._sample()

    @staticmethod
    def _sample():
        with open("/proc/stat") as f:
            parts = [int(x) for x in f.readline().split()[1:]]
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
        return sum(parts), idle

    def read(self):
        total, idle = self._sample()
        dt, di = total - self.prev[0], idle - self.prev[1]
        self.prev = (total, idle)
        if dt <= 0:
            return 0.0
        return 100.0 * (dt - di) / dt


class Sensors:
    """Where each value comes from on this machine."""

    CPU_CHIPS = ("k10temp", "coretemp", "zenpower")
    CPU_LABELS = ("Tctl", "Tdie", "Package id 0")
    GPU_CHIPS = ("amdgpu", "nouveau", "xe", "i915")
    GPU_LABELS = ("edge", "junction", "pkg")

    def __init__(self):
        self.cpu_temp = find_temp(self.CPU_CHIPS, self.CPU_LABELS) \
            or find_temp(self.CPU_CHIPS)
        self.gpu_temp = find_temp(self.GPU_CHIPS, self.GPU_LABELS) \
            or find_temp(self.GPU_CHIPS)
        self.fan = find_fan(self.GPU_CHIPS) or find_fan(("nct6775", "it87"))
        self.gpu_busy = find_gpu_busy()
        self.cpu_usage = CpuUsage()

    def read(self):
        return {
            "cpu_temp": read_int(self.cpu_temp) / 1000.0 if self.cpu_temp else 0.0,
            "gpu_temp": read_int(self.gpu_temp) / 1000.0 if self.gpu_temp else 0.0,
            "fan_rpm": read_int(self.fan) if self.fan else 0,
            "cpu_usage": self.cpu_usage.read(),
            "gpu_usage": read_int(self.gpu_busy) if self.gpu_busy else 0,
        }

    def describe(self):
        return [
            ("cpu_temp", self.cpu_temp),
            ("gpu_temp", self.gpu_temp),
            ("fan_rpm", self.fan),
            ("gpu_usage", self.gpu_busy),
            ("cpu_usage", "/proc/stat"),
        ]


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

METRICS = {
    "cpu-temp": M_CPU_TEMP,
    "cpu-usage": M_CPU_USAGE,
    "gpu-temp": M_GPU_TEMP,
    "gpu-usage": M_GPU_USAGE,
    "fan": M_FAN,
}


def log(msg):
    print("h200: " + msg, flush=True)


def open_device(explicit, retry_delay):
    """Block until the display is reachable; returns an open H200."""
    warned = False
    while True:
        path = explicit or find_hidraw()
        if path:
            dev = None
            try:
                dev = H200(path)
                log("%s, firmware %s" % (path, dev.handshake()))
                return dev
            except OSError as e:
                if dev is not None:
                    dev.close()
                if not warned:
                    log("cannot talk to %s (%s), retrying" % (path, e))
                    warned = True
        elif not warned:
            log("waiting for a %04x:%04x device" % (VID, PID))
            warned = True
        time.sleep(retry_delay)


def run(dev, sensors, cycle, unit, args):
    """Push frames until the device goes away; raises OSError if it does."""
    index, next_rotate = 0, time.monotonic() + args.rotate
    while True:
        s = sensors.read()
        ct, gt = s["cpu_temp"], s["gpu_temp"]
        if unit == UNIT_FAHRENHEIT:
            ct, gt = ct * 9 / 5 + 32, gt * 9 / 5 + 32
        dev.send(cycle[index], unit, ct, s["cpu_usage"], gt,
                 s["gpu_usage"], s["fan_rpm"])
        if args.verbose or args.once:
            print("metric=0x%02X cpu=%.0f%s cpu%%=%.0f gpu=%.0f%s gpu%%=%d "
                  "fan=%d" % (cycle[index], ct, "F" if unit else "C",
                              s["cpu_usage"], gt, "F" if unit else "C",
                              s["gpu_usage"], s["fan_rpm"]), flush=True)
        if args.once:
            return
        now = time.monotonic()
        if now >= next_rotate:
            index = (index + 1) % len(cycle)
            next_rotate = now + args.rotate
        time.sleep(args.interval)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", help="hidraw node (default: autodetect)")
    ap.add_argument("--fahrenheit", action="store_true",
                    help="send temperatures in Fahrenheit")
    ap.add_argument("--metrics", default="cpu-temp,gpu-temp,fan",
                    help="metrics to cycle on the LCD (comma separated: %s)"
                         % ",".join(METRICS))
    ap.add_argument("--interval", type=float, default=0.5,
                    help="seconds between frames (default 0.5)")
    ap.add_argument("--rotate", type=float, default=3.0,
                    help="seconds each metric stays on screen (default 3)")
    ap.add_argument("--list", action="store_true",
                    help="show detected device and sensors, then exit")
    ap.add_argument("--once", action="store_true",
                    help="send a single frame and exit")
    ap.add_argument("--retry", type=float, default=5.0,
                    help="seconds between reconnect attempts (default 5, "
                         "0 disables waiting and reconnecting)")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    sensors = Sensors()

    if args.list:
        print("device: %s" % (args.device or find_hidraw() or "NOT FOUND"))
        for name, src in sensors.describe():
            print("  %-10s %s" % (name, src or "(none)"))
        print("  readings:", sensors.read())
        return 0

    try:
        cycle = [METRICS[m.strip()] for m in args.metrics.split(",") if m.strip()]
    except KeyError as e:
        print("h200: unknown metric %s" % e, file=sys.stderr)
        return 2
    if not cycle:
        print("h200: --metrics is empty", file=sys.stderr)
        return 2

    unit = UNIT_FAHRENHEIT if args.fahrenheit else UNIT_CELSIUS

    if args.retry <= 0:
        path = args.device or find_hidraw()
        if not path:
            print("h200: no %04x:%04x hidraw node found" % (VID, PID),
                  file=sys.stderr)
            return 1
        dev = None
        try:
            dev = H200(path)
            log("%s, firmware %s" % (path, dev.handshake()))
            run(dev, sensors, cycle, unit, args)
        except KeyboardInterrupt:
            pass
        except OSError as e:
            print("h200: %s: %s" % (path, e), file=sys.stderr)
            return 1
        finally:
            if dev is not None:
                dev.close()
        return 0

    # Default: survive an unplug, a replug under a different hidraw node, and
    # a display that is simply not there yet at boot.
    try:
        while True:
            dev = open_device(args.device, args.retry)
            try:
                run(dev, sensors, cycle, unit, args)
                return 0                       # only reached with --once
            except OSError as e:
                log("lost the display (%s), reconnecting" % e)
            finally:
                dev.close()
            time.sleep(args.retry)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # `h200d --list | head` closes our stdout; die quietly like any other
        # well-behaved CLI instead of dumping a traceback.
        try:
            sys.stdout.close()
        except BrokenPipeError:
            pass
        os._exit(0)
