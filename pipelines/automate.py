import sys
import json
import random
import logging
import argparse
from datetime import datetime, timedelta

import psycopg2.extras

from config.settings import get_connection, LOG_DIR

log = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "automate.log"),
    ],
)

AVG_MOVIE_MINUTES = 105
FETCH_SIZE = 2000


def _fetchmany(cur, size: int = FETCH_SIZE):
    while True:
        rows = cur.fetchmany(size)
        if not rows:
            break
        yield from rows


def migrate_schema() -> None:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id              SERIAL PRIMARY KEY,
                run_type        TEXT,
                status          TEXT,
                users_refreshed INT,
                recs_generated  INT,
                started_at      TIMESTAMP,
                completed_at    TIMESTAMP
            );
        """)
    conn.commit()
    conn.close()
    log.info("Schema migration complete")


def get_last_run_time(run_type: str = "daily") -> datetime:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT completed_at FROM pipeline_runs
            WHERE  run_type = %s AND status = 'success'
            ORDER  BY completed_at DESC LIMIT 1
        """, (run_type,))
        row = cur.fetchone()
    conn.close()
    if row and row[0]:
        return row[0]
    return datetime.utcnow() - timedelta(days=7)


def log_run(run_type: str, users: int, recs: int, started_at: datetime) -> None:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO pipeline_runs
                (run_type, status, users_refreshed, recs_generated, started_at, completed_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (run_type, "success", users, recs, started_at, datetime.utcnow()))
    conn.commit()
    conn.close()


