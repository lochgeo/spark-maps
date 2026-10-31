import { state } from "./state.js";

const API_BASE = new URL("../../api/", import.meta.url);
const IS_STATIC_EXPORT = window.location.protocol === "file:" || Boolean(window.__STATIC_EXPORT__);

function resolveApiUrl(path) {
  if (!IS_STATIC_EXPORT) return path;
  // Convert e.g. "/api/constituencies?year=2026" -> "<API_BASE>/constituencies-2026.json"
  // or "/api/districts/Thrissur/details" -> "<API_BASE>/districts/Thrissur/details.json"
  const [pathname, search] = path.replace(/^\/api\//, "").split("?");
  const params = new URLSearchParams(search || "");
  const year = params.get("year");
  const suffix = year ? `-${year}.json` : ".json";
  return new URL(`${pathname}${suffix}`, API_BASE).toString();
}

export async function fetchJSON(url) {
  const resolved = resolveApiUrl(url);
  const response = await fetch(resolved, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`${resolved} returned HTTP ${response.status}`);
  }
  return response.json();
}

export async function loadYear(year) {
  if (state.yearData.has(year)) return state.yearData.get(year);

  const query = `?year=${year}`;
  const [constituencies, districts] = await Promise.all([
    fetchJSON(`/api/constituencies${query}`),
    fetchJSON(`/api/districts${query}`),
  ]);
  const byAc = new Map(constituencies.map((c) => [c.ac_no, c]));
  const byDistrict = new Map(districts.map((d) => [d.name, d]));
  const data = { constituencies, districts, byAc, byDistrict };
  state.yearData.set(year, data);
  return data;
}

export async function loadGeometries(year) {
  if (state.acGeo && state.districtGeo && state.stateGeo) {
    return {
      acGeo: state.acGeo,
      districtGeo: state.districtGeo,
      stateGeo: state.stateGeo,
    };
  }
  const query = `?year=${year}`;
  const [acGeo, districtGeo, stateGeo] = await Promise.all([
    fetchJSON(`/api/geojson/constituencies${query}`),
    fetchJSON(`/api/geojson/districts${query}`),
    fetchJSON("/api/geojson/state"),
  ]);
  state.acGeo = acGeo;
  state.districtGeo = districtGeo;
  state.stateGeo = stateGeo;

  if (!state.yearData.has(year)) {
    const constituencies = acGeo.features.map((f) => f.properties);
    const districts = districtGeo.features.map((f) => f.properties);
    state.yearData.set(year, {
      constituencies,
      districts,
      byAc: new Map(constituencies.map((c) => [c.ac_no, c])),
      byDistrict: new Map(districts.map((d) => [d.name, d])),
    });
  }

  return { acGeo, districtGeo, stateGeo };
}

export function loadTaluksGeo() {
  if (state.taluksGeo) return Promise.resolve(state.taluksGeo);
  return fetchJSON("/api/geojson/taluks").then((geo) => {
    state.taluksGeo = geo;
    return geo;
  });
}

export function loadDistrictDetails(name) {
  if (state.districtDetails.has(name)) {
    return Promise.resolve(state.districtDetails.get(name));
  }
  if (state.districtDetailRequests.has(name)) {
    return state.districtDetailRequests.get(name);
  }

  const request = fetchJSON(`/api/districts/${encodeURIComponent(name)}/details`)
    .then((profile) => {
      state.districtDetails.set(name, profile);
      return profile;
    })
    .catch((error) => {
      console.error(error);
      state.districtDetails.set(name, null);
      return null;
    })
    .finally(() => state.districtDetailRequests.delete(name));

  state.districtDetailRequests.set(name, request);
  return request;
}
