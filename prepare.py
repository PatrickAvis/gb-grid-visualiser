"""OSM tag parsing (voltage, capacity, plant:source) and geometry preparation."""

from __future__ import annotations

import re
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.ops import unary_union

from common import tqdm
from fuel_taxonomy import bucket_fuel_properties, bucket_fuel_source, fuel_type_ids


def parse_voltage_to_kv(value: Any) -> float | None:
    """Parse OSM voltage tags into kV, using pragmatic cleanup for display styling."""
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, (list, tuple, set)):
        parsed = [parse_voltage_to_kv(item) for item in value]
        parsed = [item for item in parsed if item is not None]
        return max(parsed) if parsed else None

    text = str(value).lower().replace(" ", "")
    tokens = re.split(r"[;,/|]+", text)
    values: list[float] = []
    for token in tokens:
        if not token:
            continue
        multiplier = 1.0
        if token.endswith("kv"):
            multiplier = 1.0
            token = token[:-2]
        elif token.endswith("v"):
            multiplier = 0.001
            token = token[:-1]

        token = token.replace(",", ".")
        match = re.search(r"\d+(?:\.\d+)?", token)
        if not match:
            continue

        number = float(match.group(0))
        if multiplier == 1.0 and number > 1200:
            # OSM voltage is usually in volts, e.g. 380000; convert to kV.
            number = number / 1000.0
        else:
            number = number * multiplier
        values.append(number)

    return max(values) if values else None


def parse_capacity_to_mw(value: Any) -> float:
    """Parse OSM plant:output:electricity tags into MW, NaN when unparseable.

    Multiple values (lists or ``"500 MW;200 MW"``) are summed because a plant
    tagged with several unit outputs produces their total — unlike voltage,
    where the max is the line's rating.
    """
    if value is None:
        return float("nan")
    if isinstance(value, float) and np.isnan(value):
        return float("nan")
    if isinstance(value, (list, tuple, set)):
        parsed = [parse_capacity_to_mw(item) for item in value]
        parsed = [item for item in parsed if not np.isnan(item)]
        return float(sum(parsed)) if parsed else float("nan")

    # ";" is OSM's multi-value separator; "," is kept for European decimals
    # ("1,5 MW") and converted to "." per token below.
    text = str(value).lower().replace(" ", "")
    tokens = text.split(";")
    values: list[float] = []
    for token in tokens:
        if not token:
            continue
        multiplier = 1.0
        if token.endswith("gw"):
            multiplier = 1000.0
            token = token[:-2]
        elif token.endswith("mw"):
            token = token[:-2]
        elif token.endswith("kw"):
            multiplier = 0.001
            token = token[:-2]
        elif token.endswith("w"):
            multiplier = 1e-6
            token = token[:-1]

        token = token.replace(",", ".")
        match = re.fullmatch(r"\d+(?:\.\d+)?", token)
        if not match:
            # Unknown units (e.g. KV) are not power ratings. Never silently
            # extract their number and interpret it as MW.
            continue
        values.append(float(match.group(0)) * multiplier)

    return float(sum(values)) if values else float("nan")


# Plant:source values are bucketed via data/shared/fuel_types.json.
PLANT_SOURCE_BUCKETS: tuple[str, ...] = fuel_type_ids()


def bucket_plant_source(source: Any) -> str:
    """Map an OSM plant:source tag onto one of the fuel taxonomy buckets."""
    return bucket_fuel_source(source)


def bucket_plant_row(row: Any) -> str:
    """Map an OSM plant row onto one of the fuel taxonomy buckets.

    Falls back to generator:source when plant:source is absent (common on older
    or decommissioned stations, e.g. Sizewell A tags only generator:source).
    """
    return bucket_fuel_properties(
        row.get("plant:source") or row.get("generator:source"),
        row.get("name"),
        row.get("operator"),
    )


