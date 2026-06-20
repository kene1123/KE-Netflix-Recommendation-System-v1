import sys
import json
import random
import logging
import argparse
from datetime import datetime, timedelta

import numpy as np
import psycopg2
import psycopg2.extras

from config.settings import get_connection, LOG_DIR

log = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "simulation.log"),
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


def migrate_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id           INT PRIMARY KEY,
                genre_preferences TEXT,
                preferred_genres  TEXT,
                rating_bias       FLOAT,
                personality       TEXT,
                total_watches     INT,
                avg_watch_pct     FLOAT,
                updated_at        TIMESTAMP
            );
        """)
        # Repair column types if ingestion created them as TEXT
        cur.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'user_activity'
                    AND column_name = 'watch_time'
                    AND data_type = 'text'
                ) THEN
                    ALTER TABLE user_activity
                    ALTER COLUMN watch_time TYPE FLOAT
                    USING CASE WHEN watch_time IS NULL OR watch_time = '' THEN NULL
                               ELSE watch_time::float END;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'user_activity'
                    AND column_name = 'rating'
                    AND data_type = 'text'
                ) THEN
                    ALTER TABLE user_activity
                    ALTER COLUMN rating TYPE FLOAT
                    USING CASE WHEN rating IS NULL OR rating = '' THEN NULL
                               ELSE rating::float END;
                END IF;
            END $$;
        """)
    conn.commit()
    log.info("Schema migration complete")


def _parse_genres(raw: str) -> list[str]:
    if not raw:
        return []
    return [g.strip() for g in raw.split("|") if g.strip() and g.strip() != "(no genres listed)"]


