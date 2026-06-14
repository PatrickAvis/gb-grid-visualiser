import {
  LINE_TYPE_COLORS,
  LINE_TYPE_LABELS,
  LINE_TYPE_ORDER,
} from "./constants.js";
import { fuelTypeColor, fuelTypeLabel, fuelTypeOrder } from "./fuelTypes.js";

const ETYS_BOUNDARY_COLOR = "#b71c1c";

function etysBoundarySortKey(name) {
  const match = String(name).match(/^([A-Z]+)(\d+(?:\.\d+)?)([a-z]?)$/);
  if (!match) return [String(name), 0, ""];
  return [match[1], parseFloat(match[2]), match[3] || ""];
}

export function compareEtysBoundaries(a, b) {
  const left = etysBoundarySortKey(a);
  const right = etysBoundarySortKey(b);
  for (let idx = 0; idx < 3; idx += 1) {
    if (left[idx] < right[idx]) return -1;
    if (left[idx] > right[idx]) return 1;
  }
  return 0;
}

export function sortEtysBoundaryIds(ids) {
  return [...ids].sort(compareEtysBoundaries);
}

export function buildLineLegend(
  lineBucketGroups,
  lineBucketVisibility,
  setLineBucketVisible,
  options = {},
) {
  const legendEl = document.getElementById("line-legend");
  const listEl = document.getElementById("line-legend-list");
  listEl.replaceChildren();

  const buckets = LINE_TYPE_ORDER.filter((bucket) => lineBucketGroups[bucket]);

  for (const bucket of buckets) {
    const label = document.createElement("label");
    label.className = "plant-legend-item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = lineBucketVisibility[bucket] !== false;
    checkbox.addEventListener("change", (event) => {
      setLineBucketVisible(bucket, event.target.checked);
    });

    const swatch = document.createElement("span");
    swatch.className = "line-swatch";
    swatch.style.background = LINE_TYPE_COLORS[bucket];

    const text = document.createTextNode(LINE_TYPE_LABELS[bucket]);

    label.append(checkbox, swatch, text);
    listEl.appendChild(label);
  }

  if (buckets.length && options.onWidthScaleChange) {
    const widthLabel = document.createElement("label");
    widthLabel.className = "legend-control";

    const text = document.createElement("span");
    text.textContent = "Line thickness x";

    const input = document.createElement("input");
    input.type = "number";
    input.min = "0.5";
    input.max = "4";
    input.step = "0.25";
    input.value = String(options.widthScale ?? 1);
    input.title = "Transmission line width multiplier";
    input.addEventListener("change", (event) => {
      options.onWidthScaleChange(Number(event.target.value));
    });

    widthLabel.append(text, input);
    listEl.appendChild(widthLabel);
  }

  legendEl.hidden = buckets.length === 0;
}

export function setLineLegendVisible(visible, lineBucketGroups) {
  const legendEl = document.getElementById("line-legend");
  if (!legendEl) return;
  legendEl.hidden = !visible || Object.keys(lineBucketGroups).length === 0;
}

export function buildPlantLegend(
  plantBucketGroups,
  plantBucketVisibility,
  setPlantBucketVisible,
  options = {},
) {
  const legendEl = document.getElementById("plant-legend");
  const listEl = document.getElementById("plant-legend-list");
  listEl.replaceChildren();

  const buckets = [
    ...fuelTypeOrder().filter((bucket) => plantBucketGroups[bucket]),
    ...Object.keys(plantBucketGroups)
      .filter((bucket) => !fuelTypeOrder().includes(bucket))
      .sort(),
  ];

  for (const bucket of buckets) {
    const label = document.createElement("label");
    label.className = "plant-legend-item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = plantBucketVisibility[bucket] !== false;
    checkbox.addEventListener("change", (event) => {
      setPlantBucketVisible(bucket, event.target.checked);
    });

    const swatch = document.createElement("span");
    swatch.className = "plant-swatch";
    swatch.style.background = fuelTypeColor(bucket);

    const text = document.createTextNode(fuelTypeLabel(bucket));

    label.append(checkbox, swatch, text);
    listEl.appendChild(label);
  }

  let actionsEl = document.getElementById("plant-legend-actions");
  if (!actionsEl) {
    actionsEl = document.createElement("div");
    actionsEl.id = "plant-legend-actions";
    legendEl.appendChild(actionsEl);
  }
  actionsEl.replaceChildren();

  if (buckets.length && options.onClearAll) {
    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.className = "clear-filter";
    clearBtn.textContent = "Clear all generation types";
    clearBtn.addEventListener("click", options.onClearAll);
    actionsEl.appendChild(clearBtn);
  }

  legendEl.hidden = buckets.length === 0;
}

export function setPlantLegendVisible(visible, plantBucketGroups) {
  const legendEl = document.getElementById("plant-legend");
  if (!legendEl) return;
  legendEl.hidden = !visible || Object.keys(plantBucketGroups).length === 0;
}

