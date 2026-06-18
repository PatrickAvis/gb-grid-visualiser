import { loadPlantBmuMap } from "./bmuMap.js";
import {
  buildRegionConfig,
  loadCatalog,
  persistRegionId,
  resolveRegionId,
} from "./catalog.js";
import { createLayerManager } from "./layers.js";
import { createZoneFilter } from "./zones.js";
import {
  buildBasemapControl,
  buildLayerPanel,
  buildRegionSelector,
  buildSearchPanel,
  fitRegionBounds,
  setMapTitle,
} from "./ui.js";
import { boundsFromGeoJson, pointInPolygonGeometry } from "./utils.js";
import { loadFuelTypes } from "./fuelTypes.js";

const statusEl = document.getElementById("status");
const zoomEl = document.getElementById("zoom-indicator");
let map;
let layerManager;
let zoneFilterState;
let zonesController;
let catalog;
let regionConfigRef = null;

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function updateZoomIndicator() {
  if (!map || !zoomEl) return;
  const zoom = map.getZoom();
  let gates = "";
  const parts = [];
  for (const [id, cfg] of Object.entries(regionConfigRef?.layers || {})) {
    if (cfg.minZoom != null) {
      parts.push(`${cfg.label || id} \u2265${cfg.minZoom}`);
    }
  }
  if (parts.length) {
    gates = `<span class="zoom-gates"> · shows at: ${parts.join(", ")}</span>`;
  }
  zoomEl.innerHTML = `Zoom: <b>${zoom}</b>${gates}`;
}

function createZoneState() {
  return {
    geometry: null,
    label: null,
    createZoneLayer: null,
    pointInside(lat, lon, geom) {
      return pointInPolygonGeometry(lat, lon, geom || this.geometry);
    },
  };
}

async function initRegion(regionId) {
  const regionConfig = buildRegionConfig(catalog, regionId);
  regionConfigRef = regionConfig;
  if (regionConfig.plantBmuMapUrl) {
    try {
      regionConfig.bmuLookup = await loadPlantBmuMap(
        regionConfig.plantBmuMapUrl,
        regionConfig.bmuConnectionSitesUrl,
      );
    } catch (error) {
      console.warn("Plant BMU map not loaded:", error);
      regionConfig.bmuLookup = null;
    }
  }
  persistRegionId(regionId);
  setMapTitle(regionConfig.title);

  if (layerManager) {
    layerManager.destroy();
  }
  if (zonesController?.clearSelection) {
    zonesController.clearSelection();
  }

  zoneFilterState = createZoneState();
  layerManager = createLayerManager(map, regionConfig, zoneFilterState);
  zonesController = createZoneFilter(layerManager, zoneFilterState);
  zoneFilterState.createZoneLayer = zonesController.createZoneLayer;

  buildLayerPanel(regionConfig, (layerId, enabled) => {
    layerManager.setLayerEnabled(layerId, enabled, setStatus);
  });
  for (const status of ["operational", "construction", "closed"]) {
    document.getElementById(`plant-status-${status}`)?.addEventListener("change", (event) => {
      layerManager.setPlantStatusVisible(status, event.target.checked);
    });
  }
  fetch(`../data/regions/${regionId}/map/plants_meta.json`)
    .then((response) => (response.ok ? response.json() : null))
    .then((meta) => {
      const el = document.getElementById("data-provenance");
      if (el && meta?.plants_fetched) el.textContent = `OSM plants fetched ${meta.plants_fetched}. `;
    })
    .catch(() => {});
  buildSearchPanel(
    (query) => layerManager.searchFeatures(query),
    (result) => layerManager.focusSearchResult(result),
  );

  fitRegionBounds(map, regionConfig.bounds);
  updateZoomIndicator();

  const defaultLayer = regionConfig.layerIds.find(
    (id) => regionConfig.layers[id]?.defaultOn,
  ) || regionConfig.layerIds.find((id) => id === "plants");

  if (!defaultLayer) {
    setStatus("Select a layer to load data.");
    return;
  }

  try {
    await layerManager.setLayerEnabled(
      defaultLayer,
      document.getElementById(`toggle-${defaultLayer}`)?.checked ?? true,
      setStatus,
    );
    const cache = layerManager.layerCache[defaultLayer];
    if (cache?.data) {
      const bounds = boundsFromGeoJson(cache.data);
      if (bounds) {
        map.fitBounds(bounds.pad(0.05));
      }
    }
    layerManager.updateStatusMessage(setStatus);
  } catch (error) {
    console.error(error);
    setStatus(
      `Failed to load ${regionConfig.title}. Run scripts/prepare_map_data.py --region ${regionId}. ${error.message}`,
      true,
    );
  }
}

async function main() {
  await loadFuelTypes();
  catalog = await loadCatalog();
  const regionId = resolveRegionId(catalog);

  map = L.map("map", { zoomControl: true, preferCanvas: true }).setView([54.5, -3.5], 6);
  const basemapLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  buildBasemapControl(map, basemapLayer);

  buildRegionSelector(catalog, regionId, (newRegionId) => {
    initRegion(newRegionId);
  });

  map.on("zoom zoomend", updateZoomIndicator);
  map.on("zoomend", () => {
    layerManager?.syncZoomGatedLayers();
    layerManager?.updateStatusMessage(setStatus);
  });
  updateZoomIndicator();

  await initRegion(regionId);
}

main().catch((error) => {
  console.error(error);
  setStatus(error.message, true);
});
