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

## Workspace UI

The workspace groups layers into Network, Generation,
Balancing and Boundaries. Search and region selection stay above the scrolling
layer controls. **Layers & search** collapses the sidebar; small screens start
collapsed and use an expandable asset panel.

Asset selection opens one panel with **Overview**, **Operating data** and
**Instructions & prices** views instead of overlapping a popup and chart.
Overview retains satellite imagery, site properties, BMU buttons and ETYS
neighbour links. Operating and balancing views are disabled for assets with no
linked BMU. BMU data still loads on selection; the window selector offers 1, 6
(default) or 24 hours. **Expand** gives the panel more room. Selecting an
instruction highlights its segments and moves the chart cursor to its first
visible segment. Source signs, gaps and overlapping instructions are preserved.

For this local review, the redesigned working tree is served at
`http://127.0.0.1:8767/map/` and a snapshot of the main UI at
`http://127.0.0.1:8768/map/`. The temporary comparison server serves main's map
files against the same local datasets; it does not copy the large data archives.
The comparison snapshot/server lives under ignored `tmp/ui-comparison/` and is
not part of deployment. Deploy `map/workspace.css` alongside the other map files.

## Operational context

### Scottish constraint area colours

Enable **Constraint area colours → Shade Scottish export areas**. Select B4
(SSE_SP2) or B6 (SCOTEX); only one nested area is shaded at a time. Click the
area or **View area details** for forecast flow, export limit, signed headroom
and exceedance, in GW. Headroom = limit − flow; exceedance = max(flow − limit, 0).
Never sum the two boundary values or treat them as local generation minus demand,
actual curtailment or a dispatch requirement.

Red means above the export limit, amber 90–100%, green below 90%. The 90%
threshold is an application convention, not an official NESO warning. Forecasts
dated before today's GB date are grey unless **Colour historical forecasts**
is explicitly enabled; their historical status remains visible. Grey also means
missing/invalid data or negative flow (the opposite-direction import limit is
not assessed). Freshness is by forecast date, not evidence of a live measurement.
The latest published period is fetched on enable/refresh; there is no polling.

