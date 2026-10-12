# Deploying GB Grid Visualiser

The app is static: deploy `map/` and only the runtime data needed by the enabled
catalog layers. Serve the repository layout from one origin, with the entry
point at `/map/`. No application server or frontend build is required.

## Runtime allowlist

Scottish constraint shading also requires
`data/regions/uk/map/constraint_areas.geojson`, `map/js/constraintZones.js` and
`map/js/constraintStatus.js`. This small derived land mask uses public NESO
boundary lines and the existing GB clip; it contains no private ETYS site
coordinate seeds. Build it with `python scripts/build_constraint_areas.py`.

The development operational-context controls use browser requests to
`https://data.elexon.co.uk` and `https://api.neso.energy`; allow both in CSP
`connect-src`. Deploy the three `map/js/operational*.js` modules and updated
workspace CSS together. The controls reuse the catalog's UK plant layer,
plant/BMU link JSON and optional ETYS boundary GeoJSON. No credentials or
new backend are needed. Unavailable feeds show an error rather than cached
data represented as current.

Wind and asset weather additionally require `map/js/weather.js`,
`map/js/weatherData.js`, `map/js/windField.js`, `map/js/windCanvas.js`, and `https://api.open-meteo.com` in CSP `connect-src`.
The development implementation uses the non-commercial public API without a
key. Check Open-Meteo's service terms before commercial deployment. Do not
embed a paid/private API key in these static browser modules.

| Path | Purpose |
| --- | --- |
| `map/index.html`, `map/js/` | Application |
| `data/catalog.json`, `data/shared/` | Layer registry and fuel taxonomy |
| `data/regions/{id}/boundary.geojson` | Region boundary where referenced |
| Catalog-referenced small files under `data/regions/{id}/map/` | Prepared map layers |
| Catalog-referenced `*.pmtiles` | Streamed layers; UK archives included in Git |
| Catalog-referenced `data/regions/{id}/zones/` files | Zone overlays |
| `data/regions/uk/map/plants_meta.json` | Plant fetch provenance |
| `data/regions/uk/reference/generated/plant_bmu_links.json` | Plant/BMU popups |
| `data/regions/uk/reference/generated/bmu_connection_sites.json` | Connection-site popups |
| `data/regions/uk/reference/operational/bmu_activity_latest.json` | Optional BM snapshot |

Copy only needed files, preserving their relative paths. Some catalog paths may
refer to `boundaries/`; include those specific files too. A fresh clone includes prepared UK runtime layers. Other regions require
preparation; remove unavailable regional layers from a deployment catalog. Keep optional layers off by default.

Do not sync entire region or reference directories. Exclude `raw/`, `source/`,
`reference/editable/`, review CSVs, caches, workbook downloads and tile-build
source GeoJSON (`all_generators_web.geojson`, `generators_web.geojson`,
`turbines_web.geojson`). Git ignores do not protect against rsync or upload tools.

The ETYS coordinate seeds come from a private reference repository. The owner
requested inclusion of the generated `data/regions/uk/map/etys_network.geojson`
in Git for runtime parity. Coordinate/override CSVs, `etys_graph.json` and
location review outputs remain local. Runtime inclusion does not establish new
reuse terms for the original coordinate source. The browser needs only the
network GeoJSON. See [the build workflow](README.md#etys-network-connections).

## Static server

Example layout: `/var/www/gb-grid-visualiser/map/` and
`/var/www/gb-grid-visualiser/data/`. Serve the directory above `map/`:

```nginx
server {
    listen 80;
    server_name grid.example.com;
    root /var/www/gb-grid-visualiser;

    location / {
        try_files $uri $uri/ =404;
    }

    location ~* \.pmtiles$ {
        gzip off;
        default_type application/octet-stream;
        add_header Cache-Control "public, max-age=3600";
        try_files $uri =404;
    }
}
```

Enable gzip/Brotli for JSON and GeoJSON if desired. **Do not apply HTTP content
compression to PMTiles**: clients address byte ranges in the original archive.
Disable any inherited Brotli or CDN automatic compression for `.pmtiles` too.
The server must return `206 Partial Content` with a correct `Content-Range` for
range requests. If data is hosted on another origin, configure CORS there.

Use short cache lifetimes for the catalog and frequently replaced BM snapshots.
Invalidate cached data when replacing files at the same URL. An operational
snapshot is refreshed by rerunning its fetch command; the browser does not
subscribe to live Elexon updates.

## Refresh and verify

Run `python scripts/refresh_uk.py` locally for infrastructure updates, observing
its final report for skipped or failed optional stages. BM snapshots use
`python scripts/fetch_bm_activity.py`; ETYS has its separate workbook build.
Tippecanoe and the PMTiles CLI require WSL/Linux in the usual Windows setup.
Do not run a large data refresh solely to deploy unchanged data.

Before publication:

1. Preview the selected files with `python scripts/serve_map.py`.
2. Test every default layer, a plant popup, search and region switching.
3. Verify PMTiles byte-range responses and optional-layer availability.
4. Check attribution and the dates shown for operational/planning snapshots.
5. Review the exact upload list, excluding local coordinate/reference material.

Preserve the OpenStreetMap and NESO attribution shown by the app. The ETYS
planning layer is not measured power flow or live switching-state data.

Include `data/regions/uk/map/plants_meta.json` and `turbines_meta.json` alongside
the runtime layers so the map can disclose snapshot dates and retained offshore
data. These metadata files contain no private ETYS coordinate seeds.

The optional on-demand BMU chart also needs `map/bmu-chart.css` and the new JS
modules, plus browser access to `https://data.elexon.co.uk`. If setting a CSP,
include that host in `connect-src`. It requires no backend or API credentials.

The redesigned workspace also requires `map/workspace.css`. The temporary local
main/UI comparison server and snapshots under `tmp/` are not deployment assets.
