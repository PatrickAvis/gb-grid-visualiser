# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An interactive Leaflet map of electricity infrastructure (transmission lines, generation, substations, wind turbines, zone boundaries), built from OpenStreetMap exports plus UK-specific Elexon BMU and NESO zone data. A static frontend under `map/` reads prepared GeoJSON/PMTiles; Python under the repo root (logic modules) and `scripts/` (thin CLIs) produces that data.

## Setup & common commands

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

```powershell
python scripts/refresh_uk.py          # one-shot: refresh the whole UK dataset end to end
python scripts/serve_map.py           # serve map at http://localhost:8000/map/ (supports HTTP range -> PMTiles)
```

`refresh_uk.py` runs the pipeline in order: BMU standing data → NESO zones → OSM export (if a `.osm.pbf`) → **plant polygons via Overpass** → **offshore wind turbines** → web layers → **derived wind-farm boundaries** → plant↔BMU match → PMTiles. Skip stages via `--skip-osm/-elexon/-zones/-plant-fetch/-offshore-turbines/-prepare/-boundaries/-bmu-match/-tiles`; `--rebuild-plants` does a clean (non-additive) plant-layer rebuild. Run stages individually:

```powershell
python scripts/export_region.py --region uk --all [--osm-pbf data/regions/uk/source/great-britain-latest.osm.pbf]
python scripts/fetch_plants_overpass.py        # authoritative plant source (see GDAL note below)
python scripts/fetch_offshore_turbines.py      # tops up offshore turbines the export clips out
python scripts/fetch_neso_zones.py
python scripts/prepare_map_data.py --region uk [--skip-plants|--skip-lines|--skip-substations|--skip-turbines|--skip-zones]
python scripts/derive_plant_boundaries.py      # hull boundaries for farms OSM maps only as points
python scripts/propose_plant_bmu_map.py [--fetch]
python scripts/audit_bmu_links.py              # data-quality report on the plant↔BMU links
python scripts/build_tiles.py --region uk      # needs Tippecanoe + PMTiles CLI on PATH (WSL)
```

There is no test suite, linter, or build config in this repo. Use `serve_map.py` (not `python -m http.server`) so PMTiles range requests work.

### Critical: GDAL drops plant relations — plants come from Overpass, not the PBF

The `.osm.pbf`/GDAL export silently drops most `power=plant` **multipolygon/site relations**, so ~600 plants (most large wind farms, all offshore) are missing from `export_region.py`'s `plants.geojson`. **`fetch_plants_overpass.py` is the authoritative plant source** — it queries Overpass directly, assembles ways/relations into polygons itself, hulls `type=site` turbine groupings, pulls offshore (clipped to UK waters, foreign sectors excluded), and tags each plant with a `status` (operational / construction / closed). It overwrites `raw/plants.geojson` after the PBF export. The same relation-drop likely affects **lines** (route relations); substations have few relations.

### Environment notes (important)

- Primary shell is **PowerShell on Windows**; most docs give PowerShell command lines. A Git Bash tool is also available.
- **Tippecanoe / PMTiles** (`build_tiles.py`) usually aren't on Windows PATH — run via WSL/Linux. There is a separate `.venv-wsl/` for this.
- The local `.osm.pbf` fast path is strongly preferred over Overpass for the UK (Overpass tiling is slow and times out). Place extracts in `data/regions/{id}/source/` (gitignored); they read via GDAL's OSM driver through `pyogrio`.

## Architecture

### Two layers: logic modules vs. script CLIs

Top-level `*.py` files are the importable logic; `scripts/*.py` are thin argparse entry points that `sys.path.insert` the repo root and call into them. When changing behaviour, edit the module; the script usually just wires CLI flags.

