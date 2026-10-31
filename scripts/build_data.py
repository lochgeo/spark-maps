"""Turn the raw downloads into the app's processed GeoJSON, CSV and SQLite database.

Run from the project root:

    uv run --extra data python -m scripts.build_data

The pipeline:
  1. Parses the result tables for every configured election from the pinned
     Wikipedia pages.
  2. Dissolves and simplifies the assembly/district polygons.
  3. Writes data/results.csv, data/processed/*.geojson and data/kerala.db.
"""

from __future__ import annotations

import csv
import difflib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from shapely import make_valid, set_precision, to_geojson
from shapely.geometry import Polygon, shape
from shapely.ops import polylabel, unary_union

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DATA_DIR = ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
RESULTS_CSV = DATA_DIR / "results.csv"
HQ_CSV = DATA_DIR / "district_hqs.csv"
DISTRICT_DETAILS_JSON = DATA_DIR / "district_details.json"
DB_PATH = DATA_DIR / "kerala.db"

# Pinned Wikipedia revisions, matching scripts/fetch_data.py.
ELECTIONS = {
    2021: "election_2021.html",
    2026: "election_2026.html",
}
EXPECTED_CONSTITUENCIES = 140
EXPECTED_DISTRICTS = 14

# Roughly 55 m at Kerala's latitude: detailed enough for street-level zoom,
# small enough to keep the payload under a megabyte.
AC_SIMPLIFY = 0.0005
DISTRICT_SIMPLIFY = 0.0005
STATE_SIMPLIFY = 0.0005
PRECISION = 1e-5

CSV_FIELDS = (
    "ac_no",
    "name",
    "district",
    "winner",
    "party",
    "alliance",
    "votes",
    "vote_share",
    "runner_up",
    "runner_up_party",
    "margin",
    "election_year",
)


def clean(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = re.sub(r"\[\s*\d+\s*\]", "", str(value))
    return re.sub(r"\s+", " ", text).strip()


def clean_person_name(value: object) -> str:
    text = clean(value)
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r"\.(?=[A-Za-z])", ". ", text)
    text = re.sub(r"\b([A-Z])\.\s*([A-Z])\s+(?=[A-Z][a-z])", r"\1. \2. ", text)
    return re.sub(r"\s+", " ", text).strip()


def pick(row: pd.Series, *columns: str) -> str:
    for column in columns:
        value = clean(row.get(column))
        if value:
            return value
    return ""


def as_int(value: str) -> int | None:
    try:
        return int(float(value.replace(",", "")))
    except (TypeError, ValueError):
        return None


def normalise_columns(table: pd.DataFrame) -> pd.DataFrame:
    table = table.copy()
    table.columns = [
        "|".join(str(part) for part in column) if isinstance(column, tuple) else str(column)
        for column in table.columns
    ]
    return table


def find_results_table(tables: list[pd.DataFrame]) -> tuple[pd.DataFrame, str]:
    candidates = []
    for raw_table in tables:
        table = normalise_columns(raw_table)
        if "Constituency|Name" not in table.columns or "Winner|Candidate" not in table.columns:
            continue
        number_column = next(
            (
                column
                for column in ("Constituency|#", "Constituency|No.")
                if column in table.columns
            ),
            None,
        )
        if number_column is None:
            continue
        numbers = pd.to_numeric(table[number_column], errors="coerce").dropna()
        if len(numbers) >= EXPECTED_CONSTITUENCIES:
            candidates.append((len(numbers), table, number_column))

    if not candidates:
        raise SystemExit("Could not find a constituency results table in the downloaded page.")
    _, table, number_column = max(candidates, key=lambda candidate: candidate[0])
    return table, number_column


