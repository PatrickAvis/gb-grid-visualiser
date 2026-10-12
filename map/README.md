# GB Grid Visualiser — interactive map

Leaflet map of transmission, generation, substations, wind turbines, and region-specific zone boundaries.

- **Map regions** (layer URLs, bounds, switcher): [`data/catalog.json`](../data/catalog.json)
- **Predefined boundaries** (multi-country export extents): [`boundaries/`](../boundaries/) + [`boundaries/manifest.json`](../boundaries/manifest.json)

UK and Europe catalog entries already point at `data/regions/uk/boundary.geojson` and `boundaries/europe.geojson`. Any manifest boundary can be exported without a catalog entry; add one when map layers are prepared.

## Quick start

### ETYS network connections

Build the optional connectivity layer separately from the OSM refresh:

```powershell
python scripts/build_etys_network.py --workbook "path/to/ETYS-2025.xlsx" --seed-workbook "path/to/coordinate-enriched-ETYS-2024.xlsx"
```

The official [ETYS 2025 Appendix B](https://www.neso.energy/document/383936/download)
contains network records but no latitude/longitude. The initial seed workbook
is the coordinate-enriched version in PSALOxford/GB-Transmission-Map (HunterTracer).
Its seed locations are attributed and labelled unverified; the build does not
independently validate them against surveyed locations. No third-party code is
copied into the importer or renderer.

The first command creates `data/regions/uk/reference/editable/etys_coordinates.csv`.
It refuses to overwrite an existing table. Subsequently run **without**
`--seed-workbook` to preserve corrections. You can also supply a separately
prepared coordinate CSV through `--coordinates`, with columns:
`owner,site_code,site_name,voltage_kv,latitude,longitude,source`.
Owner values are `SHE`, `SPT`, `NGET`, `OFTO`; matching requires the owner, code,
name and voltage to agree. Duplicate conflicting coordinates remain unresolved.

For descriptive HVDC endpoints or other exceptions, optionally create
`reference/editable/etys_node_coordinates.csv` with columns
`node_id,latitude,longitude,source`. Node IDs are owner-scoped, for example
`GB:Central DC Substation`. Supply verified coordinates rather than guessed
connections or centroids. Node overrides affect location only.

The build writes:

- `map/etys_network.geojson`: located site markers and schematic connections.
- `reference/generated/etys_graph.json`: all imported nodes and connections,
  including those without coordinates, original normalized attributes, source
  sheet/row, workbook hash, coordinate-table hash and optional override-table hash.
- `reference/generated/etys_location_review.csv`: unmatched/ambiguous locations.

Only `B-2-1*` circuits, `B-3-1*` transformers and `B-5-1` rows explicitly marked
`Existing = Yes` are imported. Future upgrade sheets are excluded. Full node IDs,
parallel records and within-site transformers are retained. Node IDs are scoped
by owner; cross-owner aliases are not claimed to be a validated electrical model.
Source row IDs identify records within a workbook version, not across editions.
The CSV review includes unused site-index records as well as actual unlocated
endpoints, so its row count exceeds the unlocated-node count displayed on the map.

Enable **ETYS 2025 network connections**, or open
`http://localhost:8000/map/?region=uk&network=etys`. The layer has its own legend,
circuit/transformer/HVDC toggles and a clear-highlight button. Click a site for
neighbours, or select a loaded site/node through the search box. Curved lines
separate parallel records; loops show co-located connections. They are schematic,
not OSM routes. Connected-site lists describe mapped connections only.

Site popups include the same Esri satellite preview and Google satellite-view
link as plant popups, centred on the displayed site marker. Imagery does not
validate the unverified coordinate seeds; use it to help review their positions.

Downloads, coordinate seeds and derived ETYS outputs stay local and are ignored
by Git pending provenance/reuse review of the private coordinate source. A fresh
clone needs the separate build before this optional layer can be enabled.

Checks: `python -m unittest scripts.test_etys_network`.

### Serve the map

```powershell
python scripts/serve_map.py
```

Open [http://localhost:8000/map/](http://localhost:8000/map/) or deep-link a region: [http://localhost:8000/map/?region=uk](http://localhost:8000/map/?region=uk). Use `serve_map.py` instead of `python -m http.server` when testing PMTiles — it supports HTTP range requests.

Use the **region** dropdown to switch between countries (UK, France, …) or the continent view (Europe, when PMTiles are built).

## Data layout

```
data/
  catalog.json                  # region registry, bounds, layer URLs and types
  shared/                        # cross-region assets (fuel_types.json)
  regions/{region_id}/           # one portable folder per region
    boundary.geojson             # export clip mask (copied from boundaries/)
    source/                      # local .osm.pbf extracts (gitignored)
    raw/                         # full OSM exports (gitignored)
    map/                         # web GeoJSON and PMTiles
    zones/                       # zone overlays (UK DNO/GSP/TNUoS/ETYS today)
    reference/                   # UK BMU + mapping tables
      source/                    # downloaded Elexon reference
      editable/                  # human-edited plant_bmu_links.csv
      generated/                 # script outputs + map runtime JSON
      operational/               # refreshable BM activity snapshots
```

Everything computed for a region lives under `data/regions/{region_id}/`, so a
region can be copied between machines as a single folder. Catalog layer paths
are relative to `data/` (e.g. `regions/uk/map/bmu_sites_web.geojson`).

## Layer naming

| Catalog id | UI label | Meaning |
|------------|----------|---------|
| `plants` | BMU-mapped sites | Grid-scale OSM `power=plant` sites; BMU links appear in UK popups. |
| `generators` | All generators | Complete OSM `power=generator` inventory, from grid assets down to domestic rooftop solar. |
| `turbines` | Wind turbines | Wind-only generator subset for turbine-level detail. |

## Export and prepare (per region)

```powershell
# UK (alias)
python scripts/export_uk.py --all
python scripts/fetch_neso_zones.py              # all registered NESO boundary datasets
python scripts/fetch_neso_zones.py --only generation
python scripts/prepare_map_data.py --region uk
# zones only (after fetch):
python scripts/prepare_map_data.py --region uk --skip-lines --skip-plants --skip-substations --skip-turbines

Offshore plants/turbines use a **250 km** sea buffer for UK (cables still use 600 km). Tile size auto-shrinks for buffered exports. If Overpass times out, abort and retry with `--tile-size-km 80 --tile-delay 45`, or raise `--offshore-sea-buffer-km 300` only if farms are still missing. Then `prepare_map_data.py` and `build_tiles.py --layer turbines`.
```

### UK plants and BMU (separate layers)

| File | Role |
|------|------|
| [`data/regions/uk/map/bmu_sites_web.geojson`](../data/regions/uk/map/bmu_sites_web.geojson) | **OSM site ground truth** — geometry and plant tags. Edit directly; sync fills blanks only. |
| [`data/regions/uk/reference/editable/plant_bmu_links.csv`](../data/regions/uk/reference/editable/plant_bmu_links.csv) | **Your join table** — links `osm_id` → BMU ids. Edit this for BMU corrections. |
| [`data/regions/uk/reference/source/elexon_bmu_units.json`](../data/regions/uk/reference/source/elexon_bmu_units.json) | Elexon BMU registry (auto-fetched). |
| [`data/regions/uk/reference/generated/plant_bmu_links.json`](../data/regions/uk/reference/generated/plant_bmu_links.json) | Map runtime copy (generated from CSV). |

The map joins plants + BMU map at popup time (`osm_id` first, plant name fallback).

```powershell
# OSM plants (editable ground truth)
python scripts/sync_uk_plants.py

# BMU mapping: migrate embedded data, propose auto matches, export JSON
python scripts/propose_plant_bmu_map.py --fetch

# Plants still without a map row
python scripts/propose_plant_bmu_map.py --list-unmatched data/regions/uk/reference/generated/plants_without_bmu_links.csv
```

Add manual BMU links in `plant_bmu_links.csv` (one row per BMU unit; use `source=manual`). Re-run `propose_plant_bmu_map.py` to refresh the JSON. Existing rows are never overwritten.

`prepare_map_data.py --region uk` uses the same OSM merge for plants. To rebuild plants from OSM and discard edits: `python scripts/sync_uk_plants.py --force`.

### UK BM activity snapshot

```powershell
python scripts/fetch_bm_activity.py
```

This fetches the last 24 hours through the latest published Elexon ISPSTACK period and writes:

- `data/regions/uk/reference/operational/bmu_activity_latest.json` for the **BM bids** and **BM offers** layers.
- `data/regions/uk/reference/operational/bmu_unmapped_ispstack.csv` for active BMUs that still need mapping.

```powershell
# Any catalog region
python scripts/export_region.py --region fr --all
python scripts/prepare_map_data.py --region fr

# Predefined boundary from boundaries/ (export-only until added to catalog)
python scripts/export_region.py --region iberia --all
python scripts/export_region.py --region continental_europe --all

# List catalog vs boundaries/ coverage
python scripts/list_regions.py
```

Per-layer refresh:

```powershell
python scripts/prepare_map_data.py --region uk --skip-lines --skip-substations --skip-turbines
```

### France pilot

```powershell
python scripts/export_region.py --region fr --single-query --skip-lines --skip-substations --skip-turbines
python scripts/prepare_map_data.py --region fr --skip-lines --skip-substations --skip-turbines
```

Full France export (lines/turbines) can take hours — use tiled export without `--single-query` for production.

## UK fast layers (PMTiles)

The UK map uses PMTiles for the heavy visual layers so the browser does not fetch
large raw GeoJSON files:

- `data/regions/uk/map/lines.pmtiles` from `lines_transmission.geojson`
- `data/regions/uk/map/all_generators.pmtiles` from `all_generators_web.geojson`
- `data/regions/uk/map/turbines.pmtiles` from `turbines_web.geojson`

Build the source web GeoJSON first, then build tiles:

```powershell
python scripts/prepare_map_data.py --region uk
python scripts/build_tiles.py --region uk
```

Requires [tippecanoe](https://github.com/felt/tippecanoe) and the
[pmtiles](https://github.com/protomaps/go-pmtiles) CLI on `PATH`.
On Windows, the simplest local route is usually WSL for Tippecanoe, with the
repo mounted from Windows or cloned inside the WSL filesystem.

`*.pmtiles` files are generated deploy artifacts and are ignored by git. They
should be copied to the static host alongside the smaller GeoJSON layers.
The browser-side PMTiles renderer is vendored at
`map/vendor/protomaps-leaflet.js` so the map does not depend on a runtime module
import from a CDN.

## Europe continent (PMTiles)

Continent-wide lines and turbines use PMTiles (phase 2). After preparing merged GeoJSON under `data/regions/europe/map/`:

```powershell
python scripts/prepare_map_data.py --region europe
python scripts/build_tiles.py --region europe
```

Requires [tippecanoe](https://github.com/felt/tippecanoe) and the [pmtiles](https://github.com/protomaps/go-pmtiles) CLI on `PATH`.

## Layer size budget (UK, approximate)

| Layer | File | Size |
|-------|------|------|
| Transmission lines | `lines_transmission.geojson` | ~50 MB |
| BMU-mapped sites | `bmu_sites_web.geojson` | ~3 MB |
| Substations | `substations_web.geojson` | ~24 MB |
| All generators | `all_generators.pmtiles` | generated |
| Wind turbines | `turbines_web.geojson` | ~250 MB |

## Map architecture

| Module | Role |
|--------|------|
| [`js/catalog.js`](js/catalog.js) | Load catalog, resolve `?region=`, build runtime config |
| [`js/layerDefs.js`](js/layerDefs.js) | Styling and popup behaviour per layer type |
| [`js/sources/geojson.js`](js/sources/geojson.js) | GeoJSON fetch loader |
| [`js/sources/pmtiles.js`](js/sources/pmtiles.js) | PMTiles vector layer loader |
| [`js/layers.js`](js/layers.js) | Dynamic layer manager per region |
| [`js/ui.js`](js/ui.js) | Region selector and layer panel |

## Features

- Region switcher with grouped continents
- Lazy-loaded layers with toggleable legends
- Plants/substations: polygon + marker
- Wind turbines: zoom gate (per catalog `minZoom`)
- UK: DNO/GSP zones with click-to-filter
- URL param and `localStorage` for last region

## Deployment

See [`DEPLOY.md`](DEPLOY.md) for nginx, compression, PMTiles serving, and data sync.

## On-demand BMU operating chart

On `feature/bmu-operational-data`, clicking a BMU-mapped site or BM action opens
one chart for PN (Physical Notification), MEL (Maximum Export Limit), SEL
(Stable Export Limit) and MIL (Maximum Import Limit). Click a BMU ID in the popup
or choose a unit in the chart for multi-unit sites. The default is the first
transmission BMU where present, otherwise the first mapped unit.

The browser fetches the last six hours from Elexon Insights on each opening,
unit change or Refresh. There is no polling, persisted history or API key.
The chart uses UTC and MW, retains source signs, and shows missing values as
"No data" rather than zero. Hover or use the time slider for values; legend
checkboxes help inspect overlapping lines. These are notifications and limits,
not metered generation or accepted balancing instructions.

Implementation: `map/js/bmuSeries.js` calls `/balancing/physical` for PN/MELS/MILS,
`/balancing/dynamic` at the start of the window for an SEL baseline, and
`/datasets/SEL` with `from`/`to` for changes. SEL is carried forward until the next
change. A failed changes request suppresses SEL rather than displaying a false
constant. No initial SEL value is inferred if the baseline is unavailable.
Requests time out after 25 seconds and are cancelled on another selection,
chart close or region change. Partial failures remain visible with a retry.
`map/js/bmuChart.js` renders the chart without an additional chart dependency.

Source documentation: https://developer.data.elexon.co.uk/ . Direct browser
requests require network access to `https://data.elexon.co.uk` (CORS supported).
Validate transformations with `node --test scripts/test_bmu_series.mjs`.

### Accepted instructions and submitted prices

The same on-demand load now also requests `/balancing/acceptances` (BOALF) and
`/balancing/bid-offer` (BOD). The Instructions checkbox overlays individual
accepted MW segments in red. Expand **Accepted instructions** to inspect issue
and effective times, levels, flags and instruction numbers; selecting a number
highlights its segments. Overlapping instructions are preserved, not summed or
collapsed into a reconstructed final dispatch profile. No instruction is not
interpreted as zero output. MW traces are not accepted energy volumes or costs.

Expand **Submitted bid/offer prices** and select a settlement date/period to see
pair IDs, interval times, MW levels relative to PN, and separate bid and offer
prices in GBP/MWh. Negative and zero prices remain intact. Settlement-period
identifiers come directly from Elexon (GB settlement calendar); displayed
interval timestamps are UTC. Data is not combined across BMUs or periods.

The price table is separate from acceptance records: this version does not
infer accepted pair volumes, revenue, final dispatch, or metered generation.
Each source can fail independently; unavailable data is labelled and the
successful chart/table data remains usable. Refresh retries all five requests.
