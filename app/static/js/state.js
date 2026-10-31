export const ALLIANCE_COLORS = {
  LDF: "#f43f5e",
  UDF: "#38bdf8",
  NDA: "#fb923c",
  OTH: "#94a3b8",
};

export const numberFormat = new Intl.NumberFormat("en-IN");

export const CLOSE_ICON = `
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
    <path d="M6 6l12 12M18 6 6 18"></path>
  </svg>`;

export const el = {
  search: document.getElementById("search"),
  searchKbd: document.getElementById("search-kbd"),
  list: document.getElementById("list"),
  listTitle: document.getElementById("list-title"),
  listCount: document.getElementById("list-count"),
  sortBtn: document.getElementById("sort-btn"),
  sortLabel: document.getElementById("sort-label"),
  swingsBtn: document.getElementById("swings-btn"),
  swingsCount: document.getElementById("swings-count"),
  partyBar: document.getElementById("party-bar"),
  legend: document.getElementById("legend"),
  details: document.getElementById("details"),
  hint: document.getElementById("hint"),
  loader: document.getElementById("loader"),
  menuBtn: document.getElementById("menu-btn"),
  scrim: document.getElementById("scrim"),
  basemaps: document.getElementById("basemaps"),
  choropleths: document.getElementById("choropleths"),
  years: document.getElementById("years"),
  labelsBtn: document.getElementById("labels-btn"),
  aboutBtn: document.getElementById("about-btn"),
  about: document.getElementById("about"),
  sources: document.getElementById("sources"),
  footYear: document.getElementById("foot-year"),
};

export const state = {
  meta: null,
  year: null,
  yearMeta: null,
  yearData: new Map(),
  acGeo: null,
  districtGeo: null,
  stateGeo: null,
  constituencies: [],
  districts: [],
  byAc: new Map(),
  byDistrict: new Map(),
  districtDetails: new Map(),
  districtDetailRequests: new Map(),
  acLayers: new Map(),
  districtLayers: new Map(),
  acLayer: null,
  districtOutline: null,
  districtFill: null,
  acLabels: null,
  districtLabels: null,
  hqLayer: null,
  stateLayer: null,
  mode: "constituencies",
  choropleth: "alliance",
  sort: "ac",
  labels: false,
  swingsOnly: false,
  partyFilter: null,
  selected: null,
  hoveredAc: null,
  hoveredDistrict: null,
  search: "",
};

export const colorFor = (alliance) => ALLIANCE_COLORS[alliance] || ALLIANCE_COLORS.OTH;

export function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[character],
  );
}

export function initialsOf(name) {
  const parts = String(name)
    .replace(/\./g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}

export function previousElectionYear(year = state.year) {
  if (!state.meta?.years) return null;
  const sortedAsc = [...state.meta.years].map((entry) => entry.year).sort((a, b) => a - b);
  const idx = sortedAsc.indexOf(year);
  return idx > 0 ? sortedAsc[idx - 1] : null;
}

export function previousAcResult(acNo, year = state.year) {
  const prevYear = previousElectionYear(year);
  if (!prevYear) return null;
  const prevData = state.yearData.get(prevYear);
  if (!prevData) return null;
  return prevData.byAc.get(acNo) ?? null;
}

export function isSeatFlipped(acNo, year = state.year) {
  const current = state.yearData.get(year)?.byAc.get(acNo);
  const prev = previousAcResult(acNo, year);
  if (!current || !prev) return false;
  return current.alliance !== prev.alliance;
}
