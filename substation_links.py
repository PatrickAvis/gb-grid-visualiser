"""Reverse links: OSM substation -> connected BMUs + plants (via TEC connection site).

The TEC Register gives each BMU a ``Connection Site`` *name* (see tec_register).
This module resolves that name to the OSM substation polygon(s) you click on and
augments ``substations_web.geojson`` in place with the connected generation, so a
substation popup can list its BMUs, plants, and total connected capacity.

OSM substation features carry no stable id, so the join is name-based and the
augmentation writes back into the (script-generated) web GeoJSON:

    edit   reference/editable/connection_site_substations.csv   (connection_site -> OSM name)
    run    scripts/match_substation_bmus.py
    write  map/substations_web.geojson                           (+connected_* props)
           reference/generated/connection_site_substation_candidates.csv  (review queue)

Existing editable rows are never overwritten (append-only, like the other links).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from bmu_data import (
    UK_REFERENCE_EDITABLE_DIR,
    UK_REFERENCE_GENERATED_DIR,
    PLANT_BMU_MAP_PATH,
    compact_site_name,
    is_empty,
    load_bmunits,
    load_plant_bmu_map,
    normalize_site_name,
)
from common import FILE_ENCODING, map_dir
from tec_register import BMU_CONNECTION_SITES_PATH, load_connection_sites

CONNECTION_SITE_SUBSTATIONS_PATH = UK_REFERENCE_EDITABLE_DIR / "connection_site_substations.csv"
CONNECTION_SITE_SUBSTATION_CANDIDATES_PATH = (
    UK_REFERENCE_GENERATED_DIR / "connection_site_substation_candidates.csv"
)

SUBSTATION_LINK_COLUMNS = (
    "connection_site",
    "substation_name",
    "voltage",
    "source",
    "notes",
)

# Augmented property keys written onto matched substation features.
CONNECTED_PROPS = (
    "connection_site",
    "bmu_count",
    "connected_capacity_mw",
    "connected_bmus",
    "connected_plants",
)

# Tokens that describe the *kind* of substation rather than its place; dropped
# before name matching so "Connah's Quay 400kV AIS" ~ "Connah's Quay Substation".
_DROP_TOKENS = frozenset({
    "ais", "gis", "agis", "gsp", "grid", "substation", "sub", "station",
    "switching", "switch", "offshore", "onshore", "node", "bsp", "primary",
    "kv", "sgt", "compound", "site",
})

_VOLT_NUM = re.compile(r"(\d+(?:\.\d+)?)")


def parse_max_voltage(value: Any) -> float | None:
    """Largest voltage in volts from an OSM ``voltage`` tag (``"400000"`` etc.)."""
    if is_empty(value):
        return None
    best: float | None = None
    for part in re.split(r"[;,/]", str(value)):
        is_kv = "k" in part.lower()
        match = _VOLT_NUM.search(part)
        if not match:
            continue
        volts = float(match.group(1))
        if is_kv or volts < 1000:  # bare "132" means 132 kV
            volts *= 1000
        best = volts if best is None else max(best, volts)
    return best


def is_transmission(props: dict[str, Any], *, min_volts: float = 132_000) -> bool:
    if str(props.get("substation") or "").strip().lower() == "transmission":
        return True
    volts = parse_max_voltage(props.get("voltage"))
    return volts is not None and volts >= min_volts


def normalize_substation_name(name: str | None) -> str:
    text = normalize_site_name(name)
    if not text:
        return ""
    out = []
    for token in text.split():
        if token in _DROP_TOKENS or re.fullmatch(r"\d+", token) or re.fullmatch(r"\d+kv", token):
            continue
        out.append(token)
    return " ".join(out)


def load_substation_features(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding=FILE_ENCODING) as handle:
        return json.load(handle)["features"]


def load_substation_links(path: Path = CONNECTION_SITE_SUBSTATIONS_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=list(SUBSTATION_LINK_COLUMNS))
    frame = pd.read_csv(path, comment="#", dtype=str).fillna("")
    for col in SUBSTATION_LINK_COLUMNS:
        if col not in frame.columns:
            frame[col] = ""
    return frame[list(SUBSTATION_LINK_COLUMNS)].copy()


def save_substation_links(frame: pd.DataFrame, path: Path = CONNECTION_SITE_SUBSTATIONS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame[list(SUBSTATION_LINK_COLUMNS)].to_csv(path, index=False)
    return path


def propose_substation_links(
    connection_sites: list[str],
    features: list[dict[str, Any]],
    *,
    map_path: Path = CONNECTION_SITE_SUBSTATIONS_PATH,
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    """Match connection-site names to OSM transmission substation names.

    Exact (space-insensitive) name matches are appended to the editable table;
    containment matches go to the candidates review queue. Append-only.
    """
    frame = load_substation_links(map_path)
    existing = {str(v).strip().lower() for v in frame["connection_site"] if str(v).strip()}

    # Index transmission substations by compacted normalised name.
    candidates_by_compact: dict[str, list[dict[str, Any]]] = {}
    transmission: list[tuple[str, dict[str, Any]]] = []
    for feat in features:
        props = feat.get("properties", {})
        name = props.get("name")
        if is_empty(name) or not is_transmission(props):
            continue
        norm = normalize_substation_name(name)
        if not norm:
            continue
        compact = compact_site_name(norm)
        if compact:
            candidates_by_compact.setdefault(compact, []).append(props)
        transmission.append((norm, props))

    new_rows: list[dict[str, str]] = []
    review: list[dict[str, str]] = []
    for site in connection_sites:
        if is_empty(site) or str(site).strip().lower() in existing:
            continue
        site_norm = normalize_substation_name(site)
        site_compact = compact_site_name(site_norm)
        if len(site_compact) < 5:
            continue

        exact = candidates_by_compact.get(site_compact, [])
        if exact:
            for props in exact:
                new_rows.append({
                    "connection_site": site,
                    "substation_name": props.get("name"),
                    "voltage": props.get("voltage"),
                    "source": "auto",
                    "notes": "exact_compact_name",
                })
            existing.add(str(site).strip().lower())
            continue

        for norm, props in transmission:
            compact = compact_site_name(norm)
            if len(compact) >= 5 and (site_compact in compact or compact in site_compact):
                review.append({
                    "connection_site": site,
                    "substation_name": props.get("name"),
                    "voltage": props.get("voltage"),
                    "source": "manual",
                    "notes": f"contains; substation_norm={norm}",
                })

    if new_rows:
        frame = pd.concat([frame, pd.DataFrame(new_rows)], ignore_index=True)
    return frame, review


def write_substation_candidates(
    review: list[dict[str, str]],
    path: Path = CONNECTION_SITE_SUBSTATION_CANDIDATES_PATH,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(review, columns=list(SUBSTATION_LINK_COLUMNS)).to_csv(path, index=False)
    return path


def _connection_site_bmus() -> dict[str, list[dict[str, Any]]]:
    """connection_site -> [{id, name, fuel, mw}], enriched from Elexon reference."""
    conn = load_connection_sites(BMU_CONNECTION_SITES_PATH)
    bmu_ref = {str(b.get("elexonBmUnit") or "").strip().upper(): b for b in load_bmunits()}
    plant_map = load_plant_bmu_map(PLANT_BMU_MAP_PATH)
    plant_by_bmu = {
        str(r.get("bmu_id") or "").strip().upper(): str(r.get("plant_name") or "").strip()
        for _, r in plant_map.iterrows()
        if not is_empty(r.get("bmu_id"))
    }

    by_site: dict[str, list[dict[str, Any]]] = {}
    for _, row in conn.iterrows():
        site = str(row.get("connection_site") or "").strip()
        bmu_id = str(row.get("bmu_id") or "").strip()
        if not site or not bmu_id:
            continue
        ref = bmu_ref.get(bmu_id.upper(), {})
        mw = ref.get("generationCapacity")
        by_site.setdefault(site, []).append({
            "id": bmu_id,
            "name": ref.get("bmUnitName") or ref.get("leadPartyName") or "",
            "fuel": ref.get("fuelType") or "",
            "mw": float(mw) if not is_empty(mw) else None,
            "plant": plant_by_bmu.get(bmu_id.upper(), ""),
        })
    return by_site


def augment_substations(
    *,
    region_id: str = "uk",
    links_path: Path = CONNECTION_SITE_SUBSTATIONS_PATH,
) -> dict[str, int]:
    """Write connected-BMU/plant props onto matched substation features in place."""
    web_path = map_dir(region_id) / "substations_web.geojson"
    with web_path.open(encoding=FILE_ENCODING) as handle:
        collection = json.load(handle)

    links = load_substation_links(links_path)
    site_bmus = _connection_site_bmus()

    # OSM substation name -> aggregated connection info (sites may share a name).
    by_osm_name: dict[str, dict[str, Any]] = {}
    for _, row in links.iterrows():
        osm_name = str(row.get("substation_name") or "").strip()
        site = str(row.get("connection_site") or "").strip()
        if not osm_name or not site:
            continue
        entry = by_osm_name.setdefault(osm_name, {"sites": set(), "bmus": []})
        entry["sites"].add(site)
        entry["bmus"].extend(site_bmus.get(site, []))

    def _fmt_bmu(b: dict[str, Any]) -> str:
        parts = [b["id"]]
        name = b.get("name") or ""
        # Drop the name when it just repeats the BMU id (common for unit BMUs).
        label = name if name and name.upper() != b["id"].upper() else ""
        descr = " ".join(p for p in (label, b.get("fuel")) if p)
        if descr:
            parts.append(f"({descr})")
        if b.get("mw") is not None:
            parts.append(f"{b['mw']:.0f}MW")
        return " ".join(parts)

    matched = 0
    cleared = 0
    for feat in collection["features"]:
        props = feat.get("properties", {})
        # Idempotent: drop any previous augmentation before re-applying.
        for key in CONNECTED_PROPS:
            if key in props:
                del props[key]
                cleared = 1
        entry = by_osm_name.get(str(props.get("name") or "").strip())
        if not entry or not entry["bmus"]:
            continue
        seen: set[str] = set()
        bmus = [b for b in entry["bmus"] if b["id"] not in seen and not seen.add(b["id"])]
        plants = sorted({b["plant"] for b in bmus if b.get("plant")})
        total_mw = sum(b["mw"] for b in bmus if b.get("mw") is not None)
        props["connection_site"] = "; ".join(sorted(entry["sites"]))
        props["bmu_count"] = len(bmus)
        props["connected_capacity_mw"] = f"{total_mw:.0f} MW"
        props["connected_bmus"] = "; ".join(_fmt_bmu(b) for b in bmus)
        if plants:
            props["connected_plants"] = "; ".join(plants)
        matched += 1

    with web_path.open("w", encoding=FILE_ENCODING) as handle:
        json.dump(collection, handle)

    return {"substations_augmented": matched, "features": len(collection["features"])}
