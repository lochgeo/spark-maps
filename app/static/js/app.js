import { fetchJSON, loadDistrictDetails, loadGeometries, loadTaluksGeo, loadYear } from "./api.js";
import {
  buildDistrictFocusLayers,
  buildResultLayers,
  focusOnTaluk,
  initMap,
  map,
  refreshAcStyles,
  refreshDistrictStyles,
  refreshFocusTalukStyles,
  selectionPadding,
  setBasemap,
  setHoveredAc,
  setHoveredDistrict,
  syncModeLayers,
  updateLabels,
  updateLayerTooltips,
} from "./map.js";
import {
  colorFor,
  el,
  esc,
  isSeatFlipped,
  previousElectionYear,
  state,
} from "./state.js";
import {
  acRowHtml,
  districtRowHtml,
  emptyHtml,
  renderAcDetailsHtml,
  renderDistrictDetailsHtml,
} from "./views.js";

let detailsTimer = null;

async function boot() {
  try {
    const meta = await fetchJSON("/api/meta");
    state.meta = meta;

    const year = yearFromHash(meta) ?? meta.default_year;
    const prevYear = previousElectionYear(year);
    const [{ acGeo, districtGeo, stateGeo }] = await Promise.all([
      loadGeometries(year),
      prevYear ? loadYear(prevYear) : Promise.resolve(),
    ]);

    renderYearSwitch();
    initMap({
      onSelectAc: (acNo) => selectAc(acNo),
      onSelectDistrict: (name) => selectDistrict(name),
      onSelectTaluk: (talukName) => {
        el.details?.querySelectorAll("[data-taluk-link]").forEach((btn) => {
          btn.classList.toggle("is-active", btn.dataset.talukLink === talukName);
        });
      },
      onHoverChange: markHoveredRow,
      onHideHint: hideHint,
    });

    state.stateLayer = L.geoJSON(stateGeo, {
      pane: "state",
      interactive: false,
      style: {
        color: "rgba(45, 212, 191, 0.45)",
        weight: 1.6,
        opacity: 0.85,
        fill: false,
        className: "state-glow",
      },
    }).addTo(map);

    applyYear(year, state.yearData.get(year));
    bindUI();
    map.fitBounds(state.stateLayer.getBounds(), { padding: [26, 26] });
    await readHash();
    finishLoading();
    setTimeout(hideHint, 9000);
  } catch (error) {
    showError(error);
  }
}

function applyYear(year, data) {
  state.year = year;
  state.yearMeta = state.meta.years.find((entry) => entry.year === year) ?? null;
  state.constituencies = data.constituencies;
  state.districts = data.districts;
  state.byAc = data.byAc;
  state.byDistrict = data.byDistrict;
  state.hoveredAc = null;
  state.hoveredDistrict = null;

  if (!state.acLayer) {
    buildResultLayers(state.acGeo, state.districtGeo);
    syncModeLayers();
  } else {
    updateLayerTooltips();
    if (state.focusedDistrict) {
      buildDistrictFocusLayers(state.focusedDistrict, state.taluksGeo);
      syncModeLayers();
    }
  }

  if (state.mode === "districts") refreshDistrictStyles();
  else refreshAcStyles();
  updateYearSwitch();
  updateChoroplethSwitch();
  updateSortChip();
  updateSwingsChip();
  renderPartyBar();
  renderLegend();
  renderList();

  if (el.footYear) {
    el.footYear.textContent = `${year} assembly election`;
  }

  if (state.selected) {
    const constituency =
      state.selected.type === "ac" ? state.byAc.get(state.selected.id) : null;
    const district =
      state.selected.type === "district" ? state.byDistrict.get(state.selected.id) : null;
    if (constituency) showAcDetails(constituency);
    else if (district) showDistrictDetails(district);
    else state.selected = null;
    markActiveRow();
  }
}

async function setYear(year, options = {}) {
  if (!state.meta || year === state.year) return;
  if (!state.meta.years.some((entry) => entry.year === year)) return;

  el.years.classList.add("is-busy");
  try {
    const prevYear = previousElectionYear(year);
    const [data] = await Promise.all([
      loadYear(year),
      prevYear ? loadYear(prevYear) : Promise.resolve(),
    ]);
    applyYear(year, data);
    if (!options.skipHash) setHash(selectionHash());
  } catch (error) {
    console.error(error);
  } finally {
    el.years.classList.remove("is-busy");
  }
}

