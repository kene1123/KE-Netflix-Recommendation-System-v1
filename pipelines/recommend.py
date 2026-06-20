import sys
import logging
import argparse
from datetime import datetime

import pandas as pd
import psycopg2.extras

from config.settings import get_connection, LOG_DIR
from pipelines.features import load_features
from models.content_model import ContentModel
from models.collaborative_model import CollaborativeModel

log = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "reccomend.log"),
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


def load_user_activity() -> tuple[dict[int, dict], pd.DataFrame]:
    """
    Single-connection-at-a-time, fetchmany() pagination.
    Works correctly against pgBouncer pooler connections, which drop
    server-side (named) cursors.
    """
    users: dict[int, dict] = {}
    rows = []

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT ua.user_id, ua.movie_id, ua.rating, ua.watch_time, m.title_clean
            FROM   user_activity ua
            JOIN   movies m ON ua.movie_id = m.movie_id
        """)
        for user_id, movie_id, rating, watch_time, title in _fetchmany(cur):
            uid = int(user_id)
            mid = int(movie_id)
            if uid not in users:
                users[uid] = {"watched": set(), "seeds": {}}
            users[uid]["watched"].add(mid)

            if rating is not None:
                rows.append((uid, mid, float(rating)))
                if float(rating) >= 3.5:
                    r         = float(rating) / 5.0
                    wt        = float(watch_time) if watch_time else AVG_MOVIE_MINUTES * 0.6
                    watch_pct = min(wt / AVG_MOVIE_MINUTES, 1.2)
                    weight    = round(r * watch_pct, 4)
                    if weight > users[uid]["seeds"].get(mid, (0, ""))[0]:
                        users[uid]["seeds"][mid] = (weight, title or "")
    conn.close()

    ratings_df = pd.DataFrame(rows, columns=["user_id", "movie_id", "rating"])
    log.info("Loaded activity for %d users  (%d ratings)", len(users), len(ratings_df))
    return users, ratings_df


def load_movie_titles() -> dict[int, str]:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT movie_id, title_clean FROM movies WHERE title_clean IS NOT NULL")
        result = {int(r[0]): r[1] for r in cur.fetchall()}
    conn.close()
    return result


def clear_recs(conn, algorithm_type: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM recommendations WHERE algorithm_type = %s", (algorithm_type,))
    conn.commit()
    log.info("Cleared existing %s recommendations", algorithm_type)


def generate_content_recs(conn, model: ContentModel, users: dict, top_n: int) -> None:
    total = 0
    chunk: list[tuple] = []

    for user_id, data in users.items():
        watched_ids = data["watched"]
        seed_movies = [(mid, weight, title) for mid, (weight, title) in data["seeds"].items()]
        if not seed_movies:
            continue

        seed_movies.sort(key=lambda x: x[1], reverse=True)
        recs = model.recommend_for_user(user_id, seed_movies[:5], watched_ids, top_n=top_n)

        for r in recs:
            chunk.append((
                r["user_id"], r["movie_id"], r["score"],
                r["algorithm_type"], r["reason"], datetime.utcnow(),
            ))

        if len(chunk) >= FETCH_SIZE:
            _insert_chunk(conn, chunk)
            total += len(chunk)
            chunk = []

    if chunk:
        _insert_chunk(conn, chunk)
        total += len(chunk)

    log.info("Content recommendations stored: %d", total)


def generate_collaborative_recs(
    conn,
    model: CollaborativeModel,
    users: dict,
    ratings_df: pd.DataFrame,
    movie_id_to_title: dict[int, str],
    top_n: int,
) -> None:
    log.info("Building SVD model on %d ratings...", len(ratings_df))
    model.fit(ratings_df)
    log.info("SVD complete  factors=%d  users=%d  movies=%d",
             model.n_factors, len(model.user_ids), len(model.movie_ids))

    watched_by_user = {uid: data["watched"] for uid, data in users.items()}

    log.info("Computing user similarity bridges...")
    bridge = model.get_similar_users_bridge(ratings_df, watched_by_user, movie_id_to_title)

    total = 0
    chunk: list[tuple] = []

    for user_id, data in users.items():
        recs = model.recommend_for_user(
            user_id, data["watched"], movie_id_to_title, bridge, top_n=top_n
        )
        for r in recs:
            chunk.append((
                r["user_id"], r["movie_id"], r["score"],
                r["algorithm_type"], r["reason"], datetime.utcnow(),
            ))

        if len(chunk) >= FETCH_SIZE:
            _insert_chunk(conn, chunk)
            total += len(chunk)
            chunk = []

    if chunk:
        _insert_chunk(conn, chunk)
        total += len(chunk)

    log.info("Collaborative recommendations stored: %d", total)


def generate_hybrid_recs(conn, top_n: int = 10) -> None:
    collab_recs: dict[int, dict[int, dict]] = {}
    content_recs: dict[int, dict[int, dict]] = {}

    with conn.cursor() as cur:
        cur.execute("""
            SELECT user_id, movie_id, score, reason, algorithm_type
            FROM   recommendations
            WHERE  algorithm_type IN ('content', 'collaborative')
        """)
        for user_id, movie_id, score, reason, algo in cur.fetchall():
            uid, mid = int(user_id), int(movie_id)
            entry = {"score": float(score), "reason": reason}
            if algo == "collaborative":
                collab_recs.setdefault(uid, {})[mid] = entry
            else:
                content_recs.setdefault(uid, {})[mid] = entry

    all_users = set(collab_recs) | set(content_recs)
    log.info("Building hybrid recs for %d users...", len(all_users))

    def normalise(scores: dict[int, float]) -> dict[int, float]:
        if not scores:
            return {}
        lo, hi = min(scores.values()), max(scores.values())
        rng = hi - lo if hi != lo else 1.0
        return {mid: (s - lo) / rng for mid, s in scores.items()}

    chunk: list[tuple] = []
    total = 0

    for user_id in all_users:
        c_raw = {mid: d["score"] for mid, d in collab_recs.get(user_id, {}).items()}
        t_raw = {mid: d["score"] for mid, d in content_recs.get(user_id, {}).items()}
        c_norm = normalise(c_raw)
        t_norm = normalise(t_raw)

        all_movies = set(c_norm) | set(t_norm)
        hybrid_scores = {
            mid: 0.6 * c_norm.get(mid, 0.0) + 0.4 * t_norm.get(mid, 0.0)
            for mid in all_movies
        }
        ranked = sorted(hybrid_scores.items(), key=lambda x: x[1], reverse=True)[:top_n]

        for mid, score in ranked:
            in_collab  = mid in collab_recs.get(user_id, {})
            in_content = mid in content_recs.get(user_id, {})

            if in_collab and in_content:
                reason = f"{content_recs[user_id][mid]['reason']} · Matched your taste profile"
            elif in_collab:
                reason = collab_recs[user_id][mid]["reason"]
            else:
                reason = content_recs[user_id][mid]["reason"]

            chunk.append((user_id, mid, round(score, 6), "hybrid", reason, datetime.utcnow()))

        if len(chunk) >= FETCH_SIZE:
            _insert_chunk(conn, chunk)
            total += len(chunk)
            chunk = []

    if chunk:
        _insert_chunk(conn, chunk)
        total += len(chunk)

    log.info("Hybrid recommendations stored: %d", total)


def _insert_chunk(conn, chunk: list[tuple]) -> None:
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, """
            INSERT INTO recommendations
                (user_id, movie_id, score, algorithm_type, reason, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, chunk, page_size=len(chunk))
    conn.commit()


