#!/usr/bin/env python3
"""Fetch UK power=plant features directly from Overpass with full geometry.

The local .osm.pbf export path (GDAL's OSM driver) silently drops most
multipolygon *relations*, so large wind farms mapped as relations (Whitelee,
Kype Muir, Clyde, ...) never reach the plant layer. This bypasses that: a single
Overpass query with ``out geom`` returns every plant with its geometry, and we
assemble ways into polygons and relations into multipolygons ourselves.

Writes ``data/regions/{region}/raw/plants.geojson`` in the same schema as
``export_region.py`` (``element`` + ``id`` + OSM tags), so the rest of the
pipeline (``prepare_map_data.py`` / ``plants_sync``) is unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import polygonize, unary_union

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from common import raw_dir  # noqa: E402

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
HEADERS = {"User-Agent": "grid2poster/1.0 (UK power plant polygon fetch)"}

# Marine bbox covering UK waters (North Sea, Irish Sea, Channel) for offshore
# farms that sit outside the GB land area. Foreign-onshore (esp. Ireland) is
# excluded by id, and everything is clipped to the UK boundary + sea buffer.
MARINE_BBOX = (49.0, -9.5, 61.5, 3.5)  # south, west, north, east
OFFSHORE_SEA_BUFFER_KM = 250.0
# Belgian/Dutch offshore farms (Borssele, Rentel, Norther, …) cluster tightly
# off the Belgian coast — too close to Kent for any UK sea-buffer to exclude, so
# drop this continental-shelf corner explicitly (no UK farm sits here).
CONTINENTAL_SHELF = {"lon_min": 2.6, "lat_max": 53.0}


def area_query(country_iso: str, out: str) -> str:
    return f"""[out:json][timeout:300];
area["ISO3166-1"="{country_iso}"][admin_level=2]->.a;
(nwr["power"="plant"](area.a););
out {out};"""


def bbox_query(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    return f"""[out:json][timeout:300];
(nwr["power"="plant"]({s},{w},{n},{e}););
out geom;"""


def overpass(query: str) -> list[dict]:
    last_err = None
    for endpoint in OVERPASS_ENDPOINTS:
        for attempt in range(2):
            try:
                print(f"Querying {endpoint} (attempt {attempt + 1})…")
                resp = requests.post(endpoint, data={"data": query}, headers=HEADERS, timeout=320)
                if resp.status_code == 200 and resp.text.lstrip().startswith("{"):
                    return resp.json()["elements"]
                last_err = f"status {resp.status_code}: {resp.text[:120]!r}"
            except requests.RequestException as exc:
                last_err = str(exc)
            time.sleep(5)
    raise RuntimeError(f"Overpass fetch failed: {last_err}")


def ring(geometry: list[dict]) -> list[tuple[float, float]]:
    return [(p["lon"], p["lat"]) for p in geometry]


def way_polygon(element: dict):
    coords = ring(element.get("geometry") or [])
    if len(coords) < 4 or coords[0] != coords[-1]:
        return None  # power=plant ways are closed areas; skip stray open ways
    poly = Polygon(coords)
    return poly if poly.is_valid else poly.buffer(0)


def relation_multipolygon(element: dict):
    """Assemble a (multi)polygon from a relation's outer/inner member ways."""
    def member_lines(want_inner: bool) -> list[LineString]:
        out = []
        for member in element.get("members", []):
            if member.get("type") != "way" or not member.get("geometry"):
                continue
            is_inner = (member.get("role") or "outer") == "inner"
            if is_inner == want_inner:
                coords = ring(member["geometry"])
                if len(coords) >= 2:
                    out.append(LineString(coords))
        return out

    # polygonize stitches member ways (which may each be a fragment of a ring).
    outer = list(polygonize(unary_union(member_lines(want_inner=False))))
    if not outer:
        return None
    inner = list(polygonize(unary_union(member_lines(want_inner=True))))
    body = unary_union(outer)
    if inner:
        body = body.difference(unary_union(inner))
    if body.is_empty:
        return None
    if body.geom_type == "Polygon":
        body = MultiPolygon([body])
    return body if body.is_valid else body.buffer(0)


def to_features(elements: list[dict]) -> list[dict]:
    features = []
    skipped = 0
    for el in elements:
        etype = el["type"]
        if etype == "node":
            geom = Point(el["lon"], el["lat"])
        elif etype == "way":
            geom = way_polygon(el)
        elif etype == "relation":
            geom = relation_multipolygon(el)
        else:
            geom = None
        if geom is None or geom.is_empty:
            skipped += 1
            continue
        props = {"element": etype, "id": el["id"]}
        props.update(el.get("tags") or {})
        features.append({"geometry": geom, "properties": props})
    print(f"Converted {len(features):,} features ({skipped} skipped: open ways / empty geometry)")
    return features


def uk_waters(region: str) -> "gpd.GeoSeries":
    """UK boundary buffered into the sea by OFFSHORE_SEA_BUFFER_KM (for clipping
    offshore additions so far-foreign farms are excluded)."""
    boundary = gpd.read_file(raw_dir(region).parent / "boundary.geojson").to_crs("EPSG:27700")
    buffered = boundary.geometry.buffer(OFFSHORE_SEA_BUFFER_KM * 1000).union_all()
    return gpd.GeoSeries([buffered], crs="EPSG:27700").to_crs("EPSG:4326").iloc[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default="uk")
    parser.add_argument("--country-iso", default="GB")
    parser.add_argument("--no-offshore", action="store_true", help="Skip the marine offshore pass")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    print("== onshore (GB land area) ==")
    onshore = overpass(area_query(args.country_iso, "geom"))
    onshore_ids = {(e["type"], e["id"]) for e in onshore}
    print(f"  {len(onshore):,} elements")
    features = to_features(onshore)

    if not args.no_offshore:
        print("== offshore (marine bbox, minus GB+IE land, clipped to UK waters) ==")
        ie_ids = {(e["type"], e["id"]) for e in overpass(area_query("IE", "ids"))}
        marine = overpass(bbox_query(MARINE_BBOX))
        new = [e for e in marine if (e["type"], e["id"]) not in onshore_ids
               and (e["type"], e["id"]) not in ie_ids]
        print(f"  {len(marine):,} in bbox, {len(new):,} new after excluding GB/IE land")
        offshore_feats = to_features(new)
        waters = uk_waters(args.region)

        def is_uk_offshore(geom) -> bool:
            if not geom.intersects(waters):
                return False
            point = geom.representative_point()
            return not (point.x > CONTINENTAL_SHELF["lon_min"] and point.y < CONTINENTAL_SHELF["lat_max"])

        kept = [f for f in offshore_feats if is_uk_offshore(f["geometry"])]
        print(f"  {len(kept):,} offshore features within UK waters (+{len(offshore_feats) - len(kept)} foreign/far dropped)")
        features += kept

    if not features:
        print("No features built", file=sys.stderr)
        return 1

    gdf = gpd.GeoDataFrame(
        [f["properties"] for f in features],
        geometry=[f["geometry"] for f in features],
        crs="EPSG:4326",
    ).drop_duplicates(subset=["element", "id"])
    out_path = args.out or (raw_dir(args.region) / "plants.geojson")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out_path, driver="GeoJSON")
    geom_counts = gdf.geometry.geom_type.value_counts().to_dict()
    print(f"Wrote {len(gdf):,} plants -> {out_path.relative_to(REPO_ROOT)}  {geom_counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
