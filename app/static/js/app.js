(() => {
  "use strict";

  const ALLIANCE_COLORS = {
    LDF: "#f43f5e",
    UDF: "#38bdf8",
    NDA: "#fb923c",
    OTH: "#94a3b8",
  };

  const numberFormat = new Intl.NumberFormat("en-IN");
  const CLOSE_ICON = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
      <path d="M6 6l12 12M18 6 6 18"></path>
    </svg>`;

  const el = {
    search: document.getElementById("search"),
    list: document.getElementById("list"),
    listTitle: document.getElementById("list-title"),
    listCount: document.getElementById("list-count"),
    legend: document.getElementById("legend"),
    details: document.getElementById("details"),
    hint: document.getElementById("hint"),
    loader: document.getElementById("loader"),
    menuBtn: document.getElementById("menu-btn"),
    scrim: document.getElementById("scrim"),
    basemaps: document.getElementById("basemaps"),
    years: document.getElementById("years"),
    labelsBtn: document.getElementById("labels-btn"),
    aboutBtn: document.getElementById("about-btn"),
    about: document.getElementById("about"),
    sources: document.getElementById("sources"),
    footYear: document.getElementById("foot-year"),
  };

  const state = {
    meta: null,
    year: null,
    yearMeta: null,
    yearData: new Map(),
    constituencies: [],
    districts: [],
    byAc: new Map(),
    byDistrict: new Map(),
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
    labels: false,
    selected: null,
    hoveredAc: null,
    hoveredDistrict: null,
    search: "",
  };

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

  let map;
  let baseLayer = null;
  let baseLabels = null;
  let detailsTimer = null;

  const colorFor = (alliance) => ALLIANCE_COLORS[alliance] || ALLIANCE_COLORS.OTH;

  function esc(value) {
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

  function initialsOf(name) {
    const parts = String(name)
      .replace(/\./g, "")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    if (!parts.length) return "?";
    return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
  }

  async function fetchJSON(url) {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) {
      throw new Error(`${url} returned HTTP ${response.status}`);
    }
    return response.json();
  }

  /* ---------- Boot ---------- */

  async function boot() {
    try {
      const meta = await fetchJSON("/api/meta");
      state.meta = meta;

      const year = yearFromHash(meta) ?? meta.default_year;
      const [data, stateGeo] = await Promise.all([
        loadYear(year),
        fetchJSON("/api/geojson/state"),
      ]);

      renderYearSwitch();
      initMap();
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

      applyYear(year, data);
      bindUI();
      map.fitBounds(state.stateLayer.getBounds(), { padding: [26, 26] });
      readHash();
      finishLoading();
      setTimeout(hideHint, 9000);
    } catch (error) {
      showError(error);
    }
  }

  async function loadYear(year) {
    if (state.yearData.has(year)) return state.yearData.get(year);

    const query = `?year=${year}`;
    const [constituencies, districts, acGeo, districtGeo] = await Promise.all([
      fetchJSON(`/api/constituencies${query}`),
      fetchJSON(`/api/districts${query}`),
      fetchJSON(`/api/geojson/constituencies${query}`),
      fetchJSON(`/api/geojson/districts${query}`),
    ]);
    const data = { constituencies, districts, acGeo, districtGeo };
    state.yearData.set(year, data);
    return data;
  }

  function applyYear(year, data) {
    state.year = year;
    state.yearMeta = state.meta.years.find((entry) => entry.year === year) ?? null;
    state.constituencies = data.constituencies;
    state.districts = data.districts;
    state.byAc = new Map(
      data.constituencies.map((constituency) => [constituency.ac_no, constituency]),
    );
    state.byDistrict = new Map(data.districts.map((district) => [district.name, district]));
    state.hoveredAc = null;
    state.hoveredDistrict = null;

    clearResultLayers();
    buildResultLayers(data.acGeo, data.districtGeo);
    syncModeLayers();
    if (state.mode === "districts") refreshDistrictStyles();
    else refreshAcStyles();
    updateYearSwitch();
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
      const data = await loadYear(year);
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

  /* ---------- Map ---------- */

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

  function initMap() {
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
  }

  function setBasemap(key) {
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

  function clearResultLayers() {
    for (const layer of [
      state.acLayer,
      state.districtOutline,
      state.districtFill,
      state.acLabels,
      state.districtLabels,
      state.hqLayer,
    ]) {
      layer?.remove();
    }
    state.acLayer = null;
    state.districtOutline = null;
    state.districtFill = null;
    state.acLabels = null;
    state.districtLabels = null;
    state.hqLayer = null;
    state.acLayers.clear();
    state.districtLayers.clear();
  }

  function buildResultLayers(acGeo, districtGeo) {
    state.acLayer = L.geoJSON(acGeo, {
      pane: "acs",
      style: acStyle,
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
      style: districtFillStyle,
      onEachFeature: bindDistrict,
    });

    state.acLabels = L.layerGroup();
    for (const [acNo, layer] of state.acLayers) {
      const constituency = state.byAc.get(acNo);
      L.marker(layer.getBounds().getCenter(), {
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
      L.marker(layer.getBounds().getCenter(), {
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
      marker.on("click", () => selectDistrict(district.name));
      group.addLayer(marker);
    }
    return group;
  }

  function syncModeLayers() {
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

  function updateHqLabels() {
    if (!map) return;
    map.getContainer().classList.toggle("hide-hq-labels", map.getZoom() < 8.5);
  }

  function acStyle(feature) {
    const color = colorFor(feature.properties.alliance);
    return {
      color,
      weight: 0.9,
      opacity: 0.9,
      fillColor: color,
      fillOpacity: 0.44,
      lineJoin: "round",
    };
  }

  function acCurrentStyle(acNo) {
    const constituency = state.byAc.get(acNo);
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
    return acStyle({ properties: constituency });
  }

  function districtFillStyle(feature) {
    return districtCurrentStyle(feature.properties, false, false);
  }

  function districtCurrentStyle(district, selected, hovered) {
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
    const constituency = feature.properties;
    state.acLayers.set(constituency.ac_no, layer);

    layer.bindTooltip(acTooltip(constituency), {
      sticky: true,
      className: "mla-tip",
      direction: "top",
      offset: [0, -8],
      opacity: 1,
    });
    layer.on("mouseover", () => setHoveredAc(constituency.ac_no, true));
    layer.on("mouseout", () => setHoveredAc(constituency.ac_no, false));
    layer.on("click", () => selectAc(constituency.ac_no));
  }

  function bindDistrict(feature, layer) {
    const district = feature.properties;
    state.districtLayers.set(district.name, layer);

    layer.bindTooltip(districtTooltip(district), {
      sticky: true,
      className: "mla-tip",
      direction: "top",
      offset: [0, -8],
      opacity: 1,
    });
    layer.on("mouseover", () => setHoveredDistrict(district.name, true));
    layer.on("mouseout", () => setHoveredDistrict(district.name, false));
    layer.on("click", () => selectDistrict(district.name));
  }

  function acTooltip(constituency) {
    return `
      <div class="tip-name">${esc(constituency.name)}</div>
      <div class="tip-meta">#${constituency.ac_no} · ${esc(constituency.district)} district</div>
      <div class="tip-mla"><i style="--c:${colorFor(constituency.alliance)}"></i><strong>${esc(constituency.winner)}</strong></div>
      <div class="tip-party">${esc(constituency.party)} · ${esc(constituency.alliance)}</div>`;
  }

  function districtTooltip(district) {
    const seats = Object.entries(district.seats)
      .filter(([, count]) => count > 0)
      .map(([alliance, count]) => `${alliance} ${count}`)
      .join(" · ");
    const hq = district.headquarters;
    return `
      <div class="tip-name">${esc(district.name)}</div>
      <div class="tip-meta">${district.ac_count} constituencies${hq ? ` · HQ ${esc(hq.name)}` : ""}</div>
      <div class="tip-party">${seats}</div>`;
  }

  function setHoveredAc(acNo, entering) {
    if (state.mode !== "constituencies") return;
    if (entering) {
      state.hoveredAc = acNo;
      hideHint();
    } else if (state.hoveredAc === acNo) {
      state.hoveredAc = null;
    }
    const layer = state.acLayers.get(acNo);
    if (!layer) return;
    layer.setStyle(acCurrentStyle(acNo));
    if (entering) layer.bringToFront();
  }

  function setHoveredDistrict(name, entering) {
    if (state.mode !== "districts") return;
    if (entering) {
      state.hoveredDistrict = name;
      hideHint();
    } else if (state.hoveredDistrict === name) {
      state.hoveredDistrict = null;
    }
    const layer = state.districtLayers.get(name);
    if (!layer) return;
    layer.setStyle(districtCurrentStyle(layer.feature.properties, false, entering));
    if (entering) layer.bringToFront();
  }

  function refreshAcStyles() {
    if (!state.acLayer) return;
    for (const [acNo, layer] of state.acLayers) {
      layer.setStyle(acCurrentStyle(acNo));
    }
  }

  function refreshDistrictStyles() {
    for (const [name, layer] of state.districtLayers) {
      const selected = state.selected?.type === "district" && state.selected.id === name;
      const hovered = state.hoveredDistrict === name;
      layer.setStyle(districtCurrentStyle(layer.feature.properties, selected, hovered));
    }
  }

  function updateLabels() {
    if (!map || !state.acLabels) return;
    const zoom = map.getZoom();
    const showAcLabels =
      state.labels && state.mode === "constituencies" && zoom >= 9;

    if (showAcLabels) {
      state.acLabels.addTo(map);
      state.districtLabels.remove();
    } else {
      state.acLabels.remove();
      state.districtLabels.addTo(map);
    }
  }

  /* ---------- Selection ---------- */

  function selectionPadding(maxZoom) {
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

  function selectAc(acNo, options = {}) {
    const constituency = state.byAc.get(acNo);
    const layer = state.acLayers.get(acNo);
    if (!constituency || !layer) return;

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
    setHash(`ac=${acNo}`);
    hideHint();
    if (window.innerWidth <= 900) closeSidebar();
  }

  function selectDistrict(name, options = {}) {
    const district = state.byDistrict.get(name);
    const layer = state.districtLayers.get(name);
    if (!district || !layer) return;

    state.selected = { type: "district", id: name };
    state.hoveredDistrict = null;
    refreshDistrictStyles();
    layer.bringToFront();

    const boundsOptions = selectionPadding(10);
    if (options.fly === false) {
      map.fitBounds(layer.getBounds(), boundsOptions);
    } else {
      map.flyToBounds(layer.getBounds(), { ...boundsOptions, duration: 0.9 });
    }

    showDistrictDetails(district);
    markActiveRow();
    setHash(`district=${encodeURIComponent(name)}`);
    hideHint();
    if (window.innerWidth <= 900) closeSidebar();
  }

  function setMode(mode) {
    if (mode === state.mode) return;
    if (mode !== "constituencies" && mode !== "districts") return;

    state.mode = mode;
    state.selected = null;
    state.hoveredAc = null;
    state.hoveredDistrict = null;
    hideDetails();
    setHash("");

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
    renderLegend();
    renderList();
    markActiveRow();
  }

  function closeDetails() {
    state.selected = null;
    state.hoveredAc = null;
    state.hoveredDistrict = null;
    if (state.mode === "constituencies") refreshAcStyles();
    else refreshDistrictStyles();
    hideDetails();
    setHash("");
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
      if (state.mode !== "districts") setMode("districts");
      selectDistrict(name);
    });

    el.details.querySelectorAll("[data-ac-link]").forEach((button) => {
      button.addEventListener("click", () => {
        const acNo = Number(button.dataset.acLink);
        if (state.mode !== "constituencies") setMode("constituencies");
        selectAc(acNo);
      });
    });

    el.details.querySelector("[data-hq]")?.addEventListener("click", (event) => {
      const [lat, lng] = event.currentTarget.dataset.hq.split(",").map(Number);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
      map.flyTo([lat, lng], Math.max(map.getZoom(), 10.5), { duration: 0.8 });
    });
  }

  function showAcDetails(constituency) {
    const color = colorFor(constituency.alliance);
    const source = state.yearMeta?.source || "#";
    const voteShare = Number(constituency.vote_share).toFixed(1);

    openDetails(`
      <div class="details-top">
        <div>
          <div class="kicker">Constituency ${constituency.ac_no} · ${esc(constituency.district)}</div>
          <h2>${esc(constituency.name)}</h2>
        </div>
        <button class="icon-btn" type="button" data-close aria-label="Close details">${CLOSE_ICON}</button>
      </div>

      <div class="winner-card" style="--c:${color}">
        <div class="winner-top">
          <div class="avatar">${esc(initialsOf(constituency.winner))}</div>
          <div>
            <span class="winner-label">Winning MLA · ${constituency.election_year}</span>
            <div class="winner-name">${esc(constituency.winner)}</div>
          </div>
        </div>
        <div class="party-line">
          <span class="pill party">${esc(constituency.party)}</span>
          <span class="pill alliance" style="--c:${color}">${esc(constituency.alliance)}</span>
        </div>
      </div>

      <div class="stats">
        <div class="stat"><span>Votes</span><strong>${numberFormat.format(constituency.votes)}</strong></div>
        <div class="stat"><span>Vote share</span><strong>${voteShare}%</strong></div>
        <div class="stat"><span>Margin</span><strong>${numberFormat.format(constituency.margin)}</strong></div>
      </div>

      <p class="runner">Runner-up <b>${esc(constituency.runner_up)}</b> (${esc(constituency.runner_up_party)})</p>

      <div class="details-actions">
        <button class="btn" type="button" data-view-district="${esc(constituency.district)}">View district</button>
        <a class="btn muted" href="${esc(source)}" target="_blank" rel="noopener">Result source ↗</a>
      </div>
    `);
  }

  function showDistrictDetails(district) {
    const members = district.ac_nos
      .map((acNo) => state.byAc.get(acNo))
      .filter(Boolean);
    const seatEntries = Object.entries(district.seats).filter(([, count]) => count > 0);
    const total = district.ac_count;

    const segments = seatEntries
      .map(
        ([alliance, count]) =>
          `<span style="width:${(count / total) * 100}%;background:${colorFor(alliance)}"></span>`,
      )
      .join("");

    const seatLegend = seatEntries
      .map(
        ([alliance, count]) =>
          `<span style="--c:${colorFor(alliance)}"><i></i>${esc(alliance)} <b>${count}</b></span>`,
      )
      .join("");

    const rows = members
      .map(
        (member) => `
          <button class="mini-row" type="button" data-ac-link="${member.ac_no}">
            <span class="dot" style="--c:${colorFor(member.alliance)}"></span>
            <span class="mini-main">
              <span>${esc(member.name)}</span>
              <small>${esc(member.winner)}</small>
            </span>
            <span class="mini-alliance" style="--c:${colorFor(member.alliance)}">${esc(member.alliance)}</span>
          </button>`,
      )
      .join("");

    const hq = district.headquarters;
    const hqLine = hq
      ? `<button class="hq-line" type="button" data-hq="${hq.lat},${hq.lng}"
           title="Zoom to ${esc(hq.name)}">
           <i aria-hidden="true"></i>
           <span>Headquarters</span>
           <b>${esc(hq.name)}</b>
         </button>`
      : "";

    openDetails(`
      <div class="details-top">
        <div>
          <div class="kicker">District · Kerala · ${district.ac_count} seats</div>
          <h2>${esc(district.name)}</h2>
        </div>
        <button class="icon-btn" type="button" data-close aria-label="Close details">${CLOSE_ICON}</button>
      </div>

      <div class="seatbar-lg">${segments}</div>
      <div class="seat-legend">${seatLegend}</div>
      ${hqLine}

      <div class="mini-list">${rows}</div>
    `);
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

  /* ---------- Sidebar ---------- */

  function renderLegend() {
    const alliances = state.yearMeta?.alliances ?? [];
    const items = alliances
      .map(
        (alliance) => `
          <span class="legend-item">
            <i style="--c:${colorFor(alliance.name)}"></i>${esc(alliance.name)} <b>${alliance.seats}</b>
          </span>`,
      )
      .join("");
    const note =
      state.mode === "districts"
        ? '<div class="legend-note hq-note"><i class="hq-swatch"></i>District headquarters</div>'
        : '<div class="legend-note"><i></i>District boundary</div>';
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
        if (!query) return true;
        return [constituency.name, constituency.winner, constituency.party, constituency.district, constituency.alliance]
          .join(" ")
          .toLowerCase()
          .includes(query);
      });
      title = query ? "Search results" : "All constituencies";
      el.list.innerHTML = items.length
        ? items.map(acRowHtml).join("")
        : emptyHtml("No constituencies match", "Try another name, party or district.");
    } else {
      items = state.districts.filter((district) => {
        if (!query) return true;
        if (district.name.toLowerCase().includes(query)) return true;
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

  function acRowHtml(constituency) {
    return `
      <button class="row" type="button" role="listitem" data-ac="${constituency.ac_no}"
        title="${esc(constituency.district)} district">
        <span class="dot" style="--c:${colorFor(constituency.alliance)}"></span>
        <span class="row-main">
          <span class="row-title">${esc(constituency.name)}</span>
          <span class="row-sub">${esc(constituency.winner)} <span class="sep">·</span> ${esc(constituency.party)}</span>
        </span>
        <span class="row-meta">${String(constituency.ac_no).padStart(2, "0")}</span>
      </button>`;
  }

  function districtRowHtml(district) {
    const segments = Object.entries(district.seats)
      .filter(([, count]) => count > 0)
      .map(
        ([alliance, count]) =>
          `<span style="width:${(count / district.ac_count) * 100}%;background:${colorFor(alliance)}"></span>`,
      )
      .join("");
    const seatText = Object.entries(district.seats)
      .filter(([, count]) => count > 0)
      .map(([alliance, count]) => `${alliance} ${count}`)
      .join(" · ");

    return `
      <button class="row district-row" type="button" role="listitem" data-district="${esc(district.name)}">
        <span class="dot" style="--c:${colorFor(district.leading)}"></span>
        <span class="row-main">
          <span class="row-title">${esc(district.name)}</span>
          <span class="row-sub">${district.ac_count} seats · ${seatText}</span>
          <span class="seatbar">${segments}</span>
        </span>
        <span class="row-meta">${district.ac_count}</span>
      </button>`;
  }

  function emptyHtml(title, copy) {
    return `<div class="empty"><strong>${esc(title)}</strong>${esc(copy)}</div>`;
  }

  function handleListClick(event) {
    const row = event.target.closest(".row");
    if (!row) return;
    if (row.dataset.ac) {
      selectAc(Number(row.dataset.ac));
    } else if (row.dataset.district) {
      if (state.mode !== "districts") setMode("districts");
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

  function setHash(value) {
    const params = [];
    if (state.year !== state.meta?.default_year) params.push(`year=${state.year}`);
    if (value) params.push(value);
    const next = params.length
      ? `#${params.join("&")}`
      : `${window.location.pathname}${window.location.search}`;
    window.history.replaceState(null, "", next);
  }

  async function readHash() {
    const params = hashParams();
    if (![...params.keys()].length) return;

    const requestedYear = Number(params.get("year"));
    if (
      state.meta.years.some((entry) => entry.year === requestedYear) &&
      requestedYear !== state.year
    ) {
      await setYear(requestedYear, { skipHash: true });
    }

    if (params.has("ac")) {
      const acNo = Number(params.get("ac"));
      if (state.byAc.has(acNo)) selectAc(acNo, { fly: false });
    } else if (params.has("district")) {
      const name = params.get("district");
      if (state.byDistrict.has(name)) {
        if (state.mode !== "districts") setMode("districts");
        selectDistrict(name, { fly: false });
      }
    }
  }

  /* ---------- UI ---------- */

  function bindUI() {
    document.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => setMode(tab.dataset.tab));
    });

    el.years.addEventListener("click", (event) => {
      const button = event.target.closest("[data-year]");
      if (button) setYear(Number(button.dataset.year));
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

    el.search.addEventListener("input", () => {
      state.search = el.search.value;
      renderList();
    });

    el.search.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        const first = el.list.querySelector(".row");
        if (first) first.click();
      }
      if (event.key === "Escape") {
        el.search.value = "";
        state.search = "";
        renderList();
        el.search.blur();
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
})();