def load_results(html_path: Path, year: int) -> list[dict]:
    table, number_column = find_results_table(pd.read_html(html_path))
    has_district_column = "District|District" in table.columns

    rows: list[dict] = []
    district = ""
    margin_mismatches = 0
    for _, record in table.iterrows():
        if has_district_column:
            row_district = clean(record.get("District|District"))
            if row_district:
                district = row_district

        name = clean(record.get("Constituency|Name"))
        if name.lower().endswith("district"):
            district = name[: -len("district")].strip()
            continue

        ac_no = as_int(clean(record.get(number_column)))
        if ac_no is None or not name or not district:
            continue

        votes = as_int(pick(record, "Winner|Votes"))
        runner_up_votes = as_int(pick(record, "Runner-up|Votes"))
        if votes is None or runner_up_votes is None:
            raise SystemExit(f"Missing vote counts for {name} ({year}).")

        # Margins are derived from the vote counts. A couple of rows in the
        # source tables disagree with their own vote totals, so the derived
        # value is the consistent one.
        margin = votes - runner_up_votes
        source_margin = as_int(pick(record, "Margin|Margin"))
        if source_margin is not None and source_margin != margin:
            margin_mismatches += 1

        vote_share = pick(record, "Winner|%")
        if not vote_share:
            raise SystemExit(f"Missing vote share for {name} ({year}).")

        rows.append(
            {
                "ac_no": ac_no,
                "name": name,
                "district": district,
                "winner": clean_person_name(record.get("Winner|Candidate")),
                "party": pick(record, "Winner|Party.1", "Winner|Party"),
                "alliance": pick(record, "Winner|Alliance.1", "Winner|Alliance"),
                "votes": votes,
                "vote_share": float(vote_share),
                "runner_up": clean_person_name(record.get("Runner-up|Candidate")),
                "runner_up_party": pick(record, "Runner-up|Party.1", "Runner-up|Party"),
                "margin": margin,
                "election_year": year,
            }
        )

    numbers = sorted(row["ac_no"] for row in rows)
    if numbers != list(range(1, EXPECTED_CONSTITUENCIES + 1)):
        raise SystemExit(
            f"{year}: expected constituencies 1-140, parsed {len(rows)} rows: {numbers[:10]}..."
        )
    if any(not row["winner"] or not row["alliance"] for row in rows):
        raise SystemExit(f"{year}: some constituencies have no winner or alliance.")
    if any(row["margin"] < 0 for row in rows):
        raise SystemExit(f"{year}: a winner has fewer votes than the runner-up.")

    if margin_mismatches:
        print(
            f"  note  {margin_mismatches} source margin(s) disagreed with the vote "
            "totals; derived margins used"
        )
    return rows


