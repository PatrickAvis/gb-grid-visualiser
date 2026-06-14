import {
  CONVERTER_COLOR,
  LINE_TYPE_COLORS,
  PLANT_CAP_REF_MW,
  PLANT_MARKER_FALLBACK_RADIUS,
  PLANT_MARKER_MAX_RADIUS,
  PLANT_MARKER_MIN_RADIUS,
  POWER_EQUIPMENT_COLORS,
  SUBSTATION_COLORS,
  TOWER_COLOR,
} from "./constants.js";
import { bucketFuelProperties, bucketFuelSource, fuelTypeColor, hasFuelType } from "./fuelTypes.js";
import { parseCapacityToMw, parseVoltageKv } from "./utils.js";

const DNO_FILL_COLORS = [
  "#8e24aa",
  "#3949ab",
  "#1e88e5",
  "#00897b",
  "#43a047",
  "#c0ca33",
  "#fdd835",
  "#fb8c00",
  "#f4511e",
  "#6d4c41",
  "#546e7a",
  "#d81b60",
  "#5e35b1",
  "#039be5",
];

const GENERATION_FILL_COLORS = [
  "#5c6bc0",
  "#7e57c2",
  "#ab47bc",
  "#ec407a",
  "#ef5350",
  "#ff7043",
  "#ffa726",
  "#ffca28",
  "#9ccc65",
  "#66bb6a",
  "#26a69a",
  "#26c6da",
  "#42a5f5",
  "#5c6bc0",
  "#8d6e63",
  "#78909c",
  "#7cb342",
  "#00acc1",
  "#8e24aa",
  "#3949ab",
  "#00897b",
  "#c2185b",
  "#d84315",
  "#f9a825",
  "#558b2f",
  "#039be5",
  "#6a1b9a",
];

const DNO_ZONE_COLORS = {
  // Chosen against the DNO adjacency graph to keep neighbouring areas distinct.
  10: "#009e73", // UKPN East England
  11: "#d55e00", // NGED East Midlands
  12: "#56b4e9", // UKPN London
  13: "#ee6677", // SPEN North Wales, Merseyside and Cheshire
  14: "#0066cc", // NGED West Midlands
  15: "#332288", // NPG North East England
  16: "#f0e442", // Electricity North West
  17: "#117733", // SSEN North Scotland
  18: "#cc79a7", // SPEN South and Central Scotland
  19: "#aa4499", // UKPN South East England
  20: "#ddcc77", // SSEN Southern England
  21: "#88ccee", // NGED South Wales
  22: "#882255", // NGED South West England
  23: "#44aa99", // NPG Yorkshire
};

function isInterconnectorCable(props) {
  if (props.power !== "cable") return false;
  const location = String(props.location || "").toLowerCase();
  const frequency = String(props.frequency || "").trim().toLowerCase();
  const text = [
    props.name,
    props.operator,
    props.location,
  ].filter(Boolean).join(" ").toLowerCase();
  return (
    location === "underwater"
    || frequency === "0"
    || text.includes("interconnector")
    || text.includes("interconnect")
    || text.includes("hvdc")
    || text.includes("subsea")
    || text.includes("submarine")
  );
}

export function lineTypeBucket(props) {
  if (isInterconnectorCable(props)) return "interconnector";
  if (props.power === "cable") return "cable";
  const kv = parseVoltageKv(props);
  if (kv == null) return "lv";
  if (kv >= 500) return "ehv";
  if (kv >= 300) return "hv";
  if (kv >= 150) return "mv";
  return "lv";
}

export function lineStyle(props) {
  const bucket = lineTypeBucket(props);
  const color = LINE_TYPE_COLORS[bucket];
  if (bucket === "interconnector") {
    return { color, weight: 2.5, opacity: 0.9, dashArray: "2 4" };
  }
  if (bucket === "cable") {
    return { color, weight: 2, opacity: 0.85, dashArray: "6 4" };
  }
  if (bucket === "ehv") return { color, weight: 4, opacity: 0.9 };
  if (bucket === "hv") return { color, weight: 3.5, opacity: 0.9 };
  if (bucket === "mv") return { color, weight: 3, opacity: 0.85 };
  const kv = parseVoltageKv(props);
  return { color, weight: 2, opacity: kv == null ? 0.75 : 0.8 };
}

export function plantCapacityMw(props) {
  if (props.capacity_mw != null && props.capacity_mw !== "") {
    const parsed = Number(props.capacity_mw);
    if (!Number.isNaN(parsed)) return parsed;
  }
  return parseCapacityToMw(
    props["plant:output:electricity"] ?? props["generator:output:electricity"],
  );
}

