"""Phase 12: the wire protocol — report layout, endianness, limits, errors.

The reference is research/PROTOCOL.md. These tests talk to FakeLcd over a real
socketpair, so they cover the encoder *and* H200's write/select/read path.
"""

import struct
import unittest

from support import FakeLcd, h200d


class ReportLayout(unittest.TestCase):
    """What actually goes out on the wire for report 0x20."""

    def setUp(self):
        self.lcd = FakeLcd().install(self)
        self.dev = h200d.H200(self.lcd.path)
        self.addCleanup(self.dev.close)

    def send(self, **kw):
        args = dict(metric=h200d.M_CPU_TEMP, unit=h200d.UNIT_CELSIUS,
                    cpu_temp=0, cpu_usage=0, gpu_temp=0, gpu_usage=0,
                    fan_rpm=0)
        args.update(kw)
        self.dev.send(**args)
        return self.lcd.requests[-1]

    def test_report_is_65_bytes_with_the_id_first(self):
        report = self.send()
        self.assertEqual(len(report), 65)
        self.assertEqual(report[0], h200d.REPORT_DATA)

    def test_field_offsets(self):
        report = self.send(metric=h200d.M_GPU_TEMP,
                           unit=h200d.UNIT_FAHRENHEIT, cpu_temp=45,
                           cpu_usage=37, gpu_temp=62, gpu_usage=88,
                           fan_rpm=1250, alarm=0x05)
        self.assertEqual(report[1], h200d.M_GPU_TEMP)   # +0 metric flags
        self.assertEqual(report[2], h200d.UNIT_FAHRENHEIT)  # +1 unit
        self.assertEqual(report[3], 0x05)               # +2 alarm bits
        self.assertEqual(report[4], 0x00)               # +3 reserved
        self.assertEqual(report[5:7], b"\x00\x2d")      # +4 cpu temp   (45)
        self.assertEqual(report[7], 37)                 # +6 cpu usage
        self.assertEqual(report[8:10], b"\x00\x3e")     # +7 gpu temp   (62)
        self.assertEqual(report[10], 88)                # +9 gpu usage
        self.assertEqual(report[11:13], b"\x04\xe2")    # +10 fan rpm (1250)

    def test_temperatures_are_big_endian_signed(self):
        report = self.send(cpu_temp=-5, gpu_temp=300)
        self.assertEqual(report[5:7], b"\xff\xfb")
        self.assertEqual(report[8:10], b"\x01\x2c")
        self.assertEqual(struct.unpack(">h", report[5:7])[0], -5)
        self.assertEqual(struct.unpack(">h", report[8:10])[0], 300)

    def test_fan_rpm_is_big_endian_unsigned(self):
        report = self.send(fan_rpm=0x1234)
        self.assertEqual(report[11:13], b"\x12\x34")

    def test_tail_is_zero_padding_and_carries_no_checksum(self):
        # PROTOCOL.md: the frame has no checksum. If one is ever discovered
        # this test is where it shows up as a failure.
        report = self.send(cpu_temp=45, fan_rpm=1250)
        self.assertEqual(report[13:], b"\x00" * 52)

    def test_values_are_rounded_not_truncated(self):
        report = self.send(cpu_temp=45.6, cpu_usage=37.5, fan_rpm=1249.5)
        self.assertEqual(struct.unpack(">h", report[5:7])[0], 46)
        self.assertEqual(report[7], 38)
        self.assertEqual(struct.unpack(">H", report[11:13])[0], 1250)

    def test_every_metric_flag_is_a_distinct_bit(self):
        flags = [h200d.M_CPU_TEMP, h200d.M_CPU_USAGE, h200d.M_GPU_TEMP,
                 h200d.M_GPU_USAGE, h200d.M_FAN]
        self.assertEqual(len(set(flags)), len(flags))
        for flag in flags:
            self.assertEqual(flag & (flag - 1), 0, "0x%02X is not a bit" % flag)
        self.assertEqual(sorted(h200d.METRICS.values()), sorted(flags))


