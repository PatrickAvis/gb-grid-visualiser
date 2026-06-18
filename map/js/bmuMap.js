function normalizePlantName(name) {
  if (!name) return "";
  return String(name)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/ power station$/, "")
    .replace(/ wind farm$/, "")
    .replace(/ solar farm$/, "")
    .replace(/ solar park$/, "")
    .replace(/ battery storage$/, "")
    .replace(/ bess$/, "");
}

// OSM ids are joined on their numeric part only: the link table uses the
// canonical "way/123" / "relation/123" form, but exported site GeoJSON often
// stores bare ids ("123") when the export source lacks an element type. Manual
// ids ("manual/...") have no OSM prefix and are matched as-is.
function normalizeOsmId(value) {
  if (value == null) return "";
  return String(value).trim().replace(/^(way|relation|node)\//, "");
}

function joinUnique(values) {
  const seen = [];
  for (const value of values) {
    const text = value == null ? "" : String(value).trim();
    if (text && !seen.includes(text)) {
      seen.push(text);
    }
  }
  return seen.length ? seen.join("; ") : undefined;
}

function aggregateMapEntries(entries, connectionByBmu) {
  if (!entries?.length) {
    return {};
  }
  const result = {
    bmu_id: joinUnique(entries.map((row) => row.bmu_id)),
    ngc_bmu_id: joinUnique(entries.map((row) => row.ngc_bmu_id)),
    bmu_type: joinUnique(entries.map((row) => row.bmu_type)),
  };
  if (connectionByBmu?.size) {
    const sites = [];
    const hosts = [];
    for (const row of entries) {
      const key = row.bmu_id == null ? "" : String(row.bmu_id).trim().toUpperCase();
      const conn = key && connectionByBmu.get(key);
      if (conn) {
        sites.push(conn.connection_site);
        hosts.push(conn.host_to);
      }
    }
    result.connection_site = joinUnique(sites);
    result.host_to = joinUnique(hosts);
  }
  return result;
}

async function fetchEntries(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to load ${url}: ${response.status}`);
  }
  const payload = await response.json();
  return Array.isArray(payload) ? payload : payload.entries || [];
}

export async function loadPlantBmuMap(url, connectionSitesUrl = null) {
  const entries = await fetchEntries(url);
  let connections = [];
  if (connectionSitesUrl) {
    try {
      connections = await fetchEntries(connectionSitesUrl);
    } catch (error) {
      console.warn("BMU connection sites not loaded:", error);
    }
  }
  return createPlantBmuLookup(entries, connections);
}

export function createPlantBmuLookup(entries, connectionEntries = []) {
  const byOsmId = new Map();
  const byName = new Map();
  const connectionByBmu = new Map();

  for (const conn of connectionEntries) {
    const key = conn.bmu_id == null ? "" : String(conn.bmu_id).trim().toUpperCase();
    if (key) {
      connectionByBmu.set(key, conn);
    }
  }

  for (const row of entries) {
    const osmId = normalizeOsmId(row.osm_id);
    if (osmId) {
      if (!byOsmId.has(osmId)) {
        byOsmId.set(osmId, []);
      }
      byOsmId.get(osmId).push(row);
    }
    const nameKey = normalizePlantName(row.plant_name);
    if (nameKey) {
      if (!byName.has(nameKey)) {
        byName.set(nameKey, []);
      }
      byName.get(nameKey).push(row);
    }
  }

  return function lookupBmu(props = {}) {
    const osmId = normalizeOsmId(props.osm_id);
    if (osmId && byOsmId.has(osmId)) {
      return aggregateMapEntries(byOsmId.get(osmId), connectionByBmu);
    }
    const nameKey = normalizePlantName(props.name);
    if (nameKey && byName.has(nameKey)) {
      return aggregateMapEntries(byName.get(nameKey), connectionByBmu);
    }
    return {};
  };
}