def build_user_profiles(conn) -> None:
    from collections import defaultdict
    user_genre_scores: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    user_ratings: dict[int, list[float]] = defaultdict(list)

    # Server-side cursor — streams 2000 rows at a time, never loads 100k at once
    read_conn = get_connection()
    with read_conn.cursor() as cur:
        cur.execute("""
            SELECT ua.user_id, ua.rating, m.genres
            FROM   user_activity ua
            JOIN   movies m ON ua.movie_id = m.movie_id
            WHERE  ua.rating IS NOT NULL
        """)
        for user_id, rating, genres in _fetchmany(cur):
            user_ratings[int(user_id)].append(float(rating))
            for genre in _parse_genres(genres or ""):
                user_genre_scores[int(user_id)][genre].append(float(rating))
    read_conn.close()

    if not user_ratings:
        log.warning("No rated activity found - cannot build profiles")
        return

    global_mean = float(np.mean([r for ratings in user_ratings.values() for r in ratings]))

    profiles = []
    for user_id, ratings in user_ratings.items():
        avg_rating = float(np.mean(ratings))
        rating_bias = float(round(avg_rating - global_mean, 4))

        if avg_rating >= 3.8:
            personality = "generous"
        elif avg_rating >= 3.0:
            personality = "balanced"
        else:
            personality = "harsh"

        genre_scores = user_genre_scores[user_id]
        genre_preferences = {
            genre: float(round(float(np.mean(scores)), 4))
            for genre, scores in genre_scores.items()
        }

        top_genres = sorted(genre_preferences, key=genre_preferences.get, reverse=True)[:3]
        preferred_genres = "|".join(top_genres)

        profiles.append((
            int(user_id),
            json.dumps(genre_preferences),
            preferred_genres,
            rating_bias,
            personality,
            int(len(ratings)),
            None,
            datetime.utcnow(),
        ))

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO user_profiles
                (user_id, genre_preferences, preferred_genres, rating_bias,
                 personality, total_watches, avg_watch_pct, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                genre_preferences = EXCLUDED.genre_preferences,
                preferred_genres  = EXCLUDED.preferred_genres,
                rating_bias       = EXCLUDED.rating_bias,
                personality       = EXCLUDED.personality,
                total_watches     = EXCLUDED.total_watches,
                updated_at        = EXCLUDED.updated_at
            """,
            profiles,
            page_size=500,
        )
    conn.commit()
    log.info("User profiles built: %d users", len(profiles))


def backfill_watch_time(conn, seed: int = 42, fetch_size: int = 2000, chunk_size: int = 2000) -> None:
    rng = random.Random(seed)

    watch_pct_by_rating = {
        (4.5, 5.0): (0.85, 1.15),
        (4.0, 4.5): (0.75, 1.00),
        (3.0, 4.0): (0.55, 0.85),
        (2.0, 3.0): (0.25, 0.60),
        (1.0, 2.0): (0.05, 0.35),
    }

    def get_watch_pct(rating: float) -> float:
        for (low, high), (pct_low, pct_high) in watch_pct_by_rating.items():
            if low <= rating <= high:
                return rng.uniform(pct_low, pct_high)
        return rng.uniform(0.5, 0.8)

    # Check count first without loading data
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM user_activity WHERE watch_time IS NULL")
        total = cur.fetchone()[0]

    if total == 0:
        log.info("Backfill: watch_time already populated")
        return

    log.info("Backfilling watch_time for %d rows...", total)

    # Server-side cursor streams rows in fetch_size batches
    # so Neon never receives a single 100k-row fetch
    processed = 0
    conn2 = get_connection()
    with conn2.cursor() as server_cur:
        server_cur.execute("""
            SELECT user_id, movie_id, rating
            FROM   user_activity
            WHERE  watch_time IS NULL
        """)

        chunk = []
        for user_id, movie_id, rating in _fetchmany(server_cur, fetch_size):
            watch_pct = get_watch_pct(float(rating)) if rating is not None else rng.uniform(0.4, 0.9)
            chunk.append((round(AVG_MOVIE_MINUTES * watch_pct, 2), int(user_id), int(movie_id)))

            if len(chunk) >= chunk_size:
                with conn.cursor() as write_cur:
                    psycopg2.extras.execute_batch(
                        write_cur,
                        "UPDATE user_activity SET watch_time = %s WHERE user_id = %s AND movie_id = %s",
                        chunk,
                        page_size=chunk_size,
                    )
                conn.commit()
                processed += len(chunk)
                log.info("  Backfill progress: %d / %d", processed, total)
                chunk = []

        if chunk:
            with conn.cursor() as write_cur:
                psycopg2.extras.execute_batch(
                    write_cur,
                    "UPDATE user_activity SET watch_time = %s WHERE user_id = %s AND movie_id = %s",
                    chunk,
                    page_size=chunk_size,
                )
            conn.commit()
            processed += len(chunk)
    conn2.close()

    log.info("Backfill done: %d rows updated", processed)


def generate_watch_events(conn, events_per_user: int = 50, seed: int = 42) -> None:
    rng = random.Random(seed)

    read_conn = get_connection()

    # user_profiles is small (610 rows) — plain fetchall is fine
    with read_conn.cursor() as cur:
        cur.execute("SELECT user_id, genre_preferences, personality FROM user_profiles")
        profiles = {
            row[0]: {"prefs": json.loads(row[1]), "personality": row[2]}
            for row in cur.fetchall()
        }

    # movies is ~9k rows — plain fetchall is fine
    with read_conn.cursor() as cur:
        cur.execute("SELECT movie_id, genres FROM movies WHERE title_clean IS NOT NULL")
        movies = [(row[0], _parse_genres(row[1] or "")) for row in cur.fetchall()]

    # user_activity is 100k rows — use server-side cursor to stream
    already_watched: set[tuple] = set()
    with read_conn.cursor() as cur:
        cur.execute("SELECT user_id, movie_id FROM user_activity")
        for row in _fetchmany(cur):
            already_watched.add((row[0], row[1]))

    read_conn.close()

    personality_watch_bias = {
        "generous": (0.65, 1.10),
        "balanced": (0.50, 0.95),
        "harsh":    (0.20, 0.70),
    }

    sim_start = datetime.utcnow() - timedelta(days=730)
    new_events = []

    for user_id, profile in profiles.items():
        prefs = profile["prefs"]
        personality = profile["personality"]
        watch_range = personality_watch_bias.get(personality, (0.5, 0.9))

        def movie_score(movie_genres: list[str]) -> float:
            if not movie_genres:
                return 0.5
            scores = [prefs.get(g, 2.5) for g in movie_genres]
            return sum(scores) / len(scores)

        scored = [(mid, movie_score(genres)) for mid, genres in movies
                  if (user_id, mid) not in already_watched]
        scored.sort(key=lambda x: x[1], reverse=True)

        top_pool = scored[:min(500, len(scored))]
        weights = [s for _, s in top_pool]
        total_weight = sum(weights)
        if total_weight == 0:
            continue
        probs = [w / total_weight for w in weights]

        candidates = [mid for mid, _ in top_pool]
        n = min(events_per_user, len(candidates))
        chosen = rng.choices(candidates, weights=probs, k=n)
        chosen = list(dict.fromkeys(chosen))

        for movie_id in chosen:
            days_ago = rng.randint(0, 730)
            ts = sim_start + timedelta(days=days_ago, hours=rng.randint(0, 23))
            watch_pct = rng.uniform(*watch_range)
            watch_time = round(AVG_MOVIE_MINUTES * watch_pct, 2)

            give_rating = rng.random() < 0.35
            if give_rating:
                if personality == "generous":
                    rating = round(rng.uniform(3.0, 5.0) * 2) / 2
                elif personality == "harsh":
                    rating = round(rng.uniform(1.0, 3.5) * 2) / 2
                else:
                    rating = round(rng.uniform(2.0, 4.5) * 2) / 2
            else:
                rating = None

            new_events.append((user_id, movie_id, watch_time, rating, ts))
            already_watched.add((user_id, movie_id))

    if not new_events:
        log.info("No new events to insert")
        return

    chunk_size = 3000
    total = len(new_events)
    for i in range(0, total, chunk_size):
        chunk = new_events[i: i + chunk_size]
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(
                cur,
                """
                INSERT INTO user_activity (user_id, movie_id, watch_time, rating, timestamp)
                VALUES (%s, %s, %s, %s, %s)
                """,
                chunk,
                page_size=chunk_size,
            )
        conn.commit()
    log.info("Generated %d new watch events across %d users", total, len(profiles))


def update_avg_watch_pct(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE user_profiles up
            SET avg_watch_pct = sub.avg_pct
            FROM (
                SELECT user_id, ROUND((AVG(watch_time) / %s)::numeric, 4) AS avg_pct
                FROM   user_activity
                WHERE  watch_time IS NOT NULL
                GROUP  BY user_id
            ) sub
            WHERE up.user_id = sub.user_id
        """, (AVG_MOVIE_MINUTES,))
    conn.commit()
    log.info("avg_watch_pct updated on user_profiles")


