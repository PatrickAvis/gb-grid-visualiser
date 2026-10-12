# Development Roadmap

## Current Direction

The project is evolving from a static asset map into an operational electricity system map: regional generation, demand, surplus/deficit, forecasts, constraints, and Balancing Mechanism activity.

## Data Layout

Computed data for each region lives under `data/regions/{id}/`. Cross-region shared assets live in `data/shared/`. Export clip masks live in `boundaries/`.

```
data/regions/uk/
  boundary.geojson
  source/          # local .osm.pbf (gitignored)
  raw/             # full OSM exports (gitignored)
  map/             # web GeoJSON + PMTiles
  zones/           # NESO DNO/GSP/TNUoS/ETYS
  reference/
    source/        # downloaded/imported reference tables
    editable/      # human-edited mapping tables
    generated/     # script outputs for review + map runtime
    operational/   # BM snapshots now; forecasts planned
```

### Region folder roles

| Folder | Role | Do not confuse with |
|--------|------|---------------------|
| `source/` | Local `.osm.pbf` extract (gitignored) | `reference/source/` Elexon/NESO downloads |
| `raw/` | Full OSM spatial exports from `export_region.py` (multi-GB, gitignored) | `reference/` lookup tables |
| `map/` | Trimmed web GeoJSON + PMTiles for the browser | `raw/` full exports |
| `zones/` | Region-specific zone polygons and download intermediates | `reference/` |
| `reference/source/` | Downloaded standing/reference data | `raw/` OSM geometry |
| `reference/editable/` | Human-edited BMU links and manual sites | generated reports |
| `reference/generated/` | Script reports + map runtime JSON | source/reference inputs |
| `reference/operational/` | Refreshable ISPSTACK BM activity snapshots | static asset layers |

Pipeline: `source/` -> `export_region.py` -> `raw/` -> `prepare_map_data.py` -> `map/`. BMU scripts join `reference/` data to `map/bmu_sites_web.geojson`.

## Layer Naming

| Catalog id | UI label | Meaning |
|------------|----------|---------|
| `plants` | BMU-mapped sites | Grid-scale OSM `power=plant` sites; curated layer; Elexon BMU popups. |
| `generators` | All generators | Complete OSM `power=generator` inventory from grid assets down to domestic rooftop solar; dense PMTiles. |
| `turbines` | Wind turbines | Wind-only generator units for turbine-level detail. |

BMUs are Elexon generator units, but the map displays them on site-level OSM `power=plant` features via `reference/editable/plant_bmu_links.csv`.

## BMU Mapping Workflow (Now)

**Edit** the plant ↔ BMU link table:

`data/regions/uk/reference/editable/plant_bmu_links.csv`

**Regenerate** the map runtime JSON:

```powershell
python scripts/propose_plant_bmu_map.py
```

**Map reads**:

`data/regions/uk/reference/generated/plant_bmu_links.json`

Optional: fetch fresh Elexon BMU standing data first:

```powershell
python scripts/propose_plant_bmu_map.py --fetch
```

### Accepting candidate matches

`generated/plant_bmu_link_candidates.csv` is a **review queue**, not a file to copy wholesale. Copy only accepted rows into `editable/plant_bmu_links.csv`, set `source=manual`, then re-run `propose_plant_bmu_map.py`.

### Reference file roles

