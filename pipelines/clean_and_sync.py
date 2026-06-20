import sys
import time
import logging
import argparse
from datetime import datetime, timedelta

import requests
import psycopg2
import psycopg2.extras

from config.settings import get_connection, get_env, TMDB_API_KEY, LOG_DIR
from utils.text_cleaner import clean_title, clean_genres, clean_text, audit_text

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

log = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "clean_and_sync.log"),
    ],
)

TMDB_KEY   = TMDB_API_KEY or ""
TMDB_BASE  = "https://api.themoviedb.org/3"
POSTER_BASE = "https://image.tmdb.org/t/p/w500"
TMDB_DELAY = float(get_env("TMDB_CALL_DELAY", "0.26"))


class TMDBClient:
    def __init__(self, api_key: str):
        self.session = requests.Session()
        self.session.params = {"api_key": api_key}

    def _get(self, path: str, **params) -> dict | None:
        url = TMDB_BASE + path
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, timeout=12)
                if r.status_code == 429:
                    wait = int(r.headers.get("Retry-After", 15))
                    log.warning("TMDB rate-limited - waiting %ds", wait)
                    time.sleep(wait)
                    continue
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.json()
            except requests.RequestException as exc:
                log.warning("TMDB attempt %d failed: %s", attempt + 1, exc)
                time.sleep(2 ** attempt)
        return None

    def search(self, title: str, year: int | None = None) -> dict | None:
        params: dict = {"query": title, "include_adult": False}
        if year:
            params["primary_release_year"] = year
        data = self._get("/search/movie", **params)
        if data and data.get("results"):
            return data["results"][0]
        if year:
            data = self._get("/search/movie", query=title, include_adult=False)
            if data and data.get("results"):
                return data["results"][0]
        return None

    def poster_url(self, result: dict) -> str:
        path = result.get("poster_path") or ""
        return (POSTER_BASE + path) if path else ""

    def discover_recent(self, days: int = 7, max_pages: int = 5) -> list[dict]:
        end   = datetime.today().strftime("%Y-%m-%d")
        start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
        movies: list[dict] = []
        for page in range(1, max_pages + 1):
            data = self._get(
                "/discover/movie",
                sort_by="release_date.desc",
                **{"release_date.gte": start, "release_date.lte": end},
                page=page,
                include_adult=False,
            )
            if not data or not data.get("results"):
                break
            movies.extend(data["results"])
            if page >= data.get("total_pages", 1):
                break
            time.sleep(TMDB_DELAY)
        log.info("TMDB discover: found %d candidate movies (last %d days)", len(movies), days)
        return movies


NEW_COLUMNS = [
    ("title_clean",       "TEXT"),
    ("release_year",      "SMALLINT"),
    ("poster_url",        "TEXT"),
    ("tmdb_id",           "INTEGER"),
    ("cleaned_at",        "TIMESTAMP"),
    ("poster_fetched_at", "TIMESTAMP"),
]


def migrate_schema(conn) -> None:
    with conn.cursor() as cur:
        for col, col_type in NEW_COLUMNS:
            cur.execute(f"ALTER TABLE movies ADD COLUMN IF NOT EXISTS {col} {col_type};")

        # Ensure movie_id has a primary key — required for ON CONFLICT upserts
        # in run_new_movie_sync(). Safe no-op if it already exists.
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'movies'::regclass
                    AND   contype = 'p'
                ) THEN
                    ALTER TABLE movies ADD CONSTRAINT movies_pkey PRIMARY KEY (movie_id);
                END IF;
            END $$;
        """)
    conn.commit()
    log.info("Schema migration complete")


def run_audit(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT title FROM movies WHERE title IS NOT NULL")
        titles = [r[0] for r in cur.fetchall()]

    results = audit_text(titles)
    if not results:
        log.info("Audit: no special characters found")
        return

    log.info("Audit: %d unique special characters in %d titles", len(results), len(titles))
    log.info("  %-6s %-10s %6s  %-35s  %s", "Char", "Unicode", "Count", "Name", "Action")
    log.info("  " + "-" * 75)
    for r in results:
        log.info(
            "  %-6s %-10s %6d  %-35s  %s",
            repr(r["char"]), r["unicode_point"], r["count"],
            r["unicode_name"][:34], r["action"],
        )


def run_cleaning(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT movie_id, title, genres FROM movies WHERE title_clean IS NULL")
        rows = cur.fetchall()

    if not rows:
        log.info("Cleaning: all rows already cleaned - nothing to do")
        return

    log.info("Cleaning %d movie records...", len(rows))
    updates = []
    for movie_id, title, genres in rows:
        cleaned_title, year = clean_title(title or "")
        cleaned_genres      = clean_genres(genres or "")
        updates.append((cleaned_title, year, cleaned_genres, datetime.utcnow(), movie_id))

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            """
            UPDATE movies
            SET title_clean  = %s,
                release_year = %s,
                genres       = %s,
                cleaned_at   = %s
            WHERE movie_id   = %s
            """,
            updates,
            page_size=500,
        )
    conn.commit()
    log.info("Cleaning done: %d rows updated", len(updates))


def run_poster_fetch(conn, tmdb: TMDBClient, limit: int | None = None) -> None:
    with conn.cursor() as cur:
        query = """
            SELECT movie_id, title_clean, release_year
            FROM   movies
            WHERE  poster_url IS NULL
            AND    poster_fetched_at IS NULL
            AND    title_clean IS NOT NULL
            ORDER  BY movie_id
        """
        if limit:
            query += f" LIMIT {limit}"
        cur.execute(query)
        rows = cur.fetchall()

    if not rows:
        log.info("Poster fetch: nothing to do")
        return

    log.info("Fetching posters for %d movies...", len(rows))
    found = 0

    for i, (movie_id, title, year) in enumerate(rows, 1):
        result  = tmdb.search(title, year)
        poster  = tmdb.poster_url(result) if result else ""
        tmdb_id = result.get("id") if result else None

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE movies
                SET poster_url        = %s,
                    tmdb_id           = %s,
                    poster_fetched_at = %s
                WHERE movie_id = %s
                """,
                (poster or None, tmdb_id, datetime.utcnow(), movie_id),
            )
        conn.commit()

        if poster:
            found += 1
        if i % 200 == 0:
            log.info("  Progress: %d / %d  (posters found: %d)", i, len(rows), found)

        time.sleep(TMDB_DELAY)

    log.info("Poster fetch done - found: %d / %d", found, len(rows))


