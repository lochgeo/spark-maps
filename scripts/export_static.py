"""Export the application as a self-contained static site in ``dist/``.

The exported site can be hosted on GitHub Pages, Cloudflare Pages, Netlify, or
any static file server with zero Python runtime required.

Run from the project root:

    uv run python -m scripts.export_static
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from app.config import DB_PATH, HQ_CSV, PROCESSED_DIR, RESULTS_CSV, ROOT, STATIC_DIR
from app.db import ensure_database
from app.store import DataStore

DEFAULT_OUT = ROOT / "dist"


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )


def _write_raw(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def export_static(out_dir: Path) -> None:
    ensure_database(DB_PATH, RESULTS_CSV, HQ_CSV)
    store = DataStore()
    store.load(DB_PATH, PROCESSED_DIR)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Copy static assets into dist/static/
    static_dest = out_dir / "static"
    shutil.copytree(STATIC_DIR, static_dest)

    # Prepare root index.html with static export flag and relative asset paths
    index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    index_html = index_html.replace('href="/static/', 'href="./static/')
    index_html = index_html.replace('src="/static/', 'src="./static/')
    index_html = index_html.replace(
        '<script type="module" src="./static/js/app.js"></script>',
        '<script>window.__STATIC_EXPORT__ = true;</script>\n'
        '  <script type="module" src="./static/js/app.js"></script>',
    )
    (out_dir / "index.html").write_text(index_html, encoding="utf-8")

    # Add .nojekyll so GitHub Pages serves everything cleanly
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    # Write pre-computed API payloads
    api_dir = out_dir / "api"
    _write_json(api_dir / "meta.json", store.meta)
    _write_json(api_dir / "district-headquarters.json", store.headquarters)
    _write_raw(api_dir / "geojson" / "state.json", store.state_geojson)
    _write_raw(api_dir / "geojson" / "taluks.json", store.taluks_geojson)

    for year in store.years:
        _write_json(api_dir / f"constituencies-{year}.json", store.results_by_year[year])
        _write_json(api_dir / f"districts-{year}.json", store.districts_by_year[year])
        _write_raw(
            api_dir / "geojson" / f"constituencies-{year}.json",
            store.constituencies_geojson[year],
        )
        _write_raw(
            api_dir / "geojson" / f"districts-{year}.json",
            store.districts_geojson[year],
        )

    for name, profile in store.district_details.items():
        _write_json(api_dir / "districts" / name / "details.json", profile)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="Destination directory (default: dist/)",
    )
    args = parser.parse_args()
    export_static(args.out)
    print(f"Exported static site to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