export function bucketPlantSource(source) {
  return bucketFuelSource(source);
}

export function plantSourceBucket(props) {
  const bucket = props.source_bucket || bucketFuelProperties(
    props["plant:source"] || props.generator_source || props.source,
    props.name,
    props.operator,
  );
  return hasFuelType(bucket) ? bucket : "other";
}

export function plantMarkerRadius(props) {
  const mw = plantCapacityMw(props);
  if (mw == null) return PLANT_MARKER_FALLBACK_RADIUS;
  const frac = Math.sqrt(Math.min(mw, PLANT_CAP_REF_MW) / PLANT_CAP_REF_MW);
  return PLANT_MARKER_MIN_RADIUS + frac * (PLANT_MARKER_MAX_RADIUS - PLANT_MARKER_MIN_RADIUS);
}

export function plantPolygonStyle(props) {
  const bucket = plantSourceBucket(props);
  const color = fuelTypeColor(bucket);
  return {
    color: "#263238",
    weight: 1,
    opacity: 0.75,
    fillColor: color,
    fillOpacity: 0.35,
  };
}

export function plantMarkerStyle(props) {
  const bucket = plantSourceBucket(props);
  const color = fuelTypeColor(bucket);
  return {
    radius: plantMarkerRadius(props),
    fillColor: color,
    color: "#263238",
    weight: 1,
    opacity: 0.95,
    fillOpacity: 0.9,
  };
}

export function generatorSourceBucket(props) {
  const bucket = props.source_bucket || bucketFuelProperties(
    props["generator:source"] || props["generator:method"] || props.source,
    props.name,
    props.operator,
  );
  return hasFuelType(bucket) ? bucket : "other";
}

export function generatorMarkerStyle(props) {
  const color = fuelTypeColor(generatorSourceBucket(props));
  return {
    radius: 4,
    fillColor: color,
    color: "#263238",
    weight: 1,
    opacity: 0.9,
    fillOpacity: 0.85,
  };
}

export function generatorPolygonStyle(props) {
  const color = fuelTypeColor(generatorSourceBucket(props));
  return {
    color: "#263238",
    weight: 1,
    opacity: 0.75,
    fillColor: color,
    fillOpacity: 0.35,
  };
}

function bmActivityRadius(props) {
  const volume = Number(props.abs_volume_mwh ?? Math.abs(Number(props.volume_mwh) || 0));
  return Math.max(5, Math.min(18, 4 + Math.sqrt(Math.max(volume, 0)) * 1.5));
}

// Fill encodes fuel type (same palette as the plant layer) so "what is being
// used" reads at a glance. Bids and offers are separate toggleable layers, so
// the side needs no colour; a neutral ring keeps the fuel fill dominant.
const BM_RING = "#ffffff";

function bmActivityFill(props) {
  return fuelTypeColor(plantSourceBucket(props));
}

function bmActivityMarkerStyle(props) {
  return {
    radius: bmActivityRadius(props),
    fillColor: bmActivityFill(props),
    color: BM_RING,
    weight: 1.5,
    opacity: 0.9,
    fillOpacity: 0.9,
  };
}

export function bmActivityBidMarkerStyle(props) {
  return bmActivityMarkerStyle(props);
}

export function bmActivityOfferMarkerStyle(props) {
  return bmActivityMarkerStyle(props);
}

export function converterMarkerStyle() {
  return {
    radius: 5,
    fillColor: CONVERTER_COLOR,
    color: "#ffffff",
    weight: 1,
    opacity: 0.95,
    fillOpacity: 0.95,
  };
}

export function converterPolygonStyle() {
  return {
    color: CONVERTER_COLOR,
    weight: 1.5,
    opacity: 0.85,
    fillColor: CONVERTER_COLOR,
    fillOpacity: 0.25,
  };
}

export function equipmentColor(props) {
  const type = String(props.power || "other").toLowerCase();
  return POWER_EQUIPMENT_COLORS[type] || POWER_EQUIPMENT_COLORS.other;
}

export function equipmentMarkerStyle(props) {
  const color = equipmentColor(props);
  return {
    radius: 3.5,
    fillColor: color,
    color: "#ffffff",
    weight: 0.75,
    opacity: 0.9,
    fillOpacity: 0.9,
  };
}

export function equipmentPolygonStyle(props) {
  const color = equipmentColor(props);
  return {
    color,
    weight: 1.2,
    opacity: 0.85,
    fillColor: color,
    fillOpacity: 0.25,
  };
}

