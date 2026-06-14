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

function aggregateMapEntries(entries) {
  if (!entries?.length) {
    return {};
  }
  return {
    bmu_id: joinUnique(entries.map((row) => row.bmu_id)),
    ngc_bmu_id: joinUnique(entries.map((row) => row.ngc_bmu_id)),
    bmu_type: joinUnique(entries.map((row) => row.bmu_type)),
  };
}

export async function loadPlantBmuMap(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to load plant BMU map: ${response.status}`);
  }
  const payload = await response.json();
  const entries = Array.isArray(payload) ? payload : payload.entries || [];
  return createPlantBmuLookup(entries);
}

export function createPlantBmuLookup(entries) {
  const byOsmId = new Map();
  const byName = new Map();

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
      return aggregateMapEntries(byOsmId.get(osmId));
    }
    const nameKey = normalizePlantName(props.name);
    if (nameKey && byName.has(nameKey)) {
      return aggregateMapEntries(byName.get(nameKey));
    }
    return {};
  };
}
