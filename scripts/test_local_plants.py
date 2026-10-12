"""Local fallback retains relation geometry and rejects incomplete extracts."""
from pathlib import Path
import tempfile
import unittest
from scripts.import_plants_osm import read_elements
from scripts.fetch_plants_overpass import to_features


class LocalPlantTests(unittest.TestCase):
    def read(self, xml):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plants.osm'
            path.write_text(xml, encoding='utf-8')
            return read_elements(path)

    def test_site_members_make_a_polygon_and_keep_lifecycle(self):
        elements = self.read('''<osm>
          <node id="1" lat="54" lon="-2"/><node id="2" lat="54.01" lon="-2"/>
          <node id="3" lat="54" lon="-2.01"/>
          <relation id="100"><tag k="type" v="site"/>
          <tag k="construction:power" v="plant"/>
          <member type="node" ref="1"/><member type="node" ref="2"/>
          <member type="node" ref="3"/></relation></osm>''')
        features = to_features(elements)
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]['properties']['status'], 'construction')
        self.assertEqual(features[0]['properties']['element'], 'relation')
        self.assertEqual(features[0]['geometry'].geom_type, 'Polygon')

    def test_missing_geometry_dependency_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'missing node'):
            self.read('''<osm><way id="1"><tag k="power" v="plant"/>
            <nd ref="99"/></way></osm>''')


if __name__ == '__main__':
    unittest.main()
