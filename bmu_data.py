"""UK BMU reference data and OSM plant ↔ BMU mapping table."""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import requests

from common import FILE_ENCODING, REPO_ROOT

ELEXON_BMUNITS_URL = "https://data.elexon.co.uk/bmrs/api/v1/reference/bmunits/all?format=json"
# UK BMU reference data lives inside the portable per-region folder.
UK_REFERENCE_DIR = REPO_ROOT / "data" / "regions" / "uk" / "reference"
UK_REFERENCE_SOURCE_DIR = UK_REFERENCE_DIR / "source"
UK_REFERENCE_EDITABLE_DIR = UK_REFERENCE_DIR / "editable"
UK_REFERENCE_GENERATED_DIR = UK_REFERENCE_DIR / "generated"
UK_REFERENCE_OPERATIONAL_DIR = UK_REFERENCE_DIR / "operational"

BMU_REFERENCE_PATH = UK_REFERENCE_SOURCE_DIR / "elexon_bmu_units.json"
BMU_FUEL_TYPES_PATH = UK_REFERENCE_SOURCE_DIR / "elexon_bmu_fuel_types.csv"
BMU_OC2_MAP_PATH = UK_REFERENCE_SOURCE_DIR / "elexon_bmu_oc2_aliases.csv"
PLANT_BMU_MAP_PATH = UK_REFERENCE_EDITABLE_DIR / "plant_bmu_links.csv"
PLANT_BMU_MAP_JSON_PATH = UK_REFERENCE_GENERATED_DIR / "plant_bmu_links.json"
BMU_UNMAPPED_DISPLAYABLE_PATH = UK_REFERENCE_GENERATED_DIR / "bmu_unmapped_displayable.csv"
BMU_CANDIDATE_MATCHES_PATH = UK_REFERENCE_GENERATED_DIR / "plant_bmu_link_candidates.csv"
BMU_REFERENCE_ONLY_PATH = UK_REFERENCE_GENERATED_DIR / "bmu_reference_only.csv"
PLANTS_MISSING_BMU_PATH = UK_REFERENCE_GENERATED_DIR / "plants_without_bmu_links.csv"

MAP_COLUMNS = ("osm_id", "plant_name", "bmu_id", "ngc_bmu_id", "bmu_type", "source", "notes")
BMU_FIELDS = ("bmu_id", "ngc_bmu_id", "bmu_type")

# Elexon fuel types that represent physical generation, storage, or interconnectors.
DISPLAYABLE_FUEL_TYPES: frozenset[str] = frozenset({
    "WIND",
    "CCGT",
    "OCGT",
    "NPSHYD",
    "PS",
    "BIOMASS",
    "NUCLEAR",
    "COAL",
    "OTHER",
    "INTELEC",
    "INTGRNL",
    "INTVKL",
    "INTNED",
    "INTEW",
    "INTFR",
    "INTIFA2",
    "INTIRL",
    "INTNSL",
    "INTNEM",
})

# Supplier, virtual, and import BMUs are kept for reference but not plotted.
REFERENCE_ONLY_BMU_TYPES: frozenset[str] = frozenset({"S", "V", "I"})

# Map Elexon fuel codes to compatible OSM source_bucket values.
ELEXON_FUEL_TO_BUCKETS: dict[str, tuple[str, ...]] = {
    "WIND": ("wind", "wind_onshore", "wind_offshore"),
    "CCGT": ("gas", "gas_ccgt", "gas_chp"),
    "OCGT": ("gas", "gas_ocgt", "gas_chp"),
    "NPSHYD": ("hydro_non_pumped", "hydro"),
    "PS": ("hydro_pumped",),
    "BIOMASS": ("biomass", "biogas", "waste"),
    "NUCLEAR": ("nuclear",),
    "COAL": ("coal",),
    "OTHER": ("other", "battery", "geothermal", "tidal", "wave", "oil"),
}

