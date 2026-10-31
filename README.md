# Kerala Map

An interactive map of Kerala's **14 districts** and **140 legislative assembly
constituencies**, showing the winning MLA for the **2021 and 2026** elections.
Hover a seat to meet its MLA, click for the full result, and switch the whole map
between election years.

Built as a deliberately small Python project: FastAPI + SQLite on the back end,
and vanilla JavaScript + Leaflet on the front end. No Django, no frontend build
step, no API keys, and no database server.

![Kerala Map screenshot](docs/screenshot.png)

District view, with the Thrissur administrative profile, headquarters marker, seat
composition and MLA list:

![District view with the Thrissur administrative profile](docs/district-view.png)

## Features

- **2021 / 2026 results layers** — switch the choropleth, legend, list and detail
  panel between elections from a single segmented control. The latest election
  (2026) is the default.
- **Constituency choropleth modes** — colour seats by winning alliance
  (`Winner`), highlight only the seats that changed hands (`Swings`), or shade
  polygons by victory margin (`Margin`).
- **Party-level breakdown & filter** — interactive party chips (`INC`, `IUML`,
  `CPI(M)`, `CPI`, `BJP`, …) to filter the list and highlight a single party's
  seats on the map.
- **Hover tooltips** with the constituency, MLA name, party and alliance.
- **Click any seat** for votes, vote share, margin, runner-up, 2021 → 2026
  seat flip / swing comparison, and a link to the source article.
- **District view** with seat-composition bars, a list of every MLA in the
  district, and a **headquarters marker** (Kakkanad, Painavu, Kalpetta, …).
- **Administrative profiles** for all **14 districts** (27 revenue divisions,
  78 taluks, 1,661 revenue villages, 152 block panchayats, 941 gram panchayats,
  6 municipal corporations, 87 municipalities, 528 towns with 2011 populations,
  and 2011 demographics).
- **Headquarters labels** that fade in once you zoom past the state level, with
  the name on hover/tap and a click-through to the district.
- **Search** across constituency, MLA, party and district names.
- **Shareable URLs** that restore the year, seat or district:
  `/#ac=12`, `/#district=Ernakulam`, `/#year=2021&ac=12`.
- **Dark, light and satellite basemaps**, plus an optional constituency-label
  toggle.
- **Responsive layout** with a bottom-sheet detail panel on mobile.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>.

The app builds its SQLite cache automatically on startup from the committed CSV
files, so the data pipeline is **not** needed just to run it. The cache is
rebuilt whenever the CSVs are newer or the schema version changes.

### Using the map

| Control | What it does |
| --- | --- |
| `2026` / `2021` | Switch the results layer |
| `Winner` / `Swings` / `Margin` | Colour seats by alliance, flipped seats, or victory margin |
| `Sort: #` / `Margin ↑` / `Margin ↓` | Sort constituencies by number, closest margin, or largest margin |
| Party chips (`INC`, `CPI(M)`, …) | Filter the list and highlight one party's seats |
| Constituencies / Districts | Switch between seat and district views |
| Labels | Toggle constituency names (shown from zoom 9) |
| Basemap chips | Dark, light or satellite tiles |
| `Ctrl`/`Cmd` + `K`, or `/` | Focus the search box |
| `↑` / `↓` | Step through constituencies or districts |
| `Enter` | Open the active or first search result |
| `Esc` | Clear search, close the sidebar or the detail panel |

### Static site export

To export a self-contained static build into `dist/` (for hosting on GitHub
Pages, Cloudflare Pages, Netlify, or any static file server without Python):

```bash
uv run python -m scripts.export_static
```

## API

| Endpoint | Description |
| --- | --- |
| `GET /api/meta` | Available years, seat counts, alliances, sources |
| `GET /api/constituencies?year=2026` | All 140 results as JSON |
| `GET /api/constituencies/{ac_no}?year=2021` | One constituency result |
| `GET /api/districts?year=2026` | District summaries, seats, headquarters |
| `GET /api/districts/{name}/details` | Administrative profile for any of the 14 districts |
| `GET /api/district-headquarters` | The 14 headquarters with coordinates |
| `GET /api/geojson/constituencies?year=2026` | Boundaries joined to results |
| `GET /api/geojson/districts?year=2026` | District boundaries + seat summary |
| `GET /api/geojson/state` | Kerala outline |
| `GET /healthz` | Liveness probe |
| `GET /docs` | Interactive OpenAPI documentation |

Every election endpoint takes `year=2021` or `year=2026` and defaults to the
latest election. An unavailable year returns `404` listing the valid ones.
GeoJSON is gzipped and cached for five minutes.

