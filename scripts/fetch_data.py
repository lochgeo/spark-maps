"""Download the raw boundary files and the election results pages.

Sources are pinned to exact revisions so the build is reproducible.
Run from the project root:

    uv run --extra data python -m scripts.fetch_data
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

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
    "KERALA_STATE.geojson": f"{GEO_BASE}/KERALA_STATE.geojson",
    **{
        f"election_{year}.html": f"https://en.wikipedia.org/w/index.php?oldid={revision}"
        for year, revision in WIKI_REVISIONS.items()
    },
}

USER_AGENT = "spark-maps/0.1 (Kerala mapping project; data build script)"


def download(url: str, destination: Path, force: bool = False) -> None:
    if destination.exists() and not force:
        print(f"  skip  {destination.name} (already present)")
        return

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    print(f"  get   {destination.name}")
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()

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
    for name, url in FILES.items():
        download(url, RAW_DIR / name, force=args.force)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
