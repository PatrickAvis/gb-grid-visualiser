import { escapeHtml, parseCapacityToMw } from "./utils.js";
import { plantCapacityMw } from "./styles.js";

const POPUP_KEY_LABELS = {
  bmu_id: "BMU",
  ngc_bmu_id: "NGC BMU ID",
  bmu_type: "BMU type",
  connection_site: "Connection site",
  host_to: "Transmission owner",
  connected_capacity_mw: "Connected capacity",
  bmu_count: "Connected BMUs",
  connected_bmus: "BMUs",
  connected_plants: "Plants",
  plant_name: "Plant",
  side: "Side",
  volume_mwh: "Volume (MWh)",
  abs_volume_mwh: "Abs volume (MWh)",
  price_gbp_mwh: "Price (£/MWh)",
  bid_offer_pair_id: "Bid-offer pair",
  action_count: "Actions",
  settlement_date: "Settlement date",
  settlement_period: "Settlement period",
  start_time: "Start time",
  created_datetime: "Published",
};

function esriWorldImageryPreview(lat, lon) {
  const delta = 0.003;
  const bbox = [
    lon - delta,
    lat - delta,
    lon + delta,
    lat + delta,
  ].join(",");
  const src = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
    + `?bbox=${encodeURIComponent(bbox)}`
    + "&bboxSR=4326&imageSR=4326"
    + "&size=260,160"
    + "&format=jpg"
    + "&f=image";
  return `<figure class="satellite-preview">
    <img src="${src}" alt="Esri World Imagery preview" loading="lazy" />
    <figcaption>Satellite imagery &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community</figcaption>
  </figure>`;
}

export function plantPropsForPopup(props, bmuLookup = null) {
  const mw = plantCapacityMw(props);
  const bmu = bmuLookup ? bmuLookup(props) : {};
  return {
    ...props,
    ...bmu,
    capacity_mw: mw != null ? `${mw.toFixed(1)} MW` : undefined,
  };
}

export function turbinePropsForPopup(props) {
  const mw = props.capacity_mw != null && props.capacity_mw !== ""
    ? Number(props.capacity_mw)
    : parseCapacityToMw(props["generator:output:electricity"]);
  return {
    ...props,
    capacity_mw: mw != null && !Number.isNaN(mw) ? `${mw.toFixed(2)} MW` : undefined,
    height_m: props.height_m != null && props.height_m !== "" ? `${props.height_m} m` : undefined,
    rotor_diameter_m: props.rotor_diameter_m != null && props.rotor_diameter_m !== ""
      ? `${props.rotor_diameter_m} m`
      : undefined,
  };
}

export function generatorPropsForPopup(props) {
  const mw = props.capacity_mw != null && props.capacity_mw !== ""
    ? Number(props.capacity_mw)
    : parseCapacityToMw(props["generator:output:electricity"]);
  return {
    ...props,
    capacity_mw: mw != null && !Number.isNaN(mw) ? `${mw.toFixed(2)} MW` : undefined,
  };
}

export function popupRows(props, preferredKeys) {
  const rows = [];
  const seen = new Set();
  for (const key of preferredKeys) {
    if (props[key] == null || props[key] === "") continue;
    rows.push([key, props[key]]);
    seen.add(key);
  }
  for (const [key, value] of Object.entries(props)) {
    if (seen.has(key) || value == null || value === "") continue;
    if (key === "geometry" || key.startsWith("bbox")) continue;
    rows.push([key, value]);
  }
  const lat = Number(props.latitude);
  const lon = Number(props.longitude);
  const hasCoords = Number.isFinite(lat) && Number.isFinite(lon);
  const imageryPreview = hasCoords ? esriWorldImageryPreview(lat, lon) : "";
  const satelliteLink = hasCoords
    ? `<p class="popup-actions"><a href="https://www.google.com/maps/@?api=1&map_action=map&center=${encodeURIComponent(`${lat},${lon}`)}&zoom=18&basemap=satellite" target="_blank" rel="noopener noreferrer">Open Google satellite view</a></p>`
    : "";
  if (!rows.length) return `${imageryPreview}<em>No properties</em>${satelliteLink}`;
  return `${imageryPreview}<table class="popup-table">${rows
    .slice(0, 12)
    .map(([key, value]) => {
      const label = POPUP_KEY_LABELS[key] || key;
      return `<tr><th>${escapeHtml(label)}</th><td>${escapeHtml(value)}</td></tr>`;
    })
    .join("")}</table>${satelliteLink}`;
}

export function attachLazyPopup(layer, props, preferredKeys) {
  layer.on("click", function handleClick() {
    if (!this.getPopup()) {
      this.bindPopup(popupRows(props, preferredKeys));
    }
    this.openPopup();
  });
}
