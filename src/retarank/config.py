"""Central, machine-independent project settings."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
INTERIM_DATA_DIR = DATA_DIR / "interim"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

LOOKBACK_DAYS = 180
OUTCOME_DAYS = 90
CONTACT_CAPACITIES = (0.10, 0.20, 0.30)
RANDOM_SEED = 42
