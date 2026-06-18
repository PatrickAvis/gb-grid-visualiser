#!/usr/bin/env python3
"""Match BMUs to TEC connection sites (substations) and export map runtime JSON.

Appends high-confidence BMU→connection-site matches to the editable table
(reference/editable/bmu_connection_sites.csv), writes a review queue of weaker
matches (reference/generated/bmu_connection_site_candidates.csv), and exports
the map runtime JSON (reference/generated/bmu_connection_sites.json).

Existing editable rows are never overwritten — copy accepted candidates into the
editable CSV by hand, set source=manual, and re-run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from bmu_data import BMU_REFERENCE_PATH, fetch_bmunits, load_bmunits, save_bmunits
from tec_register import (
    export_connection_sites_json,
    fetch_tec_register,
    load_tec_register,
    propose_connection_sites,
    save_connection_sites,
    write_connection_site_candidates,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Download fresh TEC Register and Elexon BMU reference before matching",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.fetch:
        records = fetch_bmunits()
        save_bmunits(records)
        print(f"Fetched {len(records):,} BMUs from Elexon")
        tec = fetch_tec_register()
        print(f"Fetched {len(tec):,} TEC rows from NESO")
    else:
        if not BMU_REFERENCE_PATH.exists():
            print("BMU reference not found; run with --fetch or scripts/fetch_bmu_reference.py", file=sys.stderr)
            return 1
        tec = load_tec_register()

    bmunits = load_bmunits()
    frame, candidates = propose_connection_sites(bmunits, tec)
    csv_path = save_connection_sites(frame)
    cand_path = write_connection_site_candidates(candidates)
    json_path = export_connection_sites_json(frame)

    sited = (frame["connection_site"].astype(str).str.strip() != "").sum()
    print(f"Connection sites: {sited:,} mapped BMUs, {len(candidates):,} candidates for review")
    for path in (csv_path, cand_path, json_path):
        print(f"Wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
