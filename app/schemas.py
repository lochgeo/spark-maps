"""Pydantic response models for the Kerala Map API."""

from __future__ import annotations

from pydantic import BaseModel


class SourceLink(BaseModel):
    label: str
    url: str
    short: str | None = None


class AllianceSeats(BaseModel):
    name: str
    seats: int


class YearCounts(BaseModel):
    constituencies: int
    districts: int
    alliances: dict[str, int]


class YearMeta(BaseModel):
    year: int
    counts: YearCounts
    alliances: list[AllianceSeats]
    source: str


class MetaResponse(BaseModel):
    state: str
    default_year: int
    years: list[YearMeta]
    sources: list[SourceLink]


class ConstituencyResult(BaseModel):
    ac_no: int
    election_year: int
    name: str
    district: str
    winner: str
    party: str
    alliance: str
    votes: int
    vote_share: float
    runner_up: str
    runner_up_party: str
    margin: int


class HeadquartersPoint(BaseModel):
    name: str
    lat: float
    lng: float


class DistrictHeadquartersRow(BaseModel):
    district: str
    headquarters: str
    latitude: float
    longitude: float


class DistrictSummary(BaseModel):
    name: str
    ac_count: int
    seats: dict[str, int]
    leading: str
    ac_nos: list[int]
    headquarters: HeadquartersPoint
    has_details: bool


class DistrictCounts(BaseModel):
    revenue_divisions: int
    taluks: int
    villages: int
    blocks: int
    gram_panchayats: int
    municipalities: int
    municipal_corporations: int
    towns: int
    census_towns: int
    assembly_seats: int
    parliamentary_seats: int


class DistrictDemographics(BaseModel):
    area_km2: int
    population: int
    population_year: int
    density_per_km2: int
    literacy_rate: float
    sex_ratio: int
    urban_share: float


class RevenueDivision(BaseModel):
    name: str
    taluks: list[str]


class TalukProfile(BaseModel):
    name: str
    headquarters: str
    villages: list[str]


class BlockProfile(BaseModel):
    name: str
    gram_panchayats: list[str]


class LocalGovernmentProfile(BaseModel):
    district_panchayat: str
    blocks: list[BlockProfile]
    municipalities: list[str]
    municipal_corporations: list[str]


class TownProfile(BaseModel):
    name: str
    population_2011: int
    status: str


class AssemblySeatRef(BaseModel):
    ac_no: int
    name: str


class DistrictProfile(BaseModel):
    district: str
    retrieved: str
    summary: str
    demographics: DistrictDemographics
    revenue_divisions: list[RevenueDivision]
    taluks: list[TalukProfile]
    local_government: LocalGovernmentProfile
    towns: list[TownProfile]
    assembly_seats: list[AssemblySeatRef]
    parliamentary_seats: list[str]
    counts: DistrictCounts
    sources: list[SourceLink]


class HealthResponse(BaseModel):
    status: str
