import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bmu_operational import _aggregate_mapped_actions, _finalize_action


class SoFlagTests(unittest.TestCase):
    def test_mixed_actions_preserve_counts_and_absolute_volumes(self):
        base = dict(id='T_TEST', bidOffer='bid', settlementDate='2026-10-11', settlementPeriod=1)
        rows = [{**base, 'volume': -3, 'soFlag': True},
                {**base, 'volume': -2, 'soFlag': False},
                {**base, 'volume': -1}]
        mapped, _ = _aggregate_mapped_actions(rows,
            links_by_bmu={'T_TEST': [{'osm_id': '123'}]},
            sites_by_osm={'123': {'latitude': 54, 'longitude': -2}})
        self.assertEqual(len(mapped), 1)
        result = _finalize_action(mapped[0])
        self.assertEqual(result['so_flag_status'], 'mixed')
        self.assertEqual(result['volume_mwh'], -6)
        for status, volume in [('flagged', 3), ('unflagged', 2), ('unknown', 1)]:
            self.assertEqual(result[f'so_{status}_actions'], 1)
            self.assertEqual(result[f'so_{status}_abs_mwh'], volume)

    def test_missing_flag_is_not_unflagged(self):
        result = _finalize_action(dict(action_count=2, volume_mwh=-4, abs_volume_mwh=4))
        self.assertEqual(result['so_flag_status'], 'unknown')
        self.assertEqual(result['so_unknown_actions'], 2)
        self.assertEqual(result['so_unflagged_actions'], 0)


if __name__ == '__main__':
    unittest.main()
