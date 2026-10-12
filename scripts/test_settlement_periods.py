"""Settlement windows must remain continuous across UK clock changes."""
import unittest
from unittest.mock import patch

from bmu_operational import periods_last_n_hours, settlement_slot, slot_to_settlement


class SettlementTests(unittest.TestCase):
    def test_day_lengths_and_round_trip(self):
        for day, following, count in [
            ("2026-03-29", "2026-03-30", 46),
            ("2026-10-25", "2026-10-26", 50),
            ("2026-07-01", "2026-07-02", 48),
        ]:
            with self.subTest(day=day):
                first = settlement_slot(day, 1)
                self.assertEqual(settlement_slot(following, 1) - first, count)
                for period in range(1, count + 1):
                    self.assertEqual(slot_to_settlement(first + period - 1), (day, period))
                with self.assertRaises(ValueError):
                    settlement_slot(day, count + 1)

    def test_windows_cross_clock_changes(self):
        for end, expected_start in [
            (("2026-03-30", 1), ("2026-03-28", 48)),
            (("2026-10-26", 1), ("2026-10-25", 4)),
        ]:
            with patch("bmu_operational.latest_available_period", return_value=end):
                periods = periods_last_n_hours(24)
            self.assertEqual(len(periods), 48)
            self.assertEqual(len(set(periods)), 48)
            self.assertEqual(periods[0], expected_start)
            self.assertEqual(periods[-1], end)

    def test_invalid_periods(self):
        for period in [0, -1, 1.5]:
            with self.assertRaises(ValueError):
                settlement_slot("2026-07-01", period)

    def test_invalid_windows_do_not_fetch(self):
        with patch("bmu_operational.latest_available_period") as fetch:
            for hours in [0, -1, float("nan"), float("inf")]:
                with self.assertRaises(ValueError):
                    periods_last_n_hours(hours)
            fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