export function towerMarkerStyle() {
  return {
    radius: 2.5,
    fillColor: TOWER_COLOR,
    color: "#263238",
    weight: 0.5,
    opacity: 0.85,
    fillOpacity: 0.8,
  };
}

export function substationPolygonStyle(props) {
  const type = String(props.substation || "other").toLowerCase();
  const color = SUBSTATION_COLORS[type] || SUBSTATION_COLORS.other;
  return {
    color,
    weight: 1.5,
    opacity: 0.85,
    fillColor: color,
    fillOpacity: 0.2,
  };
}

export function substationMarkerStyle(props) {
  const type = String(props.substation || "other").toLowerCase();
  const color = SUBSTATION_COLORS[type] || SUBSTATION_COLORS.other;
  return {
    radius: 4,
    fillColor: color,
    color: "#ffffff",
    weight: 1,
    opacity: 0.95,
    fillOpacity: 0.95,
  };
}

export function etysBoundaryStyle() {
  return {
    color: "#b71c1c",
    weight: 2.5,
    opacity: 0.9,
    dashArray: "10 6",
  };
}

export function turbineMarkerStyle() {
  return {
    radius: 2,
    fillColor: fuelTypeColor("wind"),
    color: "#263238",
    weight: 0.5,
    opacity: 0.85,
    fillOpacity: 0.75,
  };
}

function stableColorIndex(value, count) {
  const text = String(value || "");
  let hash = 0;
  for (let idx = 0; idx < text.length; idx += 1) {
    hash = (hash * 31 + text.charCodeAt(idx)) >>> 0;
  }
  return hash % count;
}

function dnoFillColor(props) {
  if (props.zone_id != null && DNO_ZONE_COLORS[props.zone_id]) {
    return DNO_ZONE_COLORS[props.zone_id];
  }
  const key = props.zone_id ?? props.name ?? props.operator ?? "";
  return DNO_FILL_COLORS[stableColorIndex(key, DNO_FILL_COLORS.length)];
}

function mixHex(color, target, amount) {
  const source = color.replace("#", "");
  const dest = target.replace("#", "");
  const sourceRgb = [0, 2, 4].map((idx) => parseInt(source.slice(idx, idx + 2), 16));
  const destRgb = [0, 2, 4].map((idx) => parseInt(dest.slice(idx, idx + 2), 16));
  const mixed = sourceRgb.map((channel, idx) => Math.round(channel + (destRgb[idx] - channel) * amount));
  return `#${mixed.map((channel) => channel.toString(16).padStart(2, "0")).join("")}`;
}

function generationFillColor(props) {
  const key = props.zone_id ?? props.tariff_zone ?? props.zone_name ?? props.name ?? "";
  return GENERATION_FILL_COLORS[stableColorIndex(key, GENERATION_FILL_COLORS.length)];
}

function gspFillColor(props) {
  if (props.dno_zone_id || props.dno_name || props.dno_operator) {
    const base = dnoFillColor({
      zone_id: props.dno_zone_id,
      name: props.dno_name,
      operator: props.dno_operator,
    });
    const key = props.gsp_id ?? props.gsp_name ?? "";
    const variants = [
      ["#ffffff", 0.16],
      ["#ffffff", 0.3],
      ["#ffffff", 0.44],
      ["#ffffff", 0.58],
      ["#000000", 0.08],
      ["#000000", 0.16],
      ["#000000", 0.24],
      ["#000000", 0.32],
    ];
    const [target, amount] = variants[stableColorIndex(key, variants.length)];
    return mixHex(base, target, amount);
  }
  const key = props.gsp_id ?? props.gsp_name ?? props.name ?? "";
  return DNO_FILL_COLORS[stableColorIndex(key, DNO_FILL_COLORS.length)];
}

export function zoneStyle(kind, selected = false, props = {}) {
  const color = kind === "dno"
    ? dnoFillColor(props)
    : kind === "generation"
      ? generationFillColor(props)
      : gspFillColor(props);
  const defaultWeight = kind === "dno" ? 1.4 : 1;
  const defaultFillOpacity = kind === "gsp" ? 0.34 : kind === "generation" ? 0.3 : 0.26;
  return {
    color: selected ? "#000000" : "#37474f",
    weight: selected ? 3 : defaultWeight,
    opacity: selected ? 0.95 : 0.7,
    fillColor: color,
    fillOpacity: selected ? 0.44 : defaultFillOpacity,
  };
}
