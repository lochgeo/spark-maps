"""Build the API payloads from SQLite results and the processed boundary files."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from .config import DISTRICT_DETAILS_JSON
from .db import fetch_headquarters, fetch_results
from .schemas import DistrictProfile


def _etag(payload: str) -> str:
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f'W/"{digest}"'

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
        self.district_details: dict[str, dict] = {}
        self.meta: dict = {}
        self.constituencies_geojson: dict[int, str] = {}
        self.districts_geojson: dict[int, str] = {}
        self.state_geojson: str = "{}"
        self.constituencies_etag: dict[int, str] = {}
        self.districts_etag: dict[int, str] = {}
        self.state_etag: str = ""

    def load(self, db_path: Path, processed_dir: Path) -> None:
        rows = fetch_results(db_path)
        if not rows:
            raise RuntimeError("No constituency results found. Run the data pipeline first.")

        self.headquarters = fetch_headquarters(db_path)
        if not self.headquarters:
            raise RuntimeError("No district headquarters found. Run the data pipeline first.")
        hq_by_district = {row["district"]: row for row in self.headquarters}
        self.district_details = self._load_district_details(DISTRICT_DETAILS_JSON)

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

        self._enrich_district_details()
        self.meta = self._build_meta()
        for year in self.years:
            ac_payload = self._build_constituency_geojson(
                processed_dir / "kerala_assembly.geojson", year
            )
            self.constituencies_geojson[year] = ac_payload
            self.constituencies_etag[year] = _etag(ac_payload)

            dist_payload = self._build_district_geojson(
                processed_dir / "kerala_districts.geojson", year
            )
            self.districts_geojson[year] = dist_payload
            self.districts_etag[year] = _etag(dist_payload)

        self.state_geojson = (processed_dir / "kerala_state.geojson").read_text(encoding="utf-8")
        self.state_etag = _etag(self.state_geojson)

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
                    "has_details": name in self.district_details,
                }
            )

        districts.sort(key=lambda district: min(district["ac_nos"]))
        return districts

    def _load_district_details(self, path: Path) -> dict[str, dict]:
        """Load the hand-curated administrative profiles, failing loudly on bad data."""
        if not path.exists():
            return {}

        profiles = json.loads(path.read_text(encoding="utf-8"))
        for name, profile in profiles.items():
            if profile.get("district") != name:
                raise RuntimeError(f"District profile key {name!r} does not match its district")

            taluks = profile.get("taluks", [])
            taluk_names = [taluk["name"] for taluk in taluks]
            if len(set(taluk_names)) != len(taluk_names):
                raise RuntimeError(f"Duplicate taluk in the {name} profile")

            division_taluks = [
                taluk
                for division in profile.get("revenue_divisions", [])
                for taluk in division["taluks"]
            ]
            if sorted(division_taluks) != sorted(taluk_names):
                raise RuntimeError(f"Revenue divisions and taluks disagree for {name}")

            blocks = profile.get("local_government", {}).get("blocks", [])
            panchayats = [
                panchayat
                for block in blocks
                for panchayat in block["gram_panchayats"]
            ]
            if len(set(panchayats)) != len(panchayats):
                raise RuntimeError(f"Duplicate gram panchayat in the {name} profile")

            seat_numbers = profile.get("assembly_seats", [])
            if len(set(seat_numbers)) != len(seat_numbers):
                raise RuntimeError(f"Duplicate assembly seat in the {name} profile")

        return profiles

    def _enrich_district_details(self) -> None:
        """Add shared election data and derived counts to each administrative profile."""
        rows = self.by_ac_by_year[self.default_year]
        summaries = {
            district["name"]: district for district in self.districts_by_year[self.default_year]
        }

        for name, profile in self.district_details.items():
            summary = summaries.get(name)
            if summary is None:
                raise RuntimeError(f"District profile {name!r} has no assembly results")

            seat_numbers = [
                seat["ac_no"] if isinstance(seat, dict) else seat
                for seat in profile.get("assembly_seats", [])
            ]
            if seat_numbers != summary["ac_nos"]:
                raise RuntimeError(
                    f"Assembly seats in the {name} profile do not match the results"
                )

            local_government = profile.get("local_government", {})
            blocks = local_government.get("blocks", [])
            taluks = profile.get("taluks", [])
            towns = profile.get("towns", [])
            profile["assembly_seats"] = [
                {"ac_no": ac_no, "name": rows[ac_no]["name"]} for ac_no in seat_numbers
            ]
            profile["counts"] = {
                "revenue_divisions": len(profile.get("revenue_divisions", [])),
                "taluks": len(taluks),
                "villages": sum(len(taluk["villages"]) for taluk in taluks),
                "blocks": len(blocks),
                "gram_panchayats": sum(len(block["gram_panchayats"]) for block in blocks),
                "municipalities": len(local_government.get("municipalities", [])),
                "municipal_corporations": len(
                    local_government.get("municipal_corporations", [])
                ),
                "towns": len(towns),
                "census_towns": sum(1 for town in towns if town["status"] == "Census town"),
                "assembly_seats": len(seat_numbers),
                "parliamentary_seats": len(profile.get("parliamentary_seats", [])),
            }
            DistrictProfile.model_validate(profile)

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
            props = feature["properties"]
            ac_no = int(props["ac_no"])
            row = by_ac.get(ac_no)
            if row is None:
                raise RuntimeError(f"Boundary for constituency {ac_no} has no {year} result")
            merged = dict(row)
            if "label_lat" in props and "label_lng" in props:
                merged["label_lat"] = props["label_lat"]
                merged["label_lng"] = props["label_lng"]
            features.append(
                {
                    "type": "Feature",
                    "properties": merged,
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
            props = feature["properties"]
            name = props["name"]
            summary = summaries.get(name)
            if summary is None:
                raise RuntimeError(f"Boundary for district {name!r} has no matching results")
            merged = dict(summary)
            if "label_lat" in props and "label_lng" in props:
                merged["label_lat"] = props["label_lat"]
                merged["label_lng"] = props["label_lng"]
            features.append(
                {
                    "type": "Feature",
                    "properties": merged,
                    "geometry": feature["geometry"],
                }
            )

        return json.dumps(
            {"type": "FeatureCollection", "features": features},
            separators=(",", ":"),
            ensure_ascii=False,
        )
