"""NESO TEC Register ingest + BMU ↔ connection-site (substation) matching.

The TEC (Transmission Entry Capacity) Register lists every transmission-connected
generation/storage project together with the **named connection substation**
(``Connection Site``). It does not carry Elexon BMU ids, so BMUs are joined to a
connection site by **name matching** the BMU against the TEC ``Project Name`` /
``Customer Name`` — reusing the same normalisation machinery as the plant↔BMU
matcher in ``bmu_data``.

Flow (mirrors the plant↔BMU links flow):

    fetch  reference/source/neso_tec_register.csv          (fetch_tec_register)
    edit   reference/editable/bmu_connection_sites.csv      (accepted matches; append-only)
    run    scripts/propose_bmu_connection_sites.py [--fetch]
    read   reference/generated/bmu_connection_sites.json    (catalog `bmuConnectionSites`)
           reference/generated/bmu_connection_site_candidates.csv  (review queue)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from bmu_data import (
    UK_REFERENCE_EDITABLE_DIR,
    UK_REFERENCE_GENERATED_DIR,
    UK_REFERENCE_SOURCE_DIR,
    bmu_alias_names,
    classify_bmu,
    compact_site_name,
    is_empty,
    is_supplier_or_virtual_bmu,
    normalize_bmu_site_name,
    normalize_site_name,
)
from common import FILE_ENCODING

# CKAN datastore resource on the NESO data portal. The resource id is stable
# across the twice-weekly (Tue/Fri) republishes; only the dated CSV filename
# changes, so the dump endpoint (keyed on resource id) is the durable URL.
# https://www.neso.energy/data-portal/transmission-entry-capacity-tec-register
TEC_REGISTER_RESOURCE_ID = "17becbab-e3e8-473f-b303-3806f43a6a10"
TEC_REGISTER_DUMP_URL = f"https://api.neso.energy/datastore/dump/{TEC_REGISTER_RESOURCE_ID}"

TEC_REGISTER_PATH = UK_REFERENCE_SOURCE_DIR / "neso_tec_register.csv"
BMU_CONNECTION_SITES_PATH = UK_REFERENCE_EDITABLE_DIR / "bmu_connection_sites.csv"
BMU_CONNECTION_SITES_JSON_PATH = UK_REFERENCE_GENERATED_DIR / "bmu_connection_sites.json"
BMU_CONNECTION_SITE_CANDIDATES_PATH = (
    UK_REFERENCE_GENERATED_DIR / "bmu_connection_site_candidates.csv"
)

# Exact TEC Register column headers (verified against the live datastore).
TEC_COL_PROJECT = "Project Name"
TEC_COL_CUSTOMER = "Customer Name"
TEC_COL_SITE = "Connection Site"
TEC_COL_MW = "MW Connected"
TEC_COL_STATUS = "Project Status"
TEC_COL_PLANT_TYPE = "Plant Type"
TEC_COL_HOST_TO = "HOST TO"
TEC_COL_PROJECT_ID = "Project ID"
TEC_COL_AGREEMENT = "Agreement Type"

CONNECTION_COLUMNS = (
    "bmu_id",
    "ngc_bmu_id",
    "connection_site",
    "plant_type",
    "host_to",
    "project_id",
    "source",
    "notes",
)

# TEC ``Plant Type`` values are free-ish text ("Wind Onshore", "CCGT (Combined
# Cycle Gas Turbine)", "PV Array (Photo Voltaic/solar)") and may combine several
# with ";". Map by keyword scan to the Elexon ``fuelType`` codes each may pair
# with, so a name match can be sanity-checked against fuel. (order matters:
# ccgt/ocgt before the generic "gas" fallback.)
TEC_PLANT_TYPE_KEYWORDS: tuple[tuple[str, frozenset[str]], ...] = (
    ("wind", frozenset({"WIND"})),
    ("solar", frozenset({"OTHER"})),
    ("photo", frozenset({"OTHER"})),
    ("pv", frozenset({"OTHER"})),
    ("storage", frozenset({"OTHER", "PS"})),
    ("battery", frozenset({"OTHER"})),
    ("ccgt", frozenset({"CCGT"})),
    ("ocgt", frozenset({"OCGT"})),
    ("gas", frozenset({"CCGT", "OCGT"})),
    ("nuclear", frozenset({"NUCLEAR"})),
    ("pumped", frozenset({"PS"})),
    ("hydro", frozenset({"NPSHYD", "PS"})),
    ("biomass", frozenset({"BIOMASS"})),
    ("coal", frozenset({"COAL"})),
    ("interconnector", frozenset({"INT"})),
    ("tidal", frozenset({"OTHER"})),
    ("wave", frozenset({"OTHER"})),
)


def _plant_type_fuels(plant_type: str) -> frozenset[str]:
    """Elexon fuel codes a TEC plant-type string may pair with (keyword scan)."""
    text = plant_type.lower()
    fuels: set[str] = set()
    for keyword, codes in TEC_PLANT_TYPE_KEYWORDS:
        if keyword in text:
            fuels |= codes
    return frozenset(fuels)

_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}


def fetch_tec_register(*, url: str = TEC_REGISTER_DUMP_URL, timeout: int = 120) -> pd.DataFrame:
    """Download the TEC Register CSV, save it to source/, and return it."""
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    TEC_REGISTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEC_REGISTER_PATH.write_bytes(response.content)
    return load_tec_register()


def load_tec_register(path: Path = TEC_REGISTER_PATH) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"TEC Register not found: {path}\nRun: python scripts/fetch_tec_register.py",
        )
    frame = pd.read_csv(path, dtype=str).fillna("")
    frame.columns = [str(col).strip() for col in frame.columns]
    return frame


def tec_plant_type_compatible(plant_type: str | None, bmu_fuel: str | None) -> bool | None:
    """Return True/False when TEC plant type vs Elexon fuel is known, else None.

    A TEC row may list several plant types (";"-joined); the BMU is compatible
    if it matches any of them.
    """
    if is_empty(plant_type) or is_empty(bmu_fuel):
        return None
    allowed = _plant_type_fuels(str(plant_type))
    if not allowed:
        return None
    fuel = str(bmu_fuel).strip().upper()
    if fuel.startswith("INT"):
        return "INT" in allowed
    return fuel in allowed


def _name_match(bmu_terms: list[tuple[str, str]], tec_terms: list[tuple[str, str]]):
    """Best (rank, confidence, reason) name match between two name lists, or None."""
    best: tuple[int, str, str] | None = None
    for blabel, bname in bmu_terms:
        bn = normalize_site_name(bname)
        bsite = normalize_bmu_site_name(bname)
        bc = compact_site_name(bname)
        if not bn:
            continue
        for tlabel, tname in tec_terms:
            tn = normalize_site_name(tname)
            tsite = normalize_bmu_site_name(tname)
            tc = compact_site_name(tname)
            if not tn:
                continue

            conf: str | None = None
            if bn == tn:
                conf, reason = "high", f"exact:{blabel}~{tlabel}"
            elif bc and bc == tc:
                conf, reason = "high", f"compact:{blabel}~{tlabel}"
            elif bsite and tsite and bsite == tsite:
                conf, reason = "high", f"site:{blabel}~{tlabel}"
            elif bsite and tsite and len(bsite) >= 5 and len(tsite) >= 5 and (
                bsite in tsite or tsite in bsite
            ):
                conf, reason = "medium", f"contains:{blabel}~{tlabel}"
            else:
                words = bn.split()
                if len(words) >= 2:
                    phrase = " ".join(words[:2])
                    if len(phrase) >= 5 and phrase in tn:
                        conf, reason = "low", f"phrase:{blabel}~{tlabel}"

            if conf is None:
                continue
            rank = _CONFIDENCE_RANK[conf]
            if best is None or rank < best[0]:
                best = (rank, conf, reason)
                if rank == 0:
                    return best
    return best


def _cap(match, ceiling: str):
    """Cap a match's confidence at ``ceiling`` (used for company-only matches)."""
    if match is None:
        return None
    rank, conf, reason = match
    ceiling_rank = _CONFIDENCE_RANK[ceiling]
    if rank < ceiling_rank:
        return (ceiling_rank, ceiling, f"{reason}|capped")
    return match


