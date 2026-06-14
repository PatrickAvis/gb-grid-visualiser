import {
  bmActivityBidMarkerStyle,
  bmActivityOfferMarkerStyle,
  converterMarkerStyle,
  converterPolygonStyle,
  equipmentMarkerStyle,
  equipmentPolygonStyle,
  etysBoundaryStyle,
  generatorMarkerStyle,
  generatorPolygonStyle,
  lineStyle,
  plantMarkerStyle,
  plantPolygonStyle,
  substationMarkerStyle,
  substationPolygonStyle,
  towerMarkerStyle,
  turbineMarkerStyle,
} from "./styles.js";
import { generatorPropsForPopup, plantPropsForPopup, turbinePropsForPopup } from "./popups.js";

export const LAYER_BEHAVIOR = {
  lines: {
    label: "transmission lines",
    popupKeys: ["name", "power", "voltage", "voltage_kv", "operator", "circuits", "cables"],
    kind: "lines",
  },
  plants: {
    label: "plants",
    polygonStyleFn: plantPolygonStyle,
    markerStyleFn: plantMarkerStyle,
    popupPropsFn: plantPropsForPopup,
    popupKeys: ["name", "bmu_id", "ngc_bmu_id", "bmu_type", "capacity_mw", "latitude", "longitude", "plant:source", "source_bucket", "plant:output:electricity", "operator"],
    combinedLayer: true,
    filterable: true,
    kind: "plants",
  },
  bm_activity_bid: {
    label: "BM bids",
    styleFn: bmActivityBidMarkerStyle,
    sideFilter: "bid",
    markerOffset: [-0.0004, -0.0004],
    popupKeys: [
      "plant_name",
      "bmu_id",
      "ngc_bmu_id",
      "volume_mwh",
      "price_gbp_mwh",
      "settlement_date",
      "settlement_period",
      "bid_offer_pair_id",
      "action_count",
    ],
    pointLayer: true,
    kind: "points",
  },
  bm_activity_offer: {
    label: "BM offers",
    styleFn: bmActivityOfferMarkerStyle,
    sideFilter: "offer",
    markerOffset: [0.0004, 0.0004],
    popupKeys: [
      "plant_name",
      "bmu_id",
      "ngc_bmu_id",
      "volume_mwh",
      "price_gbp_mwh",
      "settlement_date",
      "settlement_period",
      "bid_offer_pair_id",
      "action_count",
    ],
    pointLayer: true,
    kind: "points",
  },
  turbines: {
    label: "wind turbines",
    styleFn: turbineMarkerStyle,
    popupPropsFn: turbinePropsForPopup,
    popupKeys: ["name", "capacity_mw", "height_m", "rotor_diameter_m", "latitude", "longitude", "operator", "manufacturer", "model", "generator:output:electricity"],
    pointLayer: true,
    filterable: true,
    kind: "points",
  },
  substations: {
    label: "substations",
    polygonStyleFn: substationPolygonStyle,
    markerStyleFn: substationMarkerStyle,
    popupKeys: ["name", "power", "substation", "voltage", "latitude", "longitude", "operator", "ref"],
    combinedLayer: true,
    kind: "combined",
  },
  generators: {
    label: "generators",
    styleFn: generatorMarkerStyle,
    polygonStyleFn: generatorPolygonStyle,
    markerStyleFn: generatorMarkerStyle,
    popupPropsFn: generatorPropsForPopup,
    popupKeys: ["name", "capacity_mw", "generator:source", "generator:method", "generator:type", "generator:output:electricity", "operator", "latitude", "longitude"],
    pointLayer: true,
    combinedLayer: true,
    filterable: true,
    kind: "points",
  },
  converters: {
    label: "converter stations",
    polygonStyleFn: converterPolygonStyle,
    markerStyleFn: converterMarkerStyle,
    popupKeys: ["name", "power", "converter", "voltage", "frequency", "rating", "operator", "latitude", "longitude"],
    combinedLayer: true,
    kind: "combined",
  },
  equipment: {
    label: "power equipment",
    polygonStyleFn: equipmentPolygonStyle,
    markerStyleFn: equipmentMarkerStyle,
    popupKeys: ["name", "power", "voltage", "operator", "ref", "location", "latitude", "longitude"],
    combinedLayer: true,
    kind: "combined",
  },
  towers: {
    label: "transmission towers",
    styleFn: towerMarkerStyle,
    popupKeys: ["name", "power", "ref", "operator", "height"],
    pointLayer: true,
    kind: "points",
  },
  dno: {
    label: "DNO licence areas",
    zoneLayer: "dno",
    kind: "zone",
  },
  gsp: {
    label: "GSP regions",
    zoneLayer: "gsp",
    kind: "zone",
  },
  generation_zones: {
    label: "TNUoS generation zones",
    zoneLayer: "generation",
    kind: "zone",
  },
  etys_boundaries: {
    label: "ETYS transmission boundaries",
    styleFn: etysBoundaryStyle,
    popupKeys: ["name", "boundary_id", "id"],
    lineLabels: true,
    kind: "lines",
  },
};

export function buildLayerConfig(regionConfig) {
  const bmuLookup = regionConfig.bmuLookup || null;
  const result = {};
  for (const [layerId, catalogLayer] of Object.entries(regionConfig.layers)) {
    const behavior = LAYER_BEHAVIOR[layerId] || { kind: "generic", label: catalogLayer.label || layerId };
    const layerConfig = {
      ...behavior,
      ...catalogLayer,
      label: catalogLayer.label || behavior.label || layerId,
      minZoom: catalogLayer.minZoom,
    };
    if (layerId === "plants" && bmuLookup) {
      layerConfig.popupPropsFn = (props) => plantPropsForPopup(props, bmuLookup);
    }
    result[layerId] = layerConfig;
  }
  return result;
}
