#!/usr/bin/env python3
"""Audit the editable plant <-> BMU link table for integrity and likely errors.

Cross-checks every row of ``reference/editable/plant_bmu_links.csv`` against the
Elexon BMU registry and the OSM ground-truth sites, and writes a categorised
report to ``reference/generated/bmu_link_audit.csv``. The checks are deliberately
conservative: ``error`` rows are almost certainly wrong, ``warn`` rows are worth
a look, and ``info`` rows are a ranked review queue (noisy by nature, because
many Elexon ``bmUnitName`` values are uninformative like "Unit 1").

Checks
  error  bmu_unknown    bmu_id / ngc_bmu_id not in the Elexon registry
  error  osm_missing    non-manual osm_id resolves to no OSM site at all
  warn   osm_id_format  resolves only by numeric id, not exact string -> the map
                        falls back to fragile name matching instead of the id
  warn   multi_site     one BMU linked to several distinct physical sites
  warn   fuel_mismatch  plant source_bucket incompatible with BMU fuelType
  info   name_low_sim   low plant_name <-> bmUnitName similarity (review queue)

This is read-only: it never edits the link table.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from bmu_data import (
    BMU_REFERENCE_PATH,
    PLANT_BMU_MAP_PATH,
    UK_REFERENCE_GENERATED_DIR,
    _index_bmunits,
    fuel_compatible,
    is_empty,
    load_bmunits,
    load_plant_bmu_map,
    normalize_site_name,
)
from region_catalog import catalog_layer_path, map_path

AUDIT_PATH = UK_REFERENCE_GENERATED_DIR / "bmu_link_audit.csv"
SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}
DEFAULT_NAME_SIM = 0.30


def numeric_id(value: object) -> str | None:
    """Trailing OSM numeric id, ignoring any way//relation//node/ prefix."""
    if is_empty(value):
        return None
    match = re.search(r"(\d+)$", str(value).strip())
    return match.group(1) if match else None


def load_sites(plants_path: Path) -> tuple[set[str], dict[str, dict]]:
    """Return (exact osm_id strings, numeric_id -> first site properties)."""
    with plants_path.open(encoding="utf-8") as handle:
        geojson = json.load(handle)
    exact: set[str] = set()
    by_num: dict[str, dict] = {}
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        osm_id = props.get("osm_id")
        if is_empty(osm_id):
            continue
        exact.add(str(osm_id).strip())
        num = numeric_id(osm_id)
        if num and num not in by_num:
            by_num[num] = props
    return exact, by_num


def informative_bmu_name(name: str | None) -> bool:
    """True when bmUnitName is a real site name, not a code or "Unit N" filler."""
    norm = normalize_site_name(name)
    if not norm:
        return False
    if re.fullmatch(r"(unit|gas turbine|generator)?\s*\d*", norm):
        return False
    # Pure BMU codes like "t ryhps 1" carry no site-name signal.
    return not re.fullmatch(r"[a-z]\s+[a-z0-9]+(\s+\d+)?", norm)


def default_plants_path() -> Path:
    return catalog_layer_path("uk", "plants") or map_path("uk", "plants")


