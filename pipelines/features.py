import sys
import logging
import pickle
import re

import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from config.settings import get_connection, LOG_DIR, DATA_DIR
from utils.text_cleaner import whitespace_tokenizer

log = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "features.log"),
    ],
)

PROCESSED_DIR = DATA_DIR / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

FEATURES_PATH    = PROCESSED_DIR / "movie_features.pkl"
MOVIES_PATH      = PROCESSED_DIR / "movies.pkl"
SIMILARITY_PATH  = PROCESSED_DIR / "similarity_top50.pkl"

TOP_N_SIMILAR = 50

_STOP_WORDS = {
    "the", "a", "an", "of", "in", "on", "at", "to", "and", "or",
    "is", "it", "its", "de", "la", "le", "les", "des", "un", "une",
}


def _decade(year) -> str:
    try:
        y = int(year)
        return f"decade{(y // 10) * 10}s"
    except (TypeError, ValueError):
        return ""


def _title_keywords(title: str) -> str:
    if not isinstance(title, str):
        return ""
    words = re.sub(r"[^a-z0-9 ]", "", title.lower()).split()
    return " ".join(w for w in words if w not in _STOP_WORDS and len(w) > 2)


def build_feature_text(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["genre_tokens"]   = df["genres"].str.replace("|", " ", regex=False).str.lower()
    df["title_tokens"]   = df["title_clean"].apply(_title_keywords)
    df["decade_token"]   = df["release_year"].apply(_decade)
    df["feature_text"]   = (
        df["genre_tokens"] + " "
        + df["title_tokens"] + " "
        + df["decade_token"]
    ).str.strip()
    return df


def load_movies(conn) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT movie_id, title_clean, genres, release_year
            FROM   movies
            WHERE  title_clean IS NOT NULL
            AND    genres IS NOT NULL
            AND    genres != '(no genres listed)'
        """)
        rows = cur.fetchall()

    df = pd.DataFrame(rows, columns=["movie_id", "title_clean", "genres", "release_year"])
    log.info("Loaded %d movies from DB", len(df))
    return df


def build_tfidf_matrix(df: pd.DataFrame):
    vectorizer = TfidfVectorizer(
        tokenizer=whitespace_tokenizer,
        lowercase=True,
        min_df=2,
        token_pattern=None,
    )
    matrix = vectorizer.fit_transform(df["feature_text"])
    log.info("TF-IDF matrix shape: %s  |  vocab size: %d", matrix.shape, len(vectorizer.vocabulary_))
    return vectorizer, matrix


def precompute_similarity(df: pd.DataFrame, matrix, top_n: int = TOP_N_SIMILAR) -> dict[int, list[tuple[int, float]]]:
    log.info("Precomputing top-%d similarities for %d movies...", top_n, len(df))
    movie_ids = df["movie_id"].tolist()
    batch_size = 500
    similarity_map: dict[int, list[tuple[int, float]]] = {}

    for start in range(0, len(movie_ids), batch_size):
        end = min(start + batch_size, len(movie_ids))
        batch_matrix = matrix[start:end]
        sim_block = cosine_similarity(batch_matrix, matrix)

        for local_idx, global_idx in enumerate(range(start, end)):
            row = sim_block[local_idx].copy()
            row[global_idx] = 0.0
            top_idx = np.argsort(row)[::-1][:top_n]
            similarity_map[movie_ids[global_idx]] = [
                (movie_ids[i], float(row[i]))
                for i in top_idx
                if row[i] > 0
            ]

        log.info("  Similarity progress: %d / %d", end, len(movie_ids))

    return similarity_map


def save_features(df: pd.DataFrame, vectorizer, matrix, similarity_map: dict) -> None:
    df.to_pickle(MOVIES_PATH)
    with open(FEATURES_PATH, "wb") as f:
        pickle.dump({"vectorizer": vectorizer, "matrix": matrix}, f)
    with open(SIMILARITY_PATH, "wb") as f:
        pickle.dump(similarity_map, f)
    log.info("Features saved -> %s", PROCESSED_DIR)


def load_features():
    df = pd.read_pickle(MOVIES_PATH)
    with open(FEATURES_PATH, "rb") as f:
        bundle = pickle.load(f)
    with open(SIMILARITY_PATH, "rb") as f:
        similarity_map = pickle.load(f)
    return df, bundle["vectorizer"], bundle["matrix"], similarity_map


def main() -> None:
    log.info("Pipeline starting: features")
    conn = get_connection()
    df = load_movies(conn)
    conn.close()

    df = build_feature_text(df)
    vectorizer, matrix = build_tfidf_matrix(df)
    similarity_map = precompute_similarity(df, matrix)
    save_features(df, vectorizer, matrix, similarity_map)
    log.info("Pipeline complete: features")


if __name__ == "__main__":
    main()