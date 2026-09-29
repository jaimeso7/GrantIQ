"""Environment configuration; importing this module has no network effects."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
DATA_DIR = Path(os.getenv("GRANTIQ_DATA_DIR", str(ROOT / "data")))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'grantiq.db'}")
os.environ.setdefault("GRANTIQ_MODEL_CACHE", str(DATA_DIR / "models"))
os.environ.setdefault("HF_HOME", str(DATA_DIR / "models"))
os.environ.setdefault("GRANTIQ_CACHE_DIR", str(DATA_DIR / "cache"))
