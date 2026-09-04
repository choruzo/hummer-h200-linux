"""Phase 12: the whole daemon flow, from CLI arguments to bytes on the wire.

Sensors → frame → HID exchange → rotation → unplug → reconnect, all against the
fake display. Nothing here needs the real LCD.
"""

import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from support import Args, FakeLcd, FakeSensors, FakeSysfs, h200d


class RunLoop(unittest.TestCase):
    """run(): sensors in, frames out."""

    def setUp(self):
        self.lcd = FakeLcd().install(self)
        self.dev = h200d.H200(self.lcd.path)
        self.addCleanup(self.dev.close)

    def test_once_sends_exactly_one_frame(self):
        sensors = FakeSensors(cpu_temp=52.4, cpu_usage=37.2, gpu_temp=61.0,
                              gpu_usage=42, fan_rpm=1450)
        with redirect_stdout(io.StringIO()):
            h200d.run(self.dev, sensors, [h200d.M_CPU_TEMP],
                      h200d.UNIT_CELSIUS, Args(once=True))
        self.assertEqual(len(self.lcd.frames), 1)
        frame = self.lcd.frames[0]
        self.assertEqual(frame.metric, h200d.M_CPU_TEMP)
        self.assertEqual(frame.unit, h200d.UNIT_CELSIUS)
        self.assertEqual(frame.cpu_temp, 52)
        self.assertEqual(frame.cpu_usage, 37)
        self.assertEqual(frame.gpu_temp, 61)
        self.assertEqual(frame.gpu_usage, 42)
        self.assertEqual(frame.fan_rpm, 1450)

    def test_fahrenheit_conversion_happens_on_the_wire(self):
        sensors = FakeSensors(cpu_temp=100.0, gpu_temp=0.0)
        with redirect_stdout(io.StringIO()):
            h200d.run(self.dev, sensors, [h200d.M_CPU_TEMP],
                      h200d.UNIT_FAHRENHEIT, Args(once=True))
        frame = self.lcd.frames[0]
        self.assertEqual(frame.unit, h200d.UNIT_FAHRENHEIT)
        self.assertEqual(frame.cpu_temp, 212)
        self.assertEqual(frame.gpu_temp, 32)

    def test_a_long_rotate_keeps_the_same_metric_on_screen(self):
        cycle = [h200d.M_CPU_TEMP, h200d.M_GPU_TEMP, h200d.M_FAN]
        sensors = FakeSensors()
        real_sleep = h200d.time.sleep
        count = [0]

        def stop_after_five(seconds):
            count[0] += 1
            if count[0] >= 5:
                raise KeyboardInterrupt

        h200d.time.sleep = stop_after_five
        self.addCleanup(setattr, h200d.time, "sleep", real_sleep)
        with self.assertRaises(KeyboardInterrupt):
            h200d.run(self.dev, sensors, cycle, h200d.UNIT_CELSIUS,
                      Args(rotate=3600.0, interval=0.0))
        self.assertEqual([f.metric for f in self.lcd.frames],
                         [h200d.M_CPU_TEMP] * 5)

    def test_rotation_advances_over_time(self):
        cycle = [h200d.M_CPU_TEMP, h200d.M_GPU_TEMP, h200d.M_FAN]
        sensors = FakeSensors()
        args = Args(rotate=0.0, interval=0.0)
        frames_wanted = 6

        real_sleep = h200d.time.sleep
        count = [0]

        def stop_after_six(seconds):
            count[0] += 1
            if count[0] >= frames_wanted:
                raise KeyboardInterrupt
            real_sleep(0)

        h200d.time.sleep = stop_after_six
        self.addCleanup(setattr, h200d.time, "sleep", real_sleep)
        with self.assertRaises(KeyboardInterrupt):
            h200d.run(self.dev, sensors, cycle, h200d.UNIT_CELSIUS, args)

        sent = [f.metric for f in self.lcd.frames]
        self.assertEqual(sent[:6], cycle * 2)

    def test_sensors_are_reread_for_every_frame(self):
        sensors = FakeSensors()
        real_sleep = h200d.time.sleep
        count = [0]

        def stop_after_three(seconds):
            count[0] += 1
            if count[0] >= 3:
                raise KeyboardInterrupt

        h200d.time.sleep = stop_after_three
        self.addCleanup(setattr, h200d.time, "sleep", real_sleep)
        with self.assertRaises(KeyboardInterrupt):
            h200d.run(self.dev, sensors, [h200d.M_FAN], h200d.UNIT_CELSIUS,
                      Args())
        self.assertEqual(sensors.reads, 3)
        self.assertEqual(len(self.lcd.frames), 3)

    def test_a_disconnect_mid_loop_surfaces_as_oserror(self):
        sensors = FakeSensors()
        real_sleep = h200d.time.sleep
        h200d.time.sleep = lambda s: self.lcd.unplug()
        self.addCleanup(setattr, h200d.time, "sleep", real_sleep)
        with self.assertRaises(OSError):
            h200d.run(self.dev, sensors, [h200d.M_FAN], h200d.UNIT_CELSIUS,
                      Args())


