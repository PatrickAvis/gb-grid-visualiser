# Project review — 12 October 2026

## Operational context branch validation

Scottish constraint shading: 23 frontend tests and the geometry regression
test pass. Browser checks confirmed grey historical defaults, explicit
historical colours (B4 green / B6 red for 10 October 23:30), one polygon layer
at a time, GW details, off/region cleanup and no JavaScript errors. The B6
example showed 5.403 GW forecast / 2.800 GW limit / 2.603 GW exceedance.
These are historical forecasts, not current conditions. Derived masks use
public boundary lines and the existing land clip; they exclude Shetland and
offshore assets and must not be used as electrical membership polygons.

Wind/weather addition: all 19 frontend tests pass, including wind-bearing
conversion, exact-hour missing-data handling, caching and malformed/error feed
responses. Live browser validation loaded the initial 42 wind samples and an asset
forecast; +24h matched in both controls and asset details, and height/time
changes made no further weather requests. Layer-off and region changes removed
the overlay without JavaScript errors. Weather appears before satellite imagery.
The subsequent flow-display revision uses 143 samples at 1° spacing, vector
interpolation, a speed raster and animated trails. Live checks covered forecast
loading, time changes, pause, zoom and layer-off cleanup without JS errors.
Interpolation does not add source detail; missing/outside cells remain blank.

The operational-context update adds three opt-in public feeds without changing
infrastructure datasets. Final validation passed 19 Python and 23 frontend
tests. Wind coverage now uses 432 samples across 44–66° N, 20° W–16° E;
live browser checks confirmed the wider field loads and renders. Fourteen frontend
tests pass (BMU series, line rendering and the new operational-data checks).
Live browser checks loaded 227 active REMIT notices (171 mapped by exact BMU
ID), 10 interconnectors (seven mapped), and 19 forecast groups (two mapped).
Counts are observations at test time, not fixed expectations.

Verified mapped outage BMU controls and satellite view, SCOTEX selection,
unmapped entry details, layer-off cleanup, region switching, mobile width,
and a simulated HTTP 503 with no misleading retained snapshot. No browser
JavaScript errors were observed. The latest NESO period was 10 October and
was correctly labelled historical. No backend/Python code was changed.

Limitations: independent overlays do not use zone filters; outage markers
can overlap at shared sites; no inferred capacity totals or instantaneous
flows; no automatic polling. Interconnector and boundary mapping coverage
is explicitly incomplete, with every unmatched row retained in the list.
Published REMIT capacities can vary across a notice's profile and are not
treated as current MEL. Crosswalk expansion requires source review. See
`map/README.md` for endpoint and attribution details.

## Result and scope

Reviewed the infrastructure/ETYS data flow, BM settlement-window logic, map
loading/search lifecycle, repository guidance and deployment documentation.
The review fixes are local and uncommitted; no push or deployment was performed.
The standalone repository is `https://github.com/PatrickAvis/gb-grid-visualiser`.

This is a research visualiser. ETYS supplies a planning-network snapshot;
OpenStreetMap supplies asset geometry; Elexon snapshots supply separately
refreshed BM activity. None establishes live circuit flows or switching states.

## Fixed during review

- BM settlement windows now use Europe/London day boundaries, including 46/50
  periods on clock-change days. Previously every day was assumed to have 48.
  Invalid periods and non-positive/non-finite windows are rejected before fetch.
- The activity CLI resolves the latest period once, using the returned window
  endpoint for output metadata. Custom output paths no longer fail when printed.
- Failed map loads can be retried. Stale asynchronous region loads no longer
  replace the current region or re-add layers from a destroyed manager.
- Search results respect the HTML hidden state and clear when regions change.
  The sidebar scrolls within short windows; region changes remove old highlights.
- Searching for a hidden ETYS edge enables its circuit/transformer/HVDC category.
- ETYS builds reject missing/unsupported required sheet columns and record the
  coordinate override hash alongside workbook and coordinate-table hashes.
- Setup, pipeline, BM defaults, ETYS workflow and deployment docs now agree with
  the code. Deployment uses an explicit runtime allowlist and preserves PMTiles
  byte-range behavior instead of applying HTTP content compression to archives.

