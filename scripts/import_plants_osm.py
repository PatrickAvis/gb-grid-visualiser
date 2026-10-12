"""Import dependency-complete OSM XML plants using the Overpass geometry builder.

Prepare the XML with osmium tags-filter (retain references) and osmium cat.
Unlike GDAL, this also assembles site relations from their member turbine nodes.
The extract's geographic coverage limits this import; existing map sites are
preserved by the normal additive sync.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
import sys
from xml.etree import ElementTree as ET

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import raw_dir, map_dir
from scripts.fetch_plants_overpass import PLANT_KEYS, to_features, uk_waters


def read_elements(path):
    nodes, ways, relations = {}, {}, {}
    for _, el in ET.iterparse(path, events=('end',)):
        if el.tag not in ('node', 'way', 'relation'):
            continue
        item = {'type': el.tag, 'id': int(el.attrib['id']),
                'tags': {t.attrib['k']: t.attrib['v'] for t in el.findall('tag')}}
        if el.tag == 'node':
            item.update(lat=float(el.attrib['lat']), lon=float(el.attrib['lon']))
            nodes[item['id']] = item
        elif el.tag == 'way':
            item['refs'] = [int(n.attrib['ref']) for n in el.findall('nd')]
            ways[item['id']] = item
        else:
            item['members'] = [dict(m.attrib) for m in el.findall('member')]
            relations[item['id']] = item
        el.clear()
    for way in ways.values():
        missing = [ref for ref in way['refs'] if ref not in nodes]
        if missing:
            raise ValueError(f"Way {way['id']} is missing node references; retain dependencies when filtering")
        way['geometry'] = [{'lat': nodes[r]['lat'], 'lon': nodes[r]['lon']} for r in way.pop('refs')]
    for relation in relations.values():
        for member in relation['members']:
            ref = int(member['ref'])
            if member['type'] == 'node':
                if ref not in nodes:
                    raise ValueError(f"Relation {relation['id']} is missing node {ref}")
                member.update(lat=nodes[ref]['lat'], lon=nodes[ref]['lon'])
            elif member['type'] == 'way':
                if ref not in ways:
                    raise ValueError(f"Relation {relation['id']} is missing way {ref}")
                member['geometry'] = ways[ref]['geometry']
    return [item for group in (nodes, ways, relations) for item in group.values()
            if any(item['tags'].get(key) == 'plant' for key in PLANT_KEYS)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--source-date', type=date.fromisoformat, required=True)
    parser.add_argument('--region', default='uk', choices=['uk'])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    features = to_features(read_elements(args.source))
    waters = uk_waters(args.region)
    features = [f for f in features if f['geometry'].intersects(waters)]
    if not features:
        raise ValueError('No plant geometry found; existing output was not changed')
    frame = gpd.GeoDataFrame([f['properties'] for f in features],
                             geometry=[f['geometry'] for f in features], crs='EPSG:4326')
    output = args.output or raw_dir(args.region) / 'plants.geojson'
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(output, driver='GeoJSON')
    if args.output is None:
        (map_dir(args.region) / 'plants_meta.json').write_text(json.dumps({
            'plants_fetched': date.today().isoformat(), 'plant_count': len(frame),
            'source': 'Local OSM extract; relation members assembled with the Overpass geometry builder',
            'source_snapshot': args.source_date.isoformat(),
        }, indent=2), encoding='utf-8')
    print(f'Wrote {len(frame):,} plants to {output}; source snapshot {args.source_date}')


if __name__ == '__main__':
    main()
