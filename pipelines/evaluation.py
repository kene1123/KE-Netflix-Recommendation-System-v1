import sys
import logging
import numpy as np
import pandas as pd
from datetime import datetime

import psycopg2.extras
from sklearn.model_selection import train_test_split

from config.settings import get_connection, LOG_DIR
from models.collaborative_model import CollaborativeModel

log = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "evaluation.log"),
    ],
)


def load_ratings(conn) -> pd.DataFrame:
    rows = []
    with conn.cursor("eval_ratings_cursor") as cur:
        cur.itersize = 2000
        cur.execute("""
            SELECT user_id, movie_id, rating
            FROM   user_activity
            WHERE  rating IS NOT NULL
        """)
        for row in cur:
            rows.append((int(row[0]), int(row[1]), float(row[2])))
    df = pd.DataFrame(rows, columns=["user_id", "movie_id", "rating"])
    log.info("Loaded %d ratings for evaluation", len(df))
    return df


def compute_rmse(model: CollaborativeModel, test_df: pd.DataFrame) -> float:
    preds, actuals = [], []
    for _, row in test_df.iterrows():
        pred = model.predict(int(row["user_id"]), int(row["movie_id"]))
        preds.append(pred)
        actuals.append(float(row["rating"]))
    rmse = float(np.sqrt(np.mean((np.array(preds) - np.array(actuals)) ** 2)))
    log.info("RMSE: %.4f", rmse)
    return rmse


def compute_precision_at_k(
    model: CollaborativeModel,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    k: int = 10,
    threshold: float = 4.0,
) -> float:
    # Relevant = movies the user rated >= threshold in the TEST set
    relevant = (
        test_df[test_df["rating"] >= threshold]
        .groupby("user_id")["movie_id"]
        .apply(set)
        .to_dict()
    )
    # Exclude only TRAINING movies from candidates — test movies must stay in pool
    train_watched = (
        train_df.groupby("user_id")["movie_id"]
        .apply(set)
        .to_dict()
    )
    precisions = []
    for user_id, rel_movies in relevant.items():
        u = model.user_index.get(user_id)
        if u is None:
            continue
        exclude = train_watched.get(user_id, set())
        scores = [
            (mid, float(model.predictions[u, model.movie_index[mid]]))
            for mid in model.movie_ids
            if mid not in exclude and mid in model.movie_index
        ]
        scores.sort(key=lambda x: x[1], reverse=True)
        top_k = {mid for mid, _ in scores[:k]}
        hit   = len(top_k & rel_movies)
        precisions.append(hit / k)

    precision = float(np.mean(precisions)) if precisions else 0.0
    log.info("Precision@%d: %.4f", k, precision)
    return precision


def store_metrics(conn, model_name: str, rmse: float, precision_at_k: float) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO model_metrics (model_name, precision_at_k, rmse, created_at)
            VALUES (%s, %s, %s, %s)
            """,
            (model_name, round(precision_at_k, 6), round(rmse, 6), datetime.utcnow()),
        )
    conn.commit()
    log.info("Metrics stored: %s  RMSE=%.4f  P@10=%.4f", model_name, rmse, precision_at_k)


def run_evaluation(conn) -> tuple[float, float]:
    df = load_ratings(conn)
    train_df, test_df = train_test_split(df, test_size=0.2, random_state=42)
    log.info("Train: %d  Test: %d", len(train_df), len(test_df))

    model = CollaborativeModel(n_factors=50)
    model.fit(train_df)

    rmse        = compute_rmse(model, test_df)
    precision   = compute_precision_at_k(model, train_df, test_df, k=10)

    store_metrics(conn, "svd_collaborative", rmse, precision)
    return rmse, precision


def main() -> None:
    log.info("Pipeline starting: evaluation")
    conn = get_connection()
    rmse, precision = run_evaluation(conn)
    log.info("-" * 55)
    log.info("  SVD Collaborative  RMSE      : %.4f", rmse)
    log.info("  SVD Collaborative  P@10      : %.4f", precision)
    log.info("-" * 55)
    conn.close()
    log.info("Pipeline complete: evaluation")


if __name__ == "__main__":
    main()