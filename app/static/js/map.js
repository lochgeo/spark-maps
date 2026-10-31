import { colorFor, el, esc, isSeatFlipped, state } from "./state.js";
import { acTooltip, districtTooltip } from "./views.js";

// Labels sit on the seaward side for the coastal headquarters so they do
// not run into their inland neighbours.
const HQ_LABEL_LEFT = new Set([
  "Kasaragod",
  "Kannur",
  "Kozhikode",
  "Alappuzha",
  "Kollam",
  "Thiruvananthapuram",
]);

const BASEMAPS = {
  dark: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    labels:
      "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
    attribution:
      'Tiles &copy; Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  },
  light: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    labels:
      "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
    attribution:
      'Tiles &copy; Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  },
  satellite: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    labels:
      "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community",
  },
};

export let map;
let baseLayer = null;
let baseLabels = null;
let callbacks = {
  onSelectAc: () => {},
  onSelectDistrict: () => {},
  onHoverChange: () => {},
  onHideHint: () => {},
};

export function initMap(handlers) {
  callbacks = { ...callbacks, ...handlers };

  map = L.map("map", {
    zoomControl: false,
    minZoom: 6,
    maxZoom: 19,
    zoomSnap: 0.25,
    zoomDelta: 0.5,
    wheelPxPerZoomLevel: 110,
    attributionControl: true,
  });

  L.control.zoom({ position: "bottomright" }).addTo(map);
  map.attributionControl.setPrefix(false);

  map.createPane("state").style.zIndex = "415";
  map.createPane("acs").style.zIndex = "420";
  map.createPane("districts").style.zIndex = "430";
  const baseLabelPane = map.createPane("baseLabels");
  baseLabelPane.style.zIndex = "440";
  baseLabelPane.style.pointerEvents = "none";
  const labelPane = map.createPane("labels");
  labelPane.style.zIndex = "445";
  labelPane.style.pointerEvents = "none";

  map.on("zoomend", () => {
    updateLabels();
    updateHqLabels();
  });
  window.addEventListener("resize", () => map.invalidateSize());

  setBasemap("dark");
  return map;
}

export function setBasemap(key) {
  const config = BASEMAPS[key];
  if (!config) return;

  if (baseLayer) map.removeLayer(baseLayer);
  baseLayer = L.tileLayer(config.url, {
    maxZoom: 19,
    maxNativeZoom: key === "satellite" ? 19 : 16,
    attribution: config.attribution,
  }).addTo(map);

  if (baseLabels) {
    map.removeLayer(baseLabels);
    baseLabels = null;
  }
  if (config.labels) {
    baseLabels = L.tileLayer(config.labels, {
      maxZoom: 19,
      maxNativeZoom: key === "satellite" ? 19 : 16,
      minZoom: key === "satellite" ? 7 : 9,
      pane: key === "satellite" ? "baseLabels" : "tilePane",
      opacity: 0.9,
    }).addTo(map);
  }

  el.basemaps.querySelectorAll("[data-basemap]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.basemap === key);
  });
}

function labelCoordinates(feature, layer) {
  const props = feature.properties;
  if (Number.isFinite(props.label_lat) && Number.isFinite(props.label_lng)) {
    return [props.label_lat, props.label_lng];
  }
  return layer.getBounds().getCenter();
}

export function buildResultLayers(acGeo, districtGeo) {
  state.acLayer = L.geoJSON(acGeo, {
    pane: "acs",
    style: (feature) => acCurrentStyle(feature.properties.ac_no),
    onEachFeature: bindAc,
  }).addTo(map);

  state.districtOutline = L.geoJSON(districtGeo, {
    pane: "districts",
    interactive: false,
    style: {
      color: "#e2e8f0",
      weight: 1.5,
      opacity: 0.62,
      dashArray: "4 5",
      fill: false,
      lineCap: "round",
    },
  }).addTo(map);

  state.districtFill = L.geoJSON(districtGeo, {
    pane: "districts",
    style: (feature) => {
      const district = state.byDistrict.get(feature.properties.name) ?? feature.properties;
      return districtCurrentStyle(district, false, false);
    },
    onEachFeature: bindDistrict,
  });

  state.acLabels = L.layerGroup();
  for (const [acNo, layer] of state.acLayers) {
    const constituency = state.byAc.get(acNo) ?? layer.feature.properties;
    L.marker(labelCoordinates(layer.feature, layer), {
      icon: L.divIcon({
        className: "ac-label",
        html: `<span>${esc(constituency.name)}</span>`,
        iconSize: [0, 0],
      }),
      interactive: false,
      keyboard: false,
      pane: "labels",
    }).addTo(state.acLabels);
  }

  state.districtLabels = L.layerGroup();
  for (const [name, layer] of state.districtLayers) {
    L.marker(labelCoordinates(layer.feature, layer), {
      icon: L.divIcon({
        className: "district-label",
        html: `<span>${esc(name)}</span>`,
        iconSize: [0, 0],
      }),
      interactive: false,
      keyboard: false,
      pane: "labels",
    }).addTo(state.districtLabels);
  }
  state.districtLabels.addTo(map);

  state.hqLayer = buildHqLayer(state.districts);
}