function renderYearSwitch() {
  if (!el.years) return;
  el.years.innerHTML = state.meta.years
    .map(
      (entry) =>
        `<button type="button" data-year="${entry.year}" title="Show the ${entry.year} election results">${entry.year}</button>`,
    )
    .join("");
  updateYearSwitch();
}

function updateYearSwitch() {
  if (!el.years) return;
  el.years.querySelectorAll("[data-year]").forEach((button) => {
    const active = Number(button.dataset.year) === state.year;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

const SORT_LABELS = {
  ac: "#",
  "margin-asc": "Margin ↑",
  "margin-desc": "Margin ↓",
};

const SORT_ORDER = ["ac", "margin-asc", "margin-desc"];

function updateSortChip() {
  if (!el.sortBtn || !el.sortLabel) return;
  el.sortBtn.hidden = state.mode !== "constituencies";
  el.sortLabel.textContent = SORT_LABELS[state.sort] ?? "#";
  el.sortBtn.setAttribute("aria-pressed", String(state.sort !== "ac"));
}

function cycleSort() {
  const idx = SORT_ORDER.indexOf(state.sort);
  state.sort = SORT_ORDER[(idx + 1) % SORT_ORDER.length];
  updateSortChip();
  renderList();
  markActiveRow();
  setHash(selectionHash());
}

function updateSwingsChip() {
  if (!el.swingsBtn || !el.swingsCount) return;
  const prevYear = previousElectionYear(state.year);
  if (state.mode !== "constituencies" || !prevYear) {
    el.swingsBtn.hidden = true;
    if (state.swingsOnly) {
      state.swingsOnly = false;
      el.swingsBtn.setAttribute("aria-pressed", "false");
    }
    if (state.choropleth === "swings") {
      state.choropleth = "alliance";
      updateChoroplethSwitch();
    }
    return;
  }
  const flippedCount = state.constituencies.filter((c) =>
    isSeatFlipped(c.ac_no, state.year),
  ).length;
  el.swingsCount.textContent = String(flippedCount);
  el.swingsBtn.hidden = flippedCount === 0;
  el.swingsBtn.setAttribute("aria-pressed", String(state.swingsOnly));
}

function updateChoroplethSwitch() {
  if (!el.choropleths) return;
  const prevYear = previousElectionYear(state.year);
  el.choropleths.hidden = state.mode === "districts";
  el.choropleths.querySelectorAll("[data-choropleth]").forEach((button) => {
    const mode = button.dataset.choropleth;
    if (mode === "swings") {
      button.hidden = !prevYear;
    }
    const active = mode === state.choropleth;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function setChoropleth(mode, options = {}) {
  if (!mode || mode === state.choropleth) return;
  state.choropleth = mode;
  if (mode === "swings" && !state.swingsOnly) {
    state.swingsOnly = true;
    updateSwingsChip();
  } else if (mode !== "swings" && state.swingsOnly) {
    state.swingsOnly = false;
    updateSwingsChip();
  }
  updateChoroplethSwitch();
  refreshAcStyles();
  renderLegend();
  renderList();
  markActiveRow();
  if (!options.skipHash) setHash(selectionHash());
}

function renderPartyBar() {
  if (!el.partyBar) return;
  if (state.mode !== "constituencies") {
    el.partyBar.hidden = true;
    return;
  }

  const partyCounts = new Map();
  const partyAlliance = new Map();
  for (const constituency of state.constituencies) {
    partyCounts.set(constituency.party, (partyCounts.get(constituency.party) ?? 0) + 1);
    if (!partyAlliance.has(constituency.party)) {
      partyAlliance.set(constituency.party, constituency.alliance);
    }
  }

  if (state.partyFilter && !partyCounts.has(state.partyFilter)) {
    state.partyFilter = null;
  }

  const sortedParties = [...partyCounts.entries()].sort(
    (a, b) => b[1] - a[1] || a[0].localeCompare(b[0]),
  );

  el.partyBar.hidden = false;
  el.partyBar.innerHTML = sortedParties
    .map(([party, seats]) => {
      const alliance = partyAlliance.get(party);
      const active = state.partyFilter === party;
      return `
        <button class="party-chip" type="button" data-party="${esc(party)}"
          aria-pressed="${active}" style="--c:${colorFor(alliance)}"
          title="Filter by ${esc(party)} (${esc(alliance)} · ${seats} ${seats === 1 ? "seat" : "seats"})">
          <i></i><span>${esc(party)}</span><b>${seats}</b>
        </button>`;
    })
    .join("");
}

function updateFocusBar() {
  if (!el.focusBar) return;
  if (!state.focusedDistrict) {
    el.focusBar.hidden = true;
    return;
  }
  el.focusBar.hidden = false;
  if (el.focusDistrictName) {
    el.focusDistrictName.textContent = state.focusedDistrict;
  }
  el.sublayers?.querySelectorAll("[data-sublayer]").forEach((btn) => {
    const active = btn.dataset.sublayer === state.districtSubLayer;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-pressed", String(active));
  });
}

function setDistrictSubLayer(sublayer) {
  if (sublayer !== "taluks" && sublayer !== "constituencies") return;
  if (state.districtSubLayer === sublayer) return;
  state.districtSubLayer = sublayer;
  updateFocusBar();
  syncModeLayers();
  renderLegend();
}

function exitDistrictFocus(options = {}) {
  if (!state.focusedDistrict) return;
  state.focusedDistrict = null;
  state.selectedTaluk = null;
  state.hoveredTaluk = null;
  state.selected = null;
  updateFocusBar();
  updateChoroplethSwitch();
  syncModeLayers();
  if (state.mode === "districts") refreshDistrictStyles();
  else refreshAcStyles();
  hideDetails();
  renderLegend();
  markActiveRow();
  if (!options.skipFly && state.stateLayer) {
    map.flyToBounds(state.stateLayer.getBounds(), {
      padding: [26, 26],
      duration: 0.75,
    });
  }
  if (!options.skipHash) setHash("");
}

function selectAc(acNo, options = {}) {
  const constituency = state.byAc.get(acNo);
  const layer = state.acLayers.get(acNo);
  if (!constituency || !layer) return;

  if (state.focusedDistrict && state.focusedDistrict !== constituency.district) {
    state.focusedDistrict = null;
    state.selectedTaluk = null;
    updateFocusBar();
    syncModeLayers();
  }

  state.selected = { type: "ac", id: acNo };
  state.hoveredAc = null;
  refreshAcStyles();
  layer.bringToFront();

  const boundsOptions = selectionPadding(11.5);
  if (options.fly === false) {
    map.fitBounds(layer.getBounds(), boundsOptions);
  } else {
    map.flyToBounds(layer.getBounds(), { ...boundsOptions, duration: 0.9 });
  }

  showAcDetails(constituency);
  markActiveRow();
  if (!options.skipHash) setHash(`ac=${acNo}`, { push: true });
  hideHint();
  if (window.innerWidth <= 900) closeSidebar();
}

async function selectDistrict(name, options = {}) {
  const district = state.byDistrict.get(name);
  const layer = state.districtLayers.get(name);
  if (!district || !layer) return;

  state.selected = { type: "district", id: name };
  state.focusedDistrict = name;
  state.selectedTaluk = null;
  state.hoveredTaluk = null;
  state.hoveredDistrict = null;

  const taluksGeo = await loadTaluksGeo();
  if (state.focusedDistrict !== name) return;

  buildDistrictFocusLayers(name, taluksGeo);
  updateFocusBar();
  updateChoroplethSwitch();
  syncModeLayers();
  renderLegend();

  const boundsOptions = selectionPadding(10.5);
  if (options.fly === false) {
    map.fitBounds(layer.getBounds(), boundsOptions);
  } else {
    map.flyToBounds(layer.getBounds(), { ...boundsOptions, duration: 0.9 });
  }

  showDistrictDetails(district);
  markActiveRow();
  if (!options.skipHash) setHash(`district=${encodeURIComponent(name)}`, { push: true });
  hideHint();
  if (window.innerWidth <= 900) closeSidebar();
}

function setMode(mode, options = {}) {
  if (mode !== "constituencies" && mode !== "districts") return;
  if (mode === state.mode && !state.focusedDistrict) return;

  state.mode = mode;
  state.focusedDistrict = null;
  state.selectedTaluk = null;
  state.hoveredTaluk = null;
  state.selected = null;
  state.hoveredAc = null;
  state.hoveredDistrict = null;
  updateFocusBar();
  hideDetails();
  if (!options.skipHash) setHash("");

  syncModeLayers();
  if (mode === "districts") refreshDistrictStyles();
  else refreshAcStyles();

  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.tab === mode;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  el.list.setAttribute(
    "aria-label",
    mode === "districts" ? "Districts" : "Constituencies",
  );
  updateChoroplethSwitch();
  updateSortChip();
  updateSwingsChip();
  renderPartyBar();
  renderLegend();
  renderList();
  markActiveRow();
}

function closeDetails(options = {}) {
  if (state.focusedDistrict && state.selected?.type === "district") {
    exitDistrictFocus(options);
    return;
  }
  state.selected = null;
  state.hoveredAc = null;
  state.hoveredDistrict = null;
  if (state.mode === "constituencies") refreshAcStyles();
  else refreshDistrictStyles();
  hideDetails();
  if (!options.skipHash) setHash("");
  markActiveRow();
}

function hideDetails() {
  clearTimeout(detailsTimer);
  el.details.classList.remove("is-open");
  detailsTimer = setTimeout(() => {
    el.details.hidden = true;
  }, 200);
}

function openDetails(html) {
  clearTimeout(detailsTimer);
  el.details.innerHTML = html;
  el.details.hidden = false;
  requestAnimationFrame(() => el.details.classList.add("is-open"));

  el.details.querySelector("[data-close]")?.addEventListener("click", closeDetails);

  el.details.querySelector("[data-view-district]")?.addEventListener("click", (event) => {
    const name = event.currentTarget.getAttribute("data-view-district");
    if (state.mode !== "districts") setMode("districts", { skipHash: true });
    selectDistrict(name);
  });

  el.details.querySelectorAll("[data-ac-link]").forEach((button) => {
    button.addEventListener("click", () => {
      const acNo = Number(button.dataset.acLink);
      if (state.focusedDistrict) {
        setDistrictSubLayer("constituencies");
        selectAc(acNo);
        return;
      }
      if (state.mode !== "constituencies") setMode("constituencies", { skipHash: true });
      selectAc(acNo);
    });
  });

  el.details.querySelectorAll("[data-taluk-link]").forEach((button) => {
    button.addEventListener("click", () => {
      const talukName = button.dataset.talukLink;
      if (!talukName) return;
      if (state.districtSubLayer !== "taluks") {
        setDistrictSubLayer("taluks");
      }
      state.selectedTaluk = state.selectedTaluk === talukName ? null : talukName;
      refreshFocusTalukStyles();
      el.details.querySelectorAll("[data-taluk-link]").forEach((btn) => {
        btn.classList.toggle("is-active", btn.dataset.talukLink === state.selectedTaluk);
      });
      if (state.selectedTaluk) {
        focusOnTaluk(state.selectedTaluk);
      }
    });
  });

  el.details.querySelector("[data-hq]")?.addEventListener("click", (event) => {
    const [lat, lng] = event.currentTarget.dataset.hq.split(",").map(Number);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
    map.flyTo([lat, lng], Math.max(map.getZoom(), 10.5), { duration: 0.8 });
  });
}

function showAcDetails(constituency) {
  openDetails(renderAcDetailsHtml(constituency));
}

async function showDistrictDetails(district) {
  const profile = district.has_details ? await loadDistrictDetails(district.name) : null;
  if (state.selected?.type !== "district" || state.selected.id !== district.name) return;
  openDetails(renderDistrictDetailsHtml(district, profile));
}

function markActiveRow() {
  if (!el.list) return;
  el.list.querySelectorAll(".row.is-active").forEach((row) => {
    row.classList.remove("is-active");
  });
  if (!state.selected) return;

  const attribute = state.selected.type === "ac" ? "data-ac" : "data-district";
  const value =
    state.selected.type === "ac" ? String(state.selected.id) : state.selected.id;
  const row = [...el.list.querySelectorAll(`.row[${attribute}]`)].find(
    (candidate) => candidate.getAttribute(attribute) === value,
  );
  if (row) {
    row.classList.add("is-active");
    row.scrollIntoView({ block: "nearest" });
  }
}

function markHoveredRow() {
  if (!el.list) return;
  el.list.querySelectorAll(".row.is-hover").forEach((row) => {
    row.classList.remove("is-hover");
  });
  if (state.mode === "constituencies" && state.hoveredAc != null) {
    const row = el.list.querySelector(`.row[data-ac="${state.hoveredAc}"]`);
    row?.classList.add("is-hover");
  } else if (state.mode === "districts" && state.hoveredDistrict) {
    const row = [...el.list.querySelectorAll(".row[data-district]")].find(
      (candidate) => candidate.getAttribute("data-district") === state.hoveredDistrict,
    );
    row?.classList.add("is-hover");
  }
}

function renderLegend() {
  if (state.focusedDistrict && state.districtSubLayer === "taluks") {
    const talukFeatures = (state.taluksGeo?.features ?? []).filter(
      (f) => f.properties.district === state.focusedDistrict,
    );
    el.legend.innerHTML = `
      <div class="legend-title">${esc(state.focusedDistrict)} · ${talukFeatures.length} taluks</div>
      <div class="legend-note hq-note"><i class="hq-swatch"></i>District headquarters</div>`;
    return;
  }

  const alliances = state.yearMeta?.alliances ?? [];
  const items = alliances
    .map(
      (alliance) => `
        <span class="legend-item">
          <i style="--c:${colorFor(alliance.name)}"></i>${esc(alliance.name)} <b>${alliance.seats}</b>
        </span>`,
    )
    .join("");
  let note;
  if (state.mode === "districts") {
    note = '<div class="legend-note hq-note"><i class="hq-swatch"></i>District headquarters</div>';
  } else if (state.choropleth === "swings") {
    note = `<div class="legend-note"><i></i>Highlighted: flipped since ${previousElectionYear(state.year)}</div>`;
  } else if (state.choropleth === "margin") {
    note = '<div class="legend-note"><i></i>Darker fill = larger victory margin</div>';
  } else {
    note = '<div class="legend-note"><i></i>District boundary</div>';
  }
  el.legend.innerHTML = `
    <div class="legend-title">${state.year} assembly · seats</div>
    <div class="legend-items">${items}</div>
    ${note}`;
}

function renderList() {
  const query = state.search.trim().toLowerCase();
  let items;
  let title;

  if (state.mode === "constituencies") {
    items = state.constituencies.filter((constituency) => {
      if (state.swingsOnly && !isSeatFlipped(constituency.ac_no, state.year)) {
        return false;
      }
      if (state.partyFilter && constituency.party !== state.partyFilter) {
        return false;
      }
      if (!query) return true;
      return [
        constituency.ac_no,
        `#${constituency.ac_no}`,
        constituency.name,
        constituency.winner,
        constituency.party,
        constituency.district,
        constituency.alliance,
      ]
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
    if (state.sort === "margin-asc") {
      items = [...items].sort((a, b) => a.margin - b.margin || a.ac_no - b.ac_no);
    } else if (state.sort === "margin-desc") {
      items = [...items].sort((a, b) => b.margin - a.margin || a.ac_no - b.ac_no);
    }

    if (query) {
      title = "Search results";
    } else if (state.partyFilter && state.swingsOnly) {
      title = `${state.partyFilter} · Flipped`;
    } else if (state.partyFilter) {
      title = `${state.partyFilter} constituencies`;
    } else if (state.swingsOnly) {
      title = "Flipped seats";
    } else {
      title = "All constituencies";
    }
    el.list.innerHTML = items.length
      ? items.map(acRowHtml).join("")
      : emptyHtml("No constituencies match", "Try another name, party or filter.");
  } else {
    items = state.districts.filter((district) => {
      if (!query) return true;
      if (district.name.toLowerCase().includes(query)) return true;
      if (district.headquarters?.name.toLowerCase().includes(query)) return true;
      return district.ac_nos.some((acNo) => {
        const constituency = state.byAc.get(acNo);
        if (!constituency) return false;
        return [constituency.name, constituency.winner, constituency.party]
          .join(" ")
          .toLowerCase()
          .includes(query);
      });
    });
    title = query ? "Search results" : "All districts";
    el.list.innerHTML = items.length
      ? items.map(districtRowHtml).join("")
      : emptyHtml("No districts match", "Try another district or MLA name.");
  }

  el.listTitle.textContent = title;
  el.listCount.textContent = items.length;
}

function handleListClick(event) {
  const row = event.target.closest(".row");
  if (!row) return;
  if (row.dataset.ac) {
    selectAc(Number(row.dataset.ac));
  } else if (row.dataset.district) {
    if (state.mode !== "districts") setMode("districts", { skipHash: true });
    selectDistrict(row.dataset.district);
  }
}

function handleListOver(event) {
  const row = event.target.closest(".row");
  if (!row || row.contains(event.relatedTarget)) return;
  if (row.dataset.ac) setHoveredAc(Number(row.dataset.ac), true);
  else if (row.dataset.district) setHoveredDistrict(row.dataset.district, true);
}

function handleListOut(event) {
  const row = event.target.closest(".row");
  if (!row || row.contains(event.relatedTarget)) return;
  if (row.dataset.ac) setHoveredAc(Number(row.dataset.ac), false);
  else if (row.dataset.district) setHoveredDistrict(row.dataset.district, false);
}

function closeSidebar() {
  document.body.classList.remove("sidebar-open");
}

/* ---------- Hash / URL state ---------- */

function hashParams() {
  return new URLSearchParams(window.location.hash.replace(/^#/, ""));
}

function yearFromHash(meta) {
  const value = Number(hashParams().get("year"));
  return meta.years.some((entry) => entry.year === value) ? value : null;
}

function selectionHash() {
  if (state.selected?.type === "ac") return `ac=${state.selected.id}`;
  if (state.selected?.type === "district") {
    return `district=${encodeURIComponent(state.selected.id)}`;
  }
  return "";
}

function setHash(value, options = {}) {
  const params = [];
  if (state.year !== state.meta?.default_year) params.push(`year=${state.year}`);
  if (state.mode === "districts" && !value?.startsWith("district=")) {
    params.push("mode=districts");
  }
  if (state.mode === "constituencies") {
    if (state.choropleth && state.choropleth !== "alliance") {
      params.push(`view=${state.choropleth}`);
    }
    if (state.partyFilter) {
      params.push(`party=${encodeURIComponent(state.partyFilter)}`);
    }
    if (state.sort && state.sort !== "ac") {
      params.push(`sort=${state.sort}`);
    }
  }
  if (value) params.push(value);
  const next = params.length
    ? `#${params.join("&")}`
    : `${window.location.pathname}${window.location.search}`;
  const current = window.location.hash || `${window.location.pathname}${window.location.search}`;
  if (next === current) return;
  if (options.push) {
    window.history.pushState(null, "", next);
  } else {
    window.history.replaceState(null, "", next);
  }
}

async function readHash() {
  const params = hashParams();
  const requestedYear = Number(params.get("year"));
  const targetYear = state.meta.years.some((entry) => entry.year === requestedYear)
    ? requestedYear
    : state.meta.default_year;

  if (targetYear !== state.year) {
    await setYear(targetYear, { skipHash: true });
  }

  const targetMode =
    params.has("district") || params.get("mode") === "districts"
      ? "districts"
      : "constituencies";
  if (targetMode !== state.mode) {
    setMode(targetMode, { skipHash: true });
  }

  if (targetMode === "constituencies") {
    const viewParam = params.get("view");
    const targetChoropleth =
      viewParam === "swings" || viewParam === "margin" ? viewParam : "alliance";
    if (targetChoropleth !== state.choropleth) {
      setChoropleth(targetChoropleth, { skipHash: true });
    }

    const partyParam = params.get("party") || null;
    const sortParam = params.get("sort");
    const targetSort = SORT_ORDER.includes(sortParam) ? sortParam : "ac";
    if (partyParam !== state.partyFilter || targetSort !== state.sort) {
      state.partyFilter = partyParam;
      state.sort = targetSort;
      updateSortChip();
      renderPartyBar();
      refreshAcStyles();
      renderList();
    }
  }

  if (params.has("ac")) {
    const acNo = Number(params.get("ac"));
    if (state.byAc.has(acNo)) {
      selectAc(acNo, { fly: false, skipHash: true });
      return;
    }
  } else if (params.has("district")) {
    const name = params.get("district");
    if (state.byDistrict.has(name)) {
      selectDistrict(name, { fly: false, skipHash: true });
      return;
    }
  }

  if (state.selected) {
    closeDetails({ skipHash: true });
  }
}

/* ---------- UI ---------- */

function stepSelection(direction) {
  const rows = [...el.list.querySelectorAll(".row")];
  if (!rows.length) return;

  const activeIdx = rows.findIndex((row) => row.classList.contains("is-active"));
  let nextIdx;
  if (activeIdx === -1) {
    nextIdx = direction > 0 ? 0 : rows.length - 1;
  } else {
    nextIdx = (activeIdx + direction + rows.length) % rows.length;
  }
  rows[nextIdx]?.click();
}

function bindUI() {
  if (el.searchKbd && !/Mac|iPhone|iPad|iPod/i.test(navigator.platform || "")) {
    el.searchKbd.textContent = "Ctrl K";
  }

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => setMode(tab.dataset.tab));
  });

  el.backKeralaBtn?.addEventListener("click", () => exitDistrictFocus());

  el.sublayers?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-sublayer]");
    if (button) setDistrictSubLayer(button.dataset.sublayer);
  });

  el.years.addEventListener("click", (event) => {
    const button = event.target.closest("[data-year]");
    if (button) setYear(Number(button.dataset.year));
  });

  el.choropleths?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-choropleth]");
    if (button) setChoropleth(button.dataset.choropleth);
  });

  el.sortBtn?.addEventListener("click", cycleSort);

  el.partyBar?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-party]");
    if (!button) return;
    const party = button.dataset.party;
    state.partyFilter = state.partyFilter === party ? null : party;
    renderPartyBar();
    refreshAcStyles();
    renderList();
    markActiveRow();
    setHash(selectionHash());
  });

  el.basemaps.addEventListener("click", (event) => {
    const button = event.target.closest("[data-basemap]");
    if (button) setBasemap(button.dataset.basemap);
  });

  el.labelsBtn.addEventListener("click", () => {
    state.labels = !state.labels;
    el.labelsBtn.setAttribute("aria-pressed", String(state.labels));
    updateLabels();
    if (state.labels && state.mode === "constituencies" && map.getZoom() < 9) {
      map.flyTo(map.getCenter(), 9.25, { duration: 0.6 });
    }
  });

  el.swingsBtn?.addEventListener("click", () => {
    state.swingsOnly = !state.swingsOnly;
    el.swingsBtn.setAttribute("aria-pressed", String(state.swingsOnly));
    if (state.swingsOnly && state.choropleth === "alliance") {
      state.choropleth = "swings";
    } else if (!state.swingsOnly && state.choropleth === "swings") {
      state.choropleth = "alliance";
    }
    updateChoroplethSwitch();
    refreshAcStyles();
    renderLegend();
    renderList();
    markActiveRow();
    setHash(selectionHash());
  });

  el.search.addEventListener("input", () => {
    state.search = el.search.value;
    renderList();
  });

  el.search.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      stepSelection(1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      stepSelection(-1);
      return;
    }
    if (event.key === "Enter") {
      const active = el.list.querySelector(".row.is-active") || el.list.querySelector(".row");
      if (active) active.click();
    }
    if (event.key === "Escape") {
      el.search.value = "";
      state.search = "";
      renderList();
      el.search.blur();
    }
  });

  el.list.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      stepSelection(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      stepSelection(-1);
    }
  });

  el.list.addEventListener("click", handleListClick);
  el.list.addEventListener("pointerover", handleListOver);
  el.list.addEventListener("pointerout", handleListOut);

  el.menuBtn.addEventListener("click", () => {
    document.body.classList.add("sidebar-open");
  });
  el.scrim.addEventListener("click", closeSidebar);

  el.aboutBtn.addEventListener("click", () => {
    el.sources.innerHTML = state.meta.sources
      .map(
        (source) =>
          `<li><a href="${esc(source.url)}" target="_blank" rel="noopener">${esc(source.label)}</a></li>`,
      )
      .join("");
    el.about.showModal();
  });

  document.addEventListener("keydown", (event) => {
    const modifier = event.metaKey || event.ctrlKey;
    if (modifier && event.key.toLowerCase() === "k") {
      event.preventDefault();
      el.search.focus();
      el.search.select();
      return;
    }
    if (event.key === "/" && document.activeElement !== el.search) {
      event.preventDefault();
      el.search.focus();
      return;
    }
    if (event.key === "Escape") {
      if (document.body.classList.contains("sidebar-open")) closeSidebar();
      if (state.selected) closeDetails();
    }
  });

  window.addEventListener("hashchange", readHash);
  map.once("click", hideHint);
  map.once("dragstart", hideHint);
}

function hideHint() {
  el.hint?.classList.add("is-hidden");
}

function finishLoading() {
  el.loader.classList.add("is-done");
  setTimeout(() => el.loader.remove(), 500);
}

function showError(error) {
  el.loader.innerHTML = `
    <div class="loader-error">
      <strong>Could not load the map</strong>
      <p>${esc(error.message)}</p>
      <p>Make sure the API is running:</p>
      <p><code>uv run uvicorn app.main:app --reload</code></p>
    </div>`;
}

boot();
