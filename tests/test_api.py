from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_meta(client: TestClient) -> None:
    response = client.get("/api/meta")
    assert response.status_code == 200
    data = response.json()

    assert data["state"] == "Kerala"
    assert data["default_year"] == 2026
    assert [entry["year"] for entry in data["years"]] == [2026, 2021]

    by_year = {entry["year"]: entry for entry in data["years"]}
    assert by_year[2026]["counts"]["alliances"] == {"LDF": 35, "UDF": 102, "NDA": 3}
    assert by_year[2021]["counts"]["alliances"] == {"LDF": 99, "UDF": 41, "NDA": 0}
    assert by_year[2026]["source"].endswith("2026_Kerala_Legislative_Assembly_election")

    alliances = {row["name"]: row["seats"] for row in by_year[2026]["alliances"]}
    assert alliances == {"LDF": 35, "UDF": 102, "NDA": 3}
    assert len(data["sources"]) >= 4


def test_constituencies_default_to_latest(client: TestClient) -> None:
    response = client.get("/api/constituencies")
    assert response.status_code == 200
    rows = response.json()

    assert len(rows) == 140
    assert [row["ac_no"] for row in rows] == list(range(1, 141))
    assert all(row["election_year"] == 2026 for row in rows)
    assert all(row["winner"] for row in rows)
    assert all(row["district"] for row in rows)

    perumbavoor = next(row for row in rows if row["name"] == "Perumbavoor")
    # Source table's margin column has a two-vote typo; the derived value wins.
    assert perumbavoor["margin"] == 28432

    ettumanoor = next(row for row in rows if row["name"] == "Ettumanoor")
    assert ettumanoor["runner_up"] == "V. Vasavan"

    devikulam = next(row for row in rows if row["ac_no"] == 104)
    assert devikulam["winner"] == "A. D. Thomas"


def test_constituencies_2021(client: TestClient) -> None:
    response = client.get("/api/constituencies?year=2021")
    assert response.status_code == 200
    rows = response.json()

    assert len(rows) == 140
    assert all(row["election_year"] == 2021 for row in rows)
    thiruvambady = next(row for row in rows if row["name"] == "Thiruvambady")
    assert thiruvambady["margin"] == 67867 - 63224


def test_single_constituency(client: TestClient) -> None:
    row = client.get("/api/constituencies/12").json()

    assert row["name"] == "Dharmadam"
    assert row["winner"] == "Pinarayi Vijayan"
    assert row["party"] == "CPI(M)"
    assert row["alliance"] == "LDF"
    assert row["election_year"] == 2026
    assert row["margin"] == 19247


def test_single_constituency_2021(client: TestClient) -> None:
    row = client.get("/api/constituencies/12?year=2021").json()
    assert row["election_year"] == 2021
    assert row["winner"] == "Pinarayi Vijayan"
    assert row["margin"] == 50123


def test_unknown_constituency(client: TestClient) -> None:
    assert client.get("/api/constituencies/999").status_code == 404


def test_unknown_year(client: TestClient) -> None:
    for path in (
        "/api/constituencies",
        "/api/districts",
        "/api/geojson/constituencies",
        "/api/geojson/districts",
    ):
        response = client.get(f"{path}?year=2022")
        assert response.status_code == 404, path


def test_districts(client: TestClient) -> None:
    response = client.get("/api/districts")
    assert response.status_code == 200
    districts = {row["name"]: row for row in response.json()}

    assert len(districts) == 14
    ernakulam = districts["Ernakulam"]
    assert ernakulam["ac_count"] == 14
    assert ernakulam["seats"] == {"LDF": 0, "UDF": 14, "NDA": 0}
    assert ernakulam["leading"] == "UDF"
    assert ernakulam["headquarters"] == {
        "name": "Kakkanad",
        "lat": pytest.approx(10.01657),
        "lng": pytest.approx(76.34275),
    }
    assert all(district["has_details"] is True for district in districts.values())


def test_districts_2021(client: TestClient) -> None:
    districts = {row["name"]: row for row in client.get("/api/districts?year=2021").json()}
    ernakulam = districts["Ernakulam"]
    assert ernakulam["seats"] == {"LDF": 5, "UDF": 9, "NDA": 0}
    assert ernakulam["headquarters"]["name"] == "Kakkanad"