def log_stats(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT algorithm_type, COUNT(*), COUNT(DISTINCT user_id)
            FROM   recommendations GROUP BY algorithm_type
        """)
        rows = cur.fetchall()
    log.info("-" * 55)
    for algo, total, users in rows:
        log.info("  %-15s: %d recs  %d users", algo, total, users)
    log.info("-" * 55)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ke-netflix: generate recommendations")
    p.add_argument("--top-n",        type=int, default=10)
    p.add_argument("--content-only", action="store_true")
    p.add_argument("--collab-only",  action="store_true")
    p.add_argument("--hybrid-only",  action="store_true")
    p.add_argument("--skip-stats",   action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    log.info("Pipeline starting: reccomend")

    users, ratings_df = load_user_activity()
    movie_titles      = load_movie_titles()

    if not args.collab_only and not args.hybrid_only:
        df, vectorizer, matrix, similarity_map = load_features()
        content_model = ContentModel(df, similarity_map)
        log.info("Content model loaded: %d movies", len(df))
        conn = get_connection()
        clear_recs(conn, "content")
        generate_content_recs(conn, content_model, users, top_n=args.top_n)
        conn.close()

    if not args.content_only and not args.hybrid_only:
        collab_model = CollaborativeModel(n_factors=50)
        conn = get_connection()
        clear_recs(conn, "collaborative")
        generate_collaborative_recs(conn, collab_model, users, ratings_df, movie_titles, top_n=args.top_n)
        conn.close()

    if not args.content_only and not args.collab_only:
        conn = get_connection()
        clear_recs(conn, "hybrid")
        generate_hybrid_recs(conn, top_n=args.top_n)
        conn.close()

    if not args.skip_stats:
        conn = get_connection()
        log_stats(conn)
        conn.close()

    log.info("Pipeline complete: reccomend")


if __name__ == "__main__":
    main()