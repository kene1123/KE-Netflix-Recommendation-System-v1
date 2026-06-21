CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --bg-base:      #0A0A0C;
    --bg-surface:   #15151B;
    --bg-card:      #1C1C24;
    --bg-card-hover:#23232D;
    --gold:         #D4AF6A;
    --gold-dim:     #C9A05E;
    --steel-blue:   #7BA3D9;
    --text-primary: #F5F3EE;
    --text-secondary: #B8B8C2;
    --text-tertiary: #8C8C96;
    --border:       #34343F;
    --success:      #6FBF8B;
}

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, sans-serif;
    background-color: var(--bg-base) !important;
    color: var(--text-primary);
}

.stApp {
    background: radial-gradient(ellipse 80% 50% at 50% -10%, rgba(212,175,106,0.06), transparent),
                var(--bg-base);
}

#MainMenu, footer {visibility: hidden;}

/* Keep header visible (it holds the sidebar collapse/expand control) but
   make it blend with the dark theme instead of showing Streamlit's default white bar */
header[data-testid="stHeader"] {
    background-color: var(--bg-base) !important;
    box-shadow: none !important;
}

/* Sidebar collapse/expand arrow — make it clearly visible at all times,
   in both collapsed and expanded states, on desktop and mobile */
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"] {
    background-color: var(--bg-card) !important;
    border: 1px solid var(--gold-dim) !important;
    border-radius: 8px !important;
    opacity: 1 !important;
    visibility: visible !important;
    z-index: 999999 !important;
}
[data-testid="stSidebarCollapsedControl"] svg,
[data-testid="collapsedControl"] svg {
    fill: var(--gold) !important;
    color: var(--gold) !important;
}
[data-testid="stSidebarCollapsedControl"]:hover,
[data-testid="collapsedControl"]:hover {
    background-color: var(--bg-card-hover) !important;
    border-color: var(--gold) !important;
}

/* The expand/collapse arrow inside the sidebar itself, when expanded */
[data-testid="stSidebar"] button[kind="header"] svg {
    fill: var(--gold) !important;
}

[data-testid="stSidebar"] {
    background-color: var(--bg-surface);
    border-right: 1px solid var(--border);
}

[data-testid="stSidebar"] > div:first-child {
    padding-top: 1.5rem;
}

/* Sidebar text — selectbox label, radio nav labels, captions —
   all forced to a clearly readable tone against the dark sidebar */
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] p {
    color: var(--text-secondary) !important;
}

[data-testid="stSidebar"] .stRadio label p {
    color: var(--text-primary) !important;
    font-size: 0.92rem !important;
    font-weight: 500 !important;
}

[data-testid="stSidebar"] .stRadio [data-baseweb="radio"] label:has(input:checked) p {
    color: var(--gold) !important;
}

[data-testid="stSidebar"] .stSelectbox label p {
    color: var(--text-secondary) !important;
    font-size: 0.82rem !important;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

.kn-logo {
    font-family: 'Fraunces', serif;
    font-size: 1.5rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--text-primary);
    padding: 0 0.5rem 1.5rem 0.5rem;
    border-bottom: 1px solid var(--border);
    margin-bottom: 1.5rem;
}
.kn-logo span { color: var(--gold); }

.kn-hero {
    position: relative;
    border-radius: 18px;
    overflow: hidden;
    min-height: 320px;
    display: flex;
    align-items: flex-end;
    padding: 2.5rem;
    margin-bottom: 2.5rem;
    background-size: cover;
    background-position: center 20%;
    border: 1px solid var(--border);
}
.kn-hero::before {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(180deg, rgba(10,10,12,0.1) 0%, rgba(10,10,12,0.55) 55%, rgba(10,10,12,0.96) 100%);
}
.kn-hero-content { position: relative; z-index: 2; max-width: 640px; }
.kn-hero-eyebrow {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.7rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--gold);
    margin-bottom: 0.6rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.kn-hero-title {
    font-family: 'Fraunces', serif;
    font-size: 3rem;
    font-weight: 500;
    line-height: 1.05;
    color: var(--text-primary);
    margin-bottom: 0.6rem;
}
.kn-hero-meta {
    font-size: 0.9rem;
    color: var(--text-secondary);
    margin-bottom: 0.9rem;
}
.kn-hero-reason {
    font-size: 0.92rem;
    color: var(--text-primary);
    background: rgba(212,175,106,0.1);
    border: 1px solid rgba(212,175,106,0.25);
    border-radius: 8px;
    padding: 0.55rem 0.9rem;
    display: inline-block;
}

