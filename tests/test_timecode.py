import unittest

from game_vod_clipper.timecode import (
    format_timecode,
    format_timecode_for_filename,
    parse_timecode,
)


class TimecodeTest(unittest.TestCase):
    def test_parse_seconds(self):
        self.assertEqual(parse_timecode("75"), 75)
        self.assertEqual(parse_timecode("75.5"), 75.5)

    def test_parse_minutes_seconds(self):
        self.assertEqual(parse_timecode("01:15"), 75)
        self.assertEqual(parse_timecode("1:15.5"), 75.5)

    def test_parse_hours_minutes_seconds(self):
        self.assertEqual(parse_timecode("01:02:03"), 3723)
        self.assertEqual(parse_timecode("1:02:03.250"), 3723.25)

    def test_reject_invalid_timecodes(self):
        for value in ["", "1:60", "1:2:60", "1:2:3:4", "abc", "-1"]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_timecode(value)

    def test_format_timecode(self):
        self.assertEqual(format_timecode(75), "00:01:15")
        self.assertEqual(format_timecode(3723.25), "01:02:03.250")
        self.assertEqual(format_timecode(59.9999), "00:01:00")

    def test_format_timecode_for_filename(self):
        self.assertEqual(format_timecode_for_filename(3723.25), "01-02-03-250")


if __name__ == "__main__":
    unittest.main()
