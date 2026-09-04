"""Phase 12: sensor discovery and reading against a fake /sys and /proc.

Covers the cases the daemon actually meets in the field: a labelled Ryzen
k10temp, an Intel coretemp, two GPUs, a GPU that has no fan, a machine with no
sensors at all, and a sensor file that disappears while running.
"""

import os
import tempfile
import unittest

from support import FakeSysfs, h200d


class SensorTestCase(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fs = FakeSysfs(tmp.name).install(self)


class Discovery(SensorTestCase):

    def test_ryzen_and_amdgpu(self):
        self.fs.add_hwmon("k10temp", temps=[("Tctl", 52000), ("Tccd1", 48000)])
        self.fs.add_hwmon("amdgpu", temps=[("edge", 61000),
                                           ("junction", 70000)],
                          fans=[1450])
        self.fs.add_drm_card(0, busy=42)
        s = h200d.Sensors()
        self.assertTrue(s.cpu_temp.endswith("temp1_input"))
        self.assertIn("hwmon0", s.cpu_temp)
        self.assertIn("hwmon1", s.gpu_temp)
        self.assertTrue(s.fan.endswith("fan1_input"))
        self.assertTrue(s.gpu_busy.endswith("gpu_busy_percent"))

    def test_label_wins_over_file_order(self):
        # Tctl is temp3 here: picking temp1 blindly would report the wrong die.
        self.fs.add_hwmon("k10temp", temps=[("Tccd1", 48000),
                                            ("Tccd2", 49000),
                                            ("Tctl", 52000)])
        s = h200d.Sensors()
        self.assertTrue(s.cpu_temp.endswith("temp3_input"))
        self.assertEqual(s.read()["cpu_temp"], 52.0)

    def test_falls_back_to_the_first_temp_when_no_label_matches(self):
        self.fs.add_hwmon("coretemp", temps=[("Core 0", 44000),
                                             ("Core 1", 45000)])
        s = h200d.Sensors()
        self.assertTrue(s.cpu_temp.endswith("temp1_input"))
        self.assertEqual(s.read()["cpu_temp"], 44.0)

    def test_unlabelled_chip_is_still_usable(self):
        self.fs.add_hwmon("k10temp", temps=[(None, 51000)])
        s = h200d.Sensors()
        self.assertEqual(s.read()["cpu_temp"], 51.0)

    def test_unknown_chips_are_ignored(self):
        self.fs.add_hwmon("acpitz", temps=[("acpitz", 27000)])
        self.fs.add_hwmon("nvme", temps=[("Composite", 38000)])
        s = h200d.Sensors()
        self.assertIsNone(s.cpu_temp)
        self.assertIsNone(s.gpu_temp)

    def test_motherboard_fan_when_the_gpu_has_none(self):
        self.fs.add_hwmon("amdgpu", temps=[("edge", 60000)])
        self.fs.add_hwmon("nct6775", temps=[], fans=[900, 1200])
        s = h200d.Sensors()
        self.assertIn("hwmon1", s.fan)
        self.assertTrue(s.fan.endswith("fan1_input"))

    def test_intel_arc_via_xe(self):
        self.fs.add_hwmon("xe", temps=[("pkg", 55000)], fans=[])
        self.fs.add_drm_card(1, busy=7)
        s = h200d.Sensors()
        self.assertIn("hwmon0", s.gpu_temp)
        self.assertEqual(s.read()["gpu_usage"], 7)

    def test_multiple_gpus_present(self):
        # Two GPUs and two cards: discovery must be deterministic (first by
        # hwmon/card order) and must not blow up.
        self.fs.add_hwmon("k10temp", temps=[("Tctl", 50000)])
        self.fs.add_hwmon("amdgpu", temps=[("edge", 61000)], fans=[1500])
        self.fs.add_hwmon("xe", temps=[("pkg", 55000)])
        self.fs.add_drm_card(0, busy=42)
        self.fs.add_drm_card(1, busy=7)
        s = h200d.Sensors()
        self.assertIn("hwmon1", s.gpu_temp)      # amdgpu, the first GPU chip
        self.assertIn("card0", s.gpu_busy)
        reading = s.read()
        self.assertEqual(reading["gpu_temp"], 61.0)
        self.assertEqual(reading["gpu_usage"], 42)
        self.assertEqual(reading["fan_rpm"], 1500)

    def test_card_without_gpu_busy_percent_is_skipped(self):
        self.fs.add_drm_card(0)                  # e.g. an i915 without the file
        self.fs.add_drm_card(1, busy=63)
        s = h200d.Sensors()
        self.assertIn("card1", s.gpu_busy)
        self.assertEqual(s.read()["gpu_usage"], 63)

    def test_hwmon_without_a_name_file_is_skipped(self):
        os.makedirs(os.path.join(self.fs.sys, "class", "hwmon", "hwmon9"))
        self.fs.add_hwmon("k10temp", temps=[("Tctl", 50000)])
        s = h200d.Sensors()
        self.assertEqual(s.read()["cpu_temp"], 50.0)


class MissingSensors(SensorTestCase):

    def test_a_machine_with_nothing_reads_zeros(self):
        s = h200d.Sensors()
        self.assertIsNone(s.cpu_temp)
        self.assertIsNone(s.gpu_temp)
        self.assertIsNone(s.fan)
        self.assertIsNone(s.gpu_busy)
        reading = s.read()
        self.assertEqual(reading["cpu_temp"], 0.0)
        self.assertEqual(reading["gpu_temp"], 0.0)
        self.assertEqual(reading["fan_rpm"], 0)
        self.assertEqual(reading["gpu_usage"], 0)

    def test_describe_marks_the_missing_ones(self):
        self.fs.add_hwmon("k10temp", temps=[("Tctl", 50000)])
        described = dict(h200d.Sensors().describe())
        self.assertIsNotNone(described["cpu_temp"])
        self.assertIsNone(described["gpu_temp"])
        self.assertEqual(described["cpu_usage"], "/proc/stat")

    def test_a_sensor_that_vanishes_reads_as_zero(self):
        # GPU unbinds, hwmon renumbers: this must not look like an I/O error,
        # or run() would treat it as the display going away.
        node = self.fs.add_hwmon("amdgpu", temps=[("edge", 61000)], fans=[1500])
        s = h200d.Sensors()
        self.assertEqual(s.read()["gpu_temp"], 61.0)
        os.unlink(os.path.join(node, "temp1_input"))
        os.unlink(os.path.join(node, "fan1_input"))
        reading = s.read()
        self.assertEqual(reading["gpu_temp"], 0.0)
        self.assertEqual(reading["fan_rpm"], 0)

    def test_a_sensor_that_returns_garbage_reads_as_zero(self):
        node = self.fs.add_hwmon("k10temp", temps=[("Tctl", 50000)])
        s = h200d.Sensors()
        with open(os.path.join(node, "temp1_input"), "w") as f:
            f.write("N/A\n")
        self.assertEqual(s.read()["cpu_temp"], 0.0)


class CpuUsageFromProcStat(SensorTestCase):

    def test_half_busy(self):
        self.fs.write_proc_stat(0, 0, 0, 0, 0)
        usage = h200d.CpuUsage()
        self.fs.write_proc_stat(100, 0, 0, 100, 0)
        self.assertAlmostEqual(usage.read(), 50.0)

    def test_fully_idle_and_fully_busy(self):
        self.fs.write_proc_stat(0, 0, 0, 0, 0)
        usage = h200d.CpuUsage()
        self.fs.write_proc_stat(0, 0, 0, 1000, 0)
        self.assertAlmostEqual(usage.read(), 0.0)
        self.fs.write_proc_stat(1000, 0, 0, 1000, 0)
        self.assertAlmostEqual(usage.read(), 100.0)

    def test_iowait_counts_as_idle(self):
        self.fs.write_proc_stat(0, 0, 0, 0, 0)
        usage = h200d.CpuUsage()
        self.fs.write_proc_stat(50, 0, 50, 800, 100)
        self.assertAlmostEqual(usage.read(), 10.0)

    def test_extra_fields_do_not_shift_the_maths(self):
        # irq/softirq/steal/guest columns are counted as busy time.
        self.fs.write_proc_stat(100, 0, 0, 100, 0, extra=(0, 0, 0, 0, 0, 0))
        usage = h200d.CpuUsage()
        self.fs.write_proc_stat(200, 0, 0, 200, 0, extra=(0, 0, 0, 0, 0, 0))
        self.assertAlmostEqual(usage.read(), 50.0)

    def test_a_stat_line_without_iowait(self):
        path = os.path.join(self.fs.proc, "stat")
        with open(path, "w") as f:
            f.write("cpu  10 0 10 20\n")
        usage = h200d.CpuUsage()
        with open(path, "w") as f:
            f.write("cpu  20 0 20 40\n")
        self.assertAlmostEqual(usage.read(), 50.0)

    def test_no_elapsed_time_reads_zero(self):
        self.fs.write_proc_stat(10, 0, 10, 20, 0)
        usage = h200d.CpuUsage()
        self.assertEqual(usage.read(), 0.0)

    def test_percentage_stays_in_range(self):
        self.fs.write_proc_stat(0, 0, 0, 0, 0)
        usage = h200d.CpuUsage()
        for user, idle in ((5, 95), (50, 50), (100, 0)):
            self.fs.write_proc_stat(user, 0, 0, idle, 0)
            value = usage.read()
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 100.0)


if __name__ == "__main__":
    unittest.main()
