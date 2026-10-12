#!/usr/bin/env python3
"""Download NESO boundary datasets into data/regions/uk/zones/ and normalize to WGS84 GeoJSON."""

from __future__ import annotations

import argparse
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import geopandas as gpd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from common import zones_dir

UK_ZONES_DIR = zones_dir("uk")

SourceFormat = Literal["geojson", "zip", "gpkg"]

DNO_URL = (
    "https://api.neso.energy/dataset/0e377f16-95e9-4c15-a1fc-49e06a39cfa0/"
    "resource/1c6a7dc0-1b6c-443a-bc67-5f7125649434/download/"
    "gb-dno-license-areas-20240503-as-geojson.geojson"
)
GSP_URL = (
    "https://api.neso.energy/dataset/2810092e-d4b2-472f-b955-d8bea01f9ec0/"
    "resource/5dfab3dd-f192-40ab-b97f-b365a594293c/download/"
    "gsp_regions_20260209.zip"
)
GENERATION_CHARGING_ZONES_URL = (
    "https://api.neso.energy/dataset/f72029e7-3056-4021-9493-01c58a667d7a/"
    "resource/539a04ea-8bf3-4366-a277-49812c651cfb/download/"
    "tnuosgenzones_geojs.geojson"
)
ETYS_BOUNDARIES_URL = (
    "https://api.neso.energy/dataset/997f4820-1ad4-499b-b1fe-4b8d3d7fbc72/"
    "resource/e914fcec-1dc9-4f1f-97e7-59c0d9521bea/download/"
    "etys-boundary-gis-data-mar25.zip"
)


@dataclass(frozen=True)
class NesoDataset:
    key: str
    label: str
    url: str
    output_name: str
    normalize: Callable[[gpd.GeoDataFrame], gpd.GeoDataFrame]
    source_format: SourceFormat = "geojson"
    zip_member_suffixes: tuple[str, ...] = (".geojson", ".shp", ".gpkg")


def download_bytes(url: str, dest: Path) -> None:
    print(f"Downloading {url}…")
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(response.content)
    print(f"Saved raw download: {dest}")


