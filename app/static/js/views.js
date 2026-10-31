import {
  CLOSE_ICON,
  colorFor,
  esc,
  initialsOf,
  isSeatFlipped,
  numberFormat,
  previousAcResult,
  state,
} from "./state.js";

export function acTooltip(constituency) {
  return `
    <div class="tip-name">${esc(constituency.name)}</div>
    <div class="tip-meta">#${constituency.ac_no} · ${esc(constituency.district)} district</div>
    <div class="tip-mla"><i style="--c:${colorFor(constituency.alliance)}"></i><strong>${esc(constituency.winner)}</strong></div>
    <div class="tip-party">${esc(constituency.party)} · ${esc(constituency.alliance)}</div>`;
}

export const TALUK_PALETTE = [
  "#2dd4bf",
  "#38bdf8",
  "#a78bfa",
  "#fb923c",
  "#f472b6",
  "#facc15",
  "#4ade80",
];

export function talukTooltip(taluk) {
  return `
    <div class="tip-name">${esc(taluk.name)} Taluk</div>
    <div class="tip-meta">HQ ${esc(taluk.headquarters)} · ${esc(taluk.district)} district</div>
    ${taluk.revenue_division ? `<div class="tip-mla"><i style="--c:${taluk.color || "#2dd4bf"}"></i><strong>${esc(taluk.revenue_division)} division</strong></div>` : ""}
    <div class="tip-party">${taluk.village_count} revenue villages</div>`;
}

export function districtTooltip(district) {
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

export function renderAcDetailsHtml(constituency) {
  const color = colorFor(constituency.alliance);
  const source = state.yearMeta?.source || "#";
  const voteShare = Number(constituency.vote_share).toFixed(1);
  const prev = previousAcResult(constituency.ac_no, constituency.election_year);

  let swingPill = "";
  let swingNote = "";
  if (prev) {
    const flipped = prev.alliance !== constituency.alliance;
    const delta = Number(constituency.vote_share) - Number(prev.vote_share);
    const deltaSign = delta > 0 ? "+" : "";
    const deltaText = `${deltaSign}${delta.toFixed(1)}% vs ${prev.election_year}`;
    if (flipped) {
      swingPill = `<span class="pill swing is-flipped" style="--c:${color}">Flipped from ${esc(prev.alliance)}</span>`;
      swingNote = `<div class="swing-note"><b>${esc(prev.alliance)} → ${esc(constituency.alliance)}</b> from ${prev.election_year} (${esc(prev.winner)}, ${esc(prev.party)} · ${deltaText})</div>`;
    } else {
      swingPill = `<span class="pill swing">Held by ${esc(constituency.alliance)}</span>`;
      swingNote = `<div class="swing-note"><b>Held</b> since ${prev.election_year} (${esc(prev.winner)} · ${deltaText})</div>`;
    }
  }

  return `
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
        ${swingPill}
      </div>
    </div>

    <div class="stats">
      <div class="stat"><span>Votes</span><strong>${numberFormat.format(constituency.votes)}</strong></div>
      <div class="stat"><span>Vote share</span><strong>${voteShare}%</strong></div>
      <div class="stat"><span>Margin</span><strong>${numberFormat.format(constituency.margin)}</strong></div>
    </div>

    ${swingNote}
    <p class="runner">Runner-up <b>${esc(constituency.runner_up)}</b> (${esc(constituency.runner_up_party)})</p>

    <div class="details-actions">
      <button class="btn" type="button" data-view-district="${esc(constituency.district)}">View district</button>
      <a class="btn muted" href="${esc(source)}" target="_blank" rel="noopener">Result source ↗</a>
    </div>
  `;
}

export function renderDistrictDetailsHtml(district, profile) {
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

  let admin = "";
  if (profile) admin = renderDistrictProfile(profile);
  else if (district.has_details) {
    admin = '<p class="profile-note">Administrative profile unavailable right now.</p>';
  }

  return `
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
    ${admin}

    <div class="section-head">
      <span>MLAs</span>
      <small>${district.ac_count} seats · ${state.year}</small>
    </div>
    <div class="mini-list">${rows}</div>
  `;
}

function renderDistrictProfile(profile) {
  const counts = profile.counts ?? {};
  const demo = profile.demographics ?? {};
  const facts = [];

  if (demo.population) {
    facts.push(
      `${numberFormat.format(demo.population)} people${demo.population_year ? ` (${demo.population_year})` : ""}`,
    );
  }
  if (demo.area_km2) facts.push(`${numberFormat.format(demo.area_km2)} km²`);
  if (demo.literacy_rate) facts.push(`${demo.literacy_rate}% literacy`);
  if (demo.urban_share) facts.push(`${demo.urban_share}% urban`);

  const divisions = (profile.revenue_divisions ?? []).map(divisionHtml).join("");
  const divisionByTaluk = new Map();
  for (const division of profile.revenue_divisions ?? []) {
    for (const tname of division.taluks ?? []) {
      divisionByTaluk.set(tname, division.name);
    }
  }
  const taluks = `<div class="subdiv-grid">${(profile.taluks ?? [])
    .map((taluk, idx) =>
      talukHtml(
        taluk,
        divisionByTaluk.get(taluk.name) || "",
        TALUK_PALETTE[idx % TALUK_PALETTE.length],
      ),
    )
    .join("")}</div>`;
  const blocks = (profile.local_government?.blocks ?? []).map(blockHtml).join("");
  const districtPanchayat = profile.local_government?.district_panchayat;
  const blocksBody = `${
    districtPanchayat
      ? `<div class="admin-note">District panchayat <b>${esc(districtPanchayat)}</b></div>`
      : ""
  }${blocks}`;
  const towns = townGroupsHtml(profile.towns ?? []);

  const sourceLinks = (profile.sources ?? [])
    .map(
      (source) =>
        `<a href="${esc(source.url)}" target="_blank" rel="noopener" title="${esc(source.label)}">${esc(source.short ?? source.label)}</a>`,
    )
    .join('<span aria-hidden="true"> · </span>');

  const summary = profile.summary
    ? `<p class="profile-summary">${esc(profile.summary)}</p>`
    : "";

  return `
    <div class="profile-head">
      <span>Administrative profile</span>
      <small>Retrieved ${esc(profile.retrieved)}</small>
    </div>
    ${summary}

    <div class="profile-stats">
      ${profileStat("Divisions", counts.revenue_divisions)}
      ${profileStat("Taluks", counts.taluks)}
      ${profileStat("Blocks", counts.blocks)}
      ${profileStat("Panchayats", counts.gram_panchayats)}
      ${profileStat("Urban bodies", (counts.municipal_corporations ?? 0) + (counts.municipalities ?? 0))}
      ${profileStat("Towns", counts.towns)}
    </div>

    <p class="profile-facts">${facts.map(esc).join(" · ")}</p>
    <p class="profile-facts">${counts.assembly_seats ?? 0} assembly seats · ${counts.parliamentary_seats ?? 0} Lok Sabha seats (${esc((profile.parliamentary_seats ?? []).join(", "))})</p>

    ${adminSection(
      "Taluks (Subdivisions)",
      `${counts.taluks ?? 0} taluks`,
      taluks,
      true,
    )}
    ${adminSection(
      "Revenue divisions",
      `${counts.revenue_divisions ?? 0} divisions`,
      divisions,
      true,
    )}
    ${adminSection(
      "Blocks & panchayats",
      `${counts.blocks ?? 0} blocks · ${counts.gram_panchayats ?? 0} panchayats`,
      blocksBody,
    )}
    ${adminSection(
      "Urban bodies & towns",
      `${(counts.municipal_corporations ?? 0) + (counts.municipalities ?? 0)} urban bodies · ${counts.towns ?? 0} towns`,
      towns,
    )}

    <p class="profile-source"><span>Sources:</span> ${sourceLinks}</p>
  `;
}

function profileStat(label, value) {
  return `<div class="pstat"><span>${esc(label)}</span><b>${numberFormat.format(value ?? 0)}</b></div>`;
}

function adminSection(title, meta, body, open = false) {
  return `
    <details class="admin-section"${open ? " open" : ""}>
      <summary><span>${esc(title)}</span><small>${esc(meta)}</small></summary>
      <div class="admin-body">${body}</div>
    </details>`;
}

function divisionHtml(division) {
  return `
    <div class="admin-block">
      <div class="admin-head">
        <span>${esc(division.name)}</span>
        <small>${division.taluks.length} taluks</small>
      </div>
      <div class="tag-list">${division.taluks.map((taluk) => `<span class="tag">${esc(taluk)}</span>`).join("")}</div>
    </div>`;
}

function talukHtml(taluk, divisionName, color) {
  const active = state.selectedTaluk === taluk.name ? " is-active" : "";
  return `
    <button class="subdiv-card${active}" type="button" data-taluk-link="${esc(taluk.name)}" style="--c:${color}">
      <div class="subdiv-card-top">
        <i></i>
        <strong>${esc(taluk.name)}</strong>
      </div>
      <small>HQ ${esc(taluk.headquarters)}${divisionName ? ` · ${esc(divisionName)} div.` : ""}</small>
      <small>${taluk.villages.length} revenue villages</small>
    </button>`;
}

function blockHtml(block) {
  return `
    <details class="acc-item">
      <summary>
        <span>${esc(block.name)}</span>
        <small>${block.gram_panchayats.length} panchayats</small>
      </summary>
      <div class="tag-list scroll">${block.gram_panchayats.map((panchayat) => `<span class="tag">${esc(panchayat)}</span>`).join("")}</div>
    </details>`;
}

function townGroupsHtml(towns) {
  const urban = towns.filter(
    (town) => town.status === "Municipal corporation" || town.status === "Municipality",
  );
  const census = towns.filter(
    (town) => town.status !== "Municipal corporation" && town.status !== "Municipality",
  );

  const urbanRows = urban
    .map(
      (town) => `
        <div class="town-row">
          <span>${esc(town.name)}<em>${esc(town.status === "Municipal corporation" ? "Corporation" : "Municipality")}</em></span>
          <small>${numberFormat.format(town.population_2011)}</small>
        </div>`,
    )
    .join("");

  const censusRows = census
    .map(
      (town) => `
        <div class="town-row">
          <span>${esc(town.name)}</span>
          <small>${numberFormat.format(town.population_2011)}</small>
        </div>`,
    )
    .join("");

  const censusBlock = census.length
    ? `<details class="acc-item">
        <summary><span>Census towns</span><small>${census.length} ${census.length === 1 ? "town" : "towns"}</small></summary>
        <div class="town-list scroll">${censusRows}</div>
      </details>`
    : "";

  return `
    <div class="town-list urban">${urbanRows}</div>
    ${censusBlock}`;
}

export function acRowHtml(constituency) {
  const flipped = isSeatFlipped(constituency.ac_no, constituency.election_year);
  const prev = flipped ? previousAcResult(constituency.ac_no, constituency.election_year) : null;
  const flipBadge =
    flipped && prev
      ? `<span class="row-flip" title="Flipped from ${esc(prev.alliance)} in ${prev.election_year}">${esc(prev.alliance)}→${esc(constituency.alliance)}</span>`
      : "";
  const showMargin = state.choropleth === "margin" || state.sort !== "ac";
  const rightMeta = showMargin
    ? `<span class="row-meta" title="Victory margin">+${numberFormat.format(constituency.margin)}</span>`
    : `<span class="row-meta">${String(constituency.ac_no).padStart(2, "0")}</span>`;

  return `
    <button class="row" type="button" role="listitem" data-ac="${constituency.ac_no}"
      title="${esc(constituency.district)} district">
      <span class="dot" style="--c:${colorFor(constituency.alliance)}"></span>
      <span class="row-main">
        <span class="row-title">${esc(constituency.name)}${flipBadge}</span>
        <span class="row-sub">${esc(constituency.winner)} <span class="sep">·</span> ${esc(constituency.party)}</span>
      </span>
      ${rightMeta}
    </button>`;
}

export function districtRowHtml(district) {
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

export function emptyHtml(title, copy) {
  return `<div class="empty"><strong>${esc(title)}</strong>${esc(copy)}</div>`;
}
