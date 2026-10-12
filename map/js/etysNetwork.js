import { escapeHtml } from "./utils.js";
import { esriWorldImageryPreview } from "./popups.js";

const COLORS = { 400: "#2563eb", 275: "#dc2626", 220: "#0284c7", 132: "#334155" };
const ATTRIBUTE_LABELS = {
  "ohllength(km)": "Overhead line (km)", "cablelength(km)": "Cable (km)",
  "circuittype": "Circuit type", "r(%on100mva)": "R (% on 100 MVA)",
  "x(%on100mva)": "X (% on 100 MVA)", "b(%on100mva)": "B (% on 100 MVA)",
  "winterrating(mva)": "Winter rating (MVA)", "springrating(mva)": "Spring rating (MVA)",
  "summerrating(mva)": "Summer rating (MVA)", "autumnrating(mva)": "Autumn rating (MVA)",
  "rating(mva)": "Rating (MVA)", "voltageratio(kv)": "Voltage ratio (kV)",
  "voltage(kv)": "Voltage (kV)", "windfarm": "Wind farm", "ofto": "OFTO",
  "interconnectorname": "Link name", "plannedfromyear": "Planned from year",
  "length(km)": "Length (km)", "ratedvoltage(kv)": "Rated voltage (kV)",
};
export function networkColor(props) {
  if (props.kind === "hvdc") return "#9333ea";
  if (props.kind === "transformer") return "#d97706";
  return COLORS[props.voltage_kv] || "#15803d";
}

// Curves are schematic offsets in projected metres, never representations of routes.
export function schematicPath(coordinates, index, count) {
  const longitudeScale = 111320 * Math.cos((coordinates[0][1] + coordinates[1][1]) / 2 * Math.PI / 180);
  const project = ([lon, lat]) => [lon * longitudeScale, lat * 111320];
  const unproject = ([x, y]) => [y / 111320, x / longitudeScale];
  const [a, b] = coordinates.map(project);
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const distance = Math.hypot(dx, dy);
  if (distance < 30) {
    const radius = 160 + index * 65;
    return Array.from({ length: 33 }, (_, step) => {
      const angle = step / 32 * Math.PI * 2;
      return unproject([a[0] + radius * Math.sin(angle), a[1] + radius * (1 - Math.cos(angle))]);
    });
  }
  const offset = (index - (count - 1) / 2) * Math.min(1800, Math.max(350, distance * 0.05));
  const control = [(a[0] + b[0]) / 2 - dy / distance * offset, (a[1] + b[1]) / 2 + dx / distance * offset];
  return Array.from({ length: 25 }, (_, step) => {
    const t = step / 24, u = 1 - t;
    return unproject([u*u*a[0] + 2*u*t*control[0] + t*t*b[0], u*u*a[1] + 2*u*t*control[1] + t*t*b[1]]);
  });
}