def _first_column(frame: gpd.GeoDataFrame, candidates: tuple[str, ...]) -> str | None:
    lowered = {col.lower(): col for col in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def normalize_dno(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = frame.copy()
    if out.crs is None:
        out = out.set_crs("EPSG:27700")
    out = out.to_crs("EPSG:4326")
    area_col = next((col for col in out.columns if col.lower() == "area"), None)
    dno_full_col = next((col for col in out.columns if col.lower() == "dno_full"), None)
    dno_col = next((col for col in out.columns if col.lower() == "dno"), None)
    id_col = next((col for col in out.columns if col.lower() == "id"), None)
    if area_col and dno_full_col:
        out["name"] = out[dno_full_col].astype(str) + " — " + out[area_col].astype(str)
    elif area_col:
        out["name"] = out[area_col].astype(str)
    elif dno_full_col:
        out["name"] = out[dno_full_col].astype(str)
    else:
        out["name"] = out.index.astype(str)
    if dno_col:
        out["operator"] = out[dno_col]
    if id_col:
        out["zone_id"] = out[id_col]
    keep = [col for col in ["name", "operator", "zone_id"] if col in out.columns]
    return out[keep + ["geometry"]]


def normalize_generation_zones(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = frame.copy()
    if out.crs is None:
        out = out.set_crs("EPSG:27700")
    out = out.to_crs("EPSG:4326")

    zone_id_col = _first_column(out, ("zone_id", "zoneid", "genzone", "gen_zone", "tariff_zone", "zone", "id"))
    layer_col = _first_column(out, ("layer", "gen_zone", "genzone"))
    zone_name_col = _first_column(out, ("zone_name", "zonename", "name", "label", "description"))
    tariff_col = _first_column(out, ("tariff_zone", "tariff", "tnuos_zone"))

    if zone_id_col:
        out["zone_id"] = out[zone_id_col]
    if layer_col:
        out["zone_name"] = out[layer_col].astype(str)
    elif zone_name_col:
        out["zone_name"] = out[zone_name_col]
    elif zone_id_col:
        out["zone_name"] = out[zone_id_col].astype(str)
    else:
        out["zone_name"] = out.index.astype(str)

    out["name"] = out["zone_name"]
    if tariff_col:
        out["tariff_zone"] = out[tariff_col]
    elif layer_col:
        out["tariff_zone"] = out[layer_col]
    elif zone_id_col:
        out["tariff_zone"] = out[zone_id_col]

    keep = [col for col in ("zone_id", "zone_name", "name", "tariff_zone") if col in out.columns]
    return out[keep + ["geometry"]]


def normalize_etys_boundaries(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = frame.copy()
    if out.crs is None:
        out = out.set_crs("EPSG:27700")
    out = out.to_crs("EPSG:4326")

    name_col = _first_column(out, ("boundary_n", "boundary_name", "boundary", "name"))
    id_col = _first_column(out, ("id", "boundary_id"))

    if name_col:
        out["name"] = out[name_col].astype(str)
        out["boundary_id"] = out[name_col].astype(str)
    else:
        out["name"] = out.index.astype(str)
        out["boundary_id"] = out["name"]
    if id_col:
        out["id"] = out[id_col].astype(str)

    out = out[out.geometry.type.isin(["LineString", "MultiLineString"])]
    keep = [col for col in ("name", "boundary_id", "id") if col in out.columns]
    return out[keep + ["geometry"]]


def normalize_gsp(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = frame.copy()
    if out.crs is None:
        out = out.set_crs("EPSG:27700")
    out = out.to_crs("EPSG:4326")
    gsp_id_col = next((col for col in out.columns if col.lower() in {"gsps", "gsp", "gsp_id", "gspid"}), None)
    group_col = next((col for col in out.columns if col.lower() in {"gspgroup", "gsp_group", "gsp_name", "name"}), None)
    if gsp_id_col:
        out["gsp_id"] = out[gsp_id_col]
    if group_col:
        out["gsp_name"] = out[group_col]
    elif gsp_id_col:
        out["gsp_name"] = out[gsp_id_col]
    else:
        out["gsp_name"] = out.index.astype(str)
    keep = [col for col in ["gsp_id", "gsp_name", "name"] if col in out.columns]
    return out[keep + ["geometry"]]


NESO_DATASETS: dict[str, NesoDataset] = {
    "dno": NesoDataset(
        key="dno",
        label="DNO licence areas",
        url=DNO_URL,
        output_name="dno_areas.geojson",
        normalize=normalize_dno,
    ),
    "gsp": NesoDataset(
        key="gsp",
        label="GSP regions",
        url=GSP_URL,
        output_name="gsp_areas.geojson",
        normalize=normalize_gsp,
        source_format="zip",
    ),
    "generation": NesoDataset(
        key="generation",
        label="TNUoS generation charging zones",
        url=GENERATION_CHARGING_ZONES_URL,
        output_name="generation_charging_zones.geojson",
        normalize=normalize_generation_zones,
    ),
    "etys": NesoDataset(
        key="etys",
        label="ETYS transmission boundaries",
        url=ETYS_BOUNDARIES_URL,
        output_name="etys_boundaries.geojson",
        normalize=normalize_etys_boundaries,
        source_format="zip",
    ),
}


def raw_path_for(dataset: NesoDataset, zones_dir: Path) -> Path:
    if dataset.source_format == "geojson":
        return zones_dir / dataset.output_name.replace(".geojson", ".raw.geojson")
    if dataset.source_format == "zip":
        return zones_dir / dataset.output_name.replace(".geojson", ".raw.zip")
    return zones_dir / dataset.output_name.replace(".geojson", ".raw.gpkg")


def read_zip_member(zip_path: Path, suffixes: tuple[str, ...]) -> gpd.GeoDataFrame:
    with zipfile.ZipFile(zip_path) as archive:
        members = [
            name for name in archive.namelist()
            if not name.endswith("/") and Path(name).suffix.lower() in suffixes
        ]
        if not members:
            raise ValueError(f"No supported spatial file found in {zip_path}")
        member = sorted(members, key=lambda name: (Path(name).suffix.lower() != ".geojson", name))[0]
    return gpd.read_file(f"zip://{zip_path}!{member}")


def load_dataset_source(dataset: NesoDataset, raw_path: Path, url: str) -> gpd.GeoDataFrame:
    download_bytes(url, raw_path)
    if dataset.source_format == "geojson":
        return gpd.read_file(raw_path)
    if dataset.source_format == "zip":
        return read_zip_member(raw_path, dataset.zip_member_suffixes)
    return gpd.read_file(raw_path)


def fetch_dataset(
    dataset: NesoDataset,
    *,
    zones_dir: Path,
    output: Path | None = None,
    url: str | None = None,
) -> Path:
    output_path = output or (zones_dir / dataset.output_name)
    raw_path = raw_path_for(dataset, zones_dir)
    frame = load_dataset_source(dataset, raw_path, url or dataset.url)
    normalized = dataset.normalize(frame)
    normalized.to_file(output_path, driver="GeoJSON")
    print(f"Wrote {output_path} ({len(normalized)} features)")
    return output_path


def dataset_keys() -> list[str]:
    return list(NESO_DATASETS)


def resolve_selected_datasets(args: argparse.Namespace) -> list[str]:
    if args.list:
        for key, dataset in NESO_DATASETS.items():
            print(f"{key}: {dataset.label} -> data/regions/uk/zones/{dataset.output_name}")
        return []

    selected = set(NESO_DATASETS)
    if args.only:
        unknown = sorted(set(args.only) - set(NESO_DATASETS))
        if unknown:
            raise SystemExit(f"Unknown dataset(s): {', '.join(unknown)}. Choose from: {', '.join(dataset_keys())}")
        selected = set(args.only)

    skip_map = {
        "dno": args.skip_dno,
        "gsp": args.skip_gsp,
        "generation": args.skip_generation,
        "etys": args.skip_etys,
    }
    for key, skip in skip_map.items():
        if skip:
            selected.discard(key)

    return [key for key in NESO_DATASETS if key in selected]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch NESO boundary datasets into data/regions/uk/zones/ as normalized WGS84 GeoJSON.",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=dataset_keys(),
        metavar="DATASET",
        help="Fetch only these datasets (default: all registered datasets)",
    )
    parser.add_argument("--list", action="store_true", help="List registered datasets and exit")
    parser.add_argument("--zones-dir", type=Path, default=UK_ZONES_DIR)
    parser.add_argument("--dno-output", type=Path, default=None)
    parser.add_argument("--gsp-output", type=Path, default=None)
    parser.add_argument("--generation-output", type=Path, default=None)
    parser.add_argument("--etys-output", type=Path, default=None)
    parser.add_argument("--skip-dno", action="store_true")
    parser.add_argument("--skip-gsp", action="store_true")
    parser.add_argument("--skip-generation", action="store_true")
    parser.add_argument("--skip-etys", action="store_true")
    parser.add_argument("--dno-url", default=None)
    parser.add_argument("--gsp-url", default=None)
    parser.add_argument("--generation-url", default=None)
    parser.add_argument("--etys-url", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected = resolve_selected_datasets(args)
    if not selected:
        return 0

    output_overrides = {
        "dno": args.dno_output,
        "gsp": args.gsp_output,
        "generation": args.generation_output,
        "etys": args.etys_output,
    }
    url_overrides = {
        "dno": args.dno_url,
        "gsp": args.gsp_url,
        "generation": args.generation_url,
        "etys": args.etys_url,
    }

    for key in selected:
        fetch_dataset(
            NESO_DATASETS[key],
            zones_dir=args.zones_dir,
            output=output_overrides.get(key),
            url=url_overrides.get(key),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
