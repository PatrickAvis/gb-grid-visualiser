import { LINE_TYPE_ORDER } from "./constants.js";
import { createEtysNetworkLayer } from "./etysNetwork.js";
import { buildLayerConfig } from "./layerDefs.js";
import {
  buildEtysLegend,
  buildGeneratorLegend,
  buildLineLegend,
  buildPlantLegend,
  compareEtysBoundaries,
  buildBmFuelLegend,
  setBmLegendVisible,
  setEtysLegendVisible,
  setGeneratorLegendVisible,
  setLineLegendVisible,
  setPlantLegendVisible,
} from "./legends.js";
import { attachLazyPopup, plantPropsForPopup, popupRows, turbinePropsForPopup } from "./popups.js";
import { loadLayerData, createLayerFromData } from "./sources/index.js";
import { fuelTypeOrder } from "./fuelTypes.js";
import {
  generatorSourceBucket,
  lineStyle,
  lineTypeBucket,
  plantMarkerStyle,
  plantPolygonStyle,
  plantSourceBucket,
  plantStatus,
  substationMarkerStyle,
  substationPolygonStyle,
  turbineMarkerStyle,
} from "./styles.js";
import { getLatLon, isPolygonGeometry } from "./utils.js";

export function createLayerManager(map, regionConfig, zoneFilter) {
  const config = {
    ...regionConfig,
    turbineMinZoom: regionConfig.turbineMinZoom ?? 9,
    bmuLookup: regionConfig.bmuLookup ?? null,
  };
  const LAYER_CONFIG = buildLayerConfig(config);
  const layerIds = config.layerIds || Object.keys(LAYER_CONFIG);

  const layerGroups = {};
  let destroyed = false;
  const layerCache = {};
  for (const id of layerIds) {
    layerGroups[id] = L.layerGroup();
    layerCache[id] = { loaded: false, loading: null, geoLayer: null, data: null, count: 0 };
  }
  if (layerGroups.plants) {
    layerGroups.plants.addTo(map);
  }

  const lineBucketGroups = {};
  const lineBucketVisibility = {};
  let lineWidthScale = 1;
  const gatedRequested = {};
  const plantBucketGroups = {};
  const plantBucketVisibility = {};
  // Plant lifecycle filter: operational + construction on, closed off by default.
  const plantStatusVisible = { operational: true, construction: true, closed: false };
  function setPlantStatusVisible(status, visible) {
    plantStatusVisible[status] = visible;
    rebuildFilterableLayers(zoneFilter.geometry);
  }
  function updatePlantStatusCounts() {
    const cache = layerCache.plants;
    if (!cache?.loaded || !cache.data) return;
    const counts = { operational: 0, construction: 0, closed: 0 };
    for (const feature of cache.data.features || []) {
      counts[plantStatus(feature.properties || {})] += 1;
    }
    for (const status of Object.keys(counts)) {
      const el = document.getElementById(`plant-status-count-${status}`);
      if (el) el.textContent = `(${counts[status].toLocaleString()})`;
    }
  }
  const generatorBucketVisibility = {};
  const etysBucketGroups = {};
  const etysBucketVisibility = {};
  let searchHighlight = null;

  function etysBoundaryBucketId(props) {
    return props.boundary_id || props.name || "unknown";
  }

  function scaledLineStyle(props) {
    const style = lineStyle(props);
    return {
      ...style,
      weight: style.weight ? style.weight * lineWidthScale : style.weight,
    };
  }

  function addGeometryAndMarkers(bucketGroup, features, layerConfig, filterGeometry = null) {
    const polygonFeatures = features.filter((feature) => isPolygonGeometry(feature.geometry));
    if (polygonFeatures.length) {
      const polygonLayer = L.geoJSON(
        { type: "FeatureCollection", features: polygonFeatures },
        {
          style: (feature) => layerConfig.polygonStyleFn(feature.properties || {}),
          onEachFeature: (feature, layer) => {
            const props = feature.properties || {};
            const popupProps = layerConfig.popupPropsFn ? layerConfig.popupPropsFn(props) : props;
            attachLazyPopup(layer, popupProps, layerConfig.popupKeys);
          },
        },
      );
      bucketGroup.addLayer(polygonLayer);
    }

    for (const feature of features) {
      const props = feature.properties || {};
      if (filterGeometry && layerConfig.filterable) {
        const latlon = getLatLon(props, feature);
        if (!latlon || !zoneFilter.pointInside(latlon[0], latlon[1], filterGeometry)) continue;
      }
      const latlon = getLatLon(props, feature);
      if (!latlon) continue;
      const marker = L.circleMarker(latlon, layerConfig.markerStyleFn(props));
      const popupProps = layerConfig.popupPropsFn ? layerConfig.popupPropsFn(props) : props;
      attachLazyPopup(marker, popupProps, layerConfig.popupKeys);
      bucketGroup.addLayer(marker);
    }
  }

  function createGeometryAndMarkerLayer(data, layerConfig, filterGeometry = null) {
    const container = L.featureGroup();
    addGeometryAndMarkers(container, data.features || [], layerConfig, filterGeometry);
    return container;
  }

  function createLineLayer(data, layerConfig) {
    const byBucket = new Map();
    for (const feature of data.features || []) {
      const bucket = lineTypeBucket(feature.properties || {});
      if (!byBucket.has(bucket)) byBucket.set(bucket, []);
      byBucket.get(bucket).push(feature);
    }

    const container = L.layerGroup();
    for (const bucket of Object.keys(lineBucketGroups)) {
      delete lineBucketGroups[bucket];
    }

    for (const bucket of LINE_TYPE_ORDER.filter((key) => byBucket.has(key))) {
      const bucketGroup = L.geoJSON(
        { type: "FeatureCollection", features: byBucket.get(bucket) },
        {
          style: (feature) => scaledLineStyle(feature.properties || {}),
          onEachFeature: (feature, layer) => {
            attachLazyPopup(layer, feature.properties || {}, layerConfig.popupKeys);
          },
        },
      );
      lineBucketGroups[bucket] = bucketGroup;
      lineBucketVisibility[bucket] = lineBucketVisibility[bucket] ?? true;
      if (lineBucketVisibility[bucket]) {
        container.addLayer(bucketGroup);
      }
    }

    return container;
  }

  function createPlantLayer(data, layerConfig, filterGeometry = null) {
    const byBucket = new Map();
    for (const feature of data.features || []) {
      const props = feature.properties || {};
      if (!plantStatusVisible[plantStatus(props)]) continue;  // open/construction/closed filter
      if (filterGeometry && layerConfig.filterable) {
        const latlon = getLatLon(props, feature);
        if (!latlon || !zoneFilter.pointInside(latlon[0], latlon[1], filterGeometry)) continue;
      }
      const bucket = plantSourceBucket(props);
      if (!byBucket.has(bucket)) byBucket.set(bucket, []);
      byBucket.get(bucket).push(feature);
    }

    const container = L.layerGroup();
    for (const bucket of Object.keys(plantBucketGroups)) {
      delete plantBucketGroups[bucket];
    }

    const fuelOrder = fuelTypeOrder();
    const orderedBuckets = [
      ...fuelOrder.filter((bucket) => byBucket.has(bucket)),
      ...[...byBucket.keys()].filter((bucket) => !fuelOrder.includes(bucket)).sort(),
    ];

    for (const bucket of orderedBuckets) {
      const bucketGroup = L.featureGroup();
      addGeometryAndMarkers(bucketGroup, byBucket.get(bucket), layerConfig, filterGeometry);
      plantBucketGroups[bucket] = bucketGroup;
      plantBucketVisibility[bucket] = plantBucketVisibility[bucket] ?? true;
      if (plantBucketVisibility[bucket]) {
        container.addLayer(bucketGroup);
      }
    }

    return container;
  }

  function createEtysBoundaryLayer(data, layerConfig) {
    const byBucket = new Map();
    for (const feature of data.features || []) {
      const bucket = etysBoundaryBucketId(feature.properties || {});
      if (!byBucket.has(bucket)) byBucket.set(bucket, []);
      byBucket.get(bucket).push(feature);
    }

    const container = L.layerGroup();
    for (const key of Object.keys(etysBucketGroups)) {
      delete etysBucketGroups[key];
    }

    const buckets = [...byBucket.keys()].sort(compareEtysBoundaries);
    for (const bucket of buckets) {
      const bucketGroup = L.geoJSON(
        { type: "FeatureCollection", features: byBucket.get(bucket) },
        {
          style: () => (layerConfig.styleFn ? layerConfig.styleFn() : undefined),
          onEachFeature: (feature, layer) => {
            const props = feature.properties || {};
            attachLazyPopup(layer, props, layerConfig.popupKeys);
            const label = props.name || props.boundary_id;
            if (label) {
              layer.bindTooltip(String(label), {
                permanent: true,
                direction: "center",
                className: "boundary-line-label",
              });
            }
          },
        },
      );
      etysBucketGroups[bucket] = bucketGroup;
      etysBucketVisibility[bucket] = etysBucketVisibility[bucket] ?? true;
      if (etysBucketVisibility[bucket]) {
        container.addLayer(bucketGroup);
      }
    }

    return container;
  }

  function filterLayerFeatures(features, layerConfig) {
    const sideFilter = layerConfig.sideFilter;
    return features.filter((feature) => {
      const props = feature.properties || {};
      if (sideFilter && String(props.side || "").toLowerCase() !== sideFilter) {
        return false;
      }
      if (zoneFilter.geometry && layerConfig.filterable) {
        const latlon = getLatLon(props, feature);
        return latlon && zoneFilter.pointInside(latlon[0], latlon[1], zoneFilter.geometry);
      }
      return true;
    });
  }

  // Fuel buckets present across whichever BM layers are currently loaded.
  function bmFuelBuckets() {
    const buckets = new Set();
    for (const key of ["bm_activity_bid", "bm_activity_offer"]) {
      const cache = layerCache[key];
      if (!cache?.loaded || !cache.data) continue;
      for (const feature of cache.data.features || []) {
        const bucket = feature.properties?.source_bucket;
        if (bucket) buckets.add(bucket);
      }
    }
    return [...buckets];
  }

  // The BM bids/offers layers share one fuel legend, shown when either is on.
  function syncBmLegend() {
    const bmOn = document.getElementById("toggle-bm_activity_bid")?.checked
      || document.getElementById("toggle-bm_activity_offer")?.checked;
    setBmLegendVisible(Boolean(bmOn));
    if (bmOn) buildBmFuelLegend(bmFuelBuckets());
  }

  function createPointMarker(latlng, feature, layerConfig) {
    const [latOffset = 0, lngOffset = 0] = layerConfig.markerOffset || [];
    const position = L.latLng(latlng.lat + latOffset, latlng.lng + lngOffset);
    const props = feature.properties || {};
    return L.circleMarker(position, layerConfig.styleFn(props));
  }

  function buildGeoJsonLayer(layerKey, data, layerConfig) {
    if (layerKey === "etys_network") return createEtysNetworkLayer(map, data);
    if (layerKey === "lines") {
      return createLineLayer(data, layerConfig);
    }
    if (layerKey === "etys_boundaries") {
      return createEtysBoundaryLayer(data, layerConfig);
    }
    if (layerKey === "plants") {
      return createPlantLayer(data, layerConfig, zoneFilter.geometry);
    }
    if (layerConfig.combinedLayer) {
      return createGeometryAndMarkerLayer(data, layerConfig, zoneFilter.geometry);
    }
    if (layerConfig.zoneLayer) {
      return zoneFilter.createZoneLayer(data, layerConfig.zoneLayer);
    }
    const features = filterLayerFeatures(data.features || [], layerConfig);
    return L.geoJSON(
      { type: "FeatureCollection", features },
      {
        style: layerConfig.styleFn
          ? (feature) => layerConfig.styleFn(feature.properties || {})
          : undefined,
        pointToLayer: layerConfig.pointLayer
          ? (feature, latlng) => createPointMarker(latlng, feature, layerConfig)
          : undefined,
        onEachFeature: (feature, layer) => {
          const props = feature.properties || {};
          const popupProps = layerConfig.popupPropsFn ? layerConfig.popupPropsFn(props) : props;
          attachLazyPopup(layer, popupProps, layerConfig.popupKeys);
          if (layerConfig.lineLabels) {
            const label = props.name || props.boundary_id;
            if (label) {
              layer.bindTooltip(String(label), {
                permanent: true,
                direction: "center",
                className: "boundary-line-label",
              });
            }
          }
        },
      },
    );
  }

  const geoJsonHelpers = {
    buildGeoJsonLayer,
    lineStyle: scaledLineStyle,
    lineWidthScale: () => lineWidthScale,
    turbineMarkerStyle,
    lineBucketGroups,
    lineBucketVisibility,
    generatorBucketVisibility,
    generatorSourceBucket,
  };

  function lineLegendOptions() {
    return {
      widthScale: lineWidthScale,
      onWidthScaleChange: setLineWidthScale,
    };
  }

  function syncLineBucketLayers() {
    if (LAYER_CONFIG.lines?.type === "pmtiles") return;
    const parent = layerCache.lines?.geoLayer;
    if (!parent || !document.getElementById("toggle-lines")?.checked) return;
    for (const [bucket, group] of Object.entries(lineBucketGroups)) {
      const visible = lineBucketVisibility[bucket] !== false;
      if (visible && !parent.hasLayer(group)) parent.addLayer(group);
      if (!visible && parent.hasLayer(group)) parent.removeLayer(group);
    }
  }

  function setLineBucketVisible(bucket, visible) {
    if (!lineBucketGroups[bucket]) return;
    lineBucketVisibility[bucket] = visible;
    if (LAYER_CONFIG.lines?.type === "pmtiles") {
      rebuildPmtilesLineLayer();
      return;
    }
    syncLineBucketLayers();
  }

  async function setLineWidthScale(scale) {
    if (!Number.isFinite(scale) || scale <= 0) return;
    lineWidthScale = Math.max(0.5, Math.min(4, scale));
    if (!layerCache.lines?.loaded) return;
    if (LAYER_CONFIG.lines?.type === "pmtiles") {
      await rebuildPmtilesLineLayer();
      return;
    }
    const cache = layerCache.lines;
    layerGroups.lines.clearLayers();
    const geoLayer = createLineLayer(cache.data, LAYER_CONFIG.lines);
    layerGroups.lines.addLayer(geoLayer);
    cache.geoLayer = geoLayer;
    buildLineLegend(lineBucketGroups, lineBucketVisibility, setLineBucketVisible, lineLegendOptions());
    if (document.getElementById("toggle-lines")?.checked) {
      map.addLayer(layerGroups.lines);
      syncLineBucketLayers();
      setLineLegendVisible(true, lineBucketGroups);
    }
  }

  async function rebuildPmtilesLineLayer() {
    const cache = layerCache.lines;
    const layerConfig = LAYER_CONFIG.lines;
    if (!cache?.loaded || layerConfig?.type !== "pmtiles") return;
    try {
      layerGroups.lines.clearLayers();
      const geoLayer = await createLayerFromData(
        "lines",
        { type: "pmtiles", url: layerConfig.url, config: layerConfig },
        layerConfig,
        geoJsonHelpers,
      );
      layerGroups.lines.addLayer(geoLayer);
      cache.geoLayer = geoLayer;
      if (document.getElementById("toggle-lines")?.checked) {
        map.addLayer(layerGroups.lines);
      }
    } catch (error) {
      console.error("Failed to rebuild PMTiles line layer", error);
    }
  }

  async function rebuildPmtilesGeneratorLayer() {
    const cache = layerCache.generators;
    const layerConfig = LAYER_CONFIG.generators;
    if (!cache?.loaded || layerConfig?.type !== "pmtiles") return;
    try {
      layerGroups.generators.clearLayers();
      const geoLayer = await createLayerFromData(
        "generators",
        { type: "pmtiles", url: layerConfig.url, config: layerConfig },
        layerConfig,
        geoJsonHelpers,
      );
      layerGroups.generators.addLayer(geoLayer);
      cache.geoLayer = geoLayer;
      if (document.getElementById("toggle-generators")?.checked) {
        syncZoomGatedLayerOnMap("generators");
      }
    } catch (error) {
      console.error("Failed to rebuild PMTiles generator layer", error);
    }
  }

  function setGeneratorBucketVisible(bucket, visible) {
    generatorBucketVisibility[bucket] = visible;
    rebuildPmtilesGeneratorLayer();
  }

  function setAllGeneratorBuckets(visible, setStatus) {
    for (const bucket of fuelTypeOrder()) {
      generatorBucketVisibility[bucket] = visible;
    }
    buildGeneratorLegend(generatorBucketVisibility, setGeneratorBucketVisible, generatorLegendOptions(setStatus));
    rebuildPmtilesGeneratorLayer();
  }

  function generatorLegendOptions(setStatus) {
    return {
      onSelectAll: () => setAllGeneratorBuckets(true, setStatus),
      onClearAll: () => setAllGeneratorBuckets(false, setStatus),
    };
  }

  function syncPlantBucketLayers() {
    const parent = layerCache.plants?.geoLayer;
    if (!parent || !document.getElementById("toggle-plants")?.checked) return;
    for (const [bucket, group] of Object.entries(plantBucketGroups)) {
      const visible = plantBucketVisibility[bucket] !== false;
      if (visible && !parent.hasLayer(group)) parent.addLayer(group);
      if (!visible && parent.hasLayer(group)) parent.removeLayer(group);
    }
  }

  function setPlantBucketVisible(bucket, visible) {
    if (!plantBucketGroups[bucket]) return;
    plantBucketVisibility[bucket] = visible;
    syncPlantBucketLayers();
  }

  function clearAllPlantBuckets(setStatus) {
    for (const bucket of Object.keys(plantBucketGroups)) {
      plantBucketVisibility[bucket] = false;
    }
    syncPlantBucketLayers();
    buildPlantLegend(
      plantBucketGroups,
      plantBucketVisibility,
      setPlantBucketVisible,
      plantLegendOptions(setStatus),
    );
  }

  function syncEtysBucketLayers() {
    const parent = layerCache.etys_boundaries?.geoLayer;
    if (!parent || !document.getElementById("toggle-etys_boundaries")?.checked) return;
    for (const [bucket, group] of Object.entries(etysBucketGroups)) {
      const visible = etysBucketVisibility[bucket] !== false;
      if (visible && !parent.hasLayer(group)) parent.addLayer(group);
      if (!visible && parent.hasLayer(group)) parent.removeLayer(group);
    }
  }

  function setEtysBucketVisible(bucket, visible) {
    if (!etysBucketGroups[bucket]) return;
    etysBucketVisibility[bucket] = visible;
    syncEtysBucketLayers();
  }

  function setAllEtysBuckets(visible, setStatus) {
    for (const bucket of Object.keys(etysBucketGroups)) {
      etysBucketVisibility[bucket] = visible;
    }
    syncEtysBucketLayers();
    buildEtysLegend(
      etysBucketGroups,
      etysBucketVisibility,
      setEtysBucketVisible,
      etysLegendOptions(setStatus),
    );
  }

  function etysLegendOptions(setStatus) {
    return {
      onSelectAll: () => setAllEtysBuckets(true, setStatus),
      onClearAll: () => setAllEtysBuckets(false, setStatus),
    };
  }

  function layerMinZoom(id) {
    const mz = LAYER_CONFIG[id]?.minZoom;
    if (Number.isFinite(mz)) return mz;
    if (id === "turbines") return config.turbineMinZoom;
    return null;
  }

  function isZoomGated(id) {
    return layerMinZoom(id) != null;
  }

  function zoomOkFor(id) {
    const mz = layerMinZoom(id);
    return mz == null || map.getZoom() >= mz;
  }

  function syncZoomGatedLayerOnMap(id) {
    if (!gatedRequested[id] || !layerCache[id]?.loaded) return;
    if (zoomOkFor(id)) {
      if (!map.hasLayer(layerGroups[id])) map.addLayer(layerGroups[id]);
    } else if (map.hasLayer(layerGroups[id])) {
      map.removeLayer(layerGroups[id]);
    }
  }

  function syncZoomGatedLayers() {
    for (const id of layerIds) {
      if (isZoomGated(id)) syncZoomGatedLayerOnMap(id);
    }
  }

  function syncTurbineCheckboxes(enabled) {
    gatedRequested.turbines = enabled;
    const main = document.getElementById("toggle-turbines");
    if (main) main.checked = enabled;
  }

  function plantLegendOptions(setStatus) {
    return {
      onClearAll: () => clearAllPlantBuckets(setStatus),
    };
  }

  function turbineZoomOk() {
    return zoomOkFor("turbines");
  }

  function syncTurbineLayerOnMap() {
    syncZoomGatedLayerOnMap("turbines");
  }

  function setStatusFromRebuild(message, isError = false) {
    const statusEl = document.getElementById("status");
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.classList.toggle("error", isError);
  }

  function rebuildFilterableLayers(filterGeometry) {
    for (const key of ["plants", "turbines"]) {
      if (!layerIds.includes(key)) continue;
      const cache = layerCache[key];
      if (!cache.loaded || !cache.data) continue;
      const layerConfig = LAYER_CONFIG[key];
      layerGroups[key].clearLayers();
      const geoLayer = key === "plants"
        ? createPlantLayer(cache.data, layerConfig, filterGeometry)
        : L.geoJSON(
          {
            type: "FeatureCollection",
            features: (cache.data.features || []).filter((feature) => {
              const props = feature.properties || {};
              const latlon = getLatLon(props, feature);
              return latlon && zoneFilter.pointInside(latlon[0], latlon[1], filterGeometry);
            }),
          },
          {
            pointToLayer: (feature, latlng) => L.circleMarker(latlng, layerConfig.styleFn(feature.properties || {})),
            onEachFeature: (feature, layer) => {
              const props = feature.properties || {};
              const popupProps = layerConfig.popupPropsFn ? layerConfig.popupPropsFn(props) : props;
              attachLazyPopup(layer, popupProps, layerConfig.popupKeys);
            },
          },
        );
      layerGroups[key].addLayer(geoLayer);
      cache.geoLayer = geoLayer;
      if (key === "plants") {
        buildPlantLegend(plantBucketGroups, plantBucketVisibility, setPlantBucketVisible, plantLegendOptions(setStatusFromRebuild));
        syncPlantBucketLayers();
      }
      if (document.getElementById(`toggle-${key}`)?.checked) {
        if (key === "turbines") syncTurbineLayerOnMap();
        else map.addLayer(layerGroups[key]);
      }
    }
  }

  function restoreFilterableLayers() {
    for (const key of ["plants", "turbines"]) {
      if (!layerIds.includes(key)) continue;
      const cache = layerCache[key];
      if (!cache.loaded || !cache.data) continue;
      const layerConfig = LAYER_CONFIG[key];
      layerGroups[key].clearLayers();
      const geoLayer = key === "plants"
        ? createPlantLayer(cache.data, layerConfig)
        : L.geoJSON(cache.data, {
          pointToLayer: (feature, latlng) => L.circleMarker(latlng, layerConfig.styleFn(feature.properties || {})),
          onEachFeature: (feature, layer) => {
            const props = feature.properties || {};
            const popupProps = layerConfig.popupPropsFn ? layerConfig.popupPropsFn(props) : props;
            attachLazyPopup(layer, popupProps, layerConfig.popupKeys);
          },
        });
      layerGroups[key].addLayer(geoLayer);
      cache.geoLayer = geoLayer;
      if (key === "plants") {
        buildPlantLegend(plantBucketGroups, plantBucketVisibility, setPlantBucketVisible, plantLegendOptions(setStatusFromRebuild));
        syncPlantBucketLayers();
      }
      if (document.getElementById(`toggle-${key}`)?.checked) {
        if (key === "turbines") syncTurbineLayerOnMap();
        else map.addLayer(layerGroups[key]);
      }
    }
  }

  async function loadLayer(layerKey, setStatus) {
    const cache = layerCache[layerKey];
    if (!cache) return null;
    if (cache.loaded) return cache.geoLayer;
    if (cache.loading) return cache.loading;

    const layerConfig = LAYER_CONFIG[layerKey];
    cache.loading = (async () => {
      setStatus(`Loading ${layerConfig.label}…`);
      const payload = await loadLayerData(layerConfig);
      if (destroyed) return null;
      const geoLayer = await createLayerFromData(layerKey, payload, layerConfig, geoJsonHelpers);
      if (destroyed) return null;
      layerGroups[layerKey].addLayer(geoLayer);
      if (document.getElementById(`toggle-${layerKey}`)?.checked) {
        if (isZoomGated(layerKey)) {
          syncZoomGatedLayerOnMap(layerKey);
        } else {
          map.addLayer(layerGroups[layerKey]);
        }
      }
      cache.geoLayer = geoLayer;
      if (payload.type === "geojson") {
        cache.data = payload.data;
        cache.count = payload.data.features?.length ?? geoLayer.getLayers?.().length ?? 0;
      } else {
        cache.data = null;
        cache.count = 0;
      }
      cache.loaded = true;
      cache.loading = null;
      if (layerKey === "lines") {
        buildLineLegend(lineBucketGroups, lineBucketVisibility, setLineBucketVisible, lineLegendOptions());
        setLineLegendVisible(document.getElementById("toggle-lines")?.checked, lineBucketGroups);
      }
      if (layerKey === "plants") {
        buildPlantLegend(plantBucketGroups, plantBucketVisibility, setPlantBucketVisible, plantLegendOptions(setStatus));
        setPlantLegendVisible(document.getElementById("toggle-plants")?.checked, plantBucketGroups);
        updatePlantStatusCounts();
      }
      if (layerKey === "etys_boundaries") {
        buildEtysLegend(etysBucketGroups, etysBucketVisibility, setEtysBucketVisible, etysLegendOptions(setStatus));
        setEtysLegendVisible(document.getElementById("toggle-etys_boundaries")?.checked, etysBucketGroups);
      }
      if (layerKey === "generators") {
        buildGeneratorLegend(generatorBucketVisibility, setGeneratorBucketVisible, generatorLegendOptions(setStatus));
        setGeneratorLegendVisible(document.getElementById("toggle-generators")?.checked);
      }
      if (layerKey === "bm_activity_bid" || layerKey === "bm_activity_offer") {
        syncBmLegend();
      }
      return geoLayer;
    })();

    try {
      return await cache.loading;
    } finally {
      cache.loading = null;
    }
  }

  function updateStatusMessage(setStatus) {
    const parts = [];
    const network = layerCache.etys_network?.data?.metadata;
    if (network) parts.push(`${network.mapped_edges.toLocaleString()} ETYS connections at ${network.mapped_sites} sites`);
    if (layerCache.plants?.loaded) parts.push(`${layerCache.plants.count.toLocaleString()} BMU-mapped sites`);
    if (layerCache.turbines?.loaded) {
      const zoomNote = turbineZoomOk() ? "" : ` (zoom ${config.turbineMinZoom}+ to show)`;
      const turbineCount = LAYER_CONFIG.turbines?.type === "pmtiles"
        ? "tiled wind turbines"
        : `${layerCache.turbines.count.toLocaleString()} wind turbines`;
      parts.push(`${turbineCount}${zoomNote}`);
    }
    if (layerCache.lines?.loaded) {
      const lineCount = LAYER_CONFIG.lines?.type === "pmtiles"
        ? "tiled transmission lines"
        : `${layerCache.lines.count.toLocaleString()} transmission lines`;
      parts.push(lineCount);
    }
    if (layerCache.substations?.loaded) parts.push(`${layerCache.substations.count.toLocaleString()} substations`);
    if (layerCache.generators?.loaded) parts.push(`${layerCache.generators.count.toLocaleString()} generators (all scales)`);
    if (layerCache.converters?.loaded) parts.push(`${layerCache.converters.count.toLocaleString()} converter stations`);
    if (layerCache.equipment?.loaded) parts.push(`${layerCache.equipment.count.toLocaleString()} equipment`);
    if (layerCache.towers?.loaded) {
      const zoomNote = zoomOkFor("towers") ? "" : ` (zoom ${layerMinZoom("towers")}+ to show)`;
      const towerCount = LAYER_CONFIG.towers?.type === "pmtiles"
        ? "tiled towers"
        : `${layerCache.towers.count.toLocaleString()} towers`;
      parts.push(`${towerCount}${zoomNote}`);
    }
    if (layerCache.dno?.loaded) parts.push(`${layerCache.dno.count.toLocaleString()} DNO areas`);
    if (layerCache.gsp?.loaded) parts.push(`${layerCache.gsp.count.toLocaleString()} GSP regions`);
    if (layerCache.generation_zones?.loaded) {
      parts.push(`${layerCache.generation_zones.count.toLocaleString()} TNUoS generation zones`);
    }
    if (layerCache.etys_boundaries?.loaded) {
      parts.push(`${layerCache.etys_boundaries.count.toLocaleString()} ETYS boundaries`);
    }
    if (layerCache.bm_activity_bid?.loaded) {
      parts.push(`${layerCache.bm_activity_bid.count.toLocaleString()} BM bids`);
    }
    if (layerCache.bm_activity_offer?.loaded) {
      parts.push(`${layerCache.bm_activity_offer.count.toLocaleString()} BM offers`);
    }
    if (zoneFilter.label) parts.push(`filter: ${zoneFilter.label}`);
    if (!parts.length) {
      setStatus("Ready. Enable a layer to load data.");
      return;
    }
    setStatus(`Loaded ${parts.join(", ")}.`);
  }

  function resultTitle(layerKey, props) {
    return props.name
      || props.gsp_name
      || props.gsp_id
      || props.operator
      || props.osm_id
      || layerKey;
  }

  function resultSubtitle(layerKey, props) {
    const label = LAYER_CONFIG[layerKey]?.label || layerKey;
    const details = [
      props.operator,
      props.bmu_id,
      props.ngc_bmu_id,
      props.gsp_id,
      props.zone_id,
      props.tariff_zone,
      props.boundary_id,
      props.dno_operator,
    ].filter(Boolean);
    return details.length ? `${label} · ${details.join(" · ")}` : label;
  }

  function searchableText(layerKey, props) {
    const keys = [
      "name",
      "operator",
      "osm_id",
      "bmu_id",
      "ngc_bmu_id",
      "gsp_id",
      "gsp_name",
      "zone_id",
      "zone_name",
      "tariff_zone",
      "boundary_id",
      "dno_name",
      "dno_operator",
      "substation",
      "ref",
      "site_code",
      "nodes",
      "node_1_label",
      "node_2_label",
    ];
    return [
      LAYER_CONFIG[layerKey]?.label,
      ...keys.map((key) => props[key]),
    ].filter(Boolean).join(" ").toLowerCase();
  }

  function searchFeatures(query) {
    const needle = query.trim().toLowerCase();
    if (needle.length < 2) return [];
    const results = [];
    for (const layerKey of layerIds) {
      const cache = layerCache[layerKey];
      if (!cache?.data?.features?.length) continue;
      for (const feature of cache.data.features) {
        const rawProps = feature.properties || {};
        const props = layerKey === "plants" && LAYER_CONFIG[layerKey]?.popupPropsFn
          ? LAYER_CONFIG[layerKey].popupPropsFn(rawProps)
          : rawProps;
        if (!searchableText(layerKey, props).includes(needle)) continue;
        results.push({
          layerKey,
          feature,
          props,
          title: resultTitle(layerKey, props),
          subtitle: resultSubtitle(layerKey, props),
        });
        if (results.length >= 20) return results;
      }
    }
    return results;
  }

  function focusSearchResult(result) {
    if (result.layerKey === "etys_network") {
      map.addLayer(layerGroups.etys_network);
      const checkbox = document.getElementById("toggle-etys_network");
      if (checkbox) checkbox.checked = true;
      layerCache.etys_network.geoLayer.focusFeature(result.props.id);
      return;
    }
    if (searchHighlight) {
      map.removeLayer(searchHighlight);
      searchHighlight = null;
    }
    const layerConfig = LAYER_CONFIG[result.layerKey] || {};
    const latlon = getLatLon(result.props, result.feature);
    const popupHtml = popupRows(result.props, layerConfig.popupKeys || [], result.feature);

    if (latlon) {
      map.setView(latlon, Math.max(map.getZoom(), 14));
      searchHighlight = L.circleMarker(latlon, {
        radius: 9,
        color: "#ff6f00",
        weight: 3,
        fillColor: "#ffffff",
        fillOpacity: 0.4,
      }).addTo(map);
      searchHighlight.bindPopup(popupHtml).openPopup();
      return;
    }

    const layer = L.geoJSON(result.feature);
    const bounds = layer.getBounds();
    if (bounds?.isValid()) {
      map.fitBounds(bounds.pad(0.1));
      searchHighlight = L.geoJSON(result.feature, {
        style: {
          color: "#ff6f00",
          weight: 4,
          fillOpacity: 0.12,
        },
      }).addTo(map);
      searchHighlight.bindPopup(popupHtml).openPopup();
    }
  }

  async function setLayerEnabled(layerKey, enabled, setStatus) {
    const checkbox = document.getElementById(`toggle-${layerKey}`);
    try {
      if (isZoomGated(layerKey)) {
        gatedRequested[layerKey] = enabled;
      }
      if (enabled) {
        await loadLayer(layerKey, setStatus);
        if (destroyed || (checkbox && !checkbox.checked)) return;
        if (isZoomGated(layerKey)) {
          syncZoomGatedLayerOnMap(layerKey);
        } else {
          map.addLayer(layerGroups[layerKey]);
        }
        if (layerKey === "lines") {
          syncLineBucketLayers();
          setLineLegendVisible(true, lineBucketGroups);
        }
        if (layerKey === "plants") {
          syncPlantBucketLayers();
          setPlantLegendVisible(true, plantBucketGroups);
        }
        if (layerKey === "etys_boundaries") {
          syncEtysBucketLayers();
          setEtysLegendVisible(true, etysBucketGroups);
        }
        if (layerKey === "generators") {
          setGeneratorLegendVisible(true);
        }
      } else {
        map.removeLayer(layerGroups[layerKey]);
        if (layerKey === "lines") setLineLegendVisible(false, lineBucketGroups);
        if (layerKey === "plants") setPlantLegendVisible(false, plantBucketGroups);
        if (layerKey === "etys_boundaries") setEtysLegendVisible(false, etysBucketGroups);
        if (layerKey === "generators") setGeneratorLegendVisible(false);
      }
      if (layerKey === "bm_activity_bid" || layerKey === "bm_activity_offer") {
        syncBmLegend();
      }
      if (layerKey === "turbines") {
        syncTurbineCheckboxes(enabled);
      }
      updateStatusMessage(setStatus);
    } catch (error) {
      if (destroyed) return;
      console.error(error);
      if (checkbox) checkbox.checked = false;
      if (layerKey === "turbines") syncTurbineCheckboxes(false);
      setStatus(`Failed to load ${LAYER_CONFIG[layerKey]?.label || layerKey}: ${error.message}`, true);
    }
  }

  function clearSelection() {
    if (searchHighlight) map.removeLayer(searchHighlight);
    searchHighlight = null;
    layerCache.etys_network?.geoLayer?.clearSelection?.();
  }

  function destroy() {
    destroyed = true;
    if (searchHighlight) map.removeLayer(searchHighlight);
    setLineLegendVisible(false, lineBucketGroups);
    setPlantLegendVisible(false, plantBucketGroups);
    setEtysLegendVisible(false, etysBucketGroups);
    setGeneratorLegendVisible(false);
    for (const id of layerIds) {
      map.removeLayer(layerGroups[id]);
      layerGroups[id].clearLayers();
    }
  }

  return {
    layerIds,
    layerCache,
    layerGroups,
    LAYER_CONFIG,
    loadLayer,
    setLayerEnabled,
    syncTurbineLayerOnMap,
    syncZoomGatedLayers,
    updateStatusMessage,
    searchFeatures,
    focusSearchResult,
    clearSelection,
    rebuildFilterableLayers,
    restoreFilterableLayers,
    setPlantStatusVisible,
    destroy,
  };
}
