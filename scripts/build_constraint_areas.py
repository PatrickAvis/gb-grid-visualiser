"""Build illustrative land masks north of public NESO B4/B6 boundary lines.

These are geographic display masks, not electrical asset-membership polygons.
Does not alter the original ETYS or UK boundary data.
"""
import hashlib
import json
from pathlib import Path

from shapely.geometry import Point, Polygon, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]


def build_areas(lines, land):
    components = [p for f in land['features'] for p in (
        list(shape(f['geometry']).geoms) if f['geometry']['type'] == 'MultiPolygon'
        else [shape(f['geometry'])])]
    # Keep mainland GB and northern islands; explicitly exclude Northern Ireland.
    mainland = next(p for p in components if p.covers(Point(-3.19, 55.95)))
    scottish_land = unary_union([p for p in components if p.equals(mainland) or p.representative_point().y > 55.3])
    features = []
    for boundary, code in [('B4', 'SSE_SP2'), ('B6', 'SCOTEX')]:
        line = next(f for f in lines['features'] if f['properties'].get('boundary_id', f['properties'].get('name')) == boundary)
        coords = list(shape(line['geometry']).coords)
        if coords[0][0] > coords[-1][0]:
            coords.reverse()
        # Ends are offshore. Close beyond the land mask to select the north side.
        ring = [(-15, coords[0][1]), *coords, (5, coords[-1][1]), (5, 65), (-15, 65)]
        north = Polygon(ring)
        if not north.is_valid:
            raise ValueError(f'Invalid north-side mask for {boundary}')
        area = north.intersection(scottish_land).simplify(0.002, preserve_topology=True)
        if not area.is_valid or area.is_empty:
            raise ValueError(f'Invalid derived area for {boundary}')
        features.append({'type': 'Feature', 'properties': {
            'boundary_id': boundary, 'constraint_group': code,
            'name': f'Land north of {boundary}',
            'geometry_note': 'Illustrative land mask from NESO boundary line; not an electrical membership or eligibility polygon. Local land mask excludes Shetland. Offshore assets are not shaded.',
        }, 'geometry': mapping(area)})
    return {'type': 'FeatureCollection', 'features': features}


def main():
    line_path = ROOT / 'data/regions/uk/map/etys_boundaries_web.geojson'
    land_path = ROOT / 'data/regions/uk/boundary.geojson'
    result = build_areas(json.loads(line_path.read_text()), json.loads(land_path.read_text()))
    result['provenance'] = {
        'boundary_source': 'https://api.neso.energy/dataset/997f4820-1ad4-499b-b1fe-4b8d3d7fbc72/resource/e914fcec-1dc9-4f1f-97e7-59c0d9521bea/download/etys-boundary-gis-data-mar25.zip',
        'crosswalk_source': 'https://www.neso.energy/industry-information/balancing-services/local-constraint-market',
        'method': 'North-side closure of B4/B6, intersected with existing GB land geometry, simplified by 0.002 degrees.',
        'inputs': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [line_path, land_path]},
    }
    out = ROOT / 'data/regions/uk/map/constraint_areas.geojson'
    out.write_text(json.dumps(result, separators=(',', ':')), encoding='utf-8')
    print(f'Wrote {out}: {len(result["features"])} illustrative areas')


if __name__ == '__main__':
    main()
