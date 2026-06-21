import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd

from app.styles import CUSTOM_CSS
from app.components import render_hero, render_row, section_header, stat_grid
from app import db

st.set_page_config(
    page_title="Ke-Netflix",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ── Sidebar ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="kn-logo">KE<span>·</span>NETFLIX</div>', unsafe_allow_html=True)

    users_df = db.get_user_list()
    user_options = users_df["user_id"].tolist()

    if "user_id" not in st.session_state:
        st.session_state.user_id = user_options[0] if user_options else 1

    selected_user = st.selectbox(
        "Viewing as",
        options=user_options,
        index=user_options.index(st.session_state.user_id) if st.session_state.user_id in user_options else 0,
        format_func=lambda x: f"User {x}",
    )
    st.session_state.user_id = selected_user

    profile = db.get_user_profile(selected_user)
    if profile:
        st.markdown(f"""
            <div style="font-size:0.78rem; color:#8A8A95; margin-top:0.4rem; line-height:1.6;">
                Personality &nbsp;<b style="color:#D4AF6A;">{profile.get('personality','—').title()}</b><br>
                Top genres &nbsp;{(profile.get('preferred_genres') or '—').replace('|', ', ')}
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='margin-top:1.5rem;'></div>", unsafe_allow_html=True)
    page = st.radio(
        "Navigate",
        ["Home", "My Recommendations", "Watch History", "Search", "Model Insights"],
        label_visibility="collapsed",
    )

user_id = st.session_state.user_id

# ── HOME ─────────────────────────────────────────────────────────────────
if page == "Home":
    hybrid_recs = db.get_recommendations(user_id, "hybrid", limit=12)

    if not hybrid_recs.empty:
        top = hybrid_recs.iloc[0].to_dict()
        render_hero(top)
    else:
        st.markdown('<div class="kn-empty">No recommendations yet for this user.</div>', unsafe_allow_html=True)

    stats = db.get_watch_stats(user_id)
    total_movies = int(stats.get("total_movies") or 0)
    avg_screen_time = stats.get("avg_screen_time")
    avg_rating = stats.get("avg_rating")
    total_ratings = int(stats.get("total_ratings") or 0)

    stat_grid([
        ("Total Movies Watched", str(total_movies), "gold"),
        ("Avg Screen Time", f"{avg_screen_time:.0f} min" if avg_screen_time else "—", "blue"),
        ("Avg Rating Given", f"{avg_rating:.1f} ★" if avg_rating else "—", "gold"),
        ("Movies Rated", str(total_ratings), ""),
    ])

    section_header("Your Recommendations", "HYBRID MODEL · TOP PICKS")
    render_row(hybrid_recs[1:], show_badge=False, show_reason=True, cols=6)

    favorites = db.get_favorite_movies(user_id, limit=6)
    section_header("Favorite Movies", "RATED 4★ AND ABOVE")
    render_row(favorites, cols=6)

    last_watched = db.get_last_watched(user_id, limit=6)
    section_header("Continue Watching", "RECENT ACTIVITY")
    render_row(last_watched, cols=6)


# ── MY RECOMMENDATIONS ──────────────────────────────────────────────────
elif page == "My Recommendations":
    section_header("Your Recommendations", "EXPLORE BY ALGORITHM")

    tab1, tab2, tab3 = st.tabs(["Hybrid · Top Picks", "Because You Watched", "Users Like You"])

    with tab1:
        recs = db.get_recommendations(user_id, "hybrid", limit=12)
        st.caption("Combines content similarity and collaborative filtering (0.6 × collaborative + 0.4 × content)")
        render_row(recs, show_badge=True, show_reason=True, cols=4)

    with tab2:
        recs = db.get_recommendations(user_id, "content", limit=12)
        st.caption("Based on genres, themes, and titles similar to what you've watched")
        render_row(recs, show_badge=True, show_reason=True, cols=4)

    with tab3:
        recs = db.get_recommendations(user_id, "collaborative", limit=12)
        st.caption("Based on viewers with similar taste profiles to yours")
        render_row(recs, show_badge=True, show_reason=True, cols=4)


# ── WATCH HISTORY ────────────────────────────────────────────────────────
elif page == "Watch History":
    section_header("Watch History", f"USER {user_id}")

    history = db.get_watch_history(user_id, limit=24)
    if history.empty:
        st.markdown('<div class="kn-empty">No watch history yet.</div>', unsafe_allow_html=True)
    else:
        display = history.copy()
        display["Watched"] = pd.to_datetime(display["timestamp"]).dt.strftime("%b %d, %Y")
        display["Rating"] = display["rating"].apply(lambda r: f"{r:.1f} ★" if pd.notna(r) else "—")
        display["Screen Time"] = display["watch_time"].apply(lambda w: f"{w:.0f} min" if pd.notna(w) else "—")
        display["Genres"] = display["genres"].fillna("—").str.replace("|", ", ")

        st.dataframe(
            display[["title_clean", "Genres", "Rating", "Screen Time", "Watched"]].rename(
                columns={"title_clean": "Title"}
            ),
            use_container_width=True,
            hide_index=True,
            height=560,
        )

    genre_dist = db.get_genre_distribution(user_id)
    if not genre_dist.empty:
        section_header("Genre Distribution", "WHAT YOU WATCH")
        st.bar_chart(genre_dist.set_index("genre")["count"], color="#D4AF6A", height=280)


# ── SEARCH ───────────────────────────────────────────────────────────────
elif page == "Search":
    section_header("Search", "FIND SOMETHING TO WATCH")

    query = st.text_input("Search movies", placeholder="Search by title...", label_visibility="collapsed")

    if query and len(query) >= 2:
        results = db.search_movies(query, limit=12)
        if results.empty:
            st.markdown('<div class="kn-empty">No matches found.</div>', unsafe_allow_html=True)
        else:
            section_header("Results", f"{len(results)} FOUND")
            render_row(results, cols=6)

            st.markdown("<div style='margin-top:1rem;'></div>", unsafe_allow_html=True)
            pick = st.selectbox(
                "See movies similar to",
                options=results["movie_id"].tolist(),
                format_func=lambda mid: results[results["movie_id"] == mid]["title_clean"].iloc[0],
            )
            if pick:
                similar = db.get_similar_movies(pick, limit=8)
                section_header("Similar Movies", "GENRE MATCH")
                render_row(similar, cols=4)
    else:
        st.markdown('<div class="kn-empty">Start typing to search the catalog.</div>', unsafe_allow_html=True)


# ── MODEL INSIGHTS ───────────────────────────────────────────────────────
elif page == "Model Insights":
    section_header("Model Insights", "HOW THE ENGINE PERFORMS")

    metrics = db.get_model_metrics()
    if not metrics.empty:
        m = metrics.iloc[0]
        col1, col2, col3 = st.columns(3)
        col1.metric("Model", m["model_name"])
        col2.metric("RMSE", f"{m['rmse']:.4f}")
        col3.metric("Precision@10", f"{m['precision_at_k']*100:.1f}%")

        st.caption(f"Last evaluated: {pd.to_datetime(m['created_at']).strftime('%B %d, %Y at %H:%M UTC')}")
    else:
        st.markdown('<div class="kn-empty">No model metrics recorded yet.</div>', unsafe_allow_html=True)

    st.markdown("<div style='margin-top:2rem;'></div>", unsafe_allow_html=True)
    section_header("How Recommendations Work", "")
    st.markdown("""
    <div style="color:#8A8A95; font-size:0.88rem; line-height:1.8;">
        <b style="color:#5B8AC9;">Content-based</b> — finds movies with similar genres, themes, and titles to what you've rated highly,
        weighted by how much of each movie you actually watched.<br><br>
        <b style="color:#D4AF6A;">Collaborative</b> — uses SVD matrix factorization to learn hidden taste patterns from all 610 users,
        surfacing what people with similar viewing habits enjoyed.<br><br>
        <b style="color:#6FBF8B;">Hybrid</b> — combines both signals (60% collaborative, 40% content) for the most personalized result.
    </div>
    """, unsafe_allow_html=True)