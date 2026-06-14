#!/usr/bin/env python3
"""Add offshore wind turbines that the land-clipped generator export missed.

Offshore wind farms now have polygons (see fetch_plants_overpass.py), but their
individual power=generator turbines were clipped out of the generator export for
the far-offshore farms (Dogger Bank, Sofia, Seagreen, East Anglia, ...). This
fetches offshore wind generators directly from Overpass, clips them to UK waters
(excluding the Belgian/Dutch continental shelf), dedupes against the existing
turbines by osm_id, and appends the new ones to raw/wind_turbines.csv so the
normal pipeline (build_turbines_web -> turbines.pmtiles) picks them up.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from common import raw_dir  # noqa: E402
from prepare import parse_capacity_to_mw, parse_numeric_tag  # noqa: E402

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
HEADERS = {"User-Agent": "grid2poster/1.0 (offshore wind turbine fetch)"}
MARINE_BBOX = (49.0, -9.5, 61.5, 3.5)  # south, west, north, east
OFFSHORE_SEA_BUFFER_KM = 250.0
CONTINENTAL_SHELF = {"lon_min": 2.6, "lat_max": 53.0}  # Belgian/Dutch corner


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


def uk_sea(region: str):
    """Return (UK land polygon, UK sea = land buffered into the sea minus land).

    Onshore turbines are already in the export; only the offshore ones (in the
    sea ring around the UK) were clipped out, so we keep just those.
    """
    boundary = gpd.read_file(raw_dir(region).parent / "boundary.geojson").to_crs("EPSG:27700")
    land = boundary.geometry.union_all()
    sea = land.buffer(OFFSHORE_SEA_BUFFER_KM * 1000).difference(land)
    to84 = lambda g: gpd.GeoSeries([g], crs="EPSG:27700").to_crs("EPSG:4326").iloc[0]
    return to84(land), to84(sea)


def is_uk_offshore(lat: float, lon: float, sea) -> bool:
    if lon > CONTINENTAL_SHELF["lon_min"] and lat < CONTINENTAL_SHELF["lat_max"]:
        return False
    from shapely.geometry import Point
    return Point(lon, lat).within(sea)


def numeric_osm_id(value) -> str:
    """Bare numeric id for deduping ('node/123' and '123.0' both -> '123')."""
    text = str(value).strip()
    if "/" in text:
        text = text.split("/", 1)[1]
    return text.split(".", 1)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default="uk")
    args = parser.parse_args()

    s, w, n, e = MARINE_BBOX
    query = f"""[out:json][timeout:300];
(node["power"="generator"]["generator:source"="wind"]({s},{w},{n},{e}););
out tags center;"""
    elements = overpass(query)
    print(f"Overpass returned {len(elements):,} offshore-bbox wind generators")

    _, sea = uk_sea(args.region)
    rows = []
    for el in elements:
        lat, lon = el.get("lat"), el.get("lon")
        if lat is None or lon is None or not is_uk_offshore(lat, lon, sea):
            continue
        tags = el.get("tags", {})
        rows.append({
            "osm_id": f"node/{el['id']}",
            "power": tags.get("power"),
            "name": tags.get("name"),
            "operator": tags.get("operator"),
            "manufacturer": tags.get("manufacturer"),
            "model": tags.get("model"),
            "ref": tags.get("ref"),
            "generator:source": tags.get("generator:source"),
            "generator:method": tags.get("generator:method"),
            "generator:output:electricity": tags.get("generator:output:electricity"),
            "height": tags.get("height"),
            "rotor:diameter": tags.get("rotor:diameter"),
            "capacity_mw": parse_capacity_to_mw(tags.get("generator:output:electricity")),
            "height_m": parse_numeric_tag(tags.get("height")),
            "rotor_diameter_m": parse_numeric_tag(tags.get("rotor:diameter")),
            "latitude": round(float(lat), 6),
            "longitude": round(float(lon), 6),
        })
    print(f"{len(rows):,} within UK waters")

    csv_path = raw_dir(args.region) / "wind_turbines.csv"
    existing = pd.read_csv(csv_path, low_memory=False)
    have = set(existing["osm_id"].map(numeric_osm_id))
    new = pd.DataFrame([r for r in rows if numeric_osm_id(r["osm_id"]) not in have])
    print(f"{len(new):,} new turbines after deduping against {len(existing):,} existing")
    if new.empty:
        print("Nothing to add")
        return 0

    combined = pd.concat([existing, new], ignore_index=True)
    combined.to_csv(csv_path, index=False)
    print(f"Wrote {len(combined):,} turbines -> {csv_path.relative_to(REPO_ROOT)} (+{len(new):,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