def best_connection_site_for_bmu(
    bmu: dict[str, Any],
    tec_records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Best TEC connection-site match for one BMU, or None.

    Project-name matches can reach ``high``; company (Customer↔leadParty) matches
    are capped at ``medium`` because a single utility owns many TEC projects and a
    bare company match cannot disambiguate which substation.
    """
    alias_terms = bmu_alias_names(bmu)
    company_terms = alias_terms + [("leadParty", str(bmu.get("leadPartyName") or ""))]
    fuel = bmu.get("fuelType")

    best: tuple[int, str, str, dict[str, Any], bool | None] | None = None
    for rec in tec_records:
        proj_match = _name_match(alias_terms, [("project", rec.get(TEC_COL_PROJECT, ""))])
        cust_match = _cap(
            _name_match(company_terms, [("customer", rec.get(TEC_COL_CUSTOMER, ""))]),
            "medium",
        )
        chosen = min(
            (m for m in (proj_match, cust_match) if m is not None),
            key=lambda m: m[0],
            default=None,
        )
        if chosen is None:
            continue
        rank, conf, reason = chosen

        compat = tec_plant_type_compatible(rec.get(TEC_COL_PLANT_TYPE), fuel)
        if compat is False:
            if conf != "high":
                continue
            conf, rank, reason = "medium", 1, f"{reason};type_mismatch"

        if best is None or rank < best[0]:
            best = (rank, conf, reason, rec, compat)

    if best is None:
        return None
    rank, conf, reason, rec, compat = best
    return {
        "confidence": conf,
        "reason": reason,
        "fuel_compatible": compat,
        "record": rec,
    }


def load_connection_sites(path: Path = BMU_CONNECTION_SITES_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=list(CONNECTION_COLUMNS))
    frame = pd.read_csv(path, comment="#", dtype=str).fillna("")
    for col in CONNECTION_COLUMNS:
        if col not in frame.columns:
            frame[col] = ""
    return frame[list(CONNECTION_COLUMNS)].copy()


def save_connection_sites(
    frame: pd.DataFrame,
    path: Path = BMU_CONNECTION_SITES_PATH,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame[list(CONNECTION_COLUMNS)].to_csv(path, index=False)
    return path


def _connection_row(bmu: dict[str, Any], match: dict[str, Any], *, source: str) -> dict[str, str]:
    rec = match["record"]
    notes = (
        f"confidence={match['confidence']}; reason={match['reason']}; "
        f"fuel_compatible={match['fuel_compatible']}; "
        f"project={rec.get(TEC_COL_PROJECT, '')}; status={rec.get(TEC_COL_STATUS, '')}; "
        f"mw={rec.get(TEC_COL_MW, '')}"
    )
    return {
        "bmu_id": str(bmu.get("elexonBmUnit") or "").strip(),
        "ngc_bmu_id": str(bmu.get("nationalGridBmUnit") or "").strip(),
        "connection_site": str(rec.get(TEC_COL_SITE, "")).strip(),
        "plant_type": str(rec.get(TEC_COL_PLANT_TYPE, "")).strip(),
        "host_to": str(rec.get(TEC_COL_HOST_TO, "")).strip(),
        "project_id": str(rec.get(TEC_COL_PROJECT_ID, "")).strip(),
        "source": source,
        "notes": notes,
    }


def propose_connection_sites(
    bmunits: list[dict[str, Any]],
    tec_frame: pd.DataFrame,
    *,
    map_path: Path = BMU_CONNECTION_SITES_PATH,
    auto_confidence: str = "high",
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    """Append high-confidence BMU→connection-site matches; return (table, candidates).

    Existing rows are never overwritten (append-only, same contract as the
    plant↔BMU links). Sub-``high`` matches go to the candidates review queue.
    """
    frame = load_connection_sites(map_path)
    mapped = {str(v).strip().upper() for v in frame["bmu_id"] if str(v).strip()}

    tec_records = [
        rec
        for rec in tec_frame.to_dict("records")
        if not is_empty(rec.get(TEC_COL_SITE)) and not is_empty(rec.get(TEC_COL_PROJECT))
    ]

    new_rows: list[dict[str, str]] = []
    candidates: list[dict[str, str]] = []
    for bmu in bmunits:
        if classify_bmu(bmu) != "displayable" or is_supplier_or_virtual_bmu(bmu):
            continue
        bmu_id = str(bmu.get("elexonBmUnit") or "").strip().upper()
        if not bmu_id or bmu_id in mapped:
            continue
        match = best_connection_site_for_bmu(bmu, tec_records)
        if match is None:
            continue
        if match["confidence"] == auto_confidence:
            new_rows.append(_connection_row(bmu, match, source="auto"))
            mapped.add(bmu_id)
        else:
            candidates.append(_connection_row(bmu, match, source="manual"))

    if new_rows:
        frame = pd.concat([frame, pd.DataFrame(new_rows)], ignore_index=True)
    return frame, candidates


def write_connection_site_candidates(
    candidates: list[dict[str, str]],
    path: Path = BMU_CONNECTION_SITE_CANDIDATES_PATH,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(candidates, columns=list(CONNECTION_COLUMNS)).to_csv(path, index=False)
    return path


def export_connection_sites_json(
    frame: pd.DataFrame | None = None,
    *,
    csv_path: Path = BMU_CONNECTION_SITES_PATH,
    json_path: Path = BMU_CONNECTION_SITES_JSON_PATH,
) -> Path:
    """Write the map runtime JSON: one entry per BMU with a connection site."""
    if frame is None:
        frame = load_connection_sites(csv_path)
    entries = []
    for _, row in frame.iterrows():
        bmu_id = str(row.get("bmu_id") or "").strip()
        site = str(row.get("connection_site") or "").strip()
        if not bmu_id or not site:
            continue
        entries.append({
            "bmu_id": bmu_id,
            "ngc_bmu_id": str(row.get("ngc_bmu_id") or "").strip() or None,
            "connection_site": site,
            "plant_type": str(row.get("plant_type") or "").strip() or None,
            "host_to": str(row.get("host_to") or "").strip() or None,
        })
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding=FILE_ENCODING) as handle:
        json.dump(entries, handle, indent=2)
    return json_path