UNIT_NUMBER_SUFFIX = re.compile(
    r"\s+(?:unit\s*)?\d+[a-z]?$|(?:\s*[-/]\s*\d+[a-z]?)+$",
    re.IGNORECASE,
)

NAME_ABBREVIATIONS = (
    (r"\bw\s*/\s*farm\b", "wind farm"),
    (r"\bw\s*/\s*f\b", "wind farm"),
    (r"\bwfarm\b", "wind farm"),
    (r"\bwf\b", "wind farm"),
    (r"\bp\s*/\s*s\b", "power station"),
)

NAME_SUFFIXES = (
    " power station",
    " wind farm",
    " solar farm",
    " solar park",
    " solar power plant",
    " energy storage system",
    " battery storage",
    " power plant",
    " bess",
)


def normalize_site_name(name: str | None) -> str:
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name)).lower()
    for pattern, replacement in NAME_ABBREVIATIONS:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    for suffix in NAME_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def compact_site_name(name: str | None) -> str:
    return normalize_site_name(name).replace(" ", "")


# OSM plant names too generic for reliable auto BMU matching.
GENERIC_PLANT_NAMES: frozenset[str] = frozenset(
    normalize_site_name(name)
    for name in (
        "Wind Farm",
        "Solar Plant",
        "Solar Farm",
        "Solar Panels",
        "Solar Light",
    )
)


def is_generic_plant_name(name: str | None) -> bool:
    return normalize_site_name(name) in GENERIC_PLANT_NAMES


def is_supplier_or_virtual_bmu(bmu: dict[str, Any]) -> bool:
    bmu_type = str(bmu.get("bmUnitType") or "").strip().upper()
    elexon = str(bmu.get("elexonBmUnit") or "").strip().upper()
    return bmu_type in REFERENCE_ONLY_BMU_TYPES or elexon.startswith("2__")


def normalize_bmu_site_name(name: str | None) -> str:
    """Strip unit numbers from BMU names like 'Dinorwig 1' -> 'dinorwig'."""
    text = normalize_site_name(name)
    if not text:
        return ""
    text = UNIT_NUMBER_SUFFIX.sub("", text).strip()
    return text


def is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _parse_capacity_mw(value: Any) -> float | None:
    if is_empty(value):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def classify_bmu(bmu: dict[str, Any]) -> str:
    """Classify a BMU as displayable, reference_only, or needs_review."""
    bmu_type = str(bmu.get("bmUnitType") or "").strip().upper()
    fuel = str(bmu.get("fuelType") or "").strip().upper()
    flag = str(bmu.get("productionOrConsumptionFlag") or "").strip().upper()
    interconnector = bmu.get("interconnectorId")
    generation_mw = _parse_capacity_mw(bmu.get("generationCapacity")) or 0.0

    if bmu_type in REFERENCE_ONLY_BMU_TYPES:
        return "reference_only"
    if fuel.startswith("INT") or not is_empty(interconnector):
        return "displayable"
    if fuel == "PS" and bmu_type in {"T", "E", "G"}:
        return "displayable"
    if flag == "C" and is_empty(interconnector):
        return "reference_only"
    if fuel in DISPLAYABLE_FUEL_TYPES:
        if bmu_type in {"T", "E", "G"}:
            return "displayable"
        return "needs_review"
    if bmu_type in {"T", "E", "G"} and generation_mw > 0:
        return "needs_review"
    return "reference_only"


def fuel_compatible(plant_bucket: str | None, bmu_fuel: str | None) -> bool | None:
    """Return True/False when compatibility is known, else None."""
    if is_empty(plant_bucket) or is_empty(bmu_fuel):
        return None
    bucket = str(plant_bucket).strip().lower()
    fuel = str(bmu_fuel).strip().upper()
    if fuel.startswith("INT"):
        return bucket in {"other", "oil", "gas"}
    allowed = ELEXON_FUEL_TO_BUCKETS.get(fuel)
    if allowed is None:
        return None
    return bucket in allowed


