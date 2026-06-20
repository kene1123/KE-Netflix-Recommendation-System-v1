import html
import streamlit as st
import pandas as pd

PLACEHOLDER_POSTER = "https://placehold.co/300x450/1C1C24/8A8A95?text=No+Poster+Available&font=inter"


def poster_url(url) -> str:
    if pd.isna(url) or not url or str(url).strip() == "":
        return PLACEHOLDER_POSTER
    return str(url)


def esc(value) -> str:
    """HTML-escape any dynamic text before it goes into an f-string template.
    Prevents apostrophes/quotes in titles or reasons (e.g. Schindler's List)
    from breaking out of HTML attributes and rendering as raw text."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return html.escape(str(value), quote=True)


def render_hero(movie: dict) -> None:
    bg     = poster_url(movie.get("poster_url"))
    title  = esc(movie.get("title_clean", "Untitled"))
    genres = esc((movie.get("genres") or "").replace("|", " · "))
    year   = esc(movie.get("release_year", ""))
    reason = esc(movie.get("reason", ""))
    algo   = movie.get("algorithm_type", "hybrid")

    algo_label = {
        "content": "Matches your taste",
        "collaborative": "Trending with similar viewers",
        "hybrid": "Top pick for you",
    }.get(algo, "Top pick for you")

    html_block = (
        '<div class="kn-hero" style="background-image:'
        'linear-gradient(90deg, rgba(10,10,12,0.55) 0%, rgba(10,10,12,0.15) 60%),'
        f"url('{bg}');\">"
        '<div class="kn-hero-content">'
        f'<div class="kn-hero-eyebrow">\u25cf {algo_label}</div>'
        f'<div class="kn-hero-title">{title}</div>'
        f'<div class="kn-hero-meta">{year} \u00b7 {genres}</div>'
        f'<div class="kn-hero-reason">{reason}</div>'
        '</div>'
        '</div>'
    )
    st.markdown(html_block, unsafe_allow_html=True)


def render_card(row: dict, show_badge: bool = False, show_reason: bool = False) -> str:
    title      = esc(row.get("title_clean", "Untitled"))
    raw_genres = (row.get("genres") or "").split("|")
    genre_str  = esc(" \u00b7 ".join(raw_genres[:2])) if raw_genres else ""
    poster     = poster_url(row.get("poster_url"))
    algo       = row.get("algorithm_type", "")
    reason     = esc(row.get("reason", ""))

    badge_html = ""
    if show_badge and algo:
        badge_html = f'<div class="kn-badge {algo}">{esc(algo)}</div>'

    reason_html = ""
    if show_reason and reason:
        reason_html = f'<div class="kn-reason">{reason}</div>'

    return (
        f'<div class="kn-card" title="{title}">'
        f'<img class="kn-card-poster" src="{poster}" loading="lazy" '
        f'onerror="this.onerror=null;this.src=\'{PLACEHOLDER_POSTER}\';" />'
        '<div class="kn-card-body">'
        f'{badge_html}'
        f'<div class="kn-card-title">{title}</div>'
        f'<div class="kn-card-genre">{genre_str}</div>'
        f'{reason_html}'
        '</div>'
        '</div>'
    )


def render_row(df: pd.DataFrame, show_badge: bool = False, show_reason: bool = False, cols: int = 6) -> None:
    if df.empty:
        st.markdown('<div class="kn-empty">Nothing here yet. Keep watching to unlock this.</div>', unsafe_allow_html=True)
        return

    rows = [df.iloc[i:i + cols] for i in range(0, len(df), cols)]
    for chunk in rows:
        columns = st.columns(cols)
        for col, (_, row) in zip(columns, chunk.iterrows()):
            with col:
                card_html = render_card(row.to_dict(), show_badge=show_badge, show_reason=show_reason)
                st.markdown(card_html, unsafe_allow_html=True)


def section_header(title: str, sub: str = "") -> None:
    st.markdown(
        f'<div class="kn-section-header">'
        f'<div class="kn-section-title">{esc(title)}</div>'
        f'<div class="kn-section-sub">{esc(sub)}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def stat_grid(stats: list[tuple[str, str, str]]) -> None:
    """stats: list of (label, value, color_class) where color_class is '', 'gold', or 'blue'"""
    cards = "".join([
        f'<div class="kn-stat-card">'
        f'<div class="kn-stat-label">{esc(label)}</div>'
        f'<div class="kn-stat-value {color}">{esc(value)}</div>'
        f'</div>'
        for label, value, color in stats
    ])
    st.markdown(f'<div class="kn-stat-grid">{cards}</div>', unsafe_allow_html=True)