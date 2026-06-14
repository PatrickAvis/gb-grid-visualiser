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
  info   osm_id_format  link uses "way/123" but the geojson stores bare "123"
                        (handled by the map's normalized-id join; informational)
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


def name_similarity(a: str | None, b: str | None) -> float:
    return SequenceMatcher(None, normalize_site_name(a), normalize_site_name(b)).ratio()


def raw_name_similarity(a: str | None, b: str | None) -> float:
    """Similarity that keeps asset-type words (BESS, solar, power station).

    normalize_site_name strips those suffixes, which is right for general
    matching but collapses co-located assets (a BESS and a power station at one
    name) together. Disambiguating duplicates needs them preserved.
    """
    def raw(value: str | None) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()

    return SequenceMatcher(None, raw(a), raw(b)).ratio()


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


def audit(plants_path: Path, name_sim: float) -> tuple[list[dict], dict]:
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
                stored = str((sites_by_num.get(num) or {}).get("osm_id") or "").strip()
                add("info", "osm_id_format", row,
                    f"geojson stores '{stored}'; joined via normalized osm_id")

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
                sim = name_similarity(row.get("plant_name"), bmu_name)
                if sim < name_sim:
                    add("info", "name_low_sim", row, f"sim={sim:.2f} vs '{bmu_name}'")

    findings.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["issue"], str(f["osm_id"])))
    context = {
        "by_elexon": by_elexon,
        "by_ngc": by_ngc,
        "sites_by_num": sites_by_num,
        "sites_per_bmu": sites_per_bmu,
    }
    return findings, context