Geometry is **illustrative land north of the public NESO boundary line**, not an
official zone, membership or eligibility polygon. It uses the existing local
GB land mask, which excludes Shetland; offshore assets are not shaded. Northern
Ireland is excluded. The mask cannot determine which BMUs electrically sit behind
a boundary. The B4/B6 crosswalk is documented in NESO's Local Constraint Market
page, and the [Scottish boundaries description](https://www.neso.energy/publications/electricity-ten-year-statement-etys/electricity-transmission-network-requirements/scottish-boundaries)
describes the north–south transfers.

Rebuild this small derived layer with `python scripts/build_constraint_areas.py`.
It writes only `data/regions/uk/map/constraint_areas.geojson`, retaining input
hashes and provenance. It does not use private ETYS site coordinates or modify
the original boundary layers. Unit checks cover nested geometry, Scotland/NI
test points, thresholds, reverse flows, missing values and historical colours.

### Wind and asset weather

The UK **Wind & weather** control fetches Open-Meteo model forecasts on demand.
It displays a smooth speed-colour raster and animated downwind trails from
432 fixed sample points (44–66° N, 20° W–16° E), covering the nearby Atlantic,
Ireland and north-west Europe. Spacing remains 1° around GB (50–62° N,
8° W–2° E), widening to 2° farther out to limit API usage. This is spatial
interpolation of forecast samples, not native-resolution weather tiles.
Vector components are interpolated; missing cells remain blank and nothing
is extrapolated outside the sampled area. Colours encode speed in m/s.
Height options are 10 m and 120 m above ground. Animation speed is illustrative,
not a real-time parcel trajectory. Pause animation keeps the speed layer;
reduced-motion preferences disable animation. Panning, hidden tabs, layer-off
and region changes suspend or remove animation. Asset clicks pass through it.
The style was informed by Robin Hawkes' GB Renewables Map; our data remains
Open-Meteo, not that map's NOAA/GFS via WeatherLayers feed.

The hourly slider spans the current forecast hour through +48 hours in UTC.
Height, time and opacity changes use already-fetched data. **Refresh weather**
requests a new forecast. Successful responses are cached in memory for 30
minutes (bounded to 80 location sets); the displayed fetched time is retained.
There is no background polling. Open-Meteo may count multiple locations as
multiple calls for usage limits even though the grid is fetched in one request.

Selecting an asset with explicit coordinates adds weather before the satellite
view in Overview, independently of whether the wind overlay is enabled. It
shows wind at both heights, 10 m gusts, 2 m temperature, cloud cover and an
expandable hourly table. The selected overlay time also selects the asset's
weather hour, without altering the historical BMU chart window. No exact
forecast hour means unavailable, not an interpolated or substituted reading.
Unlocated records and boundary-only popups do not get guessed weather locations.

The API uses `cell_selection=nearest` so offshore requests are not forced to
land, `timezone=GMT`, Unix timestamps, `wind_speed_unit=ms`, and Best Match
model selection. The returned model grid coordinates appear in asset details.
These are modelled conditions, not turbine measurements or electrical output;
120 m is a reference height, not a claim about any turbine's hub height.

[Open-Meteo documentation](https://open-meteo.com/en/docs) and
[service terms/pricing](https://open-meteo.com/en/pricing): the free API is
rate-limited and for non-commercial use. Commercial deployment needs a suitable
subscription and secure handling of its API key. Weather attribution is shown
in the map and asset panel (CC BY 4.0). Frontend tests:
`node --test scripts/test_weather.mjs`.

### Outages, interconnectors and boundaries

The UK layer panel includes three optional
feeds. Enable a checkbox to fetch a snapshot; **Refresh** fetches again. No
background polling or saved operational data is introduced. Each feed has an
independent error state and a 90-second timeout. Switching regions cancels
requests and removes the layers. These overlays do not follow zone filters.
Click a marker, boundary or list entry to open the existing asset inspector.
Mapped BMU notices retain operating charts and satellite imagery.

- **REMIT outages**: Elexon `/remit/list/by-event` for now through seven days,
  latest revisions followed by `/remit?messageId=...` in batches of 50. Only
  active notices overlapping the window are displayed. Dismissed revisions
  suppress older active versions. Missing batches fail the whole snapshot.
  Dates, notice capacity fields and available capacity-profile segments are
  shown without summing overlapping notices or treating them as live MEL.
  Locations use exact `assetId` → linked BMU → plant IDs. Unmapped notices stay
  in the list. Absence of a notice is not proof of availability. Long-running
  notices, including those for retired assets, are retained as published.
- **Interconnectors**: Elexon `/generation/outturn/interconnectors`, last 24h,
  latest half-hour per link. Positive MW imports into GB; negative MW exports.
  Observations older than two hours are flagged. Null remains unavailable.
  Seven reviewed GB connection-area markers are provided initially; IFA2,
  BritNed and Greenlink remain in the list pending coordinate review. Marker
  positions represent connection areas, not subsea routes or exact equipment.
- **Boundary forecasts**: NESO CKAN resource
  `38a18ec1-9e40-465d-93fb-301e80fd1352`, all groups at its latest published
  forecast period. The feed's GMT/BST wall-clock timestamp is preserved and
  never interpreted in the browser's timezone. Periods before today's GB date
  are marked historical. This is day-ahead forecast flow/limit, not measured
  flow, a contingency check or circuit utilisation. Only confirmed SCOTEX/B6
  and SSE_SP2/B4 crosswalks are mapped; other groups remain in the list. Missing
  local boundary geometry leaves the full feed usable as a list.

Implementations: `js/operationalData.js` (fetching and pure transformations),
`js/operationalLocations.js` (reviewed crosswalks), and
`js/operationalContext.js` (controls, map and inspector integration).
Run `node --test scripts/test_operational_data.mjs` from the repository root.

Sources: [Elexon REMIT](https://bmrs.elexon.co.uk/remit),
[interconnector reporting](https://bmrs.elexon.co.uk/interconnector-flows),
[flow sign convention](https://www.elexon.co.uk/documents/groups/panel/2018-meetings/280/280-09-cp1506-new-interconnector-fuel-type/),
[NESO forecasts](https://www.neso.energy/data-portal/day-ahead-constraint-flows-and-limits),
[B6/B4 crosswalk](https://www.neso.energy/industry-information/balancing-services/local-constraint-market).
Connection-area coordinates come from the local OSM converter/substation
layers; [North Sea Link](https://www.nationalgrid.com/stories/energy-explained/what-are-electricity-interconnectors)
and [Viking Link](https://www.nationalgrid.com/national-grid-ventures/viking-link)
confirm their GB connection locations. Contains BMRS data © Elexon Limited;
boundary forecasts © NESO; mapped infrastructure © OpenStreetMap contributors.