def test_district_details(client: TestClient) -> None:
    response = client.get("/api/districts/Thrissur/details")
    assert response.status_code == 200
    data = response.json()

    assert data["district"] == "Thrissur"
    assert data["counts"] == {
        "revenue_divisions": 2,
        "taluks": 7,
        "villages": 255,
        "blocks": 16,
        "gram_panchayats": 86,
        "municipalities": 7,
        "municipal_corporations": 1,
        "towns": 135,
        "census_towns": 127,
        "assembly_seats": 13,
        "parliamentary_seats": 3,
    }

    divisions = {division["name"]: division["taluks"] for division in data["revenue_divisions"]}
    assert divisions["Thrissur"] == ["Thrissur", "Chavakkad", "Talappilly", "Kunnamkulam"]
    assert divisions["Irinjalakuda"] == ["Mukundapuram", "Chalakudy", "Kodungallur"]

    taluks = {taluk["name"]: taluk for taluk in data["taluks"]}
    assert len(taluks) == 7
    assert sum(len(taluk["villages"]) for taluk in taluks.values()) == 255
    assert len(taluks["Thrissur"]["villages"]) == 74
    assert taluks["Talappilly"]["headquarters"] == "Wadakkanchery"
    assert taluks["Mukundapuram"]["headquarters"] == "Irinjalakuda"

    blocks = data["local_government"]["blocks"]
    assert len(blocks) == 16
    assert sum(len(block["gram_panchayats"]) for block in blocks) == 86
    puzhakkal = next(block for block in blocks if block["name"] == "Puzhakkal")
    assert len(puzhakkal["gram_panchayats"]) == 6
    assert "Adat" in puzhakkal["gram_panchayats"]

    towns = data["towns"]
    assert len(towns) == 135
    assert sum(1 for town in towns if town["status"] == "Municipality") == 7
    assert sum(1 for town in towns if town["status"] == "Municipal corporation") == 1
    assert all(town["population_2011"] > 0 for town in towns)

    assert [seat["ac_no"] for seat in data["assembly_seats"]] == list(range(61, 74))
    assert data["assembly_seats"][-1] == {"ac_no": 73, "name": "Kodungallur"}
    assert data["parliamentary_seats"] == ["Thrissur", "Chalakudy", "Alathur"]
    assert len(data["sources"]) >= 4


def test_district_details_case_insensitive(client: TestClient) -> None:
    response = client.get("/api/districts/thrissur/details")
    assert response.status_code == 200
    assert response.json()["district"] == "Thrissur"


def test_district_details_all_districts(client: TestClient) -> None:
    districts = client.get("/api/districts").json()
    assert len(districts) == 14
    for district in districts:
        name = district["name"]
        response = client.get(f"/api/districts/{name}/details")
        assert response.status_code == 200, name
        data = response.json()
        assert data["district"] == name
        assert data["summary"]
        counts = data["counts"]
        assert counts["revenue_divisions"] >= 1
        assert counts["taluks"] >= 3
        assert counts["villages"] > 0
        assert counts["blocks"] >= 4
        assert counts["gram_panchayats"] > 0
        assert counts["towns"] == (
            counts["municipalities"] + counts["municipal_corporations"] + counts["census_towns"]
        )
        assert counts["assembly_seats"] == district["ac_count"]
        assert counts["parliamentary_seats"] >= 1
        assert len(data["sources"]) >= 4


def test_district_details_unknown(client: TestClient) -> None:
    response = client.get("/api/districts/Atlantis/details")
    assert response.status_code == 404
    assert "No administrative profile" in response.json()["detail"]


def test_district_headquarters(client: TestClient) -> None:
    response = client.get("/api/district-headquarters")
    assert response.status_code == 200
    rows = response.json()

    assert len(rows) == 14
    hqs = {row["district"]: row["headquarters"] for row in rows}
    assert hqs["Ernakulam"] == "Kakkanad"
    assert hqs["Idukki"] == "Painavu"
    assert hqs["Wayanad"] == "Kalpetta"


def test_constituency_geojson(client: TestClient) -> None:
    response = client.get("/api/geojson/constituencies")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/geo+json")

    data = response.json()
    features = data["features"]
    assert len(features) == 140
    assert sorted(feature["properties"]["ac_no"] for feature in features) == list(range(1, 141))

    sample = next(
        feature for feature in features if feature["properties"]["ac_no"] == 12
    )
    assert sample["properties"]["winner"] == "Pinarayi Vijayan"
    assert sample["properties"]["election_year"] == 2026
    assert isinstance(sample["properties"]["label_lat"], float)
    assert isinstance(sample["properties"]["label_lng"], float)
    assert sample["geometry"]["type"] in {"Polygon", "MultiPolygon"}


