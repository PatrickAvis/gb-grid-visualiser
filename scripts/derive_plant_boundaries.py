#!/usr/bin/env python3
"""Derive approximate site boundaries for plants that OSM maps only as a point.

Many UK wind (and some solar) farms are mapped in OSM as a cluster of
``power=generator`` units with no enclosing ``power=plant`` polygon, so they
appear on the map as a single point with no outline. For each point-geometry
plant in the BMU-mapped sites layer, this finds the nearby generators of the
matching fuel, isolates the cluster around the point, and computes a concave
hull as an approximate boundary.

Output: ``data/regions/{region}/map/derived_plant_boundaries.geojson`` — one
polygon per resolved plant, keyed by ``osm_id`` so it can be joined back to the
plant layer. Use ``--apply`` to also splice the polygons into
``bmu_sites_web.geojson`` (replacing those point geometries in place).

Boundaries are approximate (generator-cluster hulls), so they are kept in a
separate layer/flag rather than presented as OSM ground truth.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
from shapely import concave_hull
from shapely.geometry import shape
from shapely.ops import unary_union

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from common import map_dir  # noqa: E402

# British National Grid — metric, so buffers/distances are in metres.
METRIC_CRS = "EPSG:27700"
WGS84 = "EPSG:4326"

# Per fuel family: which generator source file, and the cluster scale (metres).
WIND_BUCKETS = {"wind", "wind_onshore", "wind_offshore"}
SOLAR_BUCKETS = {"solar"}

FAMILY_PARAMS = {
    # 2.5 km radius keeps adjacent farms (dense in the Scottish Borders /
    # Lanarkshire) from merging into one blob; a wider radius over-merges. Farms
    # whose point sits >2.5 km from their turbines, and most offshore farms
    # (sparse turbine data), will not resolve and stay as points.
    "wind": {"search_radius": 2500.0, "buffer": 350.0, "min_generators": 3, "ratio": 0.3},
    "solar": {"search_radius": 1500.0, "buffer": 120.0, "min_generators": 5, "ratio": 0.3},
}


def family_of(bucket: str | None) -> str | None:
    if bucket in WIND_BUCKETS:
        return "wind"
    if bucket in SOLAR_BUCKETS:
        return "solar"
    return None


def load_point_plants(plants_path: Path) -> gpd.GeoDataFrame:
    plants = gpd.read_file(plants_path)
    pts = plants[plants.geometry.geom_type == "Point"].copy()
    pts["family"] = pts.get("source_bucket").map(family_of)
    return pts[pts["family"].notna()].copy()


def load_generators(region: str, family: str) -> gpd.GeoDataFrame:
    """Generator points for a fuel family, projected to the metric CRS."""
    if family == "wind":
        gens = gpd.read_file(map_dir(region) / "turbines_web.geojson")  # wind-only points
    else:  # solar (and any future family) come from the full generator inventory
        gens = gpd.read_file(map_dir(region) / "all_generators_web.geojson")
        if "source_bucket" in gens.columns:
            gens = gens[gens["source_bucket"].isin(SOLAR_BUCKETS)].copy()
    gens = gens[gens.geometry.geom_type == "Point"]
    return gens.set_crs(WGS84, allow_override=True).to_crs(METRIC_CRS)


def derive_boundary(point_m, gens_m: gpd.GeoDataFrame, params: dict):
    """Concave-hull boundary of the generator cluster around a plant point.

    Returns (polygon_metric, generator_count) or (None, 0) when no usable
    cluster is found near the point.
    """
    radius = params["search_radius"]
    buffer = params["buffer"]
    nearby_idx = gens_m.sindex.query(point_m.buffer(radius), predicate="intersects")
    nearby = gens_m.iloc[nearby_idx]
    nearby = nearby[nearby.distance(point_m) <= radius]
    if len(nearby) < params["min_generators"]:
        return None, 0

    # Cluster by buffer-union; keep the component nearest the plant point.
    clusters = unary_union(nearby.geometry.buffer(buffer))
    parts = list(getattr(clusters, "geoms", [clusters]))
    cluster = min(parts, key=lambda geom: geom.distance(point_m))
    members = nearby[nearby.geometry.within(cluster)]
    if len(members) < params["min_generators"]:
        return None, 0

    hull = concave_hull(unary_union(members.geometry), ratio=params["ratio"])
    # Buffer out so every turbine sits inside, smooth, then simplify.
    boundary = hull.buffer(buffer * 0.6).buffer(-buffer * 0.3).simplify(buffer * 0.2)
    return boundary, len(members)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--region", default="uk")
    parser.add_argument("--plants", type=Path, default=None,
                        help="BMU-mapped sites GeoJSON (default: map/bmu_sites_web.geojson)")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output boundaries GeoJSON (default: map/derived_plant_boundaries.geojson)")
    parser.add_argument("--apply", action="store_true",
                        help="Also replace those point geometries in the plants GeoJSON in place")
    args = parser.parse_args()

    plants_path = args.plants or (map_dir(args.region) / "bmu_sites_web.geojson")
    if not plants_path.exists():
        print(f"Plants file not found: {plants_path}", file=sys.stderr)
        return 1
    out_path = args.out or (map_dir(args.region) / "derived_plant_boundaries.geojson")

    pts = load_point_plants(plants_path)
    print(f"Point-geometry plants needing a boundary: {len(pts)}")
    if pts.empty:
        return 0

    derived: dict[str, dict] = {}
    unresolved = 0
    for family, group in pts.groupby("family"):
        params = FAMILY_PARAMS[family]
        gens_m = load_generators(args.region, family)
        group_m = group.to_crs(METRIC_CRS)
        print(f"  {family}: {len(group)} plants vs {len(gens_m):,} generators")
        for (_, plant), (_, plant_m) in zip(group.iterrows(), group_m.iterrows()):
            boundary_m, count = derive_boundary(plant_m.geometry, gens_m, params)
            if boundary_m is None or boundary_m.is_empty:
                unresolved += 1
                continue
            boundary = gpd.GeoSeries([boundary_m], crs=METRIC_CRS).to_crs(WGS84).iloc[0]
            derived[str(plant["osm_id"])] = {
                "geometry": boundary,
                "name": plant.get("name"),
                "source_bucket": plant.get("source_bucket"),
                "generator_count": count,
            }

    print(f"Derived {len(derived)} boundaries ({unresolved} plants had no usable cluster)")
    if not derived:
        return 0

    out = gpd.GeoDataFrame(
        [{"osm_id": k, "name": v["name"], "source_bucket": v["source_bucket"],
          "generator_count": v["generator_count"], "boundary_source": "derived_generator_cluster",
          "geometry": v["geometry"]} for k, v in derived.items()],
        crs=WGS84,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_file(out_path, driver="GeoJSON")
    print(f"Wrote {out_path.relative_to(REPO_ROOT)}")

    if args.apply:
        plants = gpd.read_file(plants_path)
        replaced = 0
        for idx, row in plants.iterrows():
            entry = derived.get(str(row.get("osm_id")))
            if entry is not None:
                plants.at[idx, "geometry"] = entry["geometry"]
                replaced += 1
        plants.to_file(plants_path, driver="GeoJSON")
        print(f"Applied {replaced} boundaries into {plants_path.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