def run_new_movie_sync(conn, tmdb: TMDBClient, days: int = 7) -> None:
    candidates = tmdb.discover_recent(days=days)
    if not candidates:
        return

    with conn.cursor() as cur:
        cur.execute("SELECT tmdb_id FROM movies WHERE tmdb_id IS NOT NULL")
        existing_tmdb_ids = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT COALESCE(MAX(movie_id), 0) FROM movies")
        max_id = cur.fetchone()[0]

    inserted = 0
    for raw in candidates:
        tmdb_id = raw.get("id")
        if not tmdb_id or tmdb_id in existing_tmdb_ids:
            continue

        raw_title  = raw.get("title", "")
        clean, year = clean_title(raw_title)
        poster     = tmdb.poster_url(raw)
        genre_ids  = raw.get("genre_ids", [])
        genres_str = "|".join(str(g) for g in genre_ids)

        if not year and raw.get("release_date"):
            try:
                year = int(raw["release_date"][:4])
            except (ValueError, TypeError):
                pass

        max_id += 1
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO movies
                    (movie_id, title, title_clean, release_year, genres,
                     poster_url, tmdb_id, cleaned_at, poster_fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (movie_id) DO NOTHING
                """,
                (
                    max_id, raw_title, clean, year, genres_str,
                    poster or None, tmdb_id,
                    datetime.utcnow(), datetime.utcnow(),
                ),
            )
        conn.commit()
        existing_tmdb_ids.add(tmdb_id)
        inserted += 1

    log.info("New movie sync: %d movies inserted", inserted)


def log_stats(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM movies")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM movies WHERE title_clean IS NOT NULL")
        cleaned = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM movies WHERE poster_url IS NOT NULL")
        with_poster = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM movies WHERE poster_fetched_at IS NULL")
        unfetched = cur.fetchone()[0]

    log.info("-" * 55)
    log.info("  Total movies    : %d", total)
    log.info("  Titles cleaned  : %d / %d", cleaned, total)
    log.info("  With poster URL : %d / %d", with_poster, total)
    log.info("  Awaiting fetch  : %d", unfetched)
    log.info("-" * 55)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ke-netflix: clean titles + sync TMDB posters")
    p.add_argument("--audit",           action="store_true")
    p.add_argument("--clean-only",      action="store_true")
    p.add_argument("--tmdb-only",       action="store_true")
    p.add_argument("--new-movies-days", type=int, default=0)
    p.add_argument("--poster-limit",    type=int, default=None)
    p.add_argument("--skip-stats",      action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not TMDB_KEY and not args.clean_only and not args.audit:
        log.error("TMDB_KEY not set. Use --clean-only or set the env variable.")
        sys.exit(1)

    conn = get_connection()
    log.info("Pipeline starting: clean_and_sync")

    migrate_schema(conn)

    if args.audit:
        run_audit(conn)
        conn.close()
        return

    if not args.tmdb_only:
        run_cleaning(conn)

    if not args.clean_only and TMDB_KEY:
        tmdb = TMDBClient(TMDB_KEY)
        run_poster_fetch(conn, tmdb, limit=args.poster_limit)
        if args.new_movies_days > 0:
            run_new_movie_sync(conn, tmdb, days=args.new_movies_days)

    if not args.skip_stats:
        log_stats(conn)

    conn.close()
    log.info("Pipeline complete: clean_and_sync")


if __name__ == "__main__":
    main()