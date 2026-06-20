import pandas as pd
from db.connection import get_engine
import os

RAW_PATH = "data/raw/movielens/"

def load_movies():
    file_path = os.path.join(RAW_PATH, "movies.csv")
    df = pd.read_csv(file_path)

    # Clean columns
    df = df.rename(columns={
        "movieId": "movie_id",
        "title": "title",
        "genres": "genres"
    })

    return df


def load_ratings():
    file_path = os.path.join(RAW_PATH, "ratings.csv")
    df = pd.read_csv(file_path)

    df = df.rename(columns={
        "userId": "user_id",
        "movieId": "movie_id",
        "rating": "rating",
        "timestamp": "timestamp"
    })

    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
    df['watch_time'] = None  # placeholder for now
    
    return df


def save_to_db(df, table_name):
    engine = get_engine()
    df.to_sql(table_name, engine, if_exists="replace", index=False)


def run_ingestion():
    print("Loading datasets...")

    movies = load_movies()
    ratings = load_ratings()

    print("Saving movies...")
    save_to_db(movies, "movies")

    print("Saving user activity...")
    save_to_db(ratings, "user_activity")

    print("Ingestion complete.")


if __name__ == "__main__":
    run_ingestion()