import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
from config.settings import get_connection


@st.cache_data(ttl=300)
def get_user_list() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql("""
        SELECT user_id, total_watches, personality, preferred_genres
        FROM   user_profiles
        ORDER  BY user_id
    """, conn)
    conn.close()
    return df


@st.cache_data(ttl=120)
def get_user_profile(user_id: int) -> dict:
    conn = get_connection()
    df = pd.read_sql("""
        SELECT * FROM user_profiles WHERE user_id = %(uid)s
    """, conn, params={"uid": user_id})
    conn.close()
    return df.iloc[0].to_dict() if not df.empty else {}


@st.cache_data(ttl=120)
def get_watch_stats(user_id: int) -> dict:
    conn = get_connection()
    df = pd.read_sql("""
        SELECT
            COUNT(*)                          AS total_movies,
            ROUND(AVG(watch_time)::numeric, 1) AS avg_screen_time,
            ROUND(AVG(rating)::numeric, 2)     AS avg_rating,
            COUNT(rating)                      AS total_ratings
        FROM user_activity
        WHERE user_id = %(uid)s
    """, conn, params={"uid": user_id})
    conn.close()
    return df.iloc[0].to_dict() if not df.empty else {}


@st.cache_data(ttl=120)
def get_last_watched(user_id: int, limit: int = 1) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql("""
        SELECT m.movie_id, m.title_clean, m.poster_url, m.genres,
               ua.rating, ua.watch_time, ua.timestamp
        FROM   user_activity ua
        JOIN   movies m ON ua.movie_id = m.movie_id
        WHERE  ua.user_id = %(uid)s
        ORDER  BY ua.timestamp DESC
        LIMIT  %(limit)s
    """, conn, params={"uid": user_id, "limit": limit})
    conn.close()
    return df


@st.cache_data(ttl=120)
def get_watch_history(user_id: int, limit: int = 20) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql("""
        SELECT m.movie_id, m.title_clean, m.poster_url, m.genres, m.release_year,
               ua.rating, ua.watch_time, ua.timestamp
        FROM   user_activity ua
        JOIN   movies m ON ua.movie_id = m.movie_id
        WHERE  ua.user_id = %(uid)s
        ORDER  BY ua.timestamp DESC
        LIMIT  %(limit)s
    """, conn, params={"uid": user_id, "limit": limit})
    conn.close()
    return df


@st.cache_data(ttl=120)
def get_favorite_movies(user_id: int, limit: int = 10) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql("""
        SELECT m.movie_id, m.title_clean, m.poster_url, m.genres,
               ua.rating, ua.watch_time
        FROM   user_activity ua
        JOIN   movies m ON ua.movie_id = m.movie_id
        WHERE  ua.user_id = %(uid)s AND ua.rating >= 4.0
        ORDER  BY ua.rating DESC, ua.watch_time DESC
        LIMIT  %(limit)s
    """, conn, params={"uid": user_id, "limit": limit})
    conn.close()
    return df


@st.cache_data(ttl=120)
def get_genre_distribution(user_id: int) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql("""
        SELECT m.genres
        FROM   user_activity ua
        JOIN   movies m ON ua.movie_id = m.movie_id
        WHERE  ua.user_id = %(uid)s AND m.genres IS NOT NULL
    """, conn, params={"uid": user_id})
    conn.close()

    if df.empty:
        return pd.DataFrame(columns=["genre", "count"])

    all_genres = []
    for g in df["genres"]:
        if g and g != "(no genres listed)":
            all_genres.extend(g.split("|"))

    counts = pd.Series(all_genres).value_counts().reset_index()
    counts.columns = ["genre", "count"]
    return counts.head(8)


@st.cache_data(ttl=120)
def get_recommendations(user_id: int, algorithm_type: str = "hybrid", limit: int = 12) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql("""
        SELECT r.movie_id, m.title_clean, m.poster_url, m.genres, m.release_year,
               r.score, r.reason, r.algorithm_type
        FROM   recommendations r
        JOIN   movies m ON r.movie_id = m.movie_id
        WHERE  r.user_id = %(uid)s AND r.algorithm_type = %(algo)s
        ORDER  BY r.score DESC
        LIMIT  %(limit)s
    """, conn, params={"uid": user_id, "algo": algorithm_type, "limit": limit})
    conn.close()
    return df


@st.cache_data(ttl=300)
def get_model_metrics() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql("""
        SELECT model_name, rmse, precision_at_k, created_at
        FROM   model_metrics
        ORDER  BY created_at DESC
        LIMIT  1
    """, conn)
    conn.close()
    return df


@st.cache_data(ttl=300)
def search_movies(query: str, limit: int = 12) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql("""
        SELECT movie_id, title_clean, poster_url, genres, release_year
        FROM   movies
        WHERE  title_clean ILIKE %(q)s
        AND    title_clean IS NOT NULL
        ORDER  BY release_year DESC NULLS LAST
        LIMIT  %(limit)s
    """, conn, params={"q": f"%{query}%", "limit": limit})
    conn.close()
    return df


@st.cache_data(ttl=300)
def get_similar_movies(movie_id: int, limit: int = 8) -> pd.DataFrame:
    """Used for the search-driven 'movies like this' slicer."""
    conn = get_connection()
    df = pd.read_sql("""
        SELECT m2.movie_id, m2.title_clean, m2.poster_url, m2.genres
        FROM   movies m1
        JOIN   movies m2 ON m1.movie_id != m2.movie_id
        WHERE  m1.movie_id = %(mid)s
        AND    m2.genres IS NOT NULL
        AND    string_to_array(m1.genres, '|') && string_to_array(m2.genres, '|')
        ORDER  BY m2.release_year DESC NULLS LAST
        LIMIT  %(limit)s
    """, conn, params={"mid": movie_id, "limit": limit})
    conn.close()
    return df