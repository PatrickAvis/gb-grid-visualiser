import json
import unittest
from pathlib import Path
from shapely.geometry import Point, shape
from build_constraint_areas import build_areas, ROOT


class ConstraintAreasTest(unittest.TestCase):
    def test_north_side_masks_are_valid_nested_and_exclude_northern_ireland(self):
        lines = json.loads((ROOT / 'data/regions/uk/map/etys_boundaries_web.geojson').read_text())
        land = json.loads((ROOT / 'data/regions/uk/boundary.geojson').read_text())
        areas = {f['properties']['boundary_id']: shape(f['geometry']) for f in build_areas(lines, land)['features']}
        for area in areas.values():
            self.assertTrue(area.is_valid)
            self.assertTrue(area.covers(Point(-4.22, 57.48)))  # Inverness
            self.assertFalse(area.covers(Point(-5.93, 54.60)))  # Belfast
            self.assertFalse(area.covers(Point(-2.24, 53.48)))  # Manchester
        self.assertTrue(areas['B6'].covers(Point(-3.19, 55.95)))
        self.assertFalse(areas['B4'].covers(Point(-3.19, 55.95)))
        self.assertLess(areas['B4'].difference(areas['B6']).area, 0.001)


if __name__ == '__main__':
    unittest.main()
