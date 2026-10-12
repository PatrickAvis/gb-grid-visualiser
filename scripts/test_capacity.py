"""Power units must not silently accept voltage or other malformed tags."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare import parse_capacity_to_mw


class CapacityTests(unittest.TestCase):
    def test_power_units(self):
        for value, expected in [('1600 kW', 1.6), ('1.6 MW', 1.6),
                                ('1600000 W', 1.6), ('1 GW', 1000),
                                ('1,5 MW', 1.5), ('500 MW;200 MW', 700)]:
            with self.subTest(value=value):
                self.assertAlmostEqual(parse_capacity_to_mw(value), expected)

    def test_invalid_units(self):
        for value in ['1600 KV', '1600 kVA', '1600 MWh', 'about 1600', 'yes']:
            with self.subTest(value=value):
                self.assertTrue(math.isnan(parse_capacity_to_mw(value)))


if __name__ == '__main__':
    unittest.main()
