"""Fetch and prepare live-ish Balancing Mechanism activity snapshots."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import geopandas as gpd
import pandas as pd
import requests

from bmu_data import (
    BMU_REFERENCE_PATH,
    PLANT_BMU_MAP_PATH,
    UK_REFERENCE_OPERATIONAL_DIR,
    is_empty,
    load_bmunits,
    load_plant_bmu_map,
    mapped_bmu_ids,
)
from common import FILE_ENCODING
from region_catalog import catalog_layer_path, map_path

ELEXON_API_BASE = "https://data.elexon.co.uk/bmrs/api/v1"
BM_ACTIVITY_LATEST_PATH = UK_REFERENCE_OPERATIONAL_DIR / "bmu_activity_latest.json"
BM_UNMAPPED_ISPSTACK_PATH = UK_REFERENCE_OPERATIONAL_DIR / "bmu_unmapped_ispstack.csv"

SIDES = ("bid", "offer")
SETTLEMENT_ZONE = ZoneInfo("Europe/London")
SLOT_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

UNMAPPED_ISPSTACK_COLUMNS = (
    "bmu_id",
    "ngc_bmu_id",
    "bmUnitName",
    "fuelType",
    "bmUnitType",
    "leadPartyName",
    "generationCapacity",
    "side",
    "volume_mwh",
    "abs_volume_mwh",
    "action_count",
    "settlement_date",
    "settlement_period",
    "price_gbp_mwh",
    "bid_offer_pair_id",
    "first_seen_at",
    "last_seen_at",
    "active_latest",
)


def _data_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        rows = payload.get("data")
    else:
        rows = payload
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError("Unexpected Elexon response shape: expected a list of rows")
    return [row for row in rows if isinstance(row, dict)]


def fetch_system_prices(settlement_date: str, *, timeout: int = 60) -> list[dict[str, Any]]:
    url = f"{ELEXON_API_BASE}/balancing/settlement/system-prices/{settlement_date}"
    response = requests.get(url, params={"format": "json"}, timeout=timeout)
    response.raise_for_status()
    return _data_rows(response.json())


def settlement_slot(settlement_date: str, settlement_period: int) -> int:
    """UTC half-hour index, respecting the UK's 46/48/50-period days."""
    day = date.fromisoformat(settlement_date)
    start = datetime.combine(day, datetime.min.time(), SETTLEMENT_ZONE).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), SETTLEMENT_ZONE).astimezone(UTC)
    count = int((end - start).total_seconds() // 1800)
    if not isinstance(settlement_period, int) or not 1 <= settlement_period <= count:
        raise ValueError(f"{settlement_date} has settlement periods 1–{count}")
    return int((start - SLOT_EPOCH).total_seconds() // 1800) + settlement_period - 1


def slot_to_settlement(slot: int) -> tuple[str, int]:
    instant = SLOT_EPOCH + timedelta(minutes=slot * 30)
    day = instant.astimezone(SETTLEMENT_ZONE).date().isoformat()
    return day, slot - settlement_slot(day, 1) + 1


def periods_last_n_hours(
    hours: float = 24,
    *,
    lookback_days: int = 7,
    timeout: int = 60,
) -> list[tuple[str, int]]:
    """Settlement (date, period) pairs covering the last N hours up to latest published."""
    if not math.isfinite(hours) or hours <= 0:
        raise ValueError("hours must be a positive finite number")
    end_date, end_period = latest_available_period(
        lookback_days=lookback_days,
        timeout=timeout,
    )
    end_slot = settlement_slot(end_date, end_period)
    period_count = max(1, int(round(hours * 2)))
    start_slot = end_slot - period_count + 1
    return [slot_to_settlement(slot) for slot in range(start_slot, end_slot + 1)]


def latest_available_period(*, lookback_days: int = 7, timeout: int = 60) -> tuple[str, int]:
    """Find the latest settlement date/period with published system prices."""
    today = datetime.now(SETTLEMENT_ZONE).date()
    for offset in range(lookback_days):
        settlement_date = (today - timedelta(days=offset)).isoformat()
        rows = fetch_system_prices(settlement_date, timeout=timeout)
        periods = [
            int(row["settlementPeriod"])
            for row in rows
            if row.get("settlementPeriod") is not None
        ]
        if periods:
            return settlement_date, max(periods)
    raise RuntimeError(f"No published system prices found in the last {lookback_days} days")


def fetch_ispstack(
    *,
    bid_offer: str,
    settlement_date: str,
    settlement_period: int,
    timeout: int = 60,
) -> list[dict[str, Any]]:
    """Fetch ISPSTACK rows for one side. Elexon accepts bid or offer here."""
    settlement_slot(settlement_date, settlement_period)
    side = bid_offer.lower()
    if side not in SIDES:
        raise ValueError(f"bid_offer must be one of {SIDES}, got {bid_offer!r}")
    url = (
        f"{ELEXON_API_BASE}/balancing/settlement/stack/all/"
        f"{side}/{settlement_date}/{settlement_period}"
    )
    response = requests.get(url, params={"format": "json"}, timeout=timeout)
    response.raise_for_status()
    rows = _data_rows(response.json())
    for row in rows:
        row["bidOffer"] = side
    return rows


def fetch_ispstack_sides(
    *,
    bid_offer: str,
    settlement_date: str,
    settlement_period: int,
    timeout: int = 60,
) -> list[dict[str, Any]]:
    sides = SIDES if bid_offer == "all" else (bid_offer,)
    rows: list[dict[str, Any]] = []
    for side in sides:
        rows.extend(fetch_ispstack(
            bid_offer=side,
            settlement_date=settlement_date,
            settlement_period=settlement_period,
            timeout=timeout,
        ))
    return rows


def fetch_ispstack_window(
    hours: float = 24,
    *,
    bid_offer: str = "all",
    lookback_days: int = 7,
    timeout: int = 60,
    on_period: Callable[[str, int, int, int], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch ISPSTACK rows across the last N hours of settlement periods."""
    periods = periods_last_n_hours(
        hours,
        lookback_days=lookback_days,
        timeout=timeout,
    )
    rows: list[dict[str, Any]] = []
    for index, (settlement_date, settlement_period) in enumerate(periods, start=1):
        if on_period is not None:
            on_period(settlement_date, settlement_period, index, len(periods))
        rows.extend(
            fetch_ispstack_sides(
                bid_offer=bid_offer,
                settlement_date=settlement_date,
                settlement_period=settlement_period,
                timeout=timeout,
            )
        )
    start_date, start_period = periods[0]
    end_date, end_period = periods[-1]
    window = {
        "hours": hours,
        "period_count": len(periods),
        "settlement_date_start": start_date,
        "settlement_period_start": start_period,
        "settlement_date_end": end_date,
        "settlement_period_end": end_period,
    }
    return rows, window


def default_plants_path() -> Path:
    catalog_path = catalog_layer_path("uk", "plants")
    if catalog_path is not None:
        return catalog_path
    return map_path("uk", "plants")


def _key(value: Any) -> str:
    return "" if is_empty(value) else str(value).strip().upper()


def _index_bmu_reference(bmunits: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in bmunits:
        for field in ("elexonBmUnit", "nationalGridBmUnit"):
            key = _key(row.get(field))
            if key:
                by_id[key] = row
    return by_id


def _enrich_unmapped_row(row: dict[str, Any], reference_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    bmu = reference_by_id.get(_key(row.get("bmu_id")))
    if not bmu:
        return row
    enriched = dict(row)
    enriched["ngc_bmu_id"] = _string_or_none(bmu.get("nationalGridBmUnit"))
    enriched["bmUnitName"] = _string_or_none(bmu.get("bmUnitName"))
    enriched["fuelType"] = _string_or_none(bmu.get("fuelType"))
    enriched["bmUnitType"] = _string_or_none(bmu.get("bmUnitType"))
    enriched["leadPartyName"] = _string_or_none(bmu.get("leadPartyName"))
    enriched["generationCapacity"] = _string_or_none(bmu.get("generationCapacity"))
    return enriched


def _index_plant_bmu_links(map_frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    by_bmu: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for _, row in map_frame.iterrows():
        link = row.to_dict()
        for column in ("bmu_id", "ngc_bmu_id"):
            key = _key(row.get(column))
            if key:
                by_bmu[key].append(link)
    return dict(by_bmu)


def _normalize_osm_id(value: Any) -> str | None:
    """Join key for osm_ids: the link table uses canonical "way/123" but the
    site GeoJSON often stores bare "123" (export sources without an element
    type), so match on the numeric part. "manual/..." ids are kept as-is.
    """
    text = _string_or_none(value)
    if text is None:
        return None
    return re.sub(r"^(way|relation|node)/", "", text)


def _site_feature_lookup(plants: gpd.GeoDataFrame) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for _, row in plants.iterrows():
        osm_id = None if is_empty(row.get("osm_id")) else str(row["osm_id"]).strip()
        if not osm_id:
            continue
        key = _normalize_osm_id(osm_id)
        lon = row.get("longitude")
        lat = row.get("latitude")
        if is_empty(lat) or is_empty(lon):
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            point = geom.representative_point()
            lon = point.x
            lat = point.y
        lookup[key] = {
            "osm_id": osm_id,
            "plant_name": None if is_empty(row.get("name")) else str(row["name"]).strip(),
            "operator": None if is_empty(row.get("operator")) else str(row["operator"]).strip(),
            "source_bucket": None if is_empty(row.get("source_bucket")) else str(row["source_bucket"]).strip(),
            "latitude": float(lat),
            "longitude": float(lon),
        }
    return lookup


def _number(value: Any) -> float | None:
    if is_empty(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    return None if is_empty(value) else str(value).strip()


def _weighted_average(items: list[tuple[float, float]]) -> float | None:
    total_weight = sum(weight for _, weight in items)
    if total_weight <= 0:
        return None
    return sum(value * weight for value, weight in items) / total_weight


def _record_so_flag(entry: dict[str, Any], row: dict[str, Any], volume: float) -> None:
    flag = row.get("soFlag")
    status = "flagged" if flag is True else "unflagged" if flag is False else "unknown"
    counts = entry.setdefault("so_counts", {key: 0 for key in ("flagged", "unflagged", "unknown")})
    volumes = entry.setdefault("so_volumes", {key: 0.0 for key in counts})
    counts[status] += 1
    volumes[status] += abs(volume)


def _aggregate_mapped_actions(
    rows: list[dict[str, Any]],
    *,
    links_by_bmu: dict[str, list[dict[str, Any]]],
    sites_by_osm: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mapped: dict[tuple[str, str, str, Any, Any], dict[str, Any]] = {}
    unmapped: dict[tuple[str, str], dict[str, Any]] = {}

    for row in rows:
        bmu_id = _string_or_none(row.get("id"))
        if not bmu_id:
            continue
        side = str(row.get("bidOffer") or "").lower()
        volume = _number(row.get("volume")) or 0.0
        abs_volume = abs(volume)
        price = _number(row.get("finalPrice"))
        if price is None:
            price = _number(row.get("originalPrice"))
        links = links_by_bmu.get(_key(bmu_id), [])

        if not links:
            key = (_key(bmu_id), side)
            entry = unmapped.setdefault(key, {
                "bmu_id": bmu_id,
                "side": side,
                "volume_mwh": 0.0,
                "abs_volume_mwh": 0.0,
                "price_items": [],
                "bid_offer_pair_ids": set(),
                "action_count": 0,
                "settlement_date": row.get("settlementDate"),
                "settlement_period": row.get("settlementPeriod"),
            })
            entry["volume_mwh"] += volume
            entry["abs_volume_mwh"] += abs_volume
            if price is not None:
                entry["price_items"].append((price, abs_volume or 1.0))
            if row.get("bidOfferPairId") is not None:
                entry["bid_offer_pair_ids"].add(str(row["bidOfferPairId"]))
            entry["action_count"] += 1
            _record_so_flag(entry, row, volume)
            continue

        for link in links:
            osm_id = _normalize_osm_id(link.get("osm_id"))
            if not osm_id or osm_id not in sites_by_osm:
                continue
            key = (
                osm_id,
                _key(bmu_id),
                side,
                row.get("settlementDate"),
                row.get("settlementPeriod"),
            )
            site = sites_by_osm[osm_id]
            entry = mapped.setdefault(key, {
                **site,
                "bmu_id": bmu_id,
                "ngc_bmu_id": _string_or_none(link.get("ngc_bmu_id")),
                "side": side,
                "volume_mwh": 0.0,
                "abs_volume_mwh": 0.0,
                "price_items": [],
                "bid_offer_pair_ids": set(),
                "action_count": 0,
                "settlement_date": row.get("settlementDate"),
                "settlement_period": row.get("settlementPeriod"),
                "start_time": row.get("startTime"),
                "created_datetime": row.get("createdDateTime"),
            })
            entry["volume_mwh"] += volume
            entry["abs_volume_mwh"] += abs_volume
            if price is not None:
                entry["price_items"].append((price, abs_volume or 1.0))
            if row.get("bidOfferPairId") is not None:
                entry["bid_offer_pair_ids"].add(str(row["bidOfferPairId"]))
            entry["action_count"] += 1
            _record_so_flag(entry, row, volume)

    return list(mapped.values()), list(unmapped.values())


def _finalize_action(entry: dict[str, Any]) -> dict[str, Any]:
    price = _weighted_average(entry.pop("price_items", []))
    pair_ids = sorted(entry.pop("bid_offer_pair_ids", set()))
    finalized = dict(entry)
    counts = finalized.pop("so_counts", {"unknown": finalized.get("action_count", 0)})
    volumes = finalized.pop("so_volumes", {"unknown": finalized.get("abs_volume_mwh", 0)})
    present = [key for key, count in counts.items() if count]
    finalized["so_flag_status"] = present[0] if len(present) == 1 else "mixed" if present else "unknown"
    for key in ("flagged", "unflagged", "unknown"):
        finalized[f"so_{key}_actions"] = counts.get(key, 0)
        finalized[f"so_{key}_abs_mwh"] = round(volumes.get(key, 0.0), 3)
    finalized["volume_mwh"] = round(float(finalized["volume_mwh"]), 3)
    finalized["abs_volume_mwh"] = round(float(finalized["abs_volume_mwh"]), 3)
    finalized["price_gbp_mwh"] = None if price is None else round(price, 2)
    finalized["bid_offer_pair_id"] = "; ".join(pair_ids) if pair_ids else None
    return finalized


def _unmapped_row_key(row: dict[str, Any]) -> tuple[str, str]:
    return (_key(row.get("bmu_id")), str(row.get("side") or "").lower())


def _load_unmapped_ispstack_history(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    history: dict[tuple[str, str], dict[str, Any]] = {}
    for _, row in frame.iterrows():
        entry = {col: (None if is_empty(row.get(col)) else row[col]) for col in frame.columns}
        key = _unmapped_row_key(entry)
        if key[0]:
            history[key] = entry
    return history


def merge_unmapped_ispstack_history(
    snapshot_rows: list[dict[str, Any]],
    *,
    unmapped_path: Path,
    fetched_at: str,
    mapped_ids: set[str],
    reset: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Grow a cumulative unmapped review queue; drop rows once a BMU is mapped."""
    history = {} if reset else _load_unmapped_ispstack_history(unmapped_path)
    snapshot_keys = {_unmapped_row_key(row) for row in snapshot_rows if _unmapped_row_key(row)[0]}

    for key in list(history):
        if key[0] in mapped_ids:
            del history[key]

    added = 0
    updated = 0
    for row in snapshot_rows:
        key = _unmapped_row_key(row)
        if not key[0] or key[0] in mapped_ids:
            continue
        if key in history:
            previous = history[key]
            merged = dict(previous)
            merged.update(row)
            merged["first_seen_at"] = previous.get("first_seen_at") or fetched_at
            merged["last_seen_at"] = fetched_at
            merged["active_latest"] = True
            history[key] = merged
            updated += 1
        else:
            entry = dict(row)
            entry["first_seen_at"] = fetched_at
            entry["last_seen_at"] = fetched_at
            entry["active_latest"] = True
            history[key] = entry
            added += 1

    for key, row in history.items():
        if key not in snapshot_keys:
            row["active_latest"] = False

    merged_rows = sorted(
        history.values(),
        key=lambda row: (
            str(row.get("bmu_id") or "").upper(),
            str(row.get("side") or "").lower(),
        ),
    )
    counts = {
        "snapshot_unmapped": len(snapshot_rows),
        "queue_total": len(merged_rows),
        "queue_added": added,
        "queue_updated": updated,
        "queue_active_latest": sum(1 for row in merged_rows if row.get("active_latest")),
    }
    return merged_rows, counts


def build_activity_feature_collection(
    actions: list[dict[str, Any]],
    *,
    settlement_date: str,
    settlement_period: int,
    fetched_at: str,
    settlement_window: dict[str, Any] | None = None,
) -> dict[str, Any]:
    features = []
    for action in actions:
        props = _finalize_action(action)
        lon = props.pop("longitude")
        lat = props.pop("latitude")
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })
    metadata: dict[str, Any] = {
        "settlement_date": settlement_date,
        "settlement_period": settlement_period,
        "fetched_at": fetched_at,
        "feature_count": len(features),
    }
    if settlement_window:
        metadata.update(settlement_window)
    return {
        "type": "FeatureCollection",
        "metadata": metadata,
        "features": features,
    }


def write_activity_outputs(
    rows: list[dict[str, Any]],
    *,
    settlement_date: str,
    settlement_period: int,
    settlement_window: dict[str, Any] | None = None,
    plants_path: Path | None = None,
    map_path: Path = PLANT_BMU_MAP_PATH,
    activity_path: Path = BM_ACTIVITY_LATEST_PATH,
    unmapped_path: Path = BM_UNMAPPED_ISPSTACK_PATH,
    reset_unmapped_ispstack: bool = False,
) -> tuple[Path, Path, dict[str, int]]:
    plants_path = plants_path or default_plants_path()
    plants = gpd.read_file(plants_path)
    map_frame = load_plant_bmu_map(map_path)
    links_by_bmu = _index_plant_bmu_links(map_frame)
    sites_by_osm = _site_feature_lookup(plants)
    mapped, unmapped = _aggregate_mapped_actions(
        rows,
        links_by_bmu=links_by_bmu,
        sites_by_osm=sites_by_osm,
    )
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    collection = build_activity_feature_collection(
        mapped,
        settlement_date=settlement_date,
        settlement_period=settlement_period,
        fetched_at=fetched_at,
        settlement_window=settlement_window,
    )

    activity_path.parent.mkdir(parents=True, exist_ok=True)
    with activity_path.open("w", encoding=FILE_ENCODING) as handle:
        json.dump(collection, handle, indent=2)

    reference_by_id: dict[str, dict[str, Any]] = {}
    if BMU_REFERENCE_PATH.exists():
        reference_by_id = _index_bmu_reference(load_bmunits(BMU_REFERENCE_PATH))

    snapshot_rows = [_finalize_action(row) for row in unmapped]
    if reference_by_id:
        snapshot_rows = [_enrich_unmapped_row(row, reference_by_id) for row in snapshot_rows]

    unmapped_rows, queue_counts = merge_unmapped_ispstack_history(
        snapshot_rows,
        unmapped_path=unmapped_path,
        fetched_at=fetched_at,
        mapped_ids=mapped_bmu_ids(map_frame),
        reset=reset_unmapped_ispstack,
    )
    pd.DataFrame(unmapped_rows).to_csv(
        unmapped_path,
        index=False,
        columns=list(UNMAPPED_ISPSTACK_COLUMNS),
    )

    counts = {
        "input_rows": len(rows),
        "mapped_actions": len(mapped),
        "unmapped_actions": queue_counts["queue_total"],
        **queue_counts,
    }
    return activity_path, unmapped_path, counts
