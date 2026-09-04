"""Phase 12: VID/PID detection — h200d must never write to the wrong device."""

import tempfile
import unittest

from support import FakeSysfs, h200d


class DeviceDiscovery(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fs = FakeSysfs(tmp.name).install(self)

    def test_finds_the_h200(self):
        self.fs.add_hidraw(0)
        self.assertEqual(h200d.find_hidraw(), "/dev/hidraw0")

    def test_no_device_at_all(self):
        self.assertIsNone(h200d.find_hidraw())

    def test_ignores_other_vendors(self):
        self.fs.add_hidraw(0, vid=0x046D, pid=0xC52B)   # a Logitech receiver
        self.fs.add_hidraw(1, vid=0x1B1C, pid=0x0C10)   # a Corsair cooler
        self.assertIsNone(h200d.find_hidraw())

    def test_right_vendor_wrong_product(self):
        self.fs.add_hidraw(0, vid=h200d.VID, pid=0x0A13)
        self.assertIsNone(h200d.find_hidraw())

    def test_right_product_wrong_vendor(self):
        self.fs.add_hidraw(0, vid=0x2E3D, pid=h200d.PID)
        self.assertIsNone(h200d.find_hidraw())

    def test_picks_the_h200_out_of_a_crowd(self):
        self.fs.add_hidraw(0, vid=0x046D, pid=0xC52B)
        self.fs.add_hidraw(1)
        self.fs.add_hidraw(2, vid=0x1B1C, pid=0x0C10)
        self.assertEqual(h200d.find_hidraw(), "/dev/hidraw1")

    def test_survives_a_node_without_a_readable_uevent(self):
        self.fs.add_bare_hidraw(0)
        self.fs.add_hidraw(1)
        self.assertEqual(h200d.find_hidraw(), "/dev/hidraw1")

    def test_accepts_lowercase_hex_from_the_kernel(self):
        self.fs.add_hidraw(0, uevent="HID_ID=0003:00002e3c:00000a12\n")
        self.assertEqual(h200d.find_hidraw(), "/dev/hidraw0")

    def test_ignores_a_hid_id_that_only_looks_similar(self):
        # A substring match would accept this; the anchored regex must not.
        self.fs.add_hidraw(0, uevent="HID_ID=0003:00002E3C:00000A121\n")
        self.assertIsNone(h200d.find_hidraw())

    def test_node_number_changes_after_a_replug(self):
        self.fs.add_hidraw(0)
        self.assertEqual(h200d.find_hidraw(), "/dev/hidraw0")
        self.fs.remove_hidraw(0)
        self.assertIsNone(h200d.find_hidraw())
        self.fs.add_hidraw(7)
        self.assertEqual(h200d.find_hidraw(), "/dev/hidraw7")

    def test_double_digit_nodes_sort_numerically_enough(self):
        # hidraw10 sorts before hidraw2 lexically; either is a valid answer as
        # long as we return *an* H-200 and not None.
        self.fs.add_hidraw(2)
        self.fs.add_hidraw(10)
        self.assertIn(h200d.find_hidraw(), ("/dev/hidraw2", "/dev/hidraw10"))


if __name__ == "__main__":
    unittest.main()
