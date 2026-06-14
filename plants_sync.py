"""Merge OSM exports into the UK plants ground-truth GeoJSON (OSM fields only)."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from bmu_data import (
    BMU_FIELDS,
    export_plant_bmu_map_json,
    propose_plant_bmu_map,
    save_plant_bmu_map,
    strip_bmu_from_plants,
)
from manual_plants import merge_manual_plants
from prepare import bucket_plant_row, parse_capacity_to_mw

WEB_PLANT_COLS = [
    "osm_id",
    "power",
    "name",
    "operator",
    "plant:source",
    "plant:output:electricity",
    "generator:source",
    "generator:output:electricity",
    "longitude",
    "latitude",
    "capacity_mw",
    "source_bucket",
    "status",
]


def is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def osm_feature_id(row: pd.Series) -> str | None:
    element = row.get("element")
    osm_id = row.get("id")
    if osm_id is None or (isinstance(osm_id, float) and pd.isna(osm_id)):
        osm_id = row.get("osmid")
    if osm_id is None or (isinstance(osm_id, float) and pd.isna(osm_id)):
        return None
    try:
        osm_int = int(osm_id)
    except (TypeError, ValueError):
        return None
    if element and not (isinstance(element, float) and pd.isna(element)):
        return f"{element}/{osm_int}"
    return str(osm_int)


def trim_plant_columns(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    frame = strip_bmu_from_plants(frame)
    cols = [col for col in WEB_PLANT_COLS if col in frame.columns]
    if not cols:
        return frame
    return frame[cols + ["geometry"]]


def add_lat_lon_columns(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    reps = frame.geometry.representative_point()
    frame["longitude"] = reps.x
    frame["latitude"] = reps.y
    return frame


def plants_from_raw(source: Path) -> gpd.GeoDataFrame:
    raw_cols = [
        "element",
        "id",
        "osmid",
        "power",
        "name",
        "operator",
        "plant:source",
        "plant:output:electricity",
        "generator:source",
        "generator:output:electricity",
        "status",
    ]
    print(f"Reading OSM export {source.name}…")
    frame = gpd.read_file(source)
    keep = [col for col in raw_cols if col in frame.columns]
    frame = frame[keep + ["geometry"]].copy()
    frame["osm_id"] = frame.apply(osm_feature_id, axis=1)
    frame = add_lat_lon_columns(frame)
    capacity_raw = frame.get("plant:output:electricity")
    if capacity_raw is not None:
        frame["capacity_mw"] = capacity_raw.apply(parse_capacity_to_mw)
    source_raw = frame.get("plant:source")
    if source_raw is not None:
        frame["source_bucket"] = frame.apply(bucket_plant_row, axis=1)
    return trim_plant_columns(frame)


def _match_keys(row: pd.Series) -> list[tuple[str, float, float]]:
    name = row.get("name")
    if is_empty(name):
        return []
    lat = row.get("latitude")
    lon = row.get("longitude")
    if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
        return []
    name_key = str(name).strip().lower()
    lat_f = float(lat)
    lon_f = float(lon)
    keys = []
    for decimals in (5, 4, 3):
        key = (name_key, round(lat_f, decimals), round(lon_f, decimals))
        if key not in keys:
            keys.append(key)
    return keys


def _row_to_dict(row: pd.Series) -> dict:
    return {col: row[col] for col in row.index if col != "geometry"}


def merge_plant_properties(existing: pd.Series, incoming: pd.Series) -> pd.Series:
    merged = existing.copy()
    for col in incoming.index:
        if col in BMU_FIELDS or col == "geometry":
            continue
        incoming_value = incoming[col]
        if col == "source_bucket" and not is_empty(incoming_value):
            merged[col] = incoming_value
            continue
        if col not in merged.index:
            if not is_empty(incoming_value):
                merged[col] = incoming_value
            continue
        if is_empty(merged[col]) and not is_empty(incoming_value):
            merged[col] = incoming_value
    return merged


def merge_plants_ground_truth(
    existing: gpd.GeoDataFrame | None,
    incoming: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Keep existing values; fill blanks from incoming; append new OSM features."""
    incoming = trim_plant_columns(incoming)
    if existing is None or existing.empty:
        print(f"Creating ground-truth plants layer with {len(incoming):,} features")
        return incoming

    existing = trim_plant_columns(existing.copy())
    if "osm_id" not in existing.columns:
        existing["osm_id"] = None

    incoming_by_id: dict[str, pd.Series] = {}
    incoming_by_key: dict[tuple[str, float, float], pd.Series] = {}
    for _, row in incoming.iterrows():
        osm_id = row.get("osm_id")
        if not is_empty(osm_id):
            incoming_by_id[str(osm_id)] = row
        for key in _match_keys(row):
            incoming_by_key[key] = row

    matched_incoming: set[str] = set()
    merged_rows: list[dict] = []
    geometries: list = []

    def resolve_incoming(current: pd.Series) -> pd.Series | None:
        osm_id = current.get("osm_id")
        if not is_empty(osm_id) and str(osm_id) in incoming_by_id:
            return incoming_by_id[str(osm_id)]
        for key in _match_keys(current):
            if key in incoming_by_key:
                return incoming_by_key[key]
        return None

    for _, row in existing.iterrows():
        current = row.copy()
        incoming_row = resolve_incoming(current)

        if incoming_row is not None:
            if not is_empty(incoming_row.get("osm_id")):
                current["osm_id"] = incoming_row["osm_id"]
                matched_incoming.add(str(incoming_row["osm_id"]))
            current = merge_plant_properties(current, incoming_row)

        merged_rows.append(_row_to_dict(current))
        geometries.append(current.geometry)

    added = 0
    for osm_id, row in incoming_by_id.items():
        if osm_id in matched_incoming:
            continue
        merged_rows.append(_row_to_dict(row))
        geometries.append(row.geometry)
        added += 1

    result = gpd.GeoDataFrame(merged_rows, geometry=geometries, crs=existing.crs or incoming.crs)
    result = dedupe_plants_ground_truth(result)
    print(
        f"Ground-truth merge: kept {len(existing):,} existing, "
        f"filled gaps from OSM, added {added:,} new features",
    )
    return trim_plant_columns(result)


