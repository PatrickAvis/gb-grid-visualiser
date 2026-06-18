const CATALOG_URL = "../data/catalog.json";
const STORAGE_KEY = "powerMapRegion";

export async function loadCatalog() {
  const response = await fetch(CATALOG_URL);
  if (!response.ok) {
    throw new Error(`Failed to load catalog: ${response.status}`);
  }
  return response.json();
}

export function resolveRegionId(catalog) {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get("region");
  if (fromUrl && catalog.regions[fromUrl]) {
    return fromUrl;
  }
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored && catalog.regions[stored]) {
    return stored;
  }
  return catalog.defaultRegion || "uk";
}

export function persistRegionId(regionId) {
  localStorage.setItem(STORAGE_KEY, regionId);
  const url = new URL(window.location.href);
  url.searchParams.set("region", regionId);
  window.history.replaceState({}, "", url);
}

export function resolveDataUrl(relPath) {
  return `../data/${relPath}`;
}

export function buildRegionConfig(catalog, regionId) {
  const region = catalog.regions[regionId];
  if (!region) {
    throw new Error(`Unknown region: ${regionId}`);
  }
  const layers = {};
  for (const [layerId, layer] of Object.entries(region.layers || {})) {
    layers[layerId] = {
      ...layer,
      id: layerId,
      url: resolveDataUrl(layer.path),
    };
  }
  const turbineLayer = region.layers?.turbines;
  const plantBmuMapPath = region.plantBmuMap;
  const bmuConnectionSitesPath = region.bmuConnectionSites;
  return {
    regionId,
    title: region.title,
    parent: region.parent,
    children: region.children || [],
    bounds: region.bounds,
    layers,
    layerIds: Object.keys(layers),
    turbineMinZoom: turbineLayer?.minZoom ?? 9,
    plantBmuMapUrl: plantBmuMapPath ? resolveDataUrl(plantBmuMapPath) : null,
    bmuConnectionSitesUrl: bmuConnectionSitesPath ? resolveDataUrl(bmuConnectionSitesPath) : null,
  };
}

export function listSelectableRegions(catalog) {
  const entries = Object.entries(catalog.regions);
  const childIds = new Set();
  for (const [, region] of entries) {
    for (const child of region.children || []) {
      childIds.add(child);
    }
  }
  return entries
    .filter(([id, region]) => {
      const hasLayers = Object.keys(region.layers || {}).length > 0;
      const isParentOnly = (region.children?.length ?? 0) > 0 && !hasLayers;
      return hasLayers && !isParentOnly;
    })
    .map(([id, region]) => ({
      id,
      title: region.title,
      parent: region.parent,
      group: region.parent || id,
    }))
    .sort((a, b) => a.title.localeCompare(b.title));
}

export function groupedRegionOptions(selectable) {
  const groups = new Map();
  for (const item of selectable) {
    const key = item.parent || "other";
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key).push(item);
  }
  return groups;
}