class Reconnection(unittest.TestCase):
    """open_device() waits for the display and copes with a renumbered node."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fs = FakeSysfs(tmp.name).install(self)
        self.lcd = FakeLcd().install(self, path="/dev/hidraw3")
        self.slept = []
        real_sleep = h200d.time.sleep
        self.addCleanup(setattr, h200d.time, "sleep", real_sleep)

    def patch_sleep(self, hook):
        def sleep(seconds):
            self.slept.append(seconds)
            hook(len(self.slept))
        h200d.time.sleep = sleep

    def test_waits_until_the_display_shows_up(self):
        self.patch_sleep(lambda n: self.fs.add_hidraw(3) if n == 2 else None)
        with redirect_stdout(io.StringIO()) as out:
            dev = h200d.open_device(None, 0.01)
        self.addCleanup(dev.close)
        self.assertEqual(len(self.slept), 2)
        self.assertIn("waiting for a 2e3c:0a12 device", out.getvalue())
        self.assertIn("firmware 1.3", out.getvalue())

    def test_only_warns_once_while_waiting(self):
        self.patch_sleep(lambda n: self.fs.add_hidraw(3) if n == 4 else None)
        with redirect_stdout(io.StringIO()) as out:
            dev = h200d.open_device(None, 0.001)
        self.addCleanup(dev.close)
        self.assertEqual(out.getvalue().count("waiting for"), 1)

    def test_replug_under_a_different_node(self):
        self.fs.add_hidraw(0)          # stale node, nothing answers on it
        self.patch_sleep(lambda n: (self.fs.remove_hidraw(0),
                                    self.fs.add_hidraw(3)) if n == 1 else None)
        with redirect_stdout(io.StringIO()) as out:
            dev = h200d.open_device(None, 0.001)
        self.addCleanup(dev.close)
        self.assertEqual(dev.path, "/dev/hidraw3")
        self.assertIn("cannot talk to /dev/hidraw0", out.getvalue())

    def test_an_explicit_device_is_used_verbatim(self):
        with redirect_stdout(io.StringIO()):
            dev = h200d.open_device("/dev/hidraw3", 0.01)
        self.addCleanup(dev.close)
        self.assertEqual(dev.path, "/dev/hidraw3")
        self.assertEqual(self.slept, [])


class Cli(unittest.TestCase):
    """main(): argument handling and the two service-shaped code paths."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fs = FakeSysfs(tmp.name).install(self)
        self.fs.add_hwmon("k10temp", temps=[("Tctl", 52000)])
        self.fs.add_hwmon("amdgpu", temps=[("edge", 61000)], fans=[1450])
        self.fs.add_drm_card(0, busy=42)

    def main(self, *argv):
        old = h200d.sys.argv
        h200d.sys.argv = ["h200d"] + list(argv)
        self.addCleanup(setattr, h200d.sys, "argv", old)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = h200d.main()
        return code, out.getvalue(), err.getvalue()

    def test_list_reports_sources_without_touching_the_device(self):
        code, out, _ = self.main("--list")
        self.assertEqual(code, 0)
        self.assertIn("device: NOT FOUND", out)
        self.assertIn("cpu_temp", out)
        self.assertIn("/proc/stat", out)
        self.assertIn("'cpu_temp': 52.0", out)
        self.assertIn("'fan_rpm': 1450", out)

    def test_list_names_the_device_when_present(self):
        self.fs.add_hidraw(3)
        code, out, _ = self.main("--list")
        self.assertEqual(code, 0)
        self.assertIn("device: /dev/hidraw3", out)

    def test_unknown_metric_is_rejected(self):
        code, _, err = self.main("--metrics", "cpu-temp,vram")
        self.assertEqual(code, 2)
        self.assertIn("unknown metric", err)

    def test_empty_metrics_is_rejected(self):
        code, _, err = self.main("--metrics", " , ")
        self.assertEqual(code, 2)
        self.assertIn("--metrics is empty", err)

    def test_every_documented_metric_parses(self):
        lcd = FakeLcd().install(self, path="/dev/hidraw3")
        self.fs.add_hidraw(3)
        code, _, _ = self.main("--once", "--retry", "0", "--metrics",
                               ",".join(h200d.METRICS))
        self.assertEqual(code, 0)
        self.assertEqual(len(lcd.frames), 1)

    def test_fail_fast_when_the_display_is_absent(self):
        code, _, err = self.main("--retry", "0")
        self.assertEqual(code, 1)
        self.assertIn("no 2e3c:0a12 hidraw node found", err)

    def test_fail_fast_when_the_display_does_not_answer(self):
        FakeLcd(mute=True).install(self, path="/dev/hidraw3")
        self.fs.add_hidraw(3)
        old = h200d.H200.READ_TIMEOUT
        h200d.H200.READ_TIMEOUT = 0.2
        self.addCleanup(setattr, h200d.H200, "READ_TIMEOUT", old)
        code, _, err = self.main("--retry", "0")
        self.assertEqual(code, 1)
        self.assertIn("timed out", err)

    def test_one_shot_against_the_display(self):
        lcd = FakeLcd().install(self, path="/dev/hidraw3")
        self.fs.add_hidraw(3)
        code, out, _ = self.main("--once", "--retry", "0")
        self.assertEqual(code, 0)
        self.assertEqual(len(lcd.frames), 1)
        frame = lcd.frames[0]
        self.assertEqual(frame.cpu_temp, 52)
        self.assertEqual(frame.gpu_temp, 61)
        self.assertEqual(frame.fan_rpm, 1450)
        self.assertEqual(frame.gpu_usage, 42)
        self.assertIn("cpu=52C", out)

    def test_one_shot_in_fahrenheit(self):
        lcd = FakeLcd().install(self, path="/dev/hidraw3")
        self.fs.add_hidraw(3)
        code, out, _ = self.main("--once", "--retry", "0", "--fahrenheit")
        self.assertEqual(code, 0)
        self.assertEqual(lcd.frames[0].cpu_temp, 126)     # 52.0 C
        self.assertEqual(lcd.frames[0].unit, h200d.UNIT_FAHRENHEIT)
        self.assertIn("cpu=126F", out)

    def test_explicit_device_overrides_autodetection(self):
        lcd = FakeLcd().install(self, path="/dev/hidraw9")
        self.fs.add_hidraw(3)                     # decoy: autodetect would win
        code, _, _ = self.main("--once", "--retry", "0",
                               "--device", "/dev/hidraw9")
        self.assertEqual(code, 0)
        self.assertEqual(len(lcd.frames), 1)

    def test_service_path_reconnects_after_a_lost_display(self):
        # The unattended path: run() blows up once, main() must reopen the
        # device instead of exiting, which is what keeps the unit alive across
        # a suspend/resume or a USB hiccup.
        lcd = FakeLcd().install(self, path="/dev/hidraw3")
        self.fs.add_hidraw(3)
        calls = []
        real_run = h200d.run

        def flaky_run(dev, sensors, cycle, unit, args):
            calls.append(dev.path)
            if len(calls) == 1:
                raise IOError("timed out waiting for a reply to report 0x20")
            return real_run(dev, sensors, cycle, unit, args)

        h200d.run = flaky_run
        self.addCleanup(setattr, h200d, "run", real_run)
        real_sleep = h200d.time.sleep
        h200d.time.sleep = lambda s: None
        self.addCleanup(setattr, h200d.time, "sleep", real_sleep)

        code, out, _ = self.main("--once", "--retry", "1")
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["/dev/hidraw3", "/dev/hidraw3"])
        self.assertIn("lost the display", out)
        self.assertEqual(lcd.opens, 2)
        self.assertEqual(len(lcd.frames), 1)

    def test_version_matches_the_module(self):
        with self.assertRaises(SystemExit) as e:
            self.main("--version")
        self.assertEqual(e.exception.code, 0)


class BrokenPipe(unittest.TestCase):
    """`h200d --list | head` must not dump a traceback."""

    def test_list_survives_a_closed_stdout(self):
        # Runs the real script against the real /sys (it only reads), so it
        # works on a build machine with no display attached.
        script = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "h200d.py")
        proc = subprocess.run(
            [os.environ.get("SHELL_FOR_TESTS", "/bin/bash"), "-c",
             "%s %s --list | head -1" % (h200d.sys.executable, script)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotIn(b"Traceback", proc.stderr)
        self.assertNotIn(b"BrokenPipe", proc.stderr)
        self.assertTrue(proc.stdout.startswith(b"device:"), proc.stdout)


if __name__ == "__main__":
    unittest.main()