class Clamping(unittest.TestCase):
    """Temperature and RPM limits: nothing may wrap around on the wire."""

    def test_signed_16_bit_limits(self):
        self.assertEqual(h200d.clamp16(-40000), -32768)
        self.assertEqual(h200d.clamp16(40000), 32767)
        self.assertEqual(h200d.clamp16(-32768), -32768)
        self.assertEqual(h200d.clamp16(32767), 32767)

    def test_unsigned_8_bit_limits(self):
        self.assertEqual(h200d.clamp8(-1), 0)
        self.assertEqual(h200d.clamp8(300), 255)
        self.assertEqual(h200d.clamp8(100.4), 100)

    def test_unsigned_16_bit_limits(self):
        self.assertEqual(h200d.clampu16(-1), 0)
        self.assertEqual(h200d.clampu16(70000), 65535)
        self.assertEqual(h200d.clampu16(65535), 65535)

    def test_absurd_readings_still_produce_a_valid_frame(self):
        lcd = FakeLcd().install(self)
        dev = h200d.H200(lcd.path)
        self.addCleanup(dev.close)
        dev.send(h200d.M_CPU_TEMP, h200d.UNIT_CELSIUS,
                 cpu_temp=1e9, cpu_usage=1e9, gpu_temp=-1e9, gpu_usage=-5,
                 fan_rpm=1e9)
        frame = lcd.frames[-1]
        self.assertEqual(len(lcd.requests[-1]), 65)
        self.assertEqual(frame.cpu_temp, 32767)
        self.assertEqual(frame.gpu_temp, -32768)
        self.assertEqual(frame.cpu_usage, 255)
        self.assertEqual(frame.gpu_usage, 0)
        self.assertEqual(frame.fan_rpm, 65535)


class Exchange(unittest.TestCase):
    """Handshake, acks and every way the exchange can go wrong."""

    def open(self, **kw):
        self.lcd = FakeLcd(**kw).install(self)
        dev = h200d.H200(self.lcd.path)
        dev.READ_TIMEOUT = 0.3
        self.addCleanup(dev.close)
        return dev

    def test_handshake_reports_the_firmware_version(self):
        dev = self.open(firmware=(2, 11))
        self.assertEqual(dev.handshake(), "2.11")
        self.assertEqual(self.lcd.requests[0][0], h200d.REPORT_HELLO)
        self.assertEqual(self.lcd.requests[0][1], 0x01)

    def test_frame_is_accepted(self):
        dev = self.open()
        reply = dev.send(h200d.M_FAN, h200d.UNIT_CELSIUS, 0, 0, 0, 0, 1000)
        self.assertEqual(reply[0], h200d.REPLY_DATA)
        self.assertEqual(len(self.lcd.frames), 1)

    def test_rejected_frame_raises(self):
        dev = self.open(ack=0)
        with self.assertRaises(IOError) as e:
            dev.send(h200d.M_FAN, h200d.UNIT_CELSIUS, 0, 0, 0, 0, 0)
        self.assertIn("ack=0", str(e.exception))

    def test_wrong_report_id_in_the_reply_raises(self):
        dev = self.open(bad_reply=True)
        with self.assertRaises(IOError) as e:
            dev.handshake()
        self.assertIn("unexpected reply", str(e.exception))

    def test_a_silent_device_times_out(self):
        dev = self.open(mute=True)
        with self.assertRaises(IOError) as e:
            dev.handshake()
        self.assertIn("timed out", str(e.exception))

    def test_unplug_mid_session_raises(self):
        dev = self.open()
        dev.handshake()
        self.lcd.unplug()
        with self.assertRaises(IOError):
            dev.send(h200d.M_CPU_TEMP, h200d.UNIT_CELSIUS, 40, 0, 0, 0, 0)

    def test_close_is_idempotent(self):
        dev = self.open()
        dev.close()
        dev.close()          # must not raise on an already-closed fd


if __name__ == "__main__":
    unittest.main()
