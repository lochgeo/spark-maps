"""Application paths and constants."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

RESULTS_CSV = DATA_DIR / "results.csv"
HQ_CSV = DATA_DIR / "district_hqs.csv"
DB_PATH = DATA_DIR / "kerala.db"