export function updateLayerTooltips() {
  for (const [acNo, layer] of state.acLayers) {
    const constituency = state.byAc.get(acNo);
    if (constituency) {
      layer.feature.properties = { ...layer.feature.properties, ...constituency };
      layer.setTooltipContent(acTooltip(constituency));
    }
  }
  for (const [name, layer] of state.districtLayers) {
    const district = state.byDistrict.get(name);
    if (district) {
      layer.feature.properties = { ...layer.feature.properties, ...district };
      layer.setTooltipContent(districtTooltip(district));
    }
  }
}

function buildHqLayer(districts) {
  const group = L.layerGroup();
  for (const district of districts) {
    const hq = district.headquarters;
    if (!hq) continue;

    const labelLeft = HQ_LABEL_LEFT.has(district.name);
    const marker = L.marker([hq.lat, hq.lng], {
      icon: L.divIcon({
        className: labelLeft ? "hq-marker hq-left" : "hq-marker",
        html: `<span class="hq-dot"></span><span class="hq-name">${esc(hq.name)}</span>`,
        iconSize: [10, 10],
        iconAnchor: [5, 5],
      }),
      pane: "districts",
      riseOnHover: true,
      title: `${hq.name} — ${district.name} district headquarters`,
    });

    marker.bindTooltip(`${hq.name} · ${district.name} district HQ`, {
      direction: "top",
      offset: [0, -7],
      className: "hq-tooltip",
      opacity: 1,
    });
    marker.on("click", () => callbacks.onSelectDistrict(district.name));
    group.addLayer(marker);
  }
  return group;
}

export function syncModeLayers() {
  if (state.mode === "districts") {
    state.acLayer?.remove();
    state.acLabels?.remove();
    state.districtOutline?.remove();
    state.districtFill?.addTo(map);
    state.hqLayer?.addTo(map);
  } else {
    state.districtFill?.remove();
    state.hqLayer?.remove();
    state.districtOutline?.addTo(map);
    state.acLayer?.addTo(map);
  }
  updateLabels();
  updateHqLabels();
}

export function updateHqLabels() {
  if (!map) return;
  map.getContainer().classList.toggle("hide-hq-labels", map.getZoom() < 8.5);
}

function acStyle(constituency) {
  const color = colorFor(constituency.alliance);
  const partyFilteredOut =
    state.partyFilter && constituency.party !== state.partyFilter;

  if (partyFilteredOut) {
    return {
      color: "rgba(148, 163, 184, 0.22)",
      weight: 0.6,
      opacity: 0.5,
      fillColor: "#475569",
      fillOpacity: 0.12,
      lineJoin: "round",
    };
  }

  if (state.choropleth === "swings") {
    const flipped = isSeatFlipped(constituency.ac_no, constituency.election_year);
    if (!flipped) {
      return {
        color: "rgba(148, 163, 184, 0.26)",
        weight: 0.65,
        opacity: 0.55,
        fillColor: "#475569",
        fillOpacity: 0.14,
        lineJoin: "round",
      };
    }
    return {
      color,
      weight: 1.4,
      opacity: 0.98,
      fillColor: color,
      fillOpacity: 0.64,
      lineJoin: "round",
    };
  }

  if (state.choropleth === "margin") {
    const marginRatio = Math.min(Math.max((constituency.margin || 0) / 35000, 0), 1);
    const fillOpacity = Number((0.18 + marginRatio * 0.6).toFixed(2));
    return {
      color,
      weight: 0.9 + marginRatio * 0.6,
      opacity: 0.9,
      fillColor: color,
      fillOpacity,
      lineJoin: "round",
    };
  }

  return {
    color,
    weight: 0.9,
    opacity: 0.9,
    fillColor: color,
    fillOpacity: state.partyFilter ? 0.62 : 0.44,
    lineJoin: "round",
  };
}

