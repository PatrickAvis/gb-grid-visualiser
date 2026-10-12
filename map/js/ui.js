export function buildLayerPanel(regionConfig, onToggle) {
  const container = document.getElementById("layer-list");
  container.replaceChildren();

  for (const layerId of regionConfig.layerIds) {
    if (layerId === "turbines") continue;
    const layer = regionConfig.layers[layerId];
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = `toggle-${layerId}`;
    checkbox.checked = Boolean(layer.defaultOn);
    checkbox.addEventListener("change", (event) => {
      onToggle(layerId, event.target.checked);
    });
    const text = document.createElement("span");
    text.className = "layer-label-text";

    const title = document.createElement("span");
    title.className = "layer-label-title";
    title.textContent = layer.label || layerId;
    text.appendChild(title);

    if (layer.hint) {
      const hint = document.createElement("span");
      hint.className = "layer-label-hint";
      hint.textContent = layer.hint;
      text.appendChild(hint);
      label.title = layer.hint;
    }

    label.append(checkbox, text);
    container.appendChild(label);
  }

  const hasZones = regionConfig.layerIds.some((id) => regionConfig.layers[id]?.zone);
  const clearBtn = document.getElementById("clear-zone-filter");
  if (clearBtn) {
    clearBtn.hidden = !hasZones;
  }
}

export function buildRegionSelector(catalog, currentRegionId, onChange) {
  const select = document.getElementById("region-select");
  if (!select) return;

  select.replaceChildren();
  const selectable = Object.entries(catalog.regions)
    .filter(([, region]) => Object.keys(region.layers || {}).length > 0)
    .sort(([, a], [, b]) => a.title.localeCompare(b.title));

  const groups = new Map();
  for (const [id, region] of selectable) {
    const groupKey = region.parent || id;
    if (!groups.has(groupKey)) {
      groups.set(groupKey, []);
    }
    groups.get(groupKey).push({ id, title: region.title });
  }

  for (const [groupKey, items] of [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    const optgroup = document.createElement("optgroup");
    const parentRegion = catalog.regions[groupKey];
    optgroup.label = parentRegion?.title || groupKey.replace(/_/g, " ");
    for (const item of items.sort((a, b) => a.title.localeCompare(b.title))) {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.title;
      if (item.id === currentRegionId) {
        option.selected = true;
      }
      optgroup.appendChild(option);
    }
    select.appendChild(optgroup);
  }

  select.addEventListener("change", () => {
    onChange(select.value);
  });
}

export function buildSearchPanel(onSearch, onSelect) {
  const input = document.getElementById("map-search");
  const resultsEl = document.getElementById("search-results");
  if (!input || !resultsEl) return;
  input.value = "";
  resultsEl.replaceChildren();
  resultsEl.hidden = true;

  function renderResults(results) {
    resultsEl.replaceChildren();
    if (!results.length) {
      resultsEl.hidden = true;
      return;
    }
    for (const result of results) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "search-result";

      const title = document.createElement("div");
      title.className = "search-result-title";
      title.textContent = result.title;

      const meta = document.createElement("div");
      meta.className = "search-result-meta";
      meta.textContent = result.subtitle;

      button.append(title, meta);
      button.addEventListener("click", () => {
        resultsEl.hidden = true;
        onSelect(result);
      });
      resultsEl.appendChild(button);
    }
    resultsEl.hidden = false;
  }

  input.oninput = () => {
    const query = input.value.trim();
    if (query.length < 2) {
      renderResults([]);
      return;
    }
    renderResults(onSearch(query));
  };
}

export function buildBasemapControl(map, basemapLayer) {
  const slider = document.getElementById("basemap-intensity");
  const valueEl = document.getElementById("basemap-intensity-value");
  if (!slider) return;

  function applyIntensity(pct) {
    const tilePane = map.getPane("tilePane");
    const clamped = Math.max(0, Math.min(100, pct));
    const intensity = clamped / 100;

    if (intensity === 0) {
      if (map.hasLayer(basemapLayer)) map.removeLayer(basemapLayer);
      if (tilePane) tilePane.style.filter = "";
      if (valueEl) valueEl.textContent = "Off";
      return;
    }

    if (!map.hasLayer(basemapLayer)) basemapLayer.addTo(map);
    basemapLayer.setOpacity(intensity);

    const subdued = 1 - intensity;
    if (tilePane) {
      tilePane.style.filter = intensity >= 0.99
        ? ""
        : `grayscale(${subdued * 0.75}) brightness(${1 + subdued * 0.1}) contrast(${1 - subdued * 0.15})`;
    }

    if (valueEl) valueEl.textContent = `${Math.round(clamped)}%`;
  }

  slider.addEventListener("input", () => {
    applyIntensity(Number(slider.value));
  });

  applyIntensity(Number(slider.value));
}

export function setMapTitle(title) {
  const heading = document.getElementById("map-title");
  if (heading) {
    heading.textContent = title;
  }
  document.title = `${title} — GB Grid Visualiser`;
}

export function fitRegionBounds(map, bounds) {
  if (!bounds || bounds.length !== 2) return;
  const [[south, west], [north, east]] = bounds;
  map.fitBounds([[south, west], [north, east]], { padding: [20, 20] });
}