.kn-section-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin: 2.2rem 0 1rem 0;
}
.kn-section-title {
    font-family: 'Fraunces', serif;
    font-size: 1.3rem;
    font-weight: 500;
    color: var(--text-primary);
}
.kn-section-sub {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.7rem;
    color: var(--text-tertiary);
    letter-spacing: 0.04em;
}

.kn-stat-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.9rem;
    margin-bottom: 0.5rem;
}
.kn-stat-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.1rem 1.2rem;
}
.kn-stat-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.66rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-tertiary);
    margin-bottom: 0.4rem;
}
.kn-stat-value {
    font-family: 'Fraunces', serif;
    font-size: 1.7rem;
    font-weight: 500;
    color: var(--text-primary);
}
.kn-stat-value.gold { color: var(--gold); }
.kn-stat-value.blue { color: var(--steel-blue); }

.kn-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
    transition: transform 0.18s ease, border-color 0.18s ease;
    height: 100%;
}
.kn-card:hover {
    transform: translateY(-3px);
    border-color: var(--gold-dim);
}
.kn-card-poster {
    width: 100%;
    aspect-ratio: 2/3;
    object-fit: cover;
    display: block;
    background: var(--bg-surface);
}
.kn-card-body { padding: 0.7rem 0.8rem 0.85rem 0.8rem; }
.kn-card-title {
    font-size: 0.84rem;
    font-weight: 600;
    color: var(--text-primary);
    line-height: 1.25;
    margin-bottom: 0.3rem;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
}
.kn-card-genre {
    font-size: 0.7rem;
    color: var(--text-tertiary);
    margin-bottom: 0.45rem;
}
.kn-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.62rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 0.18rem 0.5rem;
    border-radius: 5px;
    margin-bottom: 0.4rem;
}
.kn-badge.content { background: rgba(91,138,201,0.15); color: var(--steel-blue); }
.kn-badge.collaborative { background: rgba(212,175,106,0.15); color: var(--gold); }
.kn-badge.hybrid { background: rgba(111,191,139,0.15); color: var(--success); }

.kn-reason {
    font-size: 0.7rem;
    color: var(--text-secondary);
    line-height: 1.4;
    border-top: 1px solid var(--border);
    padding-top: 0.4rem;
    margin-top: 0.4rem;
}

.kn-empty {
    text-align: center;
    padding: 3rem 1rem;
    color: var(--text-tertiary);
    font-size: 0.9rem;
}

[data-testid="stMetricValue"] { color: var(--gold) !important; font-family: 'Fraunces', serif; }

.stTextInput input {
    background-color: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    color: var(--text-primary) !important;
}
.stTextInput input:focus {
    border-color: var(--gold-dim) !important;
    box-shadow: 0 0 0 1px var(--gold-dim) !important;
}

.stSelectbox > div > div {
    background-color: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
}

button[kind="primary"], .stButton button {
    background-color: var(--gold) !important;
    color: #0A0A0C !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
}
.stButton button:hover { background-color: #E0BC7E !important; }

.stTabs [data-baseweb="tab-list"] { gap: 1.5rem; border-bottom: 1px solid var(--border); }
.stTabs [data-baseweb="tab"] {
    color: var(--text-tertiary);
    font-weight: 500;
    padding-bottom: 0.7rem;
}
.stTabs [aria-selected="true"] {
    color: var(--gold) !important;
    border-bottom: 2px solid var(--gold) !important;
}

::-webkit-scrollbar { height: 8px; width: 8px; }
::-webkit-scrollbar-track { background: var(--bg-base); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: var(--gold-dim); }
</style>
"""