```bash
curl http://127.0.0.1:8000/api/constituencies/12
```

```json
{
  "ac_no": 12,
  "election_year": 2026,
  "name": "Dharmadam",
  "district": "Kannur",
  "winner": "Pinarayi Vijayan",
  "party": "CPI(M)",
  "alliance": "LDF",
  "votes": 85614,
  "vote_share": 49.87,
  "runner_up": "Abdul Rasheed",
  "runner_up_party": "INC",
  "margin": 19247
}
```

`GET /api/meta` is the discovery endpoint: it lists the years newest-first, the
seat totals for each, and the sources shown in the app.

```json
{
  "state": "Kerala",
  "default_year": 2026,
  "years": [
    {
      "year": 2026,
      "counts": {
        "constituencies": 140,
        "districts": 14,
        "alliances": { "LDF": 35, "UDF": 102, "NDA": 3 }
      },
      "alliances": [
        { "name": "LDF", "seats": 35 },
        { "name": "UDF", "seats": 102 },
        { "name": "NDA", "seats": 3 }
      ],
      "source": "https://en.wikipedia.org/wiki/2026_Kerala_Legislative_Assembly_election"
    }
  ],
  "sources": [
    {
      "label": "Assembly & district boundaries",
      "url": "https://github.com/datta07/INDIAN-SHAPEFILES"
    }
  ]
}
```

*(Abbreviated: the real response includes both years and all four sources.)*

### District profiles

`GET /api/districts/{name}/details` returns the deeper administrative profile
for any of Kerala's 14 districts. The response includes:

- `demographics` — area, 2011 population, density, literacy, sex ratio, urban share.
- `revenue_divisions` — each division with its taluks.
- `taluks` — headquarters plus every village in the taluk.
- `local_government` — district panchayat, blocks with their gram panchayats, and
  municipalities/corporations.
- `towns` — every Census town and urban body with its 2011 population.
- `assembly_seats` — the district's seats, joined to the current names.
- `parliamentary_seats` and `sources`.

```json
{
  "district": "Thrissur",
  "counts": {
    "revenue_divisions": 2,
    "taluks": 7,
    "villages": 255,
    "blocks": 16,
    "gram_panchayats": 86,
    "municipalities": 7,
    "municipal_corporations": 1,
    "towns": 135,
    "assembly_seats": 13
  },
  "taluks": [
    {
      "name": "Thrissur",
      "headquarters": "Thrissur",
      "villages": ["Anjur", "Thangaloor", "Kaiparambu"]
    }
  ]
}
```

*(Abbreviated. Profiles are district-specific and not tied to an election year.)*

## Data model

SQLite is a disposable cache; the CSVs are the source of truth.

```sql
results        (ac_no, election_year) PRIMARY KEY, name, district, winner,
               party, alliance, votes, vote_share, runner_up,
               runner_up_party, margin
district_hqs   district PRIMARY KEY, headquarters, latitude, longitude
meta           key PRIMARY KEY, value   -- schema_version
```

Administrative profiles live in `data/district_details.json`, keyed by district.
They are hand-curated from official sources and loaded at startup, not stored in
SQLite. The loader rejects a profile whose revenue-division taluks do not match
its taluk list, that repeats a gram panchayat, or whose assembly seats do not
match the election results.

Both elections share one set of 140 boundary polygons. At startup the app joins
each year's rows to those polygons and pre-serialises the GeoJSON for every year.
The browser fetches a year's four payloads the first time that year is selected
and caches them in memory, so later switches are instant. District profiles are
fetched once, the first time a profiled district is opened.

## Data pipeline

The raw downloads are intentionally not committed. To rebuild everything from
the pinned sources:

```bash
uv sync --extra data
uv run python -m scripts.fetch_data   # ~8 MB into data/raw/
uv run python -m scripts.build_data   # writes CSV, GeoJSON and SQLite
```

What the build does:

1. Downloads the assembly, district and state boundaries from a pinned commit,
   plus the Wikipedia result tables from pinned revisions.
2. Parses the 140-row result table for each election and validates that the
   constituency numbers are exactly 1–140 with no blank winners.
3. Harmonises constituency names across years (the earliest spelling wins, while
   any 2026 `(SC)` / `(ST)` suffix is kept) and derives every margin from the
   winner and runner-up vote counts.
4. Dissolves the raw polygons by constituency number — the source splits
   Kothamangalam across two district files — repairs invalid geometry, then
   simplifies to roughly 55 m with coordinates rounded to five decimals.