Settlement handling follows the [Elexon settlement-period definition](https://www.elexon.co.uk/bsc/glossary/settlement-period/).

## ETYS source comparison

The [NESO appendices listing](https://www.neso.energy/publications/electricity-ten-year-statement-etys/etys-documents-and-appendices)
provides ETYS 2025 as the current suite checked for this work. The importer uses
[2025 Appendix B](https://www.neso.energy/document/383936/download), with the
coordinate-enriched 2024 colleague workbook only as a separately attributed
location seed. No colleague code was copied.

Counts below were computed from the downloaded workbooks, not inferred from
publication descriptions:

| Records | Official 2024 | Colleague 2024 | Official 2025 |
| --- | ---: | ---: | ---: |
| Site/voltage rows | 1,633 | 1,641 | 1,739 |
| Distinct site codes | 885 | 890 | 923 |
| Circuit rows | 1,558 | 1,558 | 1,392 |
| Transformer rows | 1,478 | 1,478 | 1,472 |
| Rows with coordinates | 0 | 1,632 | 0 |

The colleague circuit endpoint records agree with the official 2024 workbook.
Between official editions, 1,024 circuit endpoint-pair records were retained,
534 were old-only and 368 new-only. These are workbook differences, not proof of
physical asset additions/removals. A newer workbook is not necessarily larger.

The local 2025 build retains 2,868 edges: 1,392 circuits, 1,472 transformers and
four explicitly existing internal HVDC records. It displays 2,768 edges and
663 sites; 61 electrical nodes remain unlocated. The full graph retains missing
geometry and parallel records. Review CSV rows also include unused site-index
records, so their count differs from the unlocated-node count.

## Validation performed

- 14 unit regression tests passed: ETYS identity, parallel edges, coordinate
  conflicts, missing locations, grouped-site geometry, planned-link exclusion,
  overwrite protection, workbook schema, and settlement windows across DST.
- Rebuilt ETYS from the downloaded 2025 workbook; checked unique record IDs and
  valid edge references. No large OSM exports or PMTiles were regenerated.
- Python compilation and frontend JavaScript syntax checks.
- Local Edge/Playwright smoke checks: ETYS load, site search, neighbour popup,
  transformer toggle, clear highlight, layer off/on and region switching.
- Additional browser checks: simulated 404 then retry, hidden search results,
  720-pixel viewport and rapid region changes. No uncaught page errors.
- Basemap requests were suppressed during automated browser tests. These tests
  validate the application, not third-party tile service availability.

## Remaining work and limitations

1. Review coordinate accuracy and reuse provenance before publishing private-source
   ETYS artifacts. They remain ignored by Git. Fresh clones need their own
   coordinate table/build; the optional layer is off by default.
2. Match ETYS site/node IDs to existing OSM substations, TEC sites and BMUs using
   a reviewable mapping table. The schematic layer currently stands separately.
3. Resolve unlocated endpoints and cross-owner aliases before using the graph
   as a validated electrical model. Site markers collapse voltage-level buses;
   the graph preserves their distinct identities and original locations.
4. New ETYS editions need schema and edition review. `--year` labels output;
   it does not detect the workbook edition. Formulas use cached workbook values.
5. BM data is a static snapshot until refreshed. No scheduler/live subscription
   is included. Large-data refreshes, external API reliability, full PMTiles
   rebuilds and public-server deployment were not exercised in this review.
6. Dependencies are not locked and there is no CI workflow yet. The regression
   suite covers the changes above, not every exporter or matching heuristic.

## Before pushing

### Verified capacity correction

Barr River Community Hydro Scheme (OSM way 1565578407) had a malformed
`plant:output:electricity=1600 KV` tag, which the parser incorrectly treated as
1,600 MW. Glen Hydro's [scheme case study](https://www.glenhydro.co.uk/casestudies/barr-river-community-hydro-scheme)
confirms 1,600 kW. The editable ground-truth plant record now uses `1600 kW`
and `capacity_mw=1.6`; the additive merge preserves this correction. The capacity
parser now rejects unknown units rather than treating their numeric part as MW.
This is a local correction; the upstream OSM record has not been edited.

Review `git diff` and `git status`, then commit the code/docs/tests to `main` and
push to `origin` when requested. Do not force-add ignored ETYS source/coordinate
artifacts or the local `tmp/` audit material. A public code push does not itself
publish the locally generated optional network map.

## Data refresh — 12 October 2026

Refreshed the Great Britain OSM extract (11 October 2026), Elexon BMU standing
data, NESO TEC register, zone boundaries and latest 24-hour ISPSTACK snapshot.
GSP boundaries now use the February 2026 release (362 areas). The ETYS 2025
workbook is unchanged. Existing editable reference rows were preserved.

Overpass timed out. Plants were reconstructed from dependency-complete local
OSM XML with `scripts/import_plants_osm.py`, including relation geometry.
The additive plant merge retains previous sites outside the extract coverage.
There are 4,956 plant sites and 55,364 substations. Of 17,945 turbines, 4,189
offshore locations are retained from the previous snapshot, not newly verified;
`turbines_meta.json` and the map freshness note disclose this limitation.

ETYS site popups now include satellite previews and a satellite-map link.
Validation: 18 Python regression tests and three JavaScript rendering tests pass.
Large web layers were regenerated; the earlier review's untested-refresh caveat
applies to that earlier review, not this follow-up.