| Path | Role |
|------|------|
| `reference/source/elexon_bmu_units.json` | Elexon BMU registry (auto-fetched) |
| `reference/source/elexon_bmu_fuel_types.csv` | Flat BMU standing data export (same family as [Elexon BMU fuel type XLS](https://www.elexon.co.uk/documents/data/operational-data/bmu-fuel-type/)) |
| `reference/source/elexon_bmu_oc2_aliases.csv` | NGC ↔ settlement ↔ OC2 site aliases |
| `reference/editable/plant_bmu_links.csv` | **Your join table** — edit this |
| `reference/editable/manual_plants.csv` | Manual plant assets absent from OSM |
| `reference/generated/plant_bmu_links.json` | Map runtime copy (generated) |
| `reference/generated/plant_bmu_link_candidates.csv` | Proposed matches for review |
| `reference/generated/plants_without_bmu_links.csv` | Plants with no BMU link |
| `reference/generated/bmu_unmapped_displayable.csv` | Displayable BMUs not yet mapped |
| `reference/generated/bmu_reference_only.csv` | Supplier/virtual/import BMUs |

## Network Connectivity: BMU ↔ Substation (Now)

Links the otherwise-isolated BMUs to the grid: which substation each BMU connects
to, and (inverted) which BMUs/plants hang off each substation. Source of truth is
the **NESO TEC (Transmission Entry Capacity) Register**, whose `Connection Site`
column names the transmission substation for each transmission-connected project.
The Register carries no BMU ids, so BMUs are **name-matched** to TEC projects
(reusing the `bmu_data` normalisation machinery), and TEC connection-site names
are in turn **name-matched** to OSM substation polygons.

```
fetch  reference/source/neso_tec_register.csv          (scripts/fetch_tec_register.py)
       NESO CKAN resource 17becbab-e3e8-473f-b303-3806f43a6a10, refreshed Tue/Fri

BMU → connection site:
edit   reference/editable/bmu_connection_sites.csv       (one row per BMU; append-only)
run    scripts/propose_bmu_connection_sites.py [--fetch]
read   reference/generated/bmu_connection_sites.json     (catalog `bmuConnectionSites`)
       reference/generated/bmu_connection_site_candidates.csv   (review queue)

substation → BMUs/plants (inverse):
edit   reference/editable/connection_site_substations.csv (connection_site → OSM name)
run    scripts/match_substation_bmus.py
write  map/substations_web.geojson  (+connection_site, bmu_count, connected_capacity_mw,
                                      connected_bmus, connected_plants)
       reference/generated/connection_site_substation_candidates.csv  (review queue)
```

Both steps are append-only and have candidate review queues, identical in spirit
to `plant_bmu_links`. The substation step **augments `substations_web.geojson` in
place** (idempotent) because OSM substation features carry no stable id to key a
side-file on; it must run after `prepare_map_data.py` regenerates that layer. The
match is filtered to transmission substations (`substation=transmission` or
voltage ≥ 132 kV) to cut ~53k distribution kiosks down to ~1.3k candidates.

`refresh_uk.py` runs both via `--skip-tec` and `--skip-substation-links` stages.

| Path | Role |
|------|------|
| `reference/source/neso_tec_register.csv` | TEC Register (auto-fetched) |
| `reference/editable/bmu_connection_sites.csv` | **BMU → connection site** join table — edit this |
| `reference/editable/connection_site_substations.csv` | **connection site → OSM substation name** — edit this |
| `reference/generated/bmu_connection_sites.json` | Map runtime (BMU popups) |
| `reference/generated/bmu_connection_site_candidates.csv` | Proposed BMU→site matches for review |
| `reference/generated/connection_site_substation_candidates.csv` | Proposed site→substation matches for review |

## Candidate Map Enhancements

### Phase 2 — Network topology: "everything connected to a substation"

Implemented first stage: an optional ETYS 2025 schematic layer, full node/circuit
graph, parallel circuits, transformer/HVDC toggles, neighbour highlighting and
an unresolved-location review CSV. Build with `scripts/build_etys_network.py`.
Coordinate seeds remain explicitly unverified. See `map/README.md`.
The next stage below is joining those ETYS sites to the existing OSM/TEC/BMU
records; the current overlay does not yet implement that crosswalk.

Extends the substation popup from connected *generation* to connected *circuits*
("everything connected"), using **NESO ETYS Appendix B** (the published network
model: node/bus list + circuit/branch data with impedances). The bridge is the
same shape as the substation step above:

```
source/    reference/source/etys_appendix_b/*.csv          (per-TO node + branch tables)
edit       reference/editable/connection_site_nodes.csv     (connection_site → ETYS node id)
read       reference/generated/node_circuits.json           (node → [circuits to other nodes])
```

`Connection Site` names won't match ETYS node ids cleanly, so `connection_site_nodes.csv`
is a hand-maintained alias (same pattern as `elexon_bmu_oc2_aliases.csv`), small
because it only covers substations that already have BMUs. With it, a substation
popup (or a click-to-trace) can show BMU → substation → circuit → adjacent
substations. ETYS 2025 Appendix B was published on 30 June 2026 and is used by
the new layer; retain its 2025/26 snapshot label. OSM transmission lines are not
a reliable topology source (endpoints aren't tagged with their substations).

### Phase 3 — Embedded generation (ECR)

TEC is transmission-connected only, so distribution-connected BMUs (the
`gspGroup`-tagged ones) never get a connection site from it. Add the **NESO
Embedded Capacity Register (ECR)** as a parallel source, giving the DNO connection
point + connection voltage rather than a transmission substation. Reconcile the
partial overlap: TEC already flags some rows with `Agreement Type = Embedded`.

```
fetch  reference/source/neso_ecr.csv                       (NESO CKAN)
edit   reference/editable/bmu_embedded_connections.csv      (BMU → DNO connection point)
read   reference/generated/bmu_embedded_connections.json
```


### Regional balance

Show generation, demand, and net balance by zone (DNO, GSP, TNUoS generation zones, ETYS boundaries).

Suggested fields: `demand_mw`, `generation_mw`, `wind_mw`, `solar_mw`, `net_balance_mw`, `timestamp`.

### Wind and solar forecasts

- NESO day-ahead wind forecast
- NESO embedded wind/solar forecasts
- Regional aggregation by zone where direct zonal data is unavailable

### Demand

- National demand forecast (NESO)
- Regional demand estimates (Carbon Intensity API / modelling)

### Constraints

- ETYS transmission boundaries (already on map)
- NESO day-ahead constraint flows and limits
- Boundary loading % and headroom
- Correlation with regional surplus/deficit

### NESO data to investigate

- [NESO Data Portal API](https://www.neso.energy/data-portal/api-guidance) — CKAN `datastore_search`
- Day Ahead National Demand Forecast
- Day Ahead Wind Forecast
- Embedded Wind and Solar Forecasts
- Day Ahead Constraint Flows and Limits
- Carbon Intensity API (regional DNO-based forecasts)

## Balancing Mechanism Activity Layer

Show which mapped BMUs are active in the Balancing Mechanism via ISPSTACK data.

### Data source

Elexon Insights ISPSTACK / detailed system price stack:

- BMU ID, buy/sell side, settlement date/period, volume, price, bid-offer pair ID

### Pipeline

1. Resolve settlement window (default: last 24 hours through latest published period).
2. Fetch ISPSTACK buy and sell stacks for each half-hour period in that window.
3. Normalize and aggregate actions by mapped site/BMU.
4. Join to `plant_bmu_links`.
5. Export `operational/bmu_activity_latest.json` for the map.
6. Export `operational/bmu_unmapped_ispstack.csv` for review.

### Map behaviour

- Separate optional layers for bids (reduce generation) and offers (increase generation).
- Marker size by absolute volume; small offset when both sides are shown at one site.
- Popup: BMU ID, price, volume, settlement period.

Refresh the static snapshot:

```powershell
python scripts/fetch_bm_activity.py
python scripts/fetch_bm_activity.py --hours 6
python scripts/fetch_bm_activity.py --settlement-date 2026-06-10 --settlement-period 48
```

## Active But Unmapped BMUs

Use ISPSTACK to identify BMUs active in balancing but not linked to any mapped plant.

Output: `reference/operational/bmu_unmapped_ispstack.csv` — cumulative review queue enriched from `elexon_bmu_units.json`; merges each fetch, drops mapped BMUs, sets `active_latest` for the current snapshot.

[Elexon BMU fuel type spreadsheet](https://www.elexon.co.uk/documents/data/operational-data/bmu-fuel-type/) is a useful manual cross-check when identifying unmapped active BMUs; refresh standing data with `python scripts/fetch_bmu_reference.py` or `python scripts/propose_plant_bmu_map.py --fetch`.

Workflow: fetch ISPSTACK → compare with `plant_bmu_links` → enrich from `elexon_bmu_units` → write review CSV → update editable tables → regenerate JSON.

## Reference Data Store (Later)

After naming is stable, add SQLite:

`data/regions/uk/reference/uk_reference.sqlite`

PostgreSQL-compatible table names for future migration:

- `bmu_units`, `bmu_aliases`, `plants`, `plant_bmu_links`, `manual_plants`
- `bmu_mapping_candidates`, `bmu_unmapped_displayable`, `bmu_reference_only`
- `ispstack_actions`, `bmu_activity_summary`, `bmu_unmapped_ispstack`

Keep browser outputs as static JSON; do not make the frontend read SQLite directly.

### Why SQLite first, not PostgreSQL

SQLite matches the portable per-region folder model. PostgreSQL/PostGIS becomes worthwhile for multi-user editing, large historical ISPSTACK archives, and server-backed live dashboards.

