"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import DB_PATH, HQ_CSV, PROCESSED_DIR, RESULTS_CSV, STATIC_DIR
from .db import ensure_database
from .schemas import (
    ConstituencyResult,
    DistrictHeadquartersRow,
    DistrictProfile,
    DistrictSummary,
    HealthResponse,
    MetaResponse,
)
from .store import DataStore

store = DataStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_database(DB_PATH, RESULTS_CSV, HQ_CSV)
    store.load(DB_PATH, PROCESSED_DIR)
    yield


app = FastAPI(
    title="Kerala Map API",
    description=(
        "Districts and legislative assembly constituencies of Kerala, with the "
        "winning MLA for the 2021 and 2026 elections, plus administrative "
        "profiles for districts that have them."
    ),
    version="0.3.0",
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=800)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

CACHE_CONTROL = "public, max-age=300, stale-while-revalidate=3600"


def _cached_geojson_response(request: Request, content: str, etag: str) -> Response:
    headers = {"Cache-Control": CACHE_CONTROL, "ETag": etag}
    inm = request.headers.get("if-none-match")
    if inm and (etag in inm or inm.strip() == "*"):
        return Response(status_code=304, headers=headers)
    return Response(
        content=content,
        media_type="application/geo+json",
        headers=headers,
    )


def resolve_year(year: int | None) -> int:
    if year is None:
        return store.default_year
    if year not in store.results_by_year:
        raise HTTPException(
            status_code=404,
            detail=f"No results for {year}. Available: {', '.join(map(str, store.years))}",
        )
    return year


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz", response_model=HealthResponse, include_in_schema=False)
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/meta", response_model=MetaResponse, tags=["meta"])
def get_meta() -> dict:
    return store.meta


@app.get("/api/constituencies", response_model=list[ConstituencyResult], tags=["constituencies"])
def list_constituencies(year: int | None = None) -> list[dict]:
    return store.results_by_year[resolve_year(year)]


@app.get(
    "/api/constituencies/{ac_no}",
    response_model=ConstituencyResult,
    tags=["constituencies"],
)
def get_constituency(ac_no: int, year: int | None = None) -> dict:
    resolved = resolve_year(year)
    row = store.by_ac_by_year[resolved].get(ac_no)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Constituency {ac_no} not found")
    return row


@app.get("/api/districts", response_model=list[DistrictSummary], tags=["districts"])
def list_districts(year: int | None = None) -> list[dict]:
    return store.districts_by_year[resolve_year(year)]


@app.get(
    "/api/districts/{name}/details",
    response_model=DistrictProfile,
    tags=["districts"],
)
def get_district_details(name: str) -> dict:
    profile = store.district_details.get(name)
    if profile is None:
        profile = next(
            (
                candidate
                for key, candidate in store.district_details.items()
                if key.casefold() == name.casefold()
            ),
            None,
        )
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail=f"No administrative profile for {name}. Available: "
            + (", ".join(sorted(store.district_details)) or "none"),
        )
    return profile


@app.get(
    "/api/district-headquarters",
    response_model=list[DistrictHeadquartersRow],
    tags=["districts"],
)
def list_district_headquarters() -> list[dict]:
    return store.headquarters


@app.get("/api/geojson/constituencies", tags=["geojson"])
def constituencies_geojson(request: Request, year: int | None = None) -> Response:
    resolved = resolve_year(year)
    return _cached_geojson_response(
        request,
        store.constituencies_geojson[resolved],
        store.constituencies_etag[resolved],
    )


@app.get("/api/geojson/districts", tags=["geojson"])
def districts_geojson(request: Request, year: int | None = None) -> Response:
    resolved = resolve_year(year)
    return _cached_geojson_response(
        request,
        store.districts_geojson[resolved],
        store.districts_etag[resolved],
    )


@app.get("/api/geojson/state", tags=["geojson"])
def state_geojson(request: Request) -> Response:
    return _cached_geojson_response(
        request,
        store.state_geojson,
        store.state_etag,
    )


@app.get("/api/geojson/taluks", tags=["geojson"])
def taluks_geojson(request: Request) -> Response:
    return _cached_geojson_response(
        request,
        store.taluks_geojson,
        store.taluks_etag,
    )
