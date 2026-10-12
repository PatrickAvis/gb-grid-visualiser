# Deploying GB Grid Visualiser

The app is static: deploy `map/` and only the runtime data needed by the enabled
catalog layers. Serve the repository layout from one origin, with the entry
point at `/map/`. No application server or frontend build is required.

## Runtime allowlist

| Path | Purpose |
| --- | --- |
| `map/index.html`, `map/js/` | Application |
| `data/catalog.json`, `data/shared/` | Layer registry and fuel taxonomy |
| `data/regions/{id}/boundary.geojson` | Region boundary where referenced |
| Catalog-referenced small files under `data/regions/{id}/map/` | Prepared map layers |
| Catalog-referenced `*.pmtiles` | Large streamed layers; build/copy separately |
| Catalog-referenced `data/regions/{id}/zones/` files | Zone overlays |
| `data/regions/uk/map/plants_meta.json` | Plant fetch provenance |
| `data/regions/uk/reference/generated/plant_bmu_links.json` | Plant/BMU popups |
| `data/regions/uk/reference/generated/bmu_connection_sites.json` | Connection-site popups |
| `data/regions/uk/reference/operational/bmu_activity_latest.json` | Optional BM snapshot |

Copy only needed files, preserving their relative paths. Some catalog paths may
refer to `boundaries/`; include those specific files too. A fresh clone does not
contain every optional layer: generate or copy them, or remove unavailable layers
from the deployment catalog. Keep optional layers off by default.

Do not sync entire region or reference directories. Exclude `raw/`, `source/`,
`reference/editable/`, review CSVs, caches, workbook downloads and tile-build
source GeoJSON (`all_generators_web.geojson`, `generators_web.geojson`,
`turbines_web.geojson`). Git ignores do not protect against rsync or upload tools.

The ETYS coordinate seeds come from a private reference repository. Its local
`etys_network.geojson`, `etys_graph.json`, coordinate/override CSVs and location
review output are excluded from publication pending provenance/reuse review.
Once cleared, the browser requires only `map/etys_network.geojson`; the graph and
review queue need not be public. See [the build workflow](README.md#etys-network-connections).

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