def _non_empty_count(row: pd.Series) -> int:
    return sum(1 for col in row.index if col != "geometry" and not is_empty(row[col]))


def dedupe_plants_ground_truth(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Drop duplicate OSM plants while keeping the richest property set."""
    if frame.empty or "osm_id" not in frame.columns:
        return frame

    drop_indices: list = []
    best_by_osm: dict[str, int] = {}
    names_with_osm: set[str] = set()

    for idx, row in frame.iterrows():
        osm_id = row.get("osm_id")
        if is_empty(osm_id):
            continue
        osm_key = str(osm_id)
        names_with_osm.add(str(row.get("name") or "").strip().lower())
        prev = best_by_osm.get(osm_key)
        if prev is None:
            best_by_osm[osm_key] = idx
            continue
        if _non_empty_count(row) > _non_empty_count(frame.loc[prev]):
            drop_indices.append(prev)
            best_by_osm[osm_key] = idx
        else:
            drop_indices.append(idx)

    keep_indices = [idx for idx in frame.index if idx not in drop_indices]

    for idx, row in frame.iterrows():
        if idx not in keep_indices:
            continue
        if not is_empty(row.get("osm_id")):
            continue
        name = str(row.get("name") or "").strip().lower()
        if name and name in names_with_osm:
            drop_indices.append(idx)

    if not drop_indices:
        return frame

    deduped = frame.drop(index=drop_indices).copy()
    print(f"Deduped {len(drop_indices):,} duplicate plant features")
    return deduped


def sync_uk_plants(
    ground_truth_path: Path,
    *,
    raw_source: Path | None = None,
    force_rebuild: bool = False,
) -> gpd.GeoDataFrame:
    """Update editable OSM plants ground truth without clobbering manual edits."""
    existing: gpd.GeoDataFrame | None = None
    if ground_truth_path.exists() and not force_rebuild:
        print(f"Loading ground truth {ground_truth_path.name}…")
        existing = gpd.read_file(ground_truth_path)
        if any(col in existing.columns for col in BMU_FIELDS):
            print("Migrating legacy bmu_* fields from plants GeoJSON into plant_bmu_links.csv…")
            map_frame = propose_plant_bmu_map(existing, migrate_embedded=True)
            save_plant_bmu_map(map_frame)
            export_plant_bmu_map_json(map_frame)

    if force_rebuild:
        if raw_source is None or not raw_source.exists():
            raise FileNotFoundError("--force requires a raw OSM plants export")
        frame = plants_from_raw(raw_source)
    elif raw_source is not None and raw_source.exists():
        incoming = plants_from_raw(raw_source)
        frame = merge_plants_ground_truth(existing, incoming)
    elif existing is not None:
        frame = trim_plant_columns(existing)
    else:
        if raw_source is None or not raw_source.exists():
            raise FileNotFoundError(
                f"No ground-truth file at {ground_truth_path} and no raw OSM export to seed from",
            )
        frame = plants_from_raw(raw_source)

    frame = dedupe_plants_ground_truth(frame)
    frame = merge_manual_plants(frame)

    ground_truth_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_crs("EPSG:4326").to_file(ground_truth_path, driver="GeoJSON")
    size_mb = ground_truth_path.stat().st_size / (1024 * 1024)
    print(f"Wrote ground truth {ground_truth_path}: {len(frame):,} features, {size_mb:.1f} MB")
    return frame
