#!/usr/bin/env python3
"""Link OSM substations to their connected BMUs/plants via TEC connection sites.

Matches TEC connection-site names to OSM transmission substation names (appending
high-confidence matches to reference/editable/connection_site_substations.csv and
writing a review queue), then augments map/substations_web.geojson in place so a
substation popup lists its connected BMUs, plants, and total capacity.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from common import map_dir
from substation_links import (
    augment_substations,
    load_substation_features,
    propose_substation_links,
    save_substation_links,
    write_substation_candidates,
)
from tec_register import BMU_CONNECTION_SITES_PATH, load_connection_sites


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--region", default="uk", help="Catalog region id (default: uk)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not BMU_CONNECTION_SITES_PATH.exists():
        print("No BMU connection sites; run scripts/propose_bmu_connection_sites.py first", file=sys.stderr)
        return 1

    conn = load_connection_sites(BMU_CONNECTION_SITES_PATH)
    sites = sorted({s.strip() for s in conn["connection_site"] if str(s).strip()})

    web_path = map_dir(args.region) / "substations_web.geojson"
    if not web_path.exists():
        print(f"Substations layer not found: {web_path}", file=sys.stderr)
        return 1
    features = load_substation_features(web_path)

    frame, review = propose_substation_links(sites, features)
    save_substation_links(frame)
    write_substation_candidates(review)
    counts = augment_substations(region_id=args.region)

    print(
        f"Substation links: {len(frame):,} OSM-substation rows, {len(review):,} candidates; "
        f"augmented {counts['substations_augmented']:,} of {counts['features']:,} substation features",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
