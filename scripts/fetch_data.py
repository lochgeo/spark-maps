"""Download the raw boundary files and the election results pages.

Sources are pinned to exact revisions so the build is reproducible.
Run from the project root:

    uv run --extra data python -m scripts.fetch_data
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"

# datta07/INDIAN-SHAPEFILES, pinned commit from 2022-02-21.
GEO_COMMIT = "7b003e3e8c35491fadf71ced7f168f18a7423bf3"
GEO_BASE = (
    f"https://raw.githubusercontent.com/datta07/INDIAN-SHAPEFILES/{GEO_COMMIT}/STATES/KERALA"
)

# Revisions of the Wikipedia articles used for the result tables.
WIKI_REVISIONS = {
    2021: 1378901836,
    2026: 1381519237,
}

FILES = {
    "KERALA_ASSEMBLY.geojson": f"{GEO_BASE}/KERALA_ASSEMBLY.geojson",
    "KERALA_DISTRICTS.geojson": f"{GEO_BASE}/KERALA_DISTRICTS.geojson",
    "KERALA_SUBDISTRICTS.geojson": f"{GEO_BASE}/KERALA_SUBDISTRICTS.geojson",
    "KERALA_VILLAGES.geojson": f"{GEO_BASE}/KERALA_VILLAGES.geojson",
    **{
        f"election_{year}.html": f"https://en.wikipedia.org/w/index.php?oldid={revision}"
        for year, revision in WIKI_REVISIONS.items()
    },
}

USER_AGENT = "spark-maps/0.3 (Kerala mapping project; data build script)"


def download(
    client: httpx.Client, url: str, destination: Path, force: bool = False
) -> None:
    if destination.exists() and not force:
        print(f"  skip  {destination.name} (already present)")
        return

    print(f"  get   {destination.name}")
    response = client.get(url)
    response.raise_for_status()
    payload = response.content

    if len(payload) < 1000:
        raise RuntimeError(f"Downloaded file looks too small ({len(payload)} bytes): {url}")
    destination.write_bytes(payload)
    print(f"        {len(payload) / 1024:.0f} KiB")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download existing files")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading raw data into {RAW_DIR}")
    transport = httpx.HTTPTransport(retries=3)
    with httpx.Client(
        transport=transport,
        follow_redirects=True,
        timeout=120,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for name, url in FILES.items():
            download(client, url, RAW_DIR / name, force=args.force)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
