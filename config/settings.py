import os
import psycopg2
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _get(key: str, default: str = "") -> str:
    """
    Reads from os.environ first (local .env via python-dotenv).
    Falls back to Streamlit secrets when running on Streamlit Cloud,
    where credentials are injected via st.secrets instead of .env.
    """
    val = os.getenv(key)
    if val:
        return val
    try:
        import streamlit as st
        return st.secrets.get(key, default)
    except Exception:
        return default


DB_CONFIG = {
    "host":                _get("DB_HOST"),
    "port":                int(_get("DB_PORT", "5432")),
    "dbname":              _get("DB_NAME"),
    "user":                _get("DB_USER"),
    "password":            _get("DB_PASSWORD"),
    "sslmode":             "require",   # Neon requires SSL; some hosts won't default to it
    "keepalives":          1,
    "keepalives_idle":     30,
    "keepalives_interval": 10,
    "keepalives_count":    5,
    "connect_timeout":     10,
}

TMDB_API_KEY = _get("TMDB_API_KEY")

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
RAW_DIR  = DATA_DIR / "raw" / "movielens"
LOG_DIR  = ROOT_DIR / "logs"

try:
    LOG_DIR.mkdir(exist_ok=True)
except OSError:
    # Streamlit Cloud's filesystem can be read-only in some mount contexts —
    # logging to file isn't critical there, console logging still works.
    pass


def get_env(key: str, default: str = "") -> str:
    return _get(key, default)


def get_connection() -> psycopg2.extensions.connection:
    import time
    import logging

    missing = [k for k in ("host", "dbname", "user", "password") if not DB_CONFIG.get(k)]
    if missing:
        raise psycopg2.OperationalError(
            f"Missing DB config values: {missing}. "
            f"Check your .env locally or Streamlit Secrets in the cloud dashboard."
        )

    last_err = None
    for attempt in range(3):
        try:
            return psycopg2.connect(**DB_CONFIG)
        except psycopg2.OperationalError as e:
            last_err = e
            wait = 2 ** attempt
            logging.getLogger(__name__).warning(
                "DB connection attempt %d failed, retrying in %ds: %s", attempt + 1, wait, e
            )
            time.sleep(wait)
    raise last_err