def load_headquarters(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [
            {
                "district": row["district"].strip(),
                "headquarters": row["headquarters"].strip(),
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
            }
            for row in csv.DictReader(handle)
        ]
    if len(rows) != EXPECTED_DISTRICTS:
        raise SystemExit(f"Expected 14 district headquarters, found {len(rows)}.")
    return rows


def polygonal(geometry):
    if geometry.is_empty:
        raise ValueError("empty geometry")
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry
    parts = [
        part for part in geometry.geoms if part.geom_type in {"Polygon", "MultiPolygon"}
    ]
    if not parts:
        raise ValueError(f"no polygonal parts in {geometry.geom_type}")
    return unary_union(parts)


def prepare(geometry, tolerance: float):
    geometry = polygonal(make_valid(geometry))
    geometry = geometry.simplify(tolerance, preserve_topology=True)
    geometry = set_precision(geometry, PRECISION)
    if geometry.is_empty:
        raise ValueError("geometry collapsed during simplification")
    return geometry


def label_point(geometry) -> tuple[float, float]:
    polygon = (
        geometry
        if geometry.geom_type == "Polygon"
        else max(geometry.geoms, key=lambda part: part.area)
    )
    point = polylabel(polygon, tolerance=0.001)
    return round(point.y, 5), round(point.x, 5)


def feature(geometry, properties: dict) -> dict:
    label_lat, label_lng = label_point(geometry)
    return {
        "type": "Feature",
        "properties": {**properties, "label_lat": label_lat, "label_lng": label_lng},
        "geometry": json.loads(to_geojson(geometry)),
    }


def write_geojson(path: Path, features: list[dict]) -> None:
    payload = {"type": "FeatureCollection", "features": features}
    path.write_text(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  wrote {path.name:28} {path.stat().st_size / 1024:7.1f} KiB")


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {path.name:28} {path.stat().st_size / 1024:7.1f} KiB")


def build_boundaries(rows: list[dict]) -> None:
    results_by_no = {row["ac_no"]: row for row in rows}
    csv_districts = {row["district"] for row in rows}

    assembly_raw = json.loads((RAW_DIR / "KERALA_ASSEMBLY.geojson").read_text(encoding="utf-8"))
    parts_by_no: dict[int, list] = defaultdict(list)
    for raw_feature in assembly_raw["features"]:
        parts_by_no[int(raw_feature["properties"]["AC_NO"])].append(
            shape(raw_feature["geometry"])
        )

    assembly_features = []
    for ac_no, parts in sorted(parts_by_no.items()):
        if ac_no not in results_by_no:
            raise SystemExit(f"Boundary for constituency {ac_no} has no parsed result")
        geometry = prepare(unary_union([make_valid(part) for part in parts]), AC_SIMPLIFY)
        row = results_by_no[ac_no]
        assembly_features.append(
            feature(
                geometry,
                {
                    "ac_no": ac_no,
                    "name": row["name"],
                    "district": row["district"],
                },
            )
        )

    if len(assembly_features) != EXPECTED_CONSTITUENCIES:
        raise SystemExit(f"Expected 140 assembly polygons, built {len(assembly_features)}")

    districts_raw = json.loads(
        (RAW_DIR / "KERALA_DISTRICTS.geojson").read_text(encoding="utf-8")
    )
    district_features = []
    for raw_feature in districts_raw["features"]:
        name = raw_feature["properties"]["dtname"].strip()
        if name not in csv_districts:
            raise SystemExit(f"District boundary {name!r} has no matching result rows")
        geometry = prepare(shape(raw_feature["geometry"]), DISTRICT_SIMPLIFY)
        district_features.append(feature(geometry, {"name": name}))

    if len(district_features) != EXPECTED_DISTRICTS:
        raise SystemExit(f"Expected 14 district polygons, built {len(district_features)}")

    state_geometry = prepare(
        unary_union([shape(raw_feature["geometry"]) for raw_feature in districts_raw["features"]]),
        STATE_SIMPLIFY,
    )

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    write_geojson(PROCESSED_DIR / "kerala_assembly.geojson", assembly_features)
    write_geojson(PROCESSED_DIR / "kerala_districts.geojson", district_features)
    write_geojson(
        PROCESSED_DIR / "kerala_state.geojson",
        [feature(state_geometry, {"name": "Kerala"})],
    )
    if (RAW_DIR / "KERALA_VILLAGES.geojson").exists() and DISTRICT_DETAILS_JSON.exists():
        build_taluk_boundaries()


SUBDISTRICT_SPLITS = {
    ("Kasaragod", "Kasaragod"): ["Kasaragod", "Manjeshwaram"],
    ("Kasaragod", "Hosdurg"): ["Hosdurg", "Vellarikundu"],
    ("Kannur", "Taliparamba"): ["Taliparamba", "Payyanur"],
    ("Kannur", "Kannur"): ["Kannur"],
    ("Kannur", "Thalassery"): ["Thalassery", "Iritty"],
    ("Wayanad", "Mananthavady"): ["Mananthavady"],
    ("Wayanad", "Sulthanbathery"): ["Sulthan Bathery"],
    ("Wayanad", "Vythiri"): ["Vythiri"],
    ("Kozhikode", "Vadakara"): ["Vadakara"],
    ("Kozhikode", "Quilandy"): ["Koyilandy"],
    ("Kozhikode", "Kozhikode"): ["Kozhikode", "Thamarassery"],
    ("Malappuram", "Ernad"): ["Eranad", "Kondotty"],
    ("Malappuram", "Nilambur"): ["Nilambur"],
    ("Malappuram", "Perinthalmanna"): ["Perinthalmanna"],
    ("Malappuram", "Tirur"): ["Tirur"],
    ("Malappuram", "Tirurangadi"): ["Tirurangadi"],
    ("Malappuram", "Ponnani"): ["Ponnani"],
    ("Palakkad", "Ottappalam"): ["Ottapalam", "Pattambi"],
    ("Palakkad", "Mannarkad"): ["Mannarkkad", "Attappadi"],
    ("Palakkad", "Palakkad"): ["Palakkad"],
    ("Palakkad", "Chittur"): ["Chittur"],
    ("Palakkad", "Alathur"): ["Alathur"],
    ("Thrissur", "Talappilly"): ["Talappilly", "Kunnamkulam"],
    ("Thrissur", "Chavakkad"): ["Chavakkad"],
    ("Thrissur", "Thrissur"): ["Thrissur"],
    ("Thrissur", "Kodungallur"): ["Kodungallur"],
    ("Thrissur", "Mukundapuram"): ["Mukundapuram", "Chalakudy"],
    ("Ernakulam", "Kunnathunad"): ["Kunnathunad"],
    ("Ernakulam", "Aluva"): ["Aluva"],
    ("Ernakulam", "Paravur"): ["North Paravur"],
    ("Ernakulam", "Kochi"): ["Kochi"],
    ("Ernakulam", "Kanayannur"): ["Kanayannur"],
    ("Ernakulam", "Muvattupuzha"): ["Muvattupuzha"],
    ("Ernakulam", "Kothamangalam"): ["Kothamangalam"],
    ("Idukki", "Devikulam"): ["Devikulam"],
    ("Idukki", "Udumbanchola"): ["Udumbanchola", "Idukki"],
    ("Idukki", "Thodupuzha"): ["Thodupuzha", "Idukki"],
    ("Idukki", "Peerumade"): ["Peermade"],
    ("Kottayam", "Meenachil"): ["Meenachil"],
    ("Kottayam", "Vaikom"): ["Vaikom"],
    ("Kottayam", "Kottayam"): ["Kottayam"],
    ("Kottayam", "Changanassery"): ["Changanassery"],
    ("Kottayam", "Kanjirappally"): ["Kanjirappally"],
    ("Alappuzha", "Cherthala"): ["Cherthala"],
    ("Alappuzha", "Ambalappuzha"): ["Ambalappuzha"],
    ("Alappuzha", "Kuttanad"): ["Kuttanad"],
    ("Alappuzha", "Karthikappally"): ["Karthikappally"],
    ("Alappuzha", "Chengannur"): ["Chengannur"],
    ("Alappuzha", "Mavelikkara"): ["Mavelikkara"],
    ("Pathanamthitta", "Thiruvalla"): ["Thiruvalla"],
    ("Pathanamthitta", "Mallappally"): ["Mallappally"],
    ("Pathanamthitta", "Ranni"): ["Ranni"],
    ("Pathanamthitta", "Kozhenchery"): ["Kozhencherry", "Konni"],
    ("Pathanamthitta", "Adoor"): ["Adoor"],
    ("Kollam", "Karunagappally"): ["Karunagappally"],
    ("Kollam", "Kunnathur"): ["Kunnathur"],
    ("Kollam", "Pathanapuram"): ["Pathanapuram", "Punalur"],
    ("Kollam", "Kottarakkara"): ["Kottarakkara"],
    ("Kollam", "Kollam"): ["Kollam"],
    ("Thiruvananthapuram", "Chirayinkeezhu"): ["Chirayinkeezhu", "Varkala"],
    ("Thiruvananthapuram", "Nedumangad"): ["Nedumangad", "Kattakada"],
    ("Thiruvananthapuram", "Thiruvananthapuram"): ["Thiruvananthapuram"],
    ("Thiruvananthapuram", "Neyyattinkara"): ["Neyyattinkara", "Kattakada"],
}


def _norm_village(text: str) -> str:
    cleaned = re.sub(r"\(.*?\)", "", str(text).lower())
    return re.sub(r"[^a-z0-9]", "", cleaned)


def _keep_main_exterior(geometry):
    geometry = polygonal(make_valid(geometry))
    if geometry.geom_type == "Polygon":
        return Polygon(geometry.exterior)
    parts = [part for part in geometry.geoms if part.geom_type == "Polygon"]
    largest = max(parts, key=lambda part: part.area)
    return Polygon(largest.exterior)


def _clean_taluk_geometry(geometry):
    geometry = polygonal(make_valid(geometry))
    if geometry.geom_type == "Polygon":
        return Polygon(geometry.exterior)
    parts = [part for part in geometry.geoms if part.geom_type == "Polygon"]
    max_area = max(part.area for part in parts)
    # Only drop true digitising crumbs. The previous threshold (~6 km² or
    # 15 % of the main part) silently swallowed whole census villages that
    # ended up as separate pieces, leaving multi-km² holes in the taluk map
    # (e.g. the Alur gap between Kunnamkulam/Thrissur/Chavakkad taluks).
    threshold = max(5e-6, max_area * 0.002)
    significant = [Polygon(part.exterior) for part in parts if part.area >= threshold]
    return unary_union(significant)


def build_taluk_boundaries() -> None:
    details = json.loads(DISTRICT_DETAILS_JSON.read_text(encoding="utf-8"))
    subdistricts_raw = json.loads(
        (RAW_DIR / "KERALA_SUBDISTRICTS.geojson").read_text(encoding="utf-8")
    )
    villages_raw = json.loads(
        (RAW_DIR / "KERALA_VILLAGES.geojson").read_text(encoding="utf-8")
    )

    sdt_geoms: dict[tuple[str, str], object] = {}
    for raw_feature in subdistricts_raw["features"]:
        props = raw_feature["properties"]
        key = (props["dtname"].strip(), props["sdtname"].strip())
        sdt_geoms[key] = make_valid(shape(raw_feature["geometry"]))

    villages_by_sdt: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for raw_feature in villages_raw["features"]:
        props = raw_feature["properties"]
        key = (props["DTNAME"].strip().title(), props["SDTNAME"].strip())
        villages_by_sdt[key].append(raw_feature)

    # Build village -> taluk lookup per district
    village_lookup: dict[str, dict[str, str]] = {}
    for district, profile in details.items():
        vmap: dict[str, str] = {}
        for taluk in profile.get("taluks", []):
            for village in taluk["villages"]:
                vmap[_norm_village(village)] = taluk["name"]
        if district == "Idukki":
            vmap["painavu"] = "Idukki"
        village_lookup[district] = vmap

    parts_by_taluk: dict[tuple[str, str], list] = defaultdict(list)
    for (district, sdt_name), child_taluks in SUBDISTRICT_SPLITS.items():
        sdt_geom = sdt_geoms[(district, sdt_name)]
        if len(child_taluks) == 1:
            parts_by_taluk[(district, child_taluks[0])].append(sdt_geom)
            continue

        base_taluk, carved_taluk = child_taluks[0], child_taluks[1]
        vmap = {
            k: v
            for k, v in village_lookup[district].items()
            if v in (base_taluk, carved_taluk)
        }
        known_keys = list(vmap.keys())
        matched: dict[str, list] = defaultdict(list)
        unmatched: list = []

        for raw_feature in villages_by_sdt[(district, sdt_name)]:
            props = raw_feature["properties"]
            vname = _norm_village(
                (props.get("VILNAME11") or "").strip() or props.get("VILNAM_SOI") or ""
            )
            tname = vmap.get(vname)
            if not tname:
                matches = difflib.get_close_matches(vname, known_keys, n=1, cutoff=0.76)
                if matches:
                    tname = vmap[matches[0]]
            vgeom = make_valid(shape(raw_feature["geometry"]))
            if tname:
                matched[tname].append(vgeom)
            else:
                unmatched.append(vgeom)

        carved_core = _keep_main_exterior(
            unary_union(matched[carved_taluk]).buffer(0.002).buffer(-0.002)
        )
        base_core = _keep_main_exterior(
            unary_union(matched[base_taluk]).buffer(0.002).buffer(-0.002)
        )
        for ugeom in unmatched:
            if ugeom.distance(carved_core) < ugeom.distance(base_core):
                matched[carved_taluk].append(ugeom)
            else:
                matched[base_taluk].append(ugeom)

        carved_poly = _keep_main_exterior(
            unary_union(matched[carved_taluk]).buffer(0.003).buffer(-0.003)
        ).intersection(sdt_geom)
        base_poly = sdt_geom.difference(carved_poly)

        parts_by_taluk[(district, carved_taluk)].append(carved_poly)
        parts_by_taluk[(district, base_taluk)].append(base_poly)

    taluk_features = []
    for district, profile in details.items():
        division_by_taluk = {
            tname: division["name"]
            for division in profile.get("revenue_divisions", [])
            for tname in division["taluks"]
        }
        for taluk in profile.get("taluks", []):
            tname = taluk["name"]
            parts = parts_by_taluk.get((district, tname))
            if not parts:
                raise SystemExit(f"No geometry built for taluk {tname} ({district})")
            buf = 0.004 if len(parts) > 1 else 0.0005
            merged = _clean_taluk_geometry(
                unary_union(parts).buffer(buf).buffer(-buf)
            )
            geometry = prepare(merged, DISTRICT_SIMPLIFY)
            taluk_features.append(
                feature(
                    geometry,
                    {
                        "name": tname,
                        "district": district,
                        "headquarters": taluk["headquarters"],
                        "revenue_division": division_by_taluk.get(tname, ""),
                        "village_count": len(taluk["villages"]),
                    },
                )
            )

    write_geojson(PROCESSED_DIR / "kerala_taluks.geojson", taluk_features)


def main() -> int:
    missing = [
        name
        for name in (
            "KERALA_ASSEMBLY.geojson",
            "KERALA_DISTRICTS.geojson",
            *ELECTIONS.values(),
        )
        if not (RAW_DIR / name).exists()
    ]
    if missing:
        raise SystemExit(
            f"Missing raw files: {', '.join(missing)}.\n"
            "Run: uv run --extra data python -m scripts.fetch_data"
        )

    rows_by_year: dict[int, list[dict]] = {}
    for year, filename in sorted(ELECTIONS.items()):
        print(f"Parsing {year} election results...")
        rows = load_results(RAW_DIR / filename, year)
        rows_by_year[year] = rows
        seat_counts = Counter(row["alliance"] for row in rows)
        print(
            f"  {len(rows)} constituencies, {len({row['district'] for row in rows})} districts"
        )
        print(f"  seats: {dict(seat_counts)}")

    # Constituency names drift between Wikipedia revisions ("Dharmadam" vs
    # "Dharmadom"). Keep the earliest spelling and borrow any SC/ST suffix that
    # a later table adds, so the same seat reads the same in every layer.
    print("Harmonising constituency names across elections...")
    canonical = {
        row["ac_no"]: row["name"] for row in rows_by_year[min(rows_by_year)]
    }
    latest_names = {
        row["ac_no"]: row["name"] for row in rows_by_year[max(rows_by_year)]
    }
    for ac_no, name in latest_names.items():
        suffix = re.search(r"\((?:SC|ST)\)$", name)
        if suffix and "(" not in canonical[ac_no]:
            canonical[ac_no] = f"{canonical[ac_no]} {suffix.group(0)}"
    for rows in rows_by_year.values():
        for row in rows:
            row["name"] = canonical[row["ac_no"]]

    all_rows = [row for year in sorted(rows_by_year) for row in rows_by_year[year]]

    print("Checking district headquarters...")
    headquarters = load_headquarters(HQ_CSV)
    result_districts = {row["district"] for row in all_rows}
    hq_districts = {row["district"] for row in headquarters}
    if hq_districts != result_districts:
        missing_hq = sorted(result_districts - hq_districts)
        unknown_hq = sorted(hq_districts - result_districts)
        raise SystemExit(
            f"District headquarters mismatch. Missing: {missing_hq}; unknown: {unknown_hq}"
        )
    print(f"  {len(headquarters)} headquarters")

    print("Writing results CSV...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(RESULTS_CSV, all_rows)

    print("Building simplified boundaries...")
    build_boundaries(rows_by_year[max(rows_by_year)])

    print("Building SQLite database...")
    DB_PATH.unlink(missing_ok=True)
    from app.db import ensure_database

    ensure_database(DB_PATH, RESULTS_CSV, HQ_CSV)
    print(f"  wrote {DB_PATH.name:28} {DB_PATH.stat().st_size / 1024:7.1f} KiB")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