def log_stats(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM user_profiles")
        profiles = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM user_activity")
        total_events = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM user_activity WHERE watch_time IS NOT NULL")
        with_watch_time = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM user_activity WHERE rating IS NOT NULL")
        with_rating = cur.fetchone()[0]
        cur.execute("SELECT personality, COUNT(*) FROM user_profiles GROUP BY personality ORDER BY personality")
        personalities = cur.fetchall()

        avg_wt = None
        if with_watch_time > 0:
            cur.execute("""
                SELECT ROUND(AVG(watch_time::numeric), 1)
                FROM   user_activity
                WHERE  watch_time IS NOT NULL
            """)
            avg_wt = cur.fetchone()[0]

    log.info("-" * 55)
    log.info("  User profiles     : %d", profiles)
    log.info("  Total events      : %d", total_events)
    log.info("  With watch time   : %d", with_watch_time)
    log.info("  With rating       : %d", with_rating)
    log.info("  Avg watch time    : %s min", avg_wt if avg_wt else "not yet backfilled")
    for p_type, count in personalities:
        log.info("  %-18s: %d users", p_type, count)
    log.info("-" * 55)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ke-netflix: user behavior simulation")
    p.add_argument("--profiles-only",    action="store_true")
    p.add_argument("--backfill-only",    action="store_true")
    p.add_argument("--events-only",      action="store_true")
    p.add_argument("--events-per-user",  type=int, default=20)
    p.add_argument("--seed",             type=int, default=42)
    p.add_argument("--skip-stats",       action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    conn = get_connection()
    log.info("Pipeline starting: simulation")

    migrate_schema(conn)

    if args.profiles_only:
        build_user_profiles(conn)
    elif args.backfill_only:
        backfill_watch_time(conn, seed=args.seed)
    elif args.events_only:
        generate_watch_events(conn, events_per_user=args.events_per_user, seed=args.seed)
    else:
        build_user_profiles(conn)
        backfill_watch_time(conn, seed=args.seed)
        generate_watch_events(conn, events_per_user=args.events_per_user, seed=args.seed)
        update_avg_watch_pct(conn)

    if not args.skip_stats:
        log_stats(conn)

    conn.close()
    log.info("Pipeline complete: simulation")


if __name__ == "__main__":
    main()