export function createEtysNetworkLayer(map, data) {
  const group = L.featureGroup();
  const sites = new Map(), edges = new Map();
  const visible = { circuit: true, transformer: false, hvdc: true };
  let selected = null;
  const control = L.control({ position: "bottomright" });
  let panel;
  const siteFeatures = data.features.filter(f => f.properties.kind === "site");
  const edgeFeatures = data.features.filter(f => f.properties.kind !== "site");
  const parallel = new Map();
  for (const feature of edgeFeatures) {
    const p = feature.properties;
    const key = [p.site_1, p.site_2].sort().join("|");
    if (!parallel.has(key)) parallel.set(key, []);
    parallel.get(key).push(feature);
  }
  function selectedEdges() {
    return [...edges.values()].filter(({ p }) => visible[p.kind] &&
      (p.site_1 === selected || p.site_2 === selected || p.id === selected));
  }
  function restyle() {
    const nearby = new Set();
    for (const { p } of selectedEdges()) { nearby.add(p.site_1); nearby.add(p.site_2); }
    for (const { p, line } of edges.values()) {
      if (visible[p.kind]) group.addLayer(line); else group.removeLayer(line);
      const active = p.id === selected || p.site_1 === selected || p.site_2 === selected;
      line.setStyle({ color: active ? "#f97316" : networkColor(p), weight: active ? 5 : 2.5,
                      opacity: selected && !active ? 0.13 : 0.85,
                      dashArray: p.kind === "transformer" ? "4 4" : null });
      if (active) line.bringToFront();
    }
    for (const [id, { marker }] of sites) {
      const active = selected === id || nearby.has(id);
      marker.setStyle({ radius: selected === id ? 8 : active ? 6 : 4,
                        color: active ? "#c2410c" : "#334155", fillColor: active ? "#fb923c" : "#ffffff",
                        opacity: selected && !active ? 0.25 : 1, fillOpacity: selected && !active ? 0.25 : 0.95 });
      marker.bringToFront();
    }
    const status = panel?.querySelector(".etys-selection");
    if (status) status.textContent = selected ? `${selectedEdges().length} visible connections highlighted` : "Click a site to highlight its neighbours.";
  }
  function focus(id, openPopup = true) {
    selected = id;
    restyle();
    const target = sites.get(id)?.marker || edges.get(id)?.line;
    if (target && openPopup) target.openPopup();
  }
  function sitePopup(p) {
    const box = document.createElement("div");
    box.className = "etys-popup";
    const { lat, lng } = sites.get(p.id).marker.getLatLng();
    const connections = [...edges.values()].filter(({ p: edge }) => edge.site_1 === p.id || edge.site_2 === p.id);
    const neighbours = [...new Set(connections.map(({ p: edge }) => edge.site_1 === p.id ? edge.site_2 : edge.site_1))].filter(id => id !== p.id);
    box.innerHTML = `<strong>${escapeHtml(p.name)}</strong><p>${escapeHtml(p.owner)} · ${escapeHtml(p.site_code || p.id)} · ${escapeHtml(p.voltage_kv.join(" / "))} kV</p>
      ${esriWorldImageryPreview(lat, lng)}
      <p class="popup-actions"><a href="https://www.google.com/maps/@?api=1&map_action=map&center=${encodeURIComponent(`${lat},${lng}`)}&zoom=18&basemap=satellite" target="_blank" rel="noopener noreferrer">Open Google satellite view</a></p>
      <p>${p.nodes.length} electrical nodes · ${connections.length} mapped connections</p>
      <details><summary>Node IDs and coordinate source</summary><p>${escapeHtml(p.nodes.join(", "))}</p><p>${escapeHtml(p.coordinate_source || "Unknown")}</p></details>
      <p><strong>Connected sites</strong></p>`;
    for (const id of neighbours.sort()) {
      const other = sites.get(id);
      if (!other) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = other.p.name;
      button.addEventListener("click", () => { map.panTo(other.marker.getLatLng()); focus(id); });
      box.appendChild(button);
    }
    return box;
  }
  for (const feature of siteFeatures) {
    const p = feature.properties;
    const marker = L.circleMarker([...feature.geometry.coordinates].reverse(), { radius: 4, weight: 1.5, fillOpacity: 0.95 });
    marker.bindTooltip(escapeHtml(`${p.name} (${p.site_code})`));
    marker.bindPopup(() => sitePopup(p), { maxWidth: 360 });
    marker.on("click", () => focus(p.id, false));
    sites.set(p.id, { marker, p });
  }
  for (const list of parallel.values()) {
    list.sort((a, b) => a.properties.id.localeCompare(b.properties.id));
    list.forEach((feature, index) => {
      const p = feature.properties;
      // Align endpoint order before offsetting, including reversed parallel records.
      const coordinates = p.site_1 <= p.site_2 ? feature.geometry.coordinates : [...feature.geometry.coordinates].reverse();
      const line = L.polyline(schematicPath(coordinates, index, list.length));
      line.bindTooltip(escapeHtml(`${p.kind}: ${p.node_1_label} ↔ ${p.node_2_label}`));
      const attributes = Object.entries(p.attributes).filter(([key, value]) => value !== "" && !["node1", "node2"].includes(key));
      line.bindPopup(`<div class="etys-popup"><strong>${escapeHtml(p.name)}</strong>
        <p>${escapeHtml(p.node_1_label)} ↔ ${escapeHtml(p.node_2_label)}</p>
        <p>${escapeHtml(p.kind)} · ${escapeHtml(p.source_sheet)} row ${p.source_row}</p>
        <table class="popup-table">${attributes.map(([key, value]) => `<tr><th>${escapeHtml(ATTRIBUTE_LABELS[key] || key)}</th><td>${escapeHtml(value)}</td></tr>`).join("")}</table>
        <p>Schematic connection. Ratings are capacity limits, not measured flows.</p></div>`, { maxWidth: 380 });
      line.on("click", () => focus(p.id, false));
      edges.set(p.id, { line, p });
    });
  }
  for (const { marker } of sites.values()) group.addLayer(marker);
  control.onAdd = () => {
    panel = L.DomUtil.create("div", "etys-network-control");
    L.DomEvent.disableClickPropagation(panel);
    L.DomEvent.disableScrollPropagation(panel);
    const meta = data.metadata || {};
    panel.innerHTML = `<strong>ETYS ${escapeHtml(meta.edition)} connections</strong>
      <p>Planning snapshot ${escapeHtml(meta.network_period)}. Schematic routes.</p>
      <p>${meta.mapped_edges} / ${meta.total_edges} connections located · ${meta.unlocated_nodes} unlocated nodes</p>
      <p>400 kV blue · 275 kV red · 132 kV slate<br>Other voltages green · HVDC purple</p>`;
    for (const [kind, title] of [["circuit", "Circuits"], ["transformer", "Transformers"], ["hvdc", "HVDC"]]) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox"; input.checked = visible[kind]; input.dataset.kind = kind;
      input.addEventListener("change", () => { visible[kind] = input.checked; restyle(); });
      label.append(input, ` ${title}`); panel.appendChild(label);
    }
    const status = document.createElement("p"); status.className = "etys-selection"; panel.appendChild(status);
    const clear = document.createElement("button"); clear.type = "button"; clear.textContent = "Clear highlight";
    clear.addEventListener("click", () => { selected = null; map.closePopup(); restyle(); }); panel.appendChild(clear);
    const source = document.createElement("p"); source.textContent = "Locations include unverified 2024 coordinate seeds. Unlocated connections are omitted from the map."; panel.appendChild(source);
    return panel;
  };
  group.on("add", () => { control.addTo(map); restyle(); });
  group.on("remove", () => { control.remove(); map.closePopup(); selected = null; });
  group.focusFeature = (id) => {
    const kind = edges.get(id)?.p.kind;
    if (kind) {
      visible[kind] = true;
      const checkbox = panel?.querySelector(`input[data-kind="${kind}"]`);
      if (checkbox) checkbox.checked = true;
    }
    const target = sites.get(id)?.marker || edges.get(id)?.line;
    if (sites.has(id)) map.setView(target.getLatLng(), Math.max(map.getZoom(), 10));
    else if (target) map.fitBounds(target.getBounds().pad(0.3));
    focus(id);
  };
  restyle();
  return group;
}