def fetch_bmunits(*, timeout: int = 120) -> list[dict[str, Any]]:
    response = requests.get(ELEXON_BMUNITS_URL, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("Unexpected Elexon BMU response shape")
    return payload


def save_bmunits(records: list[dict[str, Any]], path: Path = BMU_REFERENCE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=FILE_ENCODING) as handle:
        json.dump(records, handle, indent=2)
    return path


def load_bmunits(path: Path = BMU_REFERENCE_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(
            f"BMU reference not found: {path}\nRun: python scripts/fetch_bmu_reference.py",
        )
    with path.open(encoding=FILE_ENCODING) as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError(f"Unexpected BMU reference format in {path}")
    return payload


@lru_cache(maxsize=1)
def load_bmu_oc2_aliases(path: Path = BMU_OC2_MAP_PATH) -> dict[str, str]:
    """Load NGC/settlement BMU id -> OC2 group/site name aliases."""
    if not path.exists():
        return {}
    frame = pd.read_csv(path, comment="#")
    aliases: dict[str, str] = {}
    for _, row in frame.iterrows():
        group_name = row.get("BMGROUP_NAME")
        if is_empty(group_name):
            continue
        for col in ("NGC_BMU_ID", "SETT_BMU_ID"):
            value = row.get(col)
            if not is_empty(value):
                aliases[str(value).strip().upper()] = str(group_name).strip()
    return aliases


def bmu_alias_names(bmu: dict[str, Any]) -> list[tuple[str, str]]:
    """Return named aliases used for matching a BMU to an OSM plant."""
    aliases = [("bmUnitName", str(bmu.get("bmUnitName") or ""))]
    oc2 = load_bmu_oc2_aliases()
    for field, source in (
        ("nationalGridBmUnit", "oc2_BMGROUP_NAME"),
        ("elexonBmUnit", "oc2_BMGROUP_NAME"),
    ):
        key = str(bmu.get(field) or "").strip().upper()
        if key and key in oc2:
            aliases.append((source, oc2[key]))

    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for source, name in aliases:
        normalized = normalize_site_name(name)
        if normalized and normalized not in seen:
            deduped.append((source, name))
            seen.add(normalized)
    return deduped


def propose_match_candidates_for_plant(
    plant: pd.Series,
    bmunits: list[dict[str, Any]],
    *,
    displayable_only: bool = True,
) -> list[dict[str, Any]]:
    """Return candidate BMU matches with confidence and reason."""
    if is_empty(plant.get("name")):
        return []

    # Names like "Wind Farm" / "Solar Farm" are substrings of many BMU names and
    # produce a flood of false-positive matches, so they are not matchable.
    if is_generic_plant_name(plant.get("name")):
        return []

    plant_norm = normalize_site_name(str(plant["name"]))
    plant_bucket = plant.get("source_bucket")
    candidates: list[dict[str, Any]] = []

    for bmu in bmunits:
        if displayable_only and classify_bmu(bmu) != "displayable":
            continue

        fuel = bmu.get("fuelType")

        confidence: str | None = None
        reason: str | None = None

        for alias_source, alias_name in bmu_alias_names(bmu):
            alias_norm = normalize_site_name(alias_name)
            alias_site = normalize_bmu_site_name(alias_name)
            alias_compact = compact_site_name(alias_name)
            plant_compact = compact_site_name(plant["name"])

            if plant_norm and alias_norm == plant_norm:
                confidence = "high"
                reason = f"exact_{alias_source}"
            elif plant_norm and alias_site and plant_norm == alias_site:
                confidence = "high"
                reason = f"site_name_{alias_source}"
            elif plant_compact and alias_compact and plant_compact == alias_compact:
                confidence = "high"
                reason = f"compact_site_name_{alias_source}"
            elif plant_norm and alias_site and len(plant_norm) >= 5 and len(alias_site) >= 5:
                if plant_norm in alias_site or alias_site in plant_norm:
                    confidence = "medium"
                    reason = f"site_name_contains_{alias_source}"
            elif plant_norm:
                words = plant_norm.split()
                if len(words) >= 2:
                    phrase = " ".join(words[:2])
                    if len(phrase) >= 5 and phrase in alias_norm:
                        confidence = "medium"
                        reason = f"two_word_phrase_{alias_source}"
                if confidence is None and words:
                    token = words[0]
                    if len(token) >= 4:
                        pattern = re.compile(rf"\b{re.escape(token)}\b")
                        if pattern.search(alias_norm):
                            confidence = "low"
                            reason = f"first_token_{alias_source}"

            if confidence is not None:
                break

        if confidence is None:
            continue

        compat = fuel_compatible(plant_bucket, fuel)
        if compat is False and confidence != "high":
            continue
        if compat is False and confidence == "high":
            confidence = "medium"
            reason = f"{reason};fuel_mismatch"

        candidates.append({
            "bmu": bmu,
            "confidence": confidence,
            "reason": reason,
            "fuel_compatible": compat,
        })

    order = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(key=lambda item: order[item["confidence"]])
    return candidates


def match_bmunits_for_plant(plant_name: str | None, bmunits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """High-confidence BMU matches for a plant name (backward-compatible helper)."""
    plant = pd.Series({"name": plant_name, "source_bucket": None, "capacity_mw": None})
    return [
        item["bmu"]
        for item in propose_match_candidates_for_plant(plant, bmunits)
        if item["confidence"] == "high"
    ]


def mapped_bmu_ids(map_frame: pd.DataFrame) -> set[str]:
    return {
        str(value).strip().upper()
        for value in map_frame["bmu_id"].dropna()
        if str(value).strip()
    }


def dedupe_bare_osm_map_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop bare numeric osm_id rows when a prefixed row exists for the same BMU."""
    prefixed: set[tuple[str, str]] = set()
    for _, row in frame.iterrows():
        osm_id = "" if is_empty(row.get("osm_id")) else str(row["osm_id"]).strip()
        bmu_id = _key_part(row.get("bmu_id"))
        if "/" in osm_id:
            prefixed.add((osm_id.split("/", 1)[1], bmu_id))

    drop_idx = []
    for idx, row in frame.iterrows():
        osm_id = "" if is_empty(row.get("osm_id")) else str(row["osm_id"]).strip()
        bmu_id = _key_part(row.get("bmu_id"))
        if "/" not in osm_id and osm_id.isdigit() and (osm_id, bmu_id) in prefixed:
            drop_idx.append(idx)
    if drop_idx:
        frame = frame.drop(index=drop_idx).reset_index(drop=True)
    return frame


def _index_bmunits(bmunits: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_elexon: dict[str, dict[str, Any]] = {}
    by_ngc: dict[str, dict[str, Any]] = {}
    for row in bmunits:
        elexon = str(row.get("elexonBmUnit") or "").strip()
        ngc = str(row.get("nationalGridBmUnit") or "").strip()
        if elexon:
            by_elexon[elexon.upper()] = row
        if ngc:
            by_ngc[ngc.upper()] = row
    return by_elexon, by_ngc


def bmu_row_to_map_fields(bmu: dict[str, Any]) -> dict[str, str | None]:
    return {
        "bmu_id": str(bmu.get("elexonBmUnit") or "").strip() or None,
        "ngc_bmu_id": str(bmu.get("nationalGridBmUnit") or "").strip() or None,
        "bmu_type": str(bmu.get("bmUnitType") or "").strip() or None,
    }


def _split_ids(value: str | None) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def _empty_map_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=list(MAP_COLUMNS))


def load_plant_bmu_map(path: Path = PLANT_BMU_MAP_PATH) -> pd.DataFrame:
    if not path.exists():
        return _empty_map_frame()
    frame = pd.read_csv(path, comment="#")
    for col in MAP_COLUMNS:
        if col not in frame.columns:
            frame[col] = None
    return frame[list(MAP_COLUMNS)].copy()


def save_plant_bmu_map(frame: pd.DataFrame, path: Path = PLANT_BMU_MAP_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = frame[list(MAP_COLUMNS)].copy()
    out.to_csv(path, index=False)
    return path


def export_plant_bmu_map_json(
    frame: pd.DataFrame | None = None,
    *,
    csv_path: Path = PLANT_BMU_MAP_PATH,
    json_path: Path = PLANT_BMU_MAP_JSON_PATH,
) -> Path:
    if frame is None:
        frame = load_plant_bmu_map(csv_path)
    entries = []
    for _, row in frame.iterrows():
        entry = {col: (None if is_empty(row.get(col)) else str(row[col]).strip()) for col in MAP_COLUMNS}
        if not entry.get("osm_id") and not entry.get("plant_name"):
            continue
        entries.append(entry)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding=FILE_ENCODING) as handle:
        json.dump(entries, handle, indent=2)
    return json_path


def _key_part(value: Any) -> str:
    return "" if is_empty(value) else str(value).strip().upper()


def _map_row_key(osm_id: str | None, bmu_id: str | None, ngc_bmu_id: str | None) -> tuple[str, str, str]:
    return (
        "" if is_empty(osm_id) else str(osm_id).strip(),
        _key_part(bmu_id),
        _key_part(ngc_bmu_id),
    )


def map_contains(frame: pd.DataFrame, osm_id: str | None, bmu_id: str | None, ngc_bmu_id: str | None) -> bool:
    key = _map_row_key(osm_id, bmu_id, ngc_bmu_id)
    for _, row in frame.iterrows():
        if _map_row_key(row.get("osm_id"), row.get("bmu_id"), row.get("ngc_bmu_id")) == key:
            return True
    return False


def append_map_row(
    frame: pd.DataFrame,
    *,
    osm_id: str | None,
    plant_name: str | None,
    bmu_id: str | None,
    ngc_bmu_id: str | None,
    bmu_type: str | None,
    source: str,
    notes: str | None = None,
) -> pd.DataFrame:
    if map_contains(frame, osm_id, bmu_id, ngc_bmu_id):
        return frame
    row = {col: None for col in MAP_COLUMNS}
    row["osm_id"] = osm_id
    row["plant_name"] = plant_name
    row["bmu_id"] = bmu_id
    row["ngc_bmu_id"] = ngc_bmu_id
    row["bmu_type"] = bmu_type
    row["source"] = source
    row["notes"] = notes
    return pd.concat([frame, pd.DataFrame([row])], ignore_index=True)


def migrate_embedded_bmu_from_plants(plants: gpd.GeoDataFrame, frame: pd.DataFrame) -> pd.DataFrame:
    """Move legacy bmu_* properties from plant GeoJSON into the map table."""
    if not any(col in plants.columns for col in BMU_FIELDS):
        return frame

    added = 0
    for _, plant in plants.iterrows():
        if all(is_empty(plant.get(field)) for field in BMU_FIELDS):
            continue
        osm_id = None if is_empty(plant.get("osm_id")) else str(plant["osm_id"])
        plant_name = None if is_empty(plant.get("name")) else str(plant["name"])
        bmu_ids = _split_ids(plant.get("bmu_id"))
        ngc_ids = _split_ids(plant.get("ngc_bmu_id"))
        types = _split_ids(plant.get("bmu_type"))
        count = max(len(bmu_ids), len(ngc_ids), len(types), 1)
        for index in range(count):
            bmu_id = bmu_ids[index] if index < len(bmu_ids) else (bmu_ids[0] if bmu_ids else None)
            ngc_id = ngc_ids[index] if index < len(ngc_ids) else (ngc_ids[0] if ngc_ids else None)
            bmu_type = types[index] if index < len(types) else (types[0] if types else None)
            before = len(frame)
            frame = append_map_row(
                frame,
                osm_id=osm_id,
                plant_name=plant_name,
                bmu_id=bmu_id,
                ngc_bmu_id=ngc_id,
                bmu_type=bmu_type,
                source="migrated",
            )
            if len(frame) > before:
                added += 1
    if added:
        print(f"Migrated {added:,} embedded BMU rows from plants GeoJSON into map table")
    return frame


def propose_plant_bmu_map(
    plants: gpd.GeoDataFrame,
    *,
    reference_path: Path = BMU_REFERENCE_PATH,
    map_path: Path = PLANT_BMU_MAP_PATH,
    migrate_embedded: bool = True,
    auto_confidence: str = "high",
) -> pd.DataFrame:
    frame = load_plant_bmu_map(map_path)
    if migrate_embedded:
        frame = migrate_embedded_bmu_from_plants(plants, frame)

    if not reference_path.exists():
        print("Skipping auto proposals: BMU reference not found")
        return frame

    bmunits = load_bmunits(reference_path)
    already_mapped = mapped_bmu_ids(frame)
    proposed = 0
    for _, plant in plants.iterrows():
        if is_empty(plant.get("name")):
            continue
        plant_name = str(plant["name"])
        # Generic names are filtered inside propose_match_candidates_for_plant.
        osm_id = None if is_empty(plant.get("osm_id")) else str(plant["osm_id"])
        for candidate in propose_match_candidates_for_plant(plant, bmunits):
            if candidate["confidence"] != auto_confidence:
                continue
            if is_supplier_or_virtual_bmu(candidate["bmu"]):
                continue
            fields = bmu_row_to_map_fields(candidate["bmu"])
            if _key_part(fields["bmu_id"]) in already_mapped:
                continue
            before = len(frame)
            frame = append_map_row(
                frame,
                osm_id=osm_id,
                plant_name=plant_name,
                bmu_id=fields["bmu_id"],
                ngc_bmu_id=fields["ngc_bmu_id"],
                bmu_type=fields["bmu_type"],
                source="auto",
            )
            if len(frame) > before:
                proposed += 1
                already_mapped.add(_key_part(fields["bmu_id"]))

    frame = dedupe_bare_osm_map_rows(frame)
    print(f"BMU map: {len(frame):,} rows ({proposed:,} new high-confidence auto proposals)")
    return frame


def write_bmu_coverage_reports(
    plants: gpd.GeoDataFrame,
    map_frame: pd.DataFrame,
    bmunits: list[dict[str, Any]],
    *,
    unmapped_path: Path = BMU_UNMAPPED_DISPLAYABLE_PATH,
    candidates_path: Path = BMU_CANDIDATE_MATCHES_PATH,
    reference_only_path: Path = BMU_REFERENCE_ONLY_PATH,
) -> dict[str, int]:
    """Write review CSVs for displayable, candidate, and reference-only BMUs."""
    mapped_ids = mapped_bmu_ids(map_frame)
    candidate_rows: list[dict[str, Any]] = []
    unmapped_rows: list[dict[str, Any]] = []
    reference_rows: list[dict[str, Any]] = []
    seen_candidates: set[tuple[str, str]] = set()

    for _, plant in plants.iterrows():
        if is_empty(plant.get("name")):
            continue
        osm_id = None if is_empty(plant.get("osm_id")) else str(plant["osm_id"])
        for candidate in propose_match_candidates_for_plant(plant, bmunits):
            bmu = candidate["bmu"]
            bmu_id = str(bmu.get("elexonBmUnit") or "").strip().upper()
            if not bmu_id or bmu_id in mapped_ids:
                continue
            if candidate["confidence"] == "high":
                continue
            key = (osm_id or str(plant["name"]), bmu_id)
            if key in seen_candidates:
                continue
            seen_candidates.add(key)
            notes = (
                "Candidate match: "
                f"bmUnitName={bmu.get('bmUnitName') or ''}; "
                f"fuelType={bmu.get('fuelType') or ''}; "
                f"confidence={candidate['confidence']}; "
                f"reason={candidate['reason']}; "
                f"fuel_compatible={candidate['fuel_compatible']}"
            )
            candidate_rows.append({
                "osm_id": osm_id,
                "plant_name": plant.get("name"),
                "bmu_id": bmu.get("elexonBmUnit"),
                "ngc_bmu_id": bmu.get("nationalGridBmUnit"),
                "bmu_type": bmu.get("bmUnitType"),
                "source": "manual",
                "notes": notes,
            })

    for bmu in bmunits:
        bmu_id = str(bmu.get("elexonBmUnit") or "").strip().upper()
        category = classify_bmu(bmu)
        row = {
            "bmu_id": bmu.get("elexonBmUnit"),
            "ngc_bmu_id": bmu.get("nationalGridBmUnit"),
            "bmUnitName": bmu.get("bmUnitName"),
            "fuelType": bmu.get("fuelType"),
            "bmUnitType": bmu.get("bmUnitType"),
            "productionOrConsumptionFlag": bmu.get("productionOrConsumptionFlag"),
            "generationCapacity": bmu.get("generationCapacity"),
            "leadPartyName": bmu.get("leadPartyName"),
            "gspGroupName": bmu.get("gspGroupName"),
            "interconnectorId": bmu.get("interconnectorId"),
            "category": category,
            "mapped": bmu_id in mapped_ids if bmu_id else False,
        }
        if category == "reference_only":
            reference_rows.append(row)
        elif category == "displayable" and bmu_id and bmu_id not in mapped_ids:
            unmapped_rows.append(row)

    for path, rows, columns in (
        (unmapped_path, unmapped_rows, None),
        (candidates_path, candidate_rows, list(MAP_COLUMNS)),
        (reference_only_path, reference_rows, None),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows, columns=columns).to_csv(path, index=False)

    counts = {
        "unmapped_displayable": len(unmapped_rows),
        "candidate_matches": len(candidate_rows),
        "reference_only": len(reference_rows),
    }
    print(
        "BMU coverage reports: "
        f"{counts['unmapped_displayable']:,} unmapped displayable, "
        f"{counts['candidate_matches']:,} candidate matches, "
        f"{counts['reference_only']:,} reference-only",
    )
    return counts


def plants_missing_bmu_map(
    plants: gpd.GeoDataFrame,
    map_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if map_frame is None:
        map_frame = load_plant_bmu_map()

    mapped_osm = {
        str(value).strip()
        for value in map_frame["osm_id"].dropna()
        if str(value).strip()
    }
    mapped_names = {
        normalize_site_name(str(value))
        for value in map_frame["plant_name"].dropna()
        if normalize_site_name(str(value))
    }

    rows = []
    for _, plant in plants.iterrows():
        if is_empty(plant.get("name")):
            continue
        osm_id = None if is_empty(plant.get("osm_id")) else str(plant["osm_id"])
        if osm_id and osm_id in mapped_osm:
            continue
        name_key = normalize_site_name(str(plant["name"]))
        if name_key and name_key in mapped_names:
            continue
        rows.append({
            "osm_id": osm_id,
            "name": plant.get("name"),
            "operator": plant.get("operator"),
            "capacity_mw": plant.get("capacity_mw"),
            "source_bucket": plant.get("source_bucket"),
            "latitude": plant.get("latitude"),
            "longitude": plant.get("longitude"),
        })

    missing = pd.DataFrame(rows)
    if not missing.empty and "name" in missing.columns:
        missing = missing.sort_values("name")
    return missing.reset_index(drop=True)


def strip_bmu_from_plants(plants: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    frame = plants.copy()
    for field in BMU_FIELDS:
        if field in frame.columns:
            frame = frame.drop(columns=[field])
    return frame