export function acCurrentStyle(acNo) {
  const constituency = state.byAc.get(acNo) ?? state.acLayers.get(acNo)?.feature?.properties;
  const color = colorFor(constituency.alliance);
  const selected = state.selected?.type === "ac" && state.selected.id === acNo;
  const hovered = state.hoveredAc === acNo;

  if (selected) {
    return {
      color: "#f8fafc",
      weight: 2.5,
      opacity: 1,
      fillColor: color,
      fillOpacity: 0.66,
      lineJoin: "round",
    };
  }
  if (hovered) {
    return {
      color: "#f8fafc",
      weight: 2,
      opacity: 1,
      fillColor: color,
      fillOpacity: 0.6,
      lineJoin: "round",
    };
  }
  return acStyle(constituency);
}

export function districtCurrentStyle(district, selected, hovered) {
  const color = colorFor(district.leading);
  return {
    color: selected || hovered ? "#ffffff" : "rgba(248, 250, 252, 0.72)",
    weight: selected ? 2.6 : hovered ? 2.2 : 1.3,
    opacity: 0.95,
    fillColor: color,
    fillOpacity: selected ? 0.58 : hovered ? 0.52 : 0.42,
    lineJoin: "round",
  };
}

function bindAc(feature, layer) {
  const acNo = feature.properties.ac_no;
  const constituency = state.byAc.get(acNo) ?? feature.properties;
  state.acLayers.set(acNo, layer);

  layer.bindTooltip(acTooltip(constituency), {
    sticky: true,
    className: "mla-tip",
    direction: "top",
    offset: [0, -8],
    opacity: 1,
  });
  layer.on("mouseover", () => setHoveredAc(acNo, true, true));
  layer.on("mouseout", () => setHoveredAc(acNo, false, true));
  layer.on("click", () => callbacks.onSelectAc(acNo));
}

function bindDistrict(feature, layer) {
  const name = feature.properties.name;
  const district = state.byDistrict.get(name) ?? feature.properties;
  state.districtLayers.set(name, layer);

  layer.bindTooltip(districtTooltip(district), {
    sticky: true,
    className: "mla-tip",
    direction: "top",
    offset: [0, -8],
    opacity: 1,
  });
  layer.on("mouseover", () => setHoveredDistrict(name, true, true));
  layer.on("mouseout", () => setHoveredDistrict(name, false, true));
  layer.on("click", () => callbacks.onSelectDistrict(name));
}

export function setHoveredAc(acNo, entering, fromMap = false) {
  if (state.mode !== "constituencies") return;
  if (entering) {
    state.hoveredAc = acNo;
    callbacks.onHideHint();
  } else if (state.hoveredAc === acNo) {
    state.hoveredAc = null;
  }
  const layer = state.acLayers.get(acNo);
  if (!layer) return;
  layer.setStyle(acCurrentStyle(acNo));
  if (entering) layer.bringToFront();
  if (fromMap) callbacks.onHoverChange();
}

export function setHoveredDistrict(name, entering, fromMap = false) {
  if (state.mode !== "districts") return;
  if (entering) {
    state.hoveredDistrict = name;
    callbacks.onHideHint();
  } else if (state.hoveredDistrict === name) {
    state.hoveredDistrict = null;
  }
  const layer = state.districtLayers.get(name);
  if (!layer) return;
  const selected = state.selected?.type === "district" && state.selected.id === name;
  const district = state.byDistrict.get(name) ?? layer.feature.properties;
  layer.setStyle(districtCurrentStyle(district, selected, entering));
  if (entering || selected) layer.bringToFront();
  if (fromMap) callbacks.onHoverChange();
}

export function refreshAcStyles() {
  if (!state.acLayer) return;
  for (const [acNo, layer] of state.acLayers) {
    layer.setStyle(acCurrentStyle(acNo));
  }
}

export function refreshDistrictStyles() {
  for (const [name, layer] of state.districtLayers) {
    const selected = state.selected?.type === "district" && state.selected.id === name;
    const hovered = state.hoveredDistrict === name;
    const district = state.byDistrict.get(name) ?? layer.feature.properties;
    layer.setStyle(districtCurrentStyle(district, selected, hovered));
  }
}

export function updateLabels() {
  if (!map || !state.acLabels) return;
  const zoom = map.getZoom();
  const showAcLabels = state.labels && state.mode === "constituencies" && zoom >= 9;

  if (showAcLabels) {
    state.acLabels.addTo(map);
    state.districtLabels.remove();
  } else {
    state.acLabels.remove();
    state.districtLabels.addTo(map);
  }
}

export function selectionPadding(maxZoom) {
  if (window.innerWidth <= 900) {
    return {
      paddingTopLeft: [26, 70],
      paddingBottomRight: [26, Math.round(window.innerHeight * 0.54)],
      maxZoom,
    };
  }
  return {
    paddingTopLeft: [50, 70],
    paddingBottomRight: [392, 60],
    maxZoom,
  };
}
