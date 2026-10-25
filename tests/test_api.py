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


def test_districts_2021(client: TestClient) -> None:
    districts = {row["name"]: row for row in client.get("/api/districts?year=2021").json()}
    ernakulam = districts["Ernakulam"]
    assert ernakulam["seats"] == {"LDF": 5, "UDF": 9, "NDA": 0}
    assert ernakulam["headquarters"]["name"] == "Kakkanad"


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


def test_index(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Kerala" in response.text


def test_health(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