def audit(plants_path: Path, name_sim: float) -> list[dict]:
    frame = load_plant_bmu_map()
    bmunits = load_bmunits(BMU_REFERENCE_PATH)
    by_elexon, by_ngc = _index_bmunits(bmunits)
    exact_ids, sites_by_num = load_sites(plants_path)

    rows = frame.to_dict("records")
    findings: list[dict] = []

    # Pre-compute: distinct physical sites (numeric id) per BMU for multi_site.
    sites_per_bmu: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        bmu = str(row.get("bmu_id") or "").strip()
        osm = row.get("osm_id")
        if bmu and not is_empty(osm):
            key = numeric_id(osm) if not str(osm).startswith("manual/") else str(osm).strip()
            if key:
                sites_per_bmu[bmu].add(key)

    def cell(value: object) -> str:
        return "" if is_empty(value) else str(value).strip()

    def add(sev: str, issue: str, row: dict, detail: str) -> None:
        findings.append({
            "severity": sev,
            "issue": issue,
            "osm_id": cell(row.get("osm_id")),
            "plant_name": cell(row.get("plant_name")),
            "bmu_id": cell(row.get("bmu_id")),
            "ngc_bmu_id": cell(row.get("ngc_bmu_id")),
            "source": cell(row.get("source")),
            "detail": detail,
        })

    for row in rows:
        osm = "" if is_empty(row.get("osm_id")) else str(row["osm_id"]).strip()
        bmu_id = str(row.get("bmu_id") or "").strip()
        ngc_id = str(row.get("ngc_bmu_id") or "").strip()
        manual_site = osm.startswith("manual/")

        unit = by_elexon.get(bmu_id.upper()) or by_ngc.get(ngc_id.upper())

        # error: BMU not in registry
        if unit is None:
            add("error", "bmu_unknown", row, f"{bmu_id or ngc_id} absent from Elexon registry")

        # osm_id resolution (manual/ sites live in manual_plants.csv, not OSM)
        if not manual_site:
            num = numeric_id(osm)
            if num is None or num not in sites_by_num:
                add("error", "osm_missing", row, f"osm_id {osm} matches no OSM site")
            elif osm not in exact_ids:
                add("warn", "osm_id_format", row,
                    f"resolves by numeric id only; map join falls back to plant_name")

        # warn: one BMU spread across several sites
        if bmu_id and len(sites_per_bmu.get(bmu_id, set())) > 1:
            others = sorted(sites_per_bmu[bmu_id])
            add("warn", "multi_site", row, f"BMU on {len(others)} sites: {', '.join(others)}")

        if unit is not None:
            # warn: fuel mismatch (reuse the project's own compatibility logic)
            site = sites_by_num.get(numeric_id(osm) or "")
            bucket = (site or {}).get("source_bucket")
            compat = fuel_compatible(bucket, unit.get("fuelType"))
            if compat is False:
                add("warn", "fuel_mismatch", row,
                    f"site={bucket} vs bmu fuelType={unit.get('fuelType')}")

            # info: weak name agreement (only when the BMU name is informative)
            bmu_name = unit.get("bmUnitName")
            if informative_bmu_name(bmu_name):
                sim = SequenceMatcher(
                    None, normalize_site_name(row.get("plant_name")), normalize_site_name(bmu_name)
                ).ratio()
                if sim < name_sim:
                    add("info", "name_low_sim", row, f"sim={sim:.2f} vs '{bmu_name}'")

    findings.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["issue"], str(f["osm_id"])))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--plants", type=Path, default=None,
                        help="BMU-mapped sites GeoJSON (default: catalog uk/plants)")
    parser.add_argument("--out", type=Path, default=AUDIT_PATH,
                        help="Audit report CSV output path")
    parser.add_argument("--name-sim", type=float, default=DEFAULT_NAME_SIM,
                        help="name_low_sim threshold (0-1); lower = fewer flags")
    parser.add_argument("--show-multi-site", action="store_true",
                        help="Print the grouped multi-site BMU breakdown to stdout")
    args = parser.parse_args()

    plants_path = args.plants or default_plants_path()
    if not plants_path.exists():
        print(f"Plants file not found: {plants_path}", file=sys.stderr)
        return 1
    if not PLANT_BMU_MAP_PATH.exists():
        print(f"Link table not found: {PLANT_BMU_MAP_PATH}", file=sys.stderr)
        return 1

    findings = audit(plants_path, args.name_sim)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["severity", "issue", "osm_id", "plant_name", "bmu_id", "ngc_bmu_id", "source", "detail"]
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(findings)

    by_issue: dict[tuple[str, str], int] = defaultdict(int)
    for f in findings:
        by_issue[(f["severity"], f["issue"])] += 1
    print(f"Audited {sum(1 for _ in findings):,} findings -> {args.out.relative_to(REPO_ROOT)}")
    for (sev, issue), n in sorted(by_issue.items(), key=lambda kv: (SEVERITY_ORDER[kv[0][0]], kv[0][1])):
        print(f"  {sev:5} {issue:14} {n:>4}")
    if not findings:
        print("  (clean)")

    if args.show_multi_site:
        groups: dict[str, set[str]] = defaultdict(set)
        names: dict[str, str] = {}
        for f in findings:
            if f["issue"] == "multi_site":
                groups[f["bmu_id"]].add(str(f["osm_id"]))
                names.setdefault(f["bmu_id"], f["plant_name"])
        if groups:
            print("\nMulti-site BMUs (one BMU, several sites):")
            for bmu in sorted(groups):
                print(f"  {bmu:14} ({names[bmu]}) -> {', '.join(sorted(groups[bmu]))}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