export function buildGeneratorLegend(visibility, setVisible, options = {}) {
  const legendEl = document.getElementById("generator-legend");
  const listEl = document.getElementById("generator-legend-list");
  if (!legendEl || !listEl) return;
  listEl.replaceChildren();

  for (const bucket of fuelTypeOrder()) {
    const label = document.createElement("label");
    label.className = "plant-legend-item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = visibility[bucket] !== false;
    checkbox.addEventListener("change", (event) => {
      setVisible(bucket, event.target.checked);
    });

    const swatch = document.createElement("span");
    swatch.className = "plant-swatch";
    swatch.style.background = fuelTypeColor(bucket);

    const text = document.createTextNode(fuelTypeLabel(bucket));

    label.append(checkbox, swatch, text);
    listEl.appendChild(label);
  }

  let actionsEl = document.getElementById("generator-legend-actions");
  if (!actionsEl) {
    actionsEl = document.createElement("div");
    actionsEl.id = "generator-legend-actions";
    actionsEl.className = "legend-actions";
    legendEl.appendChild(actionsEl);
  }
  actionsEl.replaceChildren();

  if (options.onSelectAll) {
    const selectBtn = document.createElement("button");
    selectBtn.type = "button";
    selectBtn.className = "clear-filter";
    selectBtn.textContent = "Select all fuel types";
    selectBtn.addEventListener("click", options.onSelectAll);
    actionsEl.appendChild(selectBtn);
  }
  if (options.onClearAll) {
    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.className = "clear-filter";
    clearBtn.textContent = "Clear all fuel types";
    clearBtn.addEventListener("click", options.onClearAll);
    actionsEl.appendChild(clearBtn);
  }
}

export function setGeneratorLegendVisible(visible) {
  const legendEl = document.getElementById("generator-legend");
  if (!legendEl) return;
  legendEl.hidden = !visible;
}

// Shared by the BM bids/offers layers: a fuel colour key (no per-fuel filter,
// so swatches only — no checkboxes).
export function setBmLegendVisible(visible) {
  const legendEl = document.getElementById("bm-legend");
  if (!legendEl) return;
  legendEl.hidden = !visible;
}

export function buildBmFuelLegend(buckets) {
  const listEl = document.getElementById("bm-legend-list");
  if (!listEl) return;
  listEl.replaceChildren();
  const present = new Set(buckets);
  const ordered = [
    ...fuelTypeOrder().filter((bucket) => present.has(bucket)),
    ...[...present].filter((bucket) => !fuelTypeOrder().includes(bucket)).sort(),
  ];
  for (const bucket of ordered) {
    const item = document.createElement("div");
    item.className = "plant-legend-item bm-legend-item";

    const swatch = document.createElement("span");
    swatch.className = "plant-swatch";
    swatch.style.background = fuelTypeColor(bucket);

    item.append(swatch, document.createTextNode(fuelTypeLabel(bucket)));
    listEl.appendChild(item);
  }
}

export function buildEtysLegend(
  etysBucketGroups,
  etysBucketVisibility,
  setEtysBucketVisible,
  options = {},
) {
  const legendEl = document.getElementById("etys-legend");
  const listEl = document.getElementById("etys-legend-list");
  if (!legendEl || !listEl) return;

  listEl.replaceChildren();

  const buckets = sortEtysBoundaryIds(Object.keys(etysBucketGroups));

  for (const bucket of buckets) {
    const label = document.createElement("label");
    label.className = "plant-legend-item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = etysBucketVisibility[bucket] !== false;
    checkbox.addEventListener("change", (event) => {
      setEtysBucketVisible(bucket, event.target.checked);
    });

    const swatch = document.createElement("span");
    swatch.className = "line-swatch";
    swatch.style.background = ETYS_BOUNDARY_COLOR;

    const text = document.createTextNode(bucket);

    label.append(checkbox, swatch, text);
    listEl.appendChild(label);
  }

  let actionsEl = document.getElementById("etys-legend-actions");
  if (!actionsEl) {
    actionsEl = document.createElement("div");
    actionsEl.id = "etys-legend-actions";
    actionsEl.className = "legend-actions";
    legendEl.appendChild(actionsEl);
  }
  actionsEl.replaceChildren();

  if (buckets.length) {
    if (options.onSelectAll) {
      const selectBtn = document.createElement("button");
      selectBtn.type = "button";
      selectBtn.className = "clear-filter";
      selectBtn.textContent = "Select all boundaries";
      selectBtn.addEventListener("click", options.onSelectAll);
      actionsEl.appendChild(selectBtn);
    }
    if (options.onClearAll) {
      const clearBtn = document.createElement("button");
      clearBtn.type = "button";
      clearBtn.className = "clear-filter";
      clearBtn.textContent = "Clear all boundaries";
      clearBtn.addEventListener("click", options.onClearAll);
      actionsEl.appendChild(clearBtn);
    }
  }

  legendEl.hidden = buckets.length === 0;
}

export function setEtysLegendVisible(visible, etysBucketGroups) {
  const legendEl = document.getElementById("etys-legend");
  if (!legendEl) return;
  legendEl.hidden = !visible || Object.keys(etysBucketGroups).length === 0;
}
