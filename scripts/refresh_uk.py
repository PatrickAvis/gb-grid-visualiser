#!/usr/bin/env python3
"""One-shot refresh of the whole UK map dataset.

Runs the focused pipeline scripts in order so a single command produces a fresh
dataset end to end:

  1. Elexon BMU standing data        (scripts/fetch_bmu_reference.py)
  2. NESO zone boundaries            (scripts/fetch_neso_zones.py)
  3. OSM power export (if a PBF)      (scripts/export_region.py --all)
  4. Plant polygons via Overpass     (scripts/fetch_plants_overpass.py)
  5. Offshore wind turbines          (scripts/fetch_offshore_turbines.py)
  6. Lightweight web layers          (scripts/prepare_map_data.py)
  7. Derived wind-farm boundaries    (scripts/derive_plant_boundaries.py)
  8. Plant <-> BMU matching          (scripts/propose_plant_bmu_map.py)
  9. PMTiles archives                (scripts/build_tiles.py)

The OSM export only runs when a local ``.osm.pbf`` is found (auto-detected under
``data/regions/{region}/source/`` or given with ``--osm-pbf``); otherwise the
existing ``data/regions/{region}/raw/`` exports are reused. Steps 4-5 and 7 are
UK-only and run regardless of the PBF: GDAL's OSM driver drops most power=plant
relations, so plants are re-fetched from Overpass (incl. offshore + lifecycle
status), and offshore wind turbines and turbine-cluster boundaries are added on
top. Each step can be skipped with the matching ``--skip-*`` flag.
Network/optional steps that fail are reported but do not abort the run; the OSM
export and the prepare step are treated as critical.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SCRIPTS = REPO_ROOT / "scripts"
# Legacy location kept as a fallback for extracts that predate the per-region layout.
LEGACY_OSM_DIR = REPO_ROOT / "data" / "osm"


def source_dirs(region_id: str) -> list[Path]:
    from common import source_dir

    return [source_dir(region_id), LEGACY_OSM_DIR]


def find_pbf(explicit: Path | None, region_id: str) -> Path | None:
    """Resolve the OSM extract to export from, if any."""
    if explicit is not None:
        return explicit if explicit.exists() else None
    for directory in source_dirs(region_id):
        preferred = directory / "great-britain-latest.osm.pbf"
        if preferred.exists():
            return preferred
        if directory.exists():
            candidates = sorted(directory.glob("*.osm.pbf"))
            if candidates:
                return candidates[0]
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--region", default="uk", help="Catalog region id (default: uk)")
    parser.add_argument(
        "--osm-pbf",
        type=Path,
        default=None,
        help="Local .osm.pbf to export from (default: auto-detect under data/regions/{region}/source/)",
    )
    parser.add_argument("--skip-osm", action="store_true", help="Skip OSM export even if a PBF is present")
    parser.add_argument("--skip-elexon", action="store_true", help="Skip Elexon BMU reference download")
    parser.add_argument("--skip-zones", action="store_true", help="Skip NESO zone boundary download")
    parser.add_argument("--skip-plant-fetch", action="store_true", help="Skip re-fetching plant polygons via Overpass")
    parser.add_argument("--skip-offshore-turbines", action="store_true", help="Skip the offshore wind turbine top-up")
    parser.add_argument("--skip-prepare", action="store_true", help="Skip building lightweight web layers")
    parser.add_argument("--skip-boundaries", action="store_true", help="Skip derived wind-farm boundaries")
    parser.add_argument(
        "--rebuild-plants",
        action="store_true",
        help="Rebuild bmu_sites_web.geojson fresh instead of the additive merge "
        "(clean/reproducible, but discards direct edits to that file)",
    )
    parser.add_argument("--skip-bmu-match", action="store_true", help="Skip plant <-> BMU matching")
    parser.add_argument("--skip-tec", action="store_true", help="Skip BMU <-> TEC connection-site matching")
    parser.add_argument("--skip-substation-links", action="store_true", help="Skip substation <-> BMU augmentation")
    parser.add_argument("--skip-tiles", action="store_true", help="Skip PMTiles build")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Pass --no-cache to the OSM export (ignore boundary/feature caches)",
    )
    return parser.parse_args()


def run_step(
    title: str,
    argv: list[str],
    *,
    critical: bool,
    results: list[tuple[str, str]],
) -> bool:
    """Run a pipeline script as a subprocess; record and report its outcome."""
    print("\n" + "=" * 72)
    print(f">> {title}")
    print("=" * 72, flush=True)
    start = time.time()
    proc = subprocess.run([sys.executable, *argv])
    elapsed = time.time() - start
    if proc.returncode == 0:
        print(f"[OK]   {title} ({elapsed:.0f}s)")
        results.append((title, "ok"))
        return True
    note = "FAILED (critical)" if critical else "failed (continuing)"
    print(f"[FAIL] {title}: exit {proc.returncode} - {note}", file=sys.stderr)
    results.append((title, f"failed (exit {proc.returncode})"))
    return False


def main() -> int:
    args = parse_args()
    uk_only = args.region == "uk"
    results: list[tuple[str, str]] = []

    if not uk_only and not (args.skip_elexon and args.skip_zones and args.skip_bmu_match):
        print(
            f"Region {args.region!r}: Elexon, NESO zones, and BMU matching are UK-only; "
            "those steps will be skipped.",
        )

    # 1. Elexon BMU standing data (UK only).
    if not args.skip_elexon and uk_only:
        run_step(
            "Elexon BMU reference",
            [str(SCRIPTS / "fetch_bmu_reference.py")],
            critical=False,
            results=results,
        )

    # 2. NESO zone boundaries (UK only).
    if not args.skip_zones and uk_only:
        run_step(
            "NESO zone boundaries",
            [str(SCRIPTS / "fetch_neso_zones.py")],
            critical=False,
            results=results,
        )

    # 3. OSM power export from a local PBF, when available.
    pbf = None if args.skip_osm else find_pbf(args.osm_pbf, args.region)
    if args.osm_pbf is not None and not args.skip_osm and pbf is None:
        print(f"Requested PBF not found: {args.osm_pbf}", file=sys.stderr)
        return 2
    if pbf is not None:
        export_argv = [
            str(SCRIPTS / "export_region.py"),
            "--region",
            args.region,
            "--all",
            "--osm-pbf",
            str(pbf),
        ]
        if args.no_cache:
            export_argv.append("--no-cache")
        if not run_step(f"OSM export from {pbf.name}", export_argv, critical=True, results=results):
            return 1
    else:
        reason = "--skip-osm set" if args.skip_osm else "no .osm.pbf under data/regions/{region}/source/"
        print(f"\nSkipping OSM export ({reason}); reusing existing data/regions/{args.region}/raw/ exports.")
        results.append(("OSM export", "skipped"))

    # 4. Re-fetch plant polygons from Overpass (UK only). GDAL's OSM driver drops
    # most power=plant relations, so this overwrites raw/plants.geojson with the
    # full set (onshore + offshore + construction/closed status).
    if not args.skip_plant_fetch and uk_only:
        run_step(
            "Plant polygons via Overpass",
            [str(SCRIPTS / "fetch_plants_overpass.py"), "--region", args.region],
            critical=False,
            results=results,
        )

    # 5. Top up offshore wind turbines the land-clipped generator export misses.
    # Must run after the OSM export (which regenerates wind_turbines.csv); it
    # dedupes by osm_id so re-runs are idempotent.
    if not args.skip_offshore_turbines and uk_only:
        run_step(
            "Offshore wind turbines",
            [str(SCRIPTS / "fetch_offshore_turbines.py"), "--region", args.region],
            critical=False,
            results=results,
        )

    # Optional clean rebuild: drop the ground-truth plant layer so sync rebuilds
    # it from the fresh Overpass plants + manual_plants (no stale/accumulated
    # features). Manual data in the editable CSVs is preserved regardless.
    if args.rebuild_plants:
        from common import map_dir

        plant_layer = map_dir(args.region) / "bmu_sites_web.geojson"
        if plant_layer.exists():
            plant_layer.unlink()
            print(f"\nRemoved {plant_layer.relative_to(REPO_ROOT)} for a clean rebuild.")

    # 6. Build the lightweight web GeoJSON layers (and prepared zones).
    if not args.skip_prepare:
        if not run_step(
            "Prepare web layers",
            [str(SCRIPTS / "prepare_map_data.py"), "--region", args.region],
            critical=True,
            results=results,
        ):
            return 1

    # 7. Derive turbine-cluster boundaries for farms OSM maps only as points.
    if not args.skip_boundaries and uk_only:
        run_step(
            "Derived wind-farm boundaries",
            [str(SCRIPTS / "derive_plant_boundaries.py"), "--region", args.region],
            critical=False,
            results=results,
        )

    # 5. Match OSM plants to Elexon BMUs (UK only). Elexon reference was already
    # refreshed above, so no extra --fetch here.
    if not args.skip_bmu_match and uk_only:
        run_step(
            "Plant <-> BMU matching",
            [str(SCRIPTS / "propose_plant_bmu_map.py")],
            critical=False,
            results=results,
        )

    # Match BMUs to TEC connection sites / substations (UK only). Downloads the
    # TEC Register fresh; appends only high-confidence auto matches.
    if not args.skip_tec and uk_only:
        run_step(
            "BMU <-> TEC connection sites",
            [str(SCRIPTS / "propose_bmu_connection_sites.py"), "--fetch"],
            critical=False,
            results=results,
        )

    # Augment substations_web.geojson with connected BMUs/plants (UK only). Must
    # run after prepare (regenerates the layer) and after the TEC step (provides
    # connection sites); re-runs are idempotent.
    if not args.skip_substation_links and uk_only:
        run_step(
            "Substation <-> BMU links",
            [str(SCRIPTS / "match_substation_bmus.py"), "--region", args.region],
            critical=False,
            results=results,
        )

    # 6. Tile the PMTiles layers (lines/turbines/towers). Requires tippecanoe.
    if not args.skip_tiles:
        run_step(
            "Build PMTiles",
            [str(SCRIPTS / "build_tiles.py"), "--region", args.region],
            critical=False,
            results=results,
        )

    print("\n" + "=" * 72)
    print("Refresh summary")
    print("=" * 72)
    for title, status in results:
        print(f"  {status:>18}  {title}")
    print("\nServe locally with: python scripts/serve_map.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
