"""Build the API payloads from SQLite results and the processed boundary files."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from .db import fetch_headquarters, fetch_results

ALLIANCE_ORDER = ("LDF", "UDF", "NDA")

ELECTION_SOURCES = {
    2021: "https://en.wikipedia.org/wiki/2021_Kerala_Legislative_Assembly_election",
    2026: "https://en.wikipedia.org/wiki/2026_Kerala_Legislative_Assembly_election",
}

SOURCES = [
    {
        "label": "Assembly & district boundaries",
        "url": "https://github.com/datta07/INDIAN-SHAPEFILES",
    },
    {
        "label": "2021 Kerala Legislative Assembly election results",
        "url": ELECTION_SOURCES[2021],
    },
    {
        "label": "2026 Kerala Legislative Assembly election results",
        "url": ELECTION_SOURCES[2026],
    },
    {
        "label": "District headquarters (Wikidata / OpenStreetMap)",
        "url": "https://www.openstreetmap.org/",
    },
]


class DataStore:
    """In-memory, read-only view of the dataset served by the API."""

    def __init__(self) -> None:
        self.years: list[int] = []
        self.default_year: int = 0
        self.results_by_year: dict[int, list[dict]] = {}
        self.by_ac_by_year: dict[int, dict[int, dict]] = {}
        self.districts_by_year: dict[int, list[dict]] = {}
        self.headquarters: list[dict] = []
        self.meta: dict = {}
        self.constituencies_geojson: dict[int, str] = {}
        self.districts_geojson: dict[int, str] = {}
        self.state_geojson: str = "{}"

    def load(self, db_path: Path, processed_dir: Path) -> None:
        rows = fetch_results(db_path)
        if not rows:
            raise RuntimeError("No constituency results found. Run the data pipeline first.")

        self.headquarters = fetch_headquarters(db_path)
        if not self.headquarters:
            raise RuntimeError("No district headquarters found. Run the data pipeline first.")
        hq_by_district = {row["district"]: row for row in self.headquarters}

        grouped: dict[int, list[dict]] = defaultdict(list)
        for row in rows:
            grouped[row["election_year"]].append(row)

        self.years = sorted(grouped, reverse=True)
        self.default_year = self.years[0]
        for year in self.years:
            self.results_by_year[year] = grouped[year]
            self.by_ac_by_year[year] = {row["ac_no"]: row for row in grouped[year]}
            self.districts_by_year[year] = self._summarise_districts(
                grouped[year], hq_by_district
            )

        self.meta = self._build_meta()
        for year in self.years:
            self.constituencies_geojson[year] = self._build_constituency_geojson(
                processed_dir / "kerala_assembly.geojson", year
            )
            self.districts_geojson[year] = self._build_district_geojson(
                processed_dir / "kerala_districts.geojson", year
            )
        self.state_geojson = (processed_dir / "kerala_state.geojson").read_text(encoding="utf-8")

    def _summarise_districts(
        self, rows: list[dict], hq_by_district: dict[str, dict]
    ) -> list[dict]:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            grouped[row["district"]].append(row)

        districts = []
        for name, members in grouped.items():
            seats = Counter(member["alliance"] for member in members)
            ordered = dict.fromkeys(ALLIANCE_ORDER, 0)
            for alliance, count in seats.items():
                ordered[alliance] = count
            leading = max(ordered, key=lambda alliance: ordered[alliance])
            hq = hq_by_district.get(name)
            if hq is None:
                raise RuntimeError(f"No headquarters recorded for district {name!r}")
            districts.append(
                {
                    "name": name,
                    "ac_count": len(members),
                    "seats": ordered,
                    "leading": leading,
                    "ac_nos": [member["ac_no"] for member in members],
                    "headquarters": {
                        "name": hq["headquarters"],
                        "lat": hq["latitude"],
                        "lng": hq["longitude"],
                    },
                }
            )

        districts.sort(key=lambda district: min(district["ac_nos"]))
        return districts

    def _build_meta(self) -> dict:
        years = []
        for year in self.years:
            rows = self.results_by_year[year]
            seat_counts = Counter(row["alliance"] for row in rows)
            ordered = {name: seat_counts.get(name, 0) for name in ALLIANCE_ORDER}
            for name in sorted(set(seat_counts) - set(ALLIANCE_ORDER)):
                ordered[name] = seat_counts[name]

            years.append(
                {
                    "year": year,
                    "counts": {
                        "constituencies": len(rows),
                        "districts": len({row["district"] for row in rows}),
                        "alliances": ordered,
                    },
                    "alliances": [
                        {"name": name, "seats": seats} for name, seats in ordered.items()
                    ],
                    "source": ELECTION_SOURCES.get(year, ""),
                }
            )

        return {
            "state": "Kerala",
            "default_year": self.default_year,
            "years": years,
            "sources": SOURCES,
        }

    def _build_constituency_geojson(self, path: Path, year: int) -> str:
        source = json.loads(path.read_text(encoding="utf-8"))
        by_ac = self.by_ac_by_year[year]

        features = []
        for feature in source["features"]:
            ac_no = int(feature["properties"]["ac_no"])
            row = by_ac.get(ac_no)
            if row is None:
                raise RuntimeError(f"Boundary for constituency {ac_no} has no {year} result")
            features.append(
                {
                    "type": "Feature",
                    "properties": row,
                    "geometry": feature["geometry"],
                }
            )
        return json.dumps(
            {"type": "FeatureCollection", "features": features},
            separators=(",", ":"),
            ensure_ascii=False,
        )

    def _build_district_geojson(self, path: Path, year: int) -> str:
        source = json.loads(path.read_text(encoding="utf-8"))
        summaries = {district["name"]: district for district in self.districts_by_year[year]}

        features = []
        for feature in source["features"]:
            name = feature["properties"]["name"]
            summary = summaries.get(name)
            if summary is None:
                raise RuntimeError(f"Boundary for district {name!r} has no matching results")
            features.append(
                {
                    "type": "Feature",
                    "properties": summary,
                    "geometry": feature["geometry"],
                }
            )

        return json.dumps(
            {"type": "FeatureCollection", "features": features},
            separators=(",", ":"),
            ensure_ascii=False,
        )