| Module | Responsibility |
|--------|----------------|
| `common.py` | Repo paths, per-region dir helpers (`raw_dir`, `map_dir`, `zones_dir`, `reference_dir`, `source_dir`), pickle cache (`cache_get/set`) |
| `region_catalog.py` | Resolves paths from `data/catalog.json` + `boundaries/`; the single source of truth for layer file locations |
| `osm_data.py` | Boundary resolution + Overpass/`.osm.pbf` download of OSM power features |
| `prepare.py` | OSM tag parsing (voltage, capacity, `plant:source`) and geometry prep |
| `plants_sync.py` | Merges OSM plant exports into the ground-truth `bmu_sites_web.geojson` (OSM fields only — preserves manual edits) |
| `bmu_data.py` | Elexon BMU reference data + the plant↔BMU mapping table logic |
| `bmu_operational.py` | Balancing Mechanism (ISPSTACK) activity snapshots |
| `fuel_taxonomy.py` | Shared fuel taxonomy / `plant:source` bucketing (Python side of `data/shared/fuel_types.json`) |
| `manual_plants.py` | UK plants absent from OSM |
| `export_io.py` | GeoJSON/CSV save helpers |

### Frontend (`map/`)

Static Leaflet app: `index.html` + ES modules in `map/js/` (`app.js`, `catalog.js`, `layers.js`, `bmuMap.js`, `zones.js`, `fuelTypes.js`, `popups.js`, …). It reads `data/catalog.json` for the region registry and layer URLs/types, and loads `data/shared/fuel_types.json` at startup (same taxonomy the Python prep uses). No build step — edit and reload. See `map/README.md` and `map/DEPLOY.md`.

### Per-region data layout (`data/regions/{id}/`)

Everything computed for a region lives in one portable folder so it can be copied between machines as a single tree. The pipeline flows **left to right** and the folders must not be confused:

```
source/  .osm.pbf extract (gitignored)            ─export_region.py─▶
raw/     full multi-GB OSM exports (gitignored)   ─prepare_map_data.py─▶
map/     trimmed web GeoJSON + *.pmtiles (browser-facing)
zones/   NESO DNO/GSP/TNUoS/ETYS polygons
reference/
  source/      downloaded Elexon/NESO reference   (≠ source/ above)
  editable/    human-edited tables                (edit these)
  generated/   script outputs + map runtime JSON  (do not edit)
  operational/ BM activity snapshots
```

Cross-region assets (`fuel_types.json`) live in `data/shared/`. `boundaries/` holds shared **export clip masks** only — the UK runtime boundary is `data/regions/uk/boundary.geojson`, not anything under `boundaries/`. Catalog layer `path`s are relative to `data/`.

### UK plant ↔ BMU mapping

BMU ids (Elexon generator *units*) are kept separate from OSM `power=plant` *site* geometry and joined at popup time. The flow:

```
edit  reference/editable/plant_bmu_links.csv   (one row per BMU; multi-unit sites share osm_id)
run   scripts/propose_plant_bmu_map.py
read  reference/generated/plant_bmu_links.json  (catalog `plantBmuMap`; loaded by the map)
```

`generated/plant_bmu_link_candidates.csv` is a **review queue**, not for wholesale copying — copy only accepted rows into the editable CSV, set `source=manual`, and regenerate. Scripts only ever *append* new high-confidence auto matches; existing rows are never overwritten.

The three catalog layer ids are deliberately distinct: `plants` ("BMU-mapped sites", grid-scale OSM `power=plant`, where BMU popups attach) vs. `generators` ("All generators", the full OSM `power=generator` inventory down to rooftop solar) vs. `turbines` ("Wind turbines", wind-only). BMU links appear on `plants` popups only.

## Conventions & guardrails

- **Never edit generated files** (`reference/generated/*`, `*_web.geojson` produced by prep). Edit the `editable/` CSVs and `map/bmu_sites_web.geojson` (OSM ground truth) only.
- **Do not delete or regenerate multi-GB files** (`raw/`, large PMTiles, `*_web.geojson`) unless explicitly asked.
- **Never commit** (already gitignored): `data/regions/*/raw/`, `data/regions/*/source/`, `data/regions/*/map/*.pmtiles`, `data/regions/*/map/all_generators_web.geojson`, `data/regions/*/map/generators_web.geojson` (legacy name), `data/regions/*/map/turbines_web.geojson`, `cache/`, `posters/`.
- Preserve user edits in `editable/` reference files and `bmu_sites_web.geojson`.

## Further docs

- `README.md` — full export options, data sources, derived fields, attribution/licences.
- `AGENTS.md` — concise cross-session agent guidance (overlaps this file).
- `DEVELOPMENT.md` — roadmap: regional balance, NESO forecasts, constraints, ISPSTACK BM activity, a planned SQLite reference store.
