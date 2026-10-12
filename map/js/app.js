import { loadPlantBmuMap } from "./bmuMap.js";
import { installBmuChart } from "./bmuChart.js";
import { installOperationalContext } from "./operationalContext.js";
import { installWindWeather } from "./weather.js";
import { installConstraintZones } from "./constraintZones.js";
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
  setupWorkspace,
} from "./ui.js";
import { boundsFromGeoJson, pointInPolygonGeometry } from "./utils.js";
import { loadFuelTypes } from "./fuelTypes.js";

const statusEl = document.getElementById("status");
const zoomEl = document.getElementById("zoom-indicator");
let map;
let bmuChart;
let operationalContext;
let windWeather;
let constraintZones;
let layerManager;
let zoneFilterState;
let zonesController;
let catalog;
let regionConfigRef = null;
let regionRequest = 0;

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
  bmuChart?.close();
  constraintZones?.destroy();
  constraintZones=null;
  windWeather?.destroy();
  windWeather=null;
  operationalContext?.destroy();
  operationalContext = null;
  const request = ++regionRequest;
  const regionStatus = (...args) => { if (request === regionRequest) setStatus(...args); };
  const regionConfig = buildRegionConfig(catalog, regionId);
  if (regionId === "uk" && new URLSearchParams(window.location.search).get("network") === "etys") {
    for (const layer of Object.values(regionConfig.layers)) layer.defaultOn = false;
    regionConfig.layers.etys_network.defaultOn = true;
  }
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
  if (request !== regionRequest) return;
  regionConfigRef = regionConfig;
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
    layerManager.setLayerEnabled(layerId, enabled, regionStatus);
  });
  if (regionId === 'uk') operationalContext = installOperationalContext(map, regionConfig);
  if (regionId === 'uk') windWeather = installWindWeather(map);
  if (regionId === 'uk') constraintZones = installConstraintZones(map);
  for (const status of ["operational", "construction", "closed"]) {
    document.getElementById(`plant-status-${status}`)?.addEventListener("change", (event) => {
      layerManager.setPlantStatusVisible(status, event.target.checked);
    });
  }
  Promise.all(["plants_meta.json", "turbines_meta.json"].map((name) =>
    fetch(`../data/regions/${regionId}/map/${name}`)
      .then((response) => (response.ok ? response.json() : null)).catch(() => null)))
    .then(([meta, turbines]) => {
      if (request !== regionRequest) return;
      const el = document.getElementById("data-provenance");
      const notes = [];
      if (meta?.plants_fetched) notes.push(`OSM plants fetched ${meta.plants_fetched}.`);
      if (meta?.source_snapshot) notes.push(`Plant source snapshot ${meta.source_snapshot}.`);
      if (turbines?.retained_previous_offshore_turbines) {
        notes.push(`${turbines.retained_previous_offshore_turbines.toLocaleString()} offshore turbines retained from earlier data; live refresh unavailable.`);
      }
      if (el) el.textContent = notes.length ? notes.join(" ") + " " : "";
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
      regionStatus,
    );
    if (request !== regionRequest) return;
    const cache = layerManager.layerCache[defaultLayer];
    if (cache?.data) {
      const bounds = boundsFromGeoJson(cache.data);
      if (bounds) {
        map.fitBounds(bounds.pad(0.05));
      }
    }
    if (cache?.loaded) layerManager.updateStatusMessage(regionStatus);
  } catch (error) {
    if (request !== regionRequest) return;
    console.error(error);
    setStatus(
      `Failed to load ${regionConfig.title}. Run scripts/prepare_map_data.py --region ${regionId}. ${error.message}`,
      true,
    );
  }
}

async function main() {
  setupWorkspace();
  await loadFuelTypes();
  catalog = await loadCatalog();
  const regionId = resolveRegionId(catalog);

  map = L.map("map", { zoomControl: true, preferCanvas: true }).setView([54.5, -3.5], 6);
  map.zoomControl.setPosition('bottomright');
  bmuChart = installBmuChart(map);
  const clearSelection = document.createElement('button');
  clearSelection.type = 'button';
  clearSelection.className = 'workspace-clear';
  clearSelection.textContent = 'Clear all';
  clearSelection.title = 'Clear selections and turn off all map overlays';
  clearSelection.onclick = () => {
    bmuChart.close();
    map.closePopup();
    map.eachLayer(layer => layer.closeTooltip?.());
    layerManager?.clearSelection();
    if (zoneFilterState?.geometry) zonesController?.clearSelection();
    // Use the normal toggle handlers so pending requests, legends and counts
    // are cleared along with the layers themselves.
    document.querySelectorAll('input[id^="toggle-"], input[id^="context-"], #wind-enabled, #constraint-zones-enabled').forEach(toggle => {
      if (!toggle.checked) return;
      toggle.checked = false;
      toggle.dispatchEvent(new Event('change', { bubbles: true }));
    });
    // Turbines are controlled from the wind legend, without a main layer toggle.
    if (regionConfigRef?.layers?.turbines) {
      layerManager?.setLayerEnabled('turbines', false, setStatus);
    }
    const search = document.getElementById('map-search');
    if (search) search.value = '';
    const results = document.getElementById('search-results');
    if (results) { results.replaceChildren(); results.hidden = true; }
  };
  document.body.append(clearSelection);
  const basemapLayer = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
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