def _unit_for(ctx: dict, bmu_id: str, ngc_id: str) -> dict | None:
    return ctx["by_elexon"].get(bmu_id.upper()) or ctx["by_ngc"].get(ngc_id.upper())


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def write_suggestions(findings: list[dict], ctx: dict, out_dir: Path) -> list[tuple[Path, int]]:
    """Write one resolution-oriented CSV per issue type with suggested actions."""
    sites_by_num = ctx["sites_by_num"]
    written: list[tuple[Path, int]] = []

    def by_issue(issue: str) -> list[dict]:
        return [f for f in findings if f["issue"] == issue]

    # multi_site -> per BMU, suggest one canonical site to keep, consolidate rest.
    groups: dict[str, list[dict]] = defaultdict(list)
    for f in by_issue("multi_site"):
        groups[f["bmu_id"]].append(f)
    rows = []
    for bmu_id, items in sorted(groups.items()):
        osm_ids = sorted({i["osm_id"] for i in items})
        plant_name = items[0]["plant_name"]
        ngc_id = items[0]["ngc_bmu_id"]
        unit = _unit_for(ctx, bmu_id, ngc_id)
        bmu_name = (unit or {}).get("bmUnitName")

        def keep_score(osm: str) -> tuple[float, float, int]:
            site = sites_by_num.get(numeric_id(osm) or "")
            name = (site or {}).get("name")
            # The BMU's own name identifies which co-located asset it is (e.g. a
            # "... BESS" unit belongs to the battery feature, not the solar one),
            # so match that first; fall back to the link's plant_name, then prefer
            # a relation (whole-site boundary) only to break ties.
            is_relation = 1 if osm.startswith("relation/") else 0
            return (round(raw_name_similarity(name, bmu_name), 3),
                    round(raw_name_similarity(name, plant_name), 3),
                    is_relation)

        keep = max(osm_ids, key=keep_score)
        keep_site = (sites_by_num.get(numeric_id(keep) or "") or {}).get("name", "")
        if raw_name_similarity(keep_site, bmu_name) >= 0.5:
            reason = f"name matches BMU '{bmu_name}'"
        elif keep.startswith("relation/"):
            reason = "relation (site boundary)"
        else:
            reason = "closest name match"
        for osm in osm_ids:
            rows.append({
                "bmu_id": bmu_id,
                "ngc_bmu_id": ngc_id,
                "plant_name": plant_name,
                "bmu_name": bmu_name or "",
                "osm_id": osm,
                "site_name": (sites_by_num.get(numeric_id(osm) or "") or {}).get("name", ""),
                "suggested_action": "KEEP" if osm == keep else f"consolidate into {keep}",
                "keep_reason": reason if osm == keep else "",
            })
    written.append((out_dir / "bmu_audit_multi_site.csv", _write_csv(
        out_dir / "bmu_audit_multi_site.csv",
        ["bmu_id", "ngc_bmu_id", "plant_name", "bmu_name", "osm_id", "site_name",
         "suggested_action", "keep_reason"], rows)))

    # fuel_mismatch -> guess whether the OSM tag or the link is the problem.
    rows = []
    for f in by_issue("fuel_mismatch"):
        unit = _unit_for(ctx, f["bmu_id"], f["ngc_bmu_id"])
        bmu_name = (unit or {}).get("bmUnitName")
        site = sites_by_num.get(numeric_id(f["osm_id"]) or "")
        bucket = (site or {}).get("source_bucket", "")
        sim = name_similarity(f["plant_name"], bmu_name)
        if sim >= 0.5:
            cause, action = "BMU name matches site -> OSM fuel tag likely wrong", "verify OSM plant:source; keep link"
        else:
            cause, action = "weak name agreement -> link may be wrong", "verify; remove link if BMU is a different site"
        rows.append({
            "osm_id": f["osm_id"],
            "plant_name": f["plant_name"],
            "site_fuel_bucket": bucket,
            "bmu_id": f["bmu_id"],
            "bmu_fuel": (unit or {}).get("fuelType", ""),
            "bmu_name": bmu_name or "",
            "name_sim": f"{sim:.2f}",
            "likely_cause": cause,
            "suggested_action": action,
        })
    written.append((out_dir / "bmu_audit_fuel_mismatch.csv", _write_csv(
        out_dir / "bmu_audit_fuel_mismatch.csv",
        ["osm_id", "plant_name", "site_fuel_bucket", "bmu_id", "bmu_fuel", "bmu_name",
         "name_sim", "likely_cause", "suggested_action"], rows)))

    # name_low_sim -> a plain review queue, sorted weakest first.
    rows = []
    for f in by_issue("name_low_sim"):
        unit = _unit_for(ctx, f["bmu_id"], f["ngc_bmu_id"])
        rows.append({
            "osm_id": f["osm_id"],
            "plant_name": f["plant_name"],
            "bmu_id": f["bmu_id"],
            "ngc_bmu_id": f["ngc_bmu_id"],
            "bmu_name": (unit or {}).get("bmUnitName", ""),
            "detail": f["detail"],
            "source": f["source"],
            "suggested_action": "verify the link is the same physical site",
        })
    written.append((out_dir / "bmu_audit_name_review.csv", _write_csv(
        out_dir / "bmu_audit_name_review.csv",
        ["osm_id", "plant_name", "bmu_id", "ngc_bmu_id", "bmu_name", "detail",
         "source", "suggested_action"], rows)))

    return written


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
    parser.add_argument("--no-suggestions", action="store_true",
                        help="Skip writing the per-issue resolution-suggestion CSVs")
    parser.add_argument("--suggestions-dir", type=Path, default=UK_REFERENCE_GENERATED_DIR,
                        help="Directory for the per-issue suggestion CSVs")
    args = parser.parse_args()

    plants_path = args.plants or default_plants_path()
    if not plants_path.exists():
        print(f"Plants file not found: {plants_path}", file=sys.stderr)
        return 1
    if not PLANT_BMU_MAP_PATH.exists():
        print(f"Link table not found: {PLANT_BMU_MAP_PATH}", file=sys.stderr)
        return 1

    findings, context = audit(plants_path, args.name_sim)

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

    if not args.no_suggestions:
        written = write_suggestions(findings, context, args.suggestions_dir)
        print("\nResolution suggestions:")
        for path, n in written:
            print(f"  {n:>4} -> {path.relative_to(REPO_ROOT)}")

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