5. Joins both result sets to the shared boundaries and writes
   `data/results.csv`, `data/processed/*.geojson` and `data/kerala.db`.
6. Checks that `data/district_hqs.csv` covers exactly the districts in the
   results.

The district profiles are committed as `data/district_details.json` and
validated by the app at startup. To regenerate them from the district portals,
LSGD directory, Census 2011 tables and Wikipedia:

```bash
uv run --extra data python -m scripts.build_district_details
```

Payloads are about 640 KiB for all constituencies, 180 KiB for districts and
55 KiB for the state outline. `results.csv` is ~25 KiB and the built database
~72 KiB.

## Project layout

```text
app/
  main.py          FastAPI routes and year resolution
  config.py        Paths
  db.py            Schema, CSV seeding, schema versioning
  schemas.py       Pydantic response models & OpenAPI schemas
  store.py         In-memory joins and GeoJSON payloads
  static/
    index.html
    css/app.css
    js/
      app.js       Boot, mode/year switching, UI event bindings
      api.js       API fetching and in-memory caching
      map.js       Leaflet initialization, panes, styles, layers
      state.js     Shared state, formatters, swing helpers
      views.js     HTML template renderers for details & sidebar
data/
  results.csv      Parsed 2021 + 2026 results (committed)
  district_hqs.csv District headquarters + coordinates (committed)
  district_details.json  Administrative profiles, keyed by district (committed)
  processed/       Simplified GeoJSON (committed)
  raw/             Downloaded source files (gitignored)
scripts/
  fetch_data.py              Pinned downloads
  build_data.py              Parse, simplify, join, validate
  build_district_details.py  Build administrative profiles for all 14 districts
  export_static.py           Export a self-contained static build into dist/
tests/
  test_api.py      API, both years, headquarters, profiles, GeoJSON
docs/
  screenshot.png
  district-view.png
```

## Development

```bash
uv run pytest -q                     # 23 API & static export tests
uv run ruff check .                  # lint
node --check app/static/js/*.js      # syntax-check the frontend modules
```

The tests run against the committed data, so they cover both election years,
district summaries, headquarters, the Thrissur profile and the GeoJSON payloads
without touching the network.

## Data sources & notes

- **Boundaries:** [datta07/INDIAN-SHAPEFILES](https://github.com/datta07/INDIAN-SHAPEFILES),
  pinned to commit `7b003e3e` (2022-02-21). Derived from Indian administrative
  boundary datasets (DataMeet / Census of India lineage).
- **Results:** [2021](https://en.wikipedia.org/wiki/2021_Kerala_Legislative_Assembly_election)
  and [2026](https://en.wikipedia.org/wiki/2026_Kerala_Legislative_Assembly_election)
  Kerala Legislative Assembly election articles on Wikipedia, pinned to
  revisions `1378901836` and `1381519237`.
- **Headquarters:** coordinates from Wikidata, with Kakkanad cross-checked
  against OpenStreetMap.
- **District profiles:** taluks and revenue villages from each district's
  official NIC portal (`*.nic.in` / `wayanad.gov.in`); the current block → gram
  panchayat, municipality and corporation directory from the
  [LSGD local-body directory](https://lsgkerala.gov.in/en/website/web) (codes
  like `B080600` and `G080601` share the block number); towns, 2011 populations
  and demographics from Census 2011 via
  [citypopulation.de](https://www.citypopulation.de/en/india/kerala/); and
  revenue divisions, taluk headquarters and parliamentary seats from Wikipedia.
- **Basemaps:** Esri World Dark Gray / Light Gray Canvas and World Imagery.
- **Leaflet 1.9.4:** loaded from unpkg; the rest of the frontend has no
  dependencies.

Caveats:

- The map shows **general election winners**. By-elections held afterwards
  (for example Thrikkakara and Puthuppally after 2021) are not reflected.
- Two rows in the source tables have a margin that disagrees with their own vote
  totals (2021 Thiruvambady and 2026 Perumbavoor), so margins are always derived
  from the vote counts rather than copied.
- Boundaries are simplified for interactive web use and are indicative, not
  survey-grade.
- **District administrative profiles cover all 14 districts.** Town populations
  and demographics are from Census 2011, the latest available at this level;
  the block, panchayat, municipality and corporation lists reflect the current
  LSGD directory. Village names follow each district's official portal, with
  light casing tidying and spellings aligned to the election data where they
  differ (for example Wadakkanchery, Guruvayur).
- Live tiles and the Leaflet bundle come from third-party CDNs, so the map needs
  network access even though its data is local.

## License

[Apache License 2.0](LICENSE). Election results and boundary data remain subject
to their original sources' terms.