def get_active_user_ids(since: datetime) -> list[int]:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT user_id FROM user_activity WHERE timestamp > %s
        """, (since,))
        ids = [int(r[0]) for r in cur.fetchall()]
    conn.close()
    log.info("Active users since %s: %d", since.strftime("%Y-%m-%d"), len(ids))
    return ids


def _parse_genres(raw: str) -> list[str]:
    if not raw:
        return []
    return [g.strip() for g in raw.split("|") if g.strip() and g.strip() != "(no genres listed)"]


def generate_events_for_users(user_ids: list[int], events_per_user: int = 10, seed: int = 42) -> int:
    if not user_ids:
        log.info("No active users to refresh")
        return 0

    rng = random.Random(seed)

    # ── Read profiles ───────────────────────────────────────────────────
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT user_id, genre_preferences, personality
            FROM   user_profiles WHERE user_id = ANY(%s)
        """, (user_ids,))
        profiles = {
            int(r[0]): {"prefs": json.loads(r[1]), "personality": r[2]}
            for r in cur.fetchall()
        }
    conn.close()

    # ── Read movies ─────────────────────────────────────────────────────
    movies = []
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT movie_id, genres FROM movies WHERE title_clean IS NOT NULL")
        for row in _fetchmany(cur):
            movies.append((int(row[0]), _parse_genres(row[1] or "")))
    conn.close()
    log.info("Loaded %d movies", len(movies))

    # ── Read already watched ────────────────────────────────────────────
    already_watched: set[tuple] = set()
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT user_id, movie_id FROM user_activity WHERE user_id = ANY(%s)", (user_ids,))
        for row in _fetchmany(cur):
            already_watched.add((int(row[0]), int(row[1])))
    conn.close()

    personality_watch_bias = {
        "generous": (0.65, 1.10),
        "balanced": (0.50, 0.95),
        "harsh":    (0.20, 0.70),
    }

    sim_start  = datetime.utcnow() - timedelta(days=7)
    new_events = []

    for user_id, profile in profiles.items():
        prefs       = profile["prefs"]
        personality = profile["personality"]
        watch_range = personality_watch_bias.get(personality, (0.5, 0.9))

        def movie_score(genres: list[str]) -> float:
            if not genres:
                return 0.5
            return sum(prefs.get(g, 2.5) for g in genres) / len(genres)

        scored = [
            (mid, movie_score(genres))
            for mid, genres in movies
            if (user_id, mid) not in already_watched
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        top_pool = scored[:300]
        weights  = [s for _, s in top_pool]
        total_w  = sum(weights)
        if total_w == 0:
            continue

        candidates = [mid for mid, _ in top_pool]
        probs      = [w / total_w for w in weights]
        n          = min(events_per_user, len(candidates))
        chosen     = list(dict.fromkeys(rng.choices(candidates, weights=probs, k=n)))

        for movie_id in chosen:
            days_ago   = rng.randint(0, 7)
            ts         = sim_start + timedelta(days=days_ago, hours=rng.randint(0, 23))
            watch_pct  = rng.uniform(*watch_range)
            watch_time = round(AVG_MOVIE_MINUTES * watch_pct, 2)
            rating     = None
            if rng.random() < 0.35:
                if personality == "generous":
                    rating = round(rng.uniform(3.0, 5.0) * 2) / 2
                elif personality == "harsh":
                    rating = round(rng.uniform(1.0, 3.5) * 2) / 2
                else:
                    rating = round(rng.uniform(2.0, 4.5) * 2) / 2
            new_events.append((user_id, movie_id, watch_time, rating, ts))
            already_watched.add((user_id, movie_id))

    if not new_events:
        log.info("No new events generated")
        return 0

    # ── Write events in chunks ──────────────────────────────────────────
    conn = get_connection()
    for i in range(0, len(new_events), FETCH_SIZE):
        chunk = new_events[i: i + FETCH_SIZE]
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO user_activity (user_id, movie_id, watch_time, rating, timestamp)
                VALUES (%s, %s, %s, %s, %s)
            """, chunk, page_size=FETCH_SIZE)
        conn.commit()
        log.info("  Events written: %d / %d", min(i + FETCH_SIZE, len(new_events)), len(new_events))
    conn.close()

    log.info("Generated %d new watch events for %d users", len(new_events), len(profiles))
    return len(new_events)


def rerun_recommendations(full: bool = False) -> int:
    from pipelines.recommend import (
        load_user_activity, load_movie_titles,
        clear_recs, generate_content_recs,
        generate_collaborative_recs, generate_hybrid_recs,
    )
    from models.collaborative_model import CollaborativeModel

    users, ratings_df = load_user_activity()
    movie_titles      = load_movie_titles()

    if full:
        from pipelines.features import (
            load_movies, build_feature_text, build_tfidf_matrix,
            precompute_similarity, save_features, load_features,
        )
        from models.content_model import ContentModel

        conn = get_connection()
        df   = load_movies(conn)
        conn.close()

        df = build_feature_text(df)
        vectorizer, matrix = build_tfidf_matrix(df)
        similarity_map = precompute_similarity(df, matrix)
        save_features(df, vectorizer, matrix, similarity_map)
        log.info("Features rebuilt")

        df_loaded, _, _, sim_map = load_features()
        content_model = ContentModel(df_loaded, sim_map)
        conn = get_connection()
        clear_recs(conn, "content")
        generate_content_recs(conn, content_model, users, top_n=10)
        conn.close()

    collab_model = CollaborativeModel(n_factors=50)
    conn = get_connection()
    clear_recs(conn, "collaborative")
    generate_collaborative_recs(conn, collab_model, users, ratings_df, movie_titles, top_n=10)
    conn.close()

    conn = get_connection()
    clear_recs(conn, "hybrid")
    generate_hybrid_recs(conn, top_n=10)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM recommendations WHERE algorithm_type = 'hybrid'")
        total = cur.fetchone()[0]
    conn.close()

    return int(total)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ke-netflix: automation pipeline")
    p.add_argument("--full",            action="store_true")
    p.add_argument("--events-per-user", type=int, default=10)
    p.add_argument("--run-type",        default="daily", choices=["daily", "weekly"])
    p.add_argument("--seed",            type=int, default=42)
    p.add_argument("--since-days",      type=int, default=None)
    return p.parse_args()


def main() -> None:
    args     = parse_args()
    started  = datetime.utcnow()
    run_type = "weekly" if args.full else args.run_type
    log.info("Pipeline starting: automate (%s)", run_type)

    migrate_schema()

    if args.since_days is not None:
        last_run = datetime.utcnow() - timedelta(days=args.since_days)
        log.info("Lookback override: since %s (%d days)", last_run.strftime("%Y-%m-%d"), args.since_days)
    else:
        last_run = get_last_run_time(run_type)

    active = get_active_user_ids(since=last_run)
    events = generate_events_for_users(active, events_per_user=args.events_per_user, seed=args.seed)
    recs   = rerun_recommendations(full=args.full)

    log_run(run_type, len(active), recs, started)

    log.info("-" * 55)
    log.info("  Run type        : %s", run_type)
    log.info("  Active users    : %d", len(active))
    log.info("  New events      : %d", events)
    log.info("  Hybrid recs     : %d", recs)
    log.info("-" * 55)
    log.info("Pipeline complete: automate")


if __name__ == "__main__":
    main()