def test_constituency_geojson_2021(client: TestClient) -> None:
    features = client.get("/api/geojson/constituencies?year=2021").json()["features"]
    assert len(features) == 140
    assert all(feature["properties"]["election_year"] == 2021 for feature in features)


def test_district_geojson(client: TestClient) -> None:
    response = client.get("/api/geojson/districts")
    assert response.status_code == 200

    features = response.json()["features"]
    assert len(features) == 14
    names = {feature["properties"]["name"] for feature in features}
    assert names == {
        "Kasaragod",
        "Kannur",
        "Wayanad",
        "Kozhikode",
        "Malappuram",
        "Palakkad",
        "Thrissur",
        "Ernakulam",
        "Idukki",
        "Kottayam",
        "Alappuzha",
        "Pathanamthitta",
        "Kollam",
        "Thiruvananthapuram",
    }
    assert all("seats" in feature["properties"] for feature in features)
    assert all("headquarters" in feature["properties"] for feature in features)


def test_state_geojson(client: TestClient) -> None:
    response = client.get("/api/geojson/state")
    assert response.status_code == 200
    feature = response.json()["features"][0]
    assert feature["geometry"]["type"] in {"Polygon", "MultiPolygon"}


def test_taluks_geojson(client: TestClient) -> None:
    response = client.get("/api/geojson/taluks")
    assert response.status_code == 200
    features = response.json()["features"]
    assert len(features) == 78
    # Talappilly legitimately has a detached part (Alur village piece is
    # separated from the main body by the Kunnamkulam carve).
    assert all(f["geometry"]["type"] in {"Polygon", "MultiPolygon"} for f in features)
    thrissur_taluks = {
        f["properties"]["name"]
        for f in features
        if f["properties"]["district"] == "Thrissur"
    }
    assert thrissur_taluks == {
        "Thrissur",
        "Chavakkad",
        "Talappilly",
        "Kunnamkulam",
        "Mukundapuram",
        "Chalakudy",
        "Kodungallur",
    }


def test_index(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Kerala" in response.text
    assert 'integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="' in response.text
    assert 'integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="' in response.text


def test_health(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_openapi_schemas(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    schemas = schema.get("components", {}).get("schemas", {})
    assert "ConstituencyResult" in schemas
    assert "DistrictSummary" in schemas
    assert "DistrictProfile" in schemas
    assert "MetaResponse" in schemas


def test_geojson_etag_caching(client: TestClient) -> None:
    for path in (
        "/api/geojson/constituencies",
        "/api/geojson/districts",
        "/api/geojson/state",
    ):
        first = client.get(path)
        assert first.status_code == 200
        etag = first.headers.get("etag")
        assert etag and etag.startswith('W/"')

        cached = client.get(path, headers={"If-None-Match": etag})
        assert cached.status_code == 304
        assert cached.text == ""


def test_static_export(tmp_path) -> None:
    from scripts.export_static import export_static

    export_static(tmp_path)
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "static" / "js" / "app.js").exists()
    assert (tmp_path / "api" / "meta.json").exists()
    assert (tmp_path / "api" / "constituencies-2026.json").exists()
    assert (tmp_path / "api" / "constituencies-2021.json").exists()
    assert (tmp_path / "api" / "geojson" / "constituencies-2026.json").exists()
    assert (tmp_path / "api" / "geojson" / "taluks.json").exists()
    assert (tmp_path / "api" / "districts" / "Thrissur" / "details.json").exists()


def test_atomic_ensure_database(tmp_path) -> None:
    from app.config import HQ_CSV, RESULTS_CSV
    from app.db import ensure_database, fetch_headquarters, fetch_results

    db_file = tmp_path / "kerala.db"
    ensure_database(db_file, RESULTS_CSV, HQ_CSV)
    assert db_file.exists()
    assert len(fetch_results(db_file)) == 280
    assert len(fetch_headquarters(db_file)) == 14
    # Calling a second time is a fast no-op when CSVs haven't changed
    mtime_before = db_file.stat().st_mtime
    ensure_database(db_file, RESULTS_CSV, HQ_CSV)
    assert db_file.stat().st_mtime == mtime_before