def prepare_lines(
    lines: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    output_crs: str,
    cable_sea_buffer_km: float = 0.0,
) -> gpd.GeoDataFrame:
    # These vectorized geometry ops (reprojection, clipping, exploding) are the
    # heaviest part of data prep before plotting and can take a while on dense
    # frames, so step a progress bar through each stage.
    with tqdm(total=5, desc="Preparing lines", unit="step", leave=True) as bar:
        bar.set_description("Reprojecting")
        boundary_projected = boundary.to_crs(output_crs)
        lines_projected = lines.to_crs(output_crs)
        bar.update()

        if "power" in lines_projected.columns and cable_sea_buffer_km > 0:
            is_cable = lines_projected["power"] == "cable"
        else:
            is_cable = pd.Series(False, index=lines_projected.index)

        def _safe_clip(frame: gpd.GeoDataFrame, mask_geom) -> gpd.GeoDataFrame:
            # Power grids lie overwhelmingly inside the boundary, so running a
            # geometric intersection on every line (as gpd.clip does) wastes
            # work on the ~95-99% that never cross it. Keep fully-contained
            # lines untouched and intersect only the crossing remainder —
            # roughly an order of magnitude faster on dense countries.
            try:
                geoms = frame.geometry.values
                shapely.prepare(mask_geom)
                crossing = ~shapely.contains_properly(mask_geom, geoms)
                if crossing.any():
                    new_geoms = geoms.copy()
                    new_geoms[crossing] = shapely.intersection(geoms[crossing], mask_geom)
                    frame = frame.copy()
                    frame["geometry"] = new_geoms
                return frame[~shapely.is_empty(frame.geometry.values)]
            except Exception:
                # Clipping may fail with invalid upstream geometries. The Overpass
                # polygon query already constrained the result set, so return unclipped.
                return frame

        bar.set_description("Clipping")
        parts: list[gpd.GeoDataFrame] = []
        land_lines = lines_projected[~is_cable]
        if not land_lines.empty:
            land_mask = unary_union(boundary_projected.geometry)
            parts.append(_safe_clip(land_lines, land_mask))
        cable_lines = lines_projected[is_cable]
        if not cable_lines.empty:
            cable_mask = unary_union(
                boundary_projected.geometry.buffer(cable_sea_buffer_km * 1000)
            )
            parts.append(_safe_clip(cable_lines, cable_mask))
        bar.update()

        clipped = gpd.GeoDataFrame(
            pd.concat(parts, ignore_index=True) if parts else lines_projected.iloc[0:0],
            geometry="geometry",
            crs=output_crs,
        )

        bar.set_description("Exploding")
        clipped = clipped.explode(ignore_index=True)
        clipped = clipped[clipped.geometry.type.isin(["LineString", "MultiLineString"])]
        clipped = clipped[~clipped.geometry.is_empty]
        if clipped.empty:
            raise RuntimeError("Power-line geometries became empty after projection/clipping")
        bar.update()

        bar.set_description("Parsing voltages")
        clipped["voltage_kv"] = clipped.get("voltage", None).apply(parse_voltage_to_kv)
        clipped["sort_voltage"] = clipped["voltage_kv"].fillna(0)
        bar.update()

        bar.set_description("Sorting")
        result = clipped.sort_values("sort_voltage")
        bar.update()

    return result


def parse_numeric_tag(value: Any) -> float | None:
    """Parse a simple OSM numeric tag such as height or rotor diameter."""
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    text = str(value).lower().strip()
    multiplier = 1.0
    if text.endswith("m"):
        text = text[:-1].strip()
    text = text.replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group()) * multiplier


def prepare_wind_turbines(turbines: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add parsed numeric columns while preserving all downloaded OSM tags."""
    if turbines.empty:
        return turbines

    out = turbines.copy()
    capacity_raw = out.get("generator:output:electricity")
    if capacity_raw is not None:
        out["capacity_mw"] = capacity_raw.apply(parse_capacity_to_mw)

    height_raw = out.get("height")
    if height_raw is not None:
        out["height_m"] = height_raw.apply(parse_numeric_tag)

    rotor_raw = out.get("rotor:diameter")
    if rotor_raw is not None:
        out["rotor_diameter_m"] = rotor_raw.apply(parse_numeric_tag)

    return out
