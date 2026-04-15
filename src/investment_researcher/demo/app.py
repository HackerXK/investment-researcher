"""Investment Researcher — Financial Dashboard

A professional financial analytics dashboard powered by SEC XBRL data.

Run:  streamlit run src/investment_researcher/demo/app.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from investment_researcher.analytics.queries import (
    all_ratios_latest,
    all_ratios_ttm,
    all_ratios_wide,
    get_all_tickers,
    growth_rates,
    metric_timeseries,
    pivot_metrics,
    quarterly_detail,
    ratio_timeseries,
    ticker_summary,
)
from investment_researcher.ratios import (
    RATIO_CATEGORIES,
    RATIO_REGISTRY,
    get_ratios_by_category,
)

# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Investment Researcher",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Design system ────────────────────────────────────────────────────────────

COLORS = {
    "emerald": "#10b981",
    "rose": "#f43f5e",
    "sky": "#38bdf8",
    "violet": "#a78bfa",
    "amber": "#f59e0b",
    "teal": "#2dd4bf",
    "slate": "#64748b",
    "zinc": "#a1a1aa",
}

COLOR_SEQ = [
    COLORS["sky"],
    COLORS["emerald"],
    COLORS["violet"],
    COLORS["amber"],
    COLORS["rose"],
    COLORS["teal"],
]

# Plotly layout defaults
_PLOTLY_LAYOUT = dict(
    font=dict(family="DM Sans, sans-serif", color="#e2e8f0"),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=0, r=0, t=36, b=0),
    legend=dict(
        orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
        font=dict(size=11, color="#94a3b8"),
        bgcolor="rgba(0,0,0,0)",
    ),
    xaxis=dict(gridcolor="rgba(148,163,184,0.08)", zerolinecolor="rgba(148,163,184,0.12)"),
    yaxis=dict(gridcolor="rgba(148,163,184,0.08)", zerolinecolor="rgba(148,163,184,0.12)"),
    hoverlabel=dict(
        bgcolor="#1e293b", font_size=12, font_family="DM Sans, sans-serif",
        bordercolor="rgba(148,163,184,0.2)",
    ),
    hovermode="x unified",
)


def _apply_layout(fig: go.Figure, **overrides) -> go.Figure:
    merged = {**_PLOTLY_LAYOUT, **overrides}
    fig.update_layout(**merged)
    return fig


# ── Inject global CSS ────────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,300&family=Instrument+Serif:ital@0;1&display=swap');

/* ── Root variables ── */
:root {
    --font-body: 'DM Sans', sans-serif;
    --font-display: 'Instrument Serif', Georgia, serif;
    --c-emerald: #10b981;
    --c-rose: #f43f5e;
    --c-sky: #38bdf8;
    --c-amber: #f59e0b;
    --c-surface: rgba(15,23,42,0.45);
    --c-border: rgba(148,163,184,0.10);
    --c-text: #e2e8f0;
    --c-text-muted: #94a3b8;
    --radius: 12px;
}

/* ── Typography ── */
html, body, [class*="css"] { font-family: var(--font-body) !important; }
h1, h2, h3 { font-family: var(--font-display) !important; font-weight: 400 !important; letter-spacing: -0.02em; }
h1 { font-size: 2.8rem !important; line-height: 1.1 !important; }
h2, .stTabs [data-baseweb="tab-panel"] h2 { font-size: 1.5rem !important; }
h3 { font-size: 1.25rem !important; color: var(--c-text-muted) !important; }

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, rgba(15,23,42,0.95) 0%, rgba(15,23,42,0.85) 100%);
    border-right: 1px solid var(--c-border);
}
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] .stRadio label { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--c-text-muted); }

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] { gap: 0; border-bottom: 1px solid var(--c-border); }
.stTabs [data-baseweb="tab"] {
    font-family: var(--font-body) !important;
    font-size: 0.85rem;
    font-weight: 500;
    padding: 0.7rem 1.2rem;
    color: var(--c-text-muted);
    border-bottom: 2px solid transparent;
    transition: all 0.2s ease;
}
.stTabs [data-baseweb="tab"]:hover { color: var(--c-text); }
.stTabs [aria-selected="true"] {
    color: var(--c-sky) !important;
    border-bottom-color: var(--c-sky) !important;
    background: transparent !important;
}

/* ── Metric cards ── */
div[data-testid="stMetric"] {
    background: var(--c-surface);
    border: 1px solid var(--c-border);
    border-radius: var(--radius);
    padding: 1rem 1.1rem;
    transition: border-color 0.2s ease;
}
div[data-testid="stMetric"]:hover { border-color: rgba(148,163,184,0.25); }
div[data-testid="stMetric"] label { font-size: 0.72rem !important; text-transform: uppercase; letter-spacing: 0.06em; color: var(--c-text-muted) !important; }
div[data-testid="stMetric"] [data-testid="stMetricValue"] { font-family: var(--font-display) !important; font-size: 1.35rem !important; }
div[data-testid="stMetric"] [data-testid="stMetricDelta"] { font-size: 0.75rem !important; }

/* ── DataFrames ── */
.stDataFrame { border-radius: var(--radius); overflow: hidden; border: 1px solid var(--c-border); }
.stDataFrame [data-testid="stDataFrameResizable"] { border-radius: var(--radius); }

/* ── Divider ── */
hr { border-color: var(--c-border) !important; margin: 1.5rem 0 !important; }

/* ── Info/warning banners ── */
.stAlert { border-radius: var(--radius); border: 1px solid var(--c-border); }

/* ── Subheader helper ── */
.section-label {
    font-family: var(--font-body);
    font-size: 0.72rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--c-text-muted);
    margin-bottom: 0.3rem;
}
</style>
""", unsafe_allow_html=True)

# ── Sidebar ──────────────────────────────────────────────────────────────────

st.sidebar.markdown(
    "<h2 style='font-family: Instrument Serif, Georgia, serif; font-weight: 400; "
    "margin-bottom: 0;'>Investment<br>Researcher</h2>",
    unsafe_allow_html=True,
)
st.sidebar.caption("SEC XBRL · Financial Data Explorer")
st.sidebar.markdown("---")

all_tickers = get_all_tickers()
if not all_tickers:
    st.warning("No data available. Run the ingestion pipeline first to load SEC filings.")
    st.stop()
ticker = st.sidebar.selectbox(
    "Company",
    all_tickers,
    index=all_tickers.index("AAPL") if "AAPL" in all_tickers else 0,
)

period_type = st.sidebar.radio(
    "Period",
    ["annual", "quarterly"],
    horizontal=True,
)

st.sidebar.markdown("---")
st.sidebar.markdown(
    "<div style='font-size:0.7rem; color:#64748b; line-height:1.6;'>"
    "Data sourced from SEC EDGAR XBRL filings.<br>"
    "Not financial advice.</div>",
    unsafe_allow_html=True,
)

# ── Helper formatters ────────────────────────────────────────────────────────

def _fmt(val: float | None) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "N/A"
    abs_val = abs(val)
    sign = "-" if val < 0 else ""
    if abs_val >= 1e12:
        return f"{sign}${abs_val / 1e12:.2f}T"
    if abs_val >= 1e9:
        return f"{sign}${abs_val / 1e9:.2f}B"
    if abs_val >= 1e6:
        return f"{sign}${abs_val / 1e6:.1f}M"
    if abs_val >= 1e3:
        return f"{sign}${abs_val / 1e3:.0f}K"
    return f"{sign}${abs_val:,.0f}"


def _fmt_count(val: float | None) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "N/A"
    abs_val = abs(val)
    sign = "-" if val < 0 else ""
    if abs_val >= 1e12:
        return f"{sign}{abs_val / 1e12:.2f}T"
    if abs_val >= 1e9:
        return f"{sign}{abs_val / 1e9:.2f}B"
    if abs_val >= 1e6:
        return f"{sign}{abs_val / 1e6:.1f}M"
    if abs_val >= 1e3:
        return f"{sign}{abs_val / 1e3:.0f}K"
    return f"{sign}{abs_val:,.0f}"


def _pct(val: float | None) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "N/A"
    return f"{val:+.1f}%"


def _delta_color(val: float | None) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "off"
    return "normal"


# ── Fetch data ───────────────────────────────────────────────────────────────

summary = ticker_summary(ticker, period_type)
if summary.empty:
    st.warning(f"No data found for **{ticker}**. Try another ticker.")
    st.stop()

latest = dict(zip(summary["metric_type"], summary["value"]))

# ── Page header ──────────────────────────────────────────────────────────────

latest_date = summary["period_end"].max()
filing_label = "Annual filing" if period_type == "annual" else "Quarterly filing"
latest_date_str = pd.Timestamp(latest_date).strftime("%Y-%m-%d")
st.markdown(
    f"<h1>{ticker}</h1>"
    f"<p style='color: #64748b; margin-top: -0.8rem; font-size: 0.9rem;'>"
    f"{filing_label} · Period ending <strong style='color:#94a3b8'>{latest_date_str}</strong></p>",
    unsafe_allow_html=True,
)

# ── Key Metrics Row ──────────────────────────────────────────────────────────

key_metrics = [
    ("Revenue", "revenue"),
    ("Net Income", "net_income"),
    ("Total Assets", "total_assets"),
    ("Total Liabilities", "total_liabilities"),
    ("Stockholders' Equity", "stockholders_equity"),
    ("Operating Cash Flow", "operating_cash_flow"),
    ("EPS (Diluted)", "eps_diluted"),
    ("Shares Outstanding", "common_shares_outstanding"),
]

growth_metrics = [m[1] for m in key_metrics if m[1] in latest]
gr = growth_rates(ticker, growth_metrics, period_type)

cols = st.columns(4)
for i, (label, metric) in enumerate(key_metrics):
    val = latest.get(metric)
    with cols[i % 4]:
        delta = None
        delta_color = "off"
        if not gr.empty and metric in gr.columns:
            last_growth = gr[metric].iloc[-1] if len(gr) > 0 else None
            if last_growth is not None and not np.isnan(last_growth):
                delta = f"{last_growth:+.1f}% YoY"
                delta_color = "normal"
        if metric == "eps_diluted":
            display_val = f"${val:.2f}" if val else "N/A"
        elif metric == "common_shares_outstanding":
            display_val = _fmt_count(val)
        else:
            display_val = _fmt(val)
        st.metric(label, display_val, delta=delta, delta_color=delta_color)

st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
# TAB LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════

tab_income, tab_balance, tab_cash, tab_health, tab_ratios, tab_growth, tab_quarterly = st.tabs([
    "Income Statement",
    "Balance Sheet",
    "Cash Flow",
    "Financial Health",
    "Financial Ratios",
    "Growth & Margins",
    "Quarterly Detail",
])

# ── Tab 1: Income Statement ─────────────────────────────────────────────────

with tab_income:
    inc_metrics = ["revenue", "cost_of_revenue", "gross_profit", "operating_income", "net_income"]
    inc_data = metric_timeseries(ticker, inc_metrics, period_type)

    if inc_data.empty:
        st.info("No income statement data available.")
    else:
        st.markdown('<p class="section-label">Revenue & Earnings</p>', unsafe_allow_html=True)
        st.subheader("Revenue vs Net Income")
        fig = px.bar(
            inc_data[inc_data["metric_type"].isin(["revenue", "net_income"])],
            x="period_end",
            y="value",
            color="metric_type",
            barmode="group",
            color_discrete_map={"revenue": COLORS["sky"], "net_income": COLORS["emerald"]},
            labels={"period_end": "Period", "value": "USD", "metric_type": ""},
        )
        _apply_layout(fig, yaxis_tickprefix="$")
        st.plotly_chart(fig, use_container_width=True)

        # Earnings waterfall
        st.markdown('<p class="section-label">Latest Period</p>', unsafe_allow_html=True)
        st.subheader("Income Breakdown")
        piv = pivot_metrics(ticker, inc_metrics, period_type)
        if not piv.empty:
            last_row = piv.iloc[-1]
            waterfall_items = []
            for m_name, m_key in [
                ("Revenue", "revenue"),
                ("Cost of Revenue", "cost_of_revenue"),
                ("Gross Profit", "gross_profit"),
                ("Operating Expenses", "operating_expenses"),
                ("Operating Income", "operating_income"),
                ("Net Income", "net_income"),
            ]:
                if m_key in last_row and not np.isnan(last_row.get(m_key, np.nan)):
                    waterfall_items.append((m_name, last_row[m_key]))

            if waterfall_items:
                fig_w = go.Figure(go.Bar(
                    x=[w[0] for w in waterfall_items],
                    y=[w[1] for w in waterfall_items],
                    marker_color=[
                        COLORS["sky"] if w[1] >= 0 else COLORS["rose"]
                        for w in waterfall_items
                    ],
                    marker_line=dict(width=0),
                ))
                _apply_layout(fig_w, yaxis_tickprefix="$", showlegend=False)
                st.plotly_chart(fig_w, use_container_width=True)

        # Detailed table
        st.markdown('<p class="section-label">Full Breakdown</p>', unsafe_allow_html=True)
        st.subheader("Period Detail")
        detail_metrics = [
            "revenue", "cost_of_revenue", "gross_profit",
            "operating_expenses", "research_and_development",
            "depreciation_and_amortization", "operating_income",
            "interest_expense", "income_tax_expense", "net_income",
            "eps_basic", "eps_diluted",
        ]
        detail_piv = pivot_metrics(ticker, detail_metrics, period_type)
        if not detail_piv.empty:
            display_df = detail_piv.copy()
            display_df.index = pd.to_datetime(display_df.index).strftime("%Y-%m-%d")
            st.dataframe(
                display_df.T.style.format("${:,.0f}", na_rep="—"),
                use_container_width=True,
            )


# ── Tab 2: Balance Sheet ────────────────────────────────────────────────────

with tab_balance:
    bs_metrics = [
        "total_assets", "total_current_assets", "cash",
        "accounts_receivable", "inventory", "goodwill", "intangible_assets",
        "total_liabilities", "total_current_liabilities",
        "accounts_payable", "short_term_debt", "long_term_debt",
        "stockholders_equity", "retained_earnings",
    ]
    bs_data = pivot_metrics(ticker, bs_metrics, period_type)

    if bs_data.empty:
        st.info("No balance sheet data available.")
    else:
        st.markdown('<p class="section-label">Overview</p>', unsafe_allow_html=True)
        st.subheader("Assets vs Liabilities vs Equity")
        top_bs = ["total_assets", "total_liabilities", "stockholders_equity"]
        top_piv = pivot_metrics(ticker, top_bs, period_type)
        if not top_piv.empty:
            melted = top_piv.reset_index().melt(
                id_vars="period_end", var_name="metric_type", value_name="value"
            )
            fig = px.bar(
                melted,
                x="period_end",
                y="value",
                color="metric_type",
                barmode="group",
                color_discrete_map={
                    "total_assets": COLORS["sky"],
                    "total_liabilities": COLORS["rose"],
                    "stockholders_equity": COLORS["emerald"],
                },
                labels={"period_end": "Period", "value": "USD", "metric_type": ""},
            )
            _apply_layout(fig, yaxis_tickprefix="$")
            st.plotly_chart(fig, use_container_width=True)

        # Composition charts
        col1, col2 = st.columns(2)

        with col1:
            st.markdown('<p class="section-label">Composition</p>', unsafe_allow_html=True)
            st.subheader("Asset Breakdown")
            asset_items = [
                ("Cash", "cash"),
                ("Receivables", "accounts_receivable"),
                ("Inventory", "inventory"),
                ("Goodwill", "goodwill"),
                ("Intangibles", "intangible_assets"),
            ]
            last_row = bs_data.iloc[-1]
            asset_vals = [
                (label, last_row.get(key, 0))
                for label, key in asset_items
                if key in last_row and not np.isnan(last_row.get(key, np.nan)) and last_row.get(key, 0) > 0
            ]
            if asset_vals:
                total_assets = last_row.get("total_assets", 0)
                known_sum = sum(v for _, v in asset_vals)
                if total_assets and not np.isnan(total_assets) and total_assets > known_sum:
                    asset_vals.append(("Other Assets", total_assets - known_sum))
                fig = px.pie(
                    names=[a[0] for a in asset_vals],
                    values=[a[1] for a in asset_vals],
                    color_discrete_sequence=COLOR_SEQ,
                    hole=0.55,
                )
                fig.update_traces(textposition="inside", textinfo="percent+label",
                                  textfont_size=11, textfont_color="#e2e8f0")
                _apply_layout(fig, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.markdown('<p class="section-label">Composition</p>', unsafe_allow_html=True)
            st.subheader("Liability Breakdown")
            liab_items = [
                ("Accounts Payable", "accounts_payable"),
                ("Short-term Debt", "short_term_debt"),
                ("Long-term Debt", "long_term_debt"),
            ]
            liab_vals = [
                (label, last_row.get(key, 0))
                for label, key in liab_items
                if key in last_row and not np.isnan(last_row.get(key, np.nan)) and last_row.get(key, 0) > 0
            ]
            if liab_vals:
                total_liab = last_row.get("total_liabilities", 0)
                known_sum = sum(v for _, v in liab_vals)
                if total_liab and not np.isnan(total_liab) and total_liab > known_sum:
                    liab_vals.append(("Other Liabilities", total_liab - known_sum))
                fig = px.pie(
                    names=[a[0] for a in liab_vals],
                    values=[a[1] for a in liab_vals],
                    color_discrete_sequence=[COLORS["rose"], COLORS["amber"], COLORS["violet"], COLORS["slate"]],
                    hole=0.55,
                )
                fig.update_traces(textposition="inside", textinfo="percent+label",
                                  textfont_size=11, textfont_color="#e2e8f0")
                _apply_layout(fig, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        # Detailed table
        st.markdown('<p class="section-label">Full Breakdown</p>', unsafe_allow_html=True)
        st.subheader("Balance Sheet Detail")
        display_df = bs_data.copy()
        display_df.index = pd.to_datetime(display_df.index).strftime("%Y-%m-%d")
        st.dataframe(
            display_df.T.style.format("${:,.0f}", na_rep="—"),
            use_container_width=True,
        )


# ── Tab 3: Cash Flow ────────────────────────────────────────────────────────

with tab_cash:
    cf_metrics = [
        "operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
        "capex", "dividends_paid",
    ]
    cf_data = metric_timeseries(ticker, cf_metrics, period_type)

    if cf_data.empty:
        st.info("No cash flow data available.")
    else:
        st.markdown('<p class="section-label">Overview</p>', unsafe_allow_html=True)
        st.subheader("Cash Flow Components")
        three_cf = cf_data[cf_data["metric_type"].isin([
            "operating_cash_flow", "investing_cash_flow", "financing_cash_flow"
        ])]
        fig = px.bar(
            three_cf,
            x="period_end",
            y="value",
            color="metric_type",
            barmode="group",
            color_discrete_map={
                "operating_cash_flow": COLORS["emerald"],
                "investing_cash_flow": COLORS["amber"],
                "financing_cash_flow": COLORS["violet"],
            },
            labels={"period_end": "Period", "value": "USD", "metric_type": ""},
        )
        _apply_layout(fig, yaxis_tickprefix="$")
        st.plotly_chart(fig, use_container_width=True)

        # Free cash flow
        st.markdown('<p class="section-label">Free Cash Flow</p>', unsafe_allow_html=True)
        st.subheader("OCF minus CapEx")
        fcf_data = metric_timeseries(
            ticker,
            ["operating_cash_flow", "capex"],
            period_type,
        )
        if not fcf_data.empty:
            fcf_piv = fcf_data.pivot(index="period_end", columns="metric_type", values="value").sort_index()
            if "operating_cash_flow" in fcf_piv.columns and "capex" in fcf_piv.columns:
                fcf_piv["free_cash_flow"] = fcf_piv["operating_cash_flow"] + fcf_piv["capex"]
                fcf_df = fcf_piv.reset_index()[["period_end", "free_cash_flow"]].dropna()
                fig = px.bar(
                    fcf_df,
                    x="period_end",
                    y="free_cash_flow",
                    color_discrete_sequence=[COLORS["teal"]],
                    labels={"period_end": "Period", "free_cash_flow": "Free Cash Flow"},
                )
                _apply_layout(fig, yaxis_tickprefix="$", showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        # Capex & Dividends
        col1, col2 = st.columns(2)
        with col1:
            capex_data = cf_data[cf_data["metric_type"] == "capex"]
            if not capex_data.empty:
                st.markdown('<p class="section-label">Investing</p>', unsafe_allow_html=True)
                st.subheader("Capital Expenditures")
                fig = px.bar(
                    capex_data,
                    x="period_end", y="value",
                    color_discrete_sequence=[COLORS["amber"]],
                    labels={"period_end": "Period", "value": "CapEx"},
                )
                _apply_layout(fig, yaxis_tickprefix="$", showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        with col2:
            div_data = cf_data[cf_data["metric_type"] == "dividends_paid"]
            if not div_data.empty:
                st.markdown('<p class="section-label">Shareholder Returns</p>', unsafe_allow_html=True)
                st.subheader("Dividends Paid")
                fig = px.bar(
                    div_data,
                    x="period_end", y="value",
                    color_discrete_sequence=[COLORS["violet"]],
                    labels={"period_end": "Period", "value": "Dividends"},
                )
                _apply_layout(fig, yaxis_tickprefix="$", showlegend=False)
                st.plotly_chart(fig, use_container_width=True)


# ── Tab 4: Financial Health (Snowflake / Radar) ─────────────────────────────

with tab_health:
    st.markdown('<p class="section-label">Snapshot</p>', unsafe_allow_html=True)
    st.subheader("Financial Health")

    # Compute ratios via the centralized backend
    ratios = all_ratios_latest(ticker, period_type)

    gross_margin = ratios.get("gross_profit_margin")
    net_margin = ratios.get("net_profit_margin")
    roe = ratios.get("return_on_equity")
    roa = ratios.get("return_on_assets")
    leverage = ratios.get("financial_leverage_ratio")
    current_ratio = ratios.get("current_ratio")
    asset_turnover = ratios.get("asset_turnover")

    def _score(val: float | None, good_threshold: float, bad_threshold: float, invert: bool = False) -> float:
        if val is None or np.isnan(val):
            return 0
        if invert:
            val = -val
            good_threshold, bad_threshold = -good_threshold, -bad_threshold
        if val >= good_threshold:
            return min(100, 50 + 50 * (val / good_threshold))
        if val <= bad_threshold:
            return max(0, 50 * (val - bad_threshold) / (good_threshold - bad_threshold))
        return 50 * (val - bad_threshold) / (good_threshold - bad_threshold)

    dimensions = [
        ("Profitability", _score(net_margin, 0.15, -0.05) if net_margin else 0),
        ("ROE", _score(roe, 0.20, -0.10) if roe else 0),
        ("Liquidity", _score(current_ratio, 2.0, 0.5) if current_ratio else 0),
        ("Debt Health", _score(leverage, 1.5, 5.0, invert=True) if leverage else 50),
        ("Growth", 50),
        ("Cash Generation", _score(
            ratios.get("operating_cash_flow_sales_ratio"),
            0.20, -0.05,
        ) if ratios.get("operating_cash_flow_sales_ratio") is not None else 0),
    ]

    rev_growth = growth_rates(ticker, ["revenue"], "annual")
    if not rev_growth.empty and "revenue" in rev_growth.columns:
        last_rev_g = rev_growth["revenue"].iloc[-1]
        if not np.isnan(last_rev_g):
            dimensions[4] = ("Growth", _score(last_rev_g / 100, 0.15, -0.10))

    categories = [d[0] for d in dimensions]
    values = [d[1] for d in dimensions]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values + [values[0]],
        theta=categories + [categories[0]],
        fill="toself",
        fillcolor="rgba(56, 189, 248, 0.12)",
        line=dict(color=COLORS["sky"], width=2),
        marker=dict(size=6, color=COLORS["sky"]),
        name=ticker,
    ))
    _apply_layout(fig,
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(visible=True, range=[0, 100], showticklabels=False,
                           gridcolor="rgba(148,163,184,0.10)"),
            angularaxis=dict(gridcolor="rgba(148,163,184,0.10)",
                            tickfont=dict(size=12, color="#94a3b8")),
        ),
        showlegend=False,
        height=420,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Ratio cards — show period value with TTM as delta
    ttm_health = all_ratios_ttm(ticker)
    st.markdown('<p class="section-label">Key Ratios</p>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)

    def _health_ttm_delta(ratio_name, fmt="pct"):
        v = ttm_health.get(ratio_name)
        if v is None:
            return None
        return f"TTM: {v:.1%}" if fmt == "pct" else f"TTM: {v:.2f}"

    with c1:
        st.metric("Gross Margin", f"{gross_margin:.1%}" if gross_margin else "N/A",
                   delta=_health_ttm_delta("gross_profit_margin"), delta_color="off")
        st.metric("Net Margin", f"{net_margin:.1%}" if net_margin else "N/A",
                   delta=_health_ttm_delta("net_profit_margin"), delta_color="off")

    with c2:
        st.metric("Return on Equity", f"{roe:.1%}" if roe else "N/A",
                   delta=_health_ttm_delta("return_on_equity"), delta_color="off")
        st.metric("Return on Assets", f"{roa:.1%}" if roa else "N/A",
                   delta=_health_ttm_delta("return_on_assets"), delta_color="off")

    with c3:
        st.metric("Current Ratio", f"{current_ratio:.2f}" if current_ratio else "N/A",
                   delta=_health_ttm_delta("current_ratio", "x"), delta_color="off")
        st.metric("Leverage", f"{leverage:.2f}" if leverage else "N/A",
                   delta=_health_ttm_delta("financial_leverage_ratio", "x"), delta_color="off")

    with c4:
        st.metric("Asset Turnover", f"{asset_turnover:.2f}" if asset_turnover else "N/A",
                   delta=_health_ttm_delta("asset_turnover", "x"), delta_color="off")
        ocf_margin = ratios.get("operating_cash_flow_sales_ratio")
        st.metric("OCF Margin", f"{ocf_margin:.1%}" if ocf_margin else "N/A",
                   delta=_health_ttm_delta("operating_cash_flow_sales_ratio"), delta_color="off")


# ── Tab 5: Financial Ratios (All) ───────────────────────────────────────────

with tab_ratios:
    st.markdown('<p class="section-label">Comprehensive Analysis</p>', unsafe_allow_html=True)
    st.subheader("Financial Ratios")
    st.caption(
        "All ratios computed from SEC XBRL filings. "
        "Ratios requiring market price (P/E, P/B, etc.) are excluded."
    )

    # Get all ratios (latest + time series)
    all_latest = all_ratios_latest(ticker, period_type)
    all_wide = all_ratios_wide(ticker, period_type)
    ttm_latest = all_ratios_ttm(ticker)

    def _fmt_ratio(val, fmt_type):
        if val is None:
            return "N/A"
        if fmt_type == "pct":
            return f"{val:.2%}"
        elif fmt_type == "days":
            return f"{val:.1f} days"
        elif fmt_type == "dollar":
            if abs(val) >= 1e9:
                return f"${val / 1e9:,.2f}B"
            if abs(val) >= 1e6:
                return f"${val / 1e6:,.1f}M"
            return f"${val:,.2f}"
        else:
            return f"{val:.2f}x"

    ratio_categories = get_ratios_by_category()

    for cat_name, cat_ratios in ratio_categories.items():
        st.markdown(f'<p class="section-label">{cat_name}</p>', unsafe_allow_html=True)

        # Show latest values as metric cards (4 per row)
        # Each card shows the period-based value + TTM delta
        num_cols = 4
        for row_start in range(0, len(cat_ratios), num_cols):
            row_ratios = cat_ratios[row_start:row_start + num_cols]
            cols = st.columns(num_cols)
            for i, rdef in enumerate(row_ratios):
                val = all_latest.get(rdef.name)
                ttm_val = ttm_latest.get(rdef.name)
                label = rdef.name.replace("_", " ").title()
                with cols[i]:
                    ttm_label = f"TTM: {_fmt_ratio(ttm_val, rdef.display_format)}" if ttm_val is not None else None
                    st.metric(label, _fmt_ratio(val, rdef.display_format), delta=ttm_label, delta_color="off")

        # Show time series chart if we have the data
        cat_ratio_names = [r.name for r in cat_ratios]
        available_in_wide = [n for n in cat_ratio_names if not all_wide.empty and n in all_wide.columns]
        if available_in_wide and not all_wide.empty:
            chart_data = all_wide[available_in_wide].copy()
            chart_data = chart_data.dropna(how="all")
            if not chart_data.empty:
                chart_reset = chart_data.reset_index()
                chart_melted = chart_reset.melt(
                    id_vars="period_end", var_name="ratio", value_name="value",
                )
                chart_melted["ratio"] = chart_melted["ratio"].str.replace("_", " ").str.title()
                fig = px.line(
                    chart_melted,
                    x="period_end",
                    y="value",
                    color="ratio",
                    markers=True,
                    labels={"period_end": "Period", "value": "", "ratio": ""},
                )
                fig.update_traces(line_width=2.5, marker_size=6)
                _apply_layout(fig)
                st.plotly_chart(fig, use_container_width=True)

        st.divider()


# ── Tab 6: Growth & Margins ─────────────────────────────────────────────────

with tab_growth:
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown('<p class="section-label">Year-over-Year</p>', unsafe_allow_html=True)
        st.subheader("Revenue & Earnings Growth")
        g = growth_rates(ticker, ["revenue", "net_income"], period_type)
        if not g.empty:
            g_reset = g.reset_index()
            g_melted = g_reset.melt(id_vars="period_end", var_name="metric", value_name="growth_pct")
            fig = px.bar(
                g_melted,
                x="period_end",
                y="growth_pct",
                color="metric",
                barmode="group",
                color_discrete_map={"revenue": COLORS["sky"], "net_income": COLORS["emerald"]},
                labels={"period_end": "Period", "growth_pct": "YoY %", "metric": ""},
            )
            _apply_layout(fig, yaxis_ticksuffix="%")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Not enough data to compute growth rates.")

    with col_right:
        st.markdown('<p class="section-label">Trend</p>', unsafe_allow_html=True)
        st.subheader("Profitability Margins")
        margin_metrics = ["revenue", "gross_profit", "operating_income", "net_income"]
        piv = pivot_metrics(ticker, margin_metrics, period_type)
        if not piv.empty and "revenue" in piv.columns:
            margin_df = pd.DataFrame(index=piv.index)
            if "gross_profit" in piv.columns:
                margin_df["Gross Margin"] = piv["gross_profit"] / piv["revenue"] * 100
            if "operating_income" in piv.columns:
                margin_df["Operating Margin"] = piv["operating_income"] / piv["revenue"] * 100
            if "net_income" in piv.columns:
                margin_df["Net Margin"] = piv["net_income"] / piv["revenue"] * 100

            if not margin_df.empty:
                m_reset = margin_df.reset_index()
                m_melted = m_reset.melt(id_vars="period_end", var_name="margin", value_name="pct")
                fig = px.line(
                    m_melted,
                    x="period_end",
                    y="pct",
                    color="margin",
                    color_discrete_sequence=[COLORS["sky"], COLORS["amber"], COLORS["emerald"]],
                    markers=True,
                    labels={"period_end": "Period", "pct": "%", "margin": ""},
                )
                fig.update_traces(line_width=2.5, marker_size=7)
                _apply_layout(fig, yaxis_ticksuffix="%")
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Not enough data to compute margins.")

    # Cash flow vs net income
    st.markdown('<p class="section-label">Earnings Quality</p>', unsafe_allow_html=True)
    st.subheader("Net Income vs Operating Cash Flow")
    eq_data = pivot_metrics(ticker, ["net_income", "operating_cash_flow"], period_type)
    if not eq_data.empty:
        eq_reset = eq_data.reset_index()
        eq_melted = eq_reset.melt(id_vars="period_end", var_name="metric", value_name="value")
        fig = px.line(
            eq_melted,
            x="period_end",
            y="value",
            color="metric",
            color_discrete_map={
                "net_income": COLORS["sky"],
                "operating_cash_flow": COLORS["emerald"],
            },
            markers=True,
            labels={"period_end": "Period", "value": "USD", "metric": ""},
        )
        fig.update_traces(line_width=2.5, marker_size=7)
        _apply_layout(fig, yaxis_tickprefix="$")
        st.plotly_chart(fig, use_container_width=True)

# ── Tab 7: Quarterly Detail ──────────────────────────────────────────────────

with tab_quarterly:
    st.markdown('<p class="section-label">Discrete Quarters</p>', unsafe_allow_html=True)
    st.subheader("Quarterly Breakdown")
    st.caption(
        "Discrete quarter values (Q4 derived from Annual minus 9-month YTD). "
        "TTM = sum of last 4 quarters for income / cash-flow items when the metric is current through the latest quarter."
    )

    qd_metrics = [
        "gross_profit", "operating_expenses", "operating_income",
        "net_income", "eps_diluted", "eps_basic",
        "common_shares_outstanding", "dividends_paid",
        "revenue", "cost_of_revenue",
        "income_tax_expense", "interest_expense",
        "research_and_development", "depreciation_and_amortization",
    ]

    qd = quarterly_detail(ticker, qd_metrics, n_quarters=10)

    if qd.empty:
        st.info("No quarterly data available. Re-run data extraction to populate discrete quarter values.")
    else:
        # Pretty labels for metric rows
        METRIC_LABELS = {
            "revenue": "Revenue",
            "cost_of_revenue": "Cost of Revenue",
            "gross_profit": "Gross Profit",
            "operating_expenses": "Operating Income/Expenses",
            "operating_income": "Total Operating Profit/Loss",
            "income_tax_expense": "Provision for Income Tax",
            "interest_expense": "Interest Expense",
            "net_income": "Net Income",
            "eps_basic": "Basic EPS",
            "eps_diluted": "Diluted EPS",
            "common_shares_outstanding": "Shares Outstanding",
            "dividends_paid": "Dividends Paid",
            "research_and_development": "R&D Expense",
            "depreciation_and_amortization": "Depreciation & Amortization",
        }
        qd.index = qd.index.map(lambda m: METRIC_LABELS.get(m, m))

        # Display with formatting
        def _fmt_cell(val):
            if pd.isna(val):
                return "—"
            abs_val = abs(val)
            sign = "-" if val < 0 else ""
            if abs_val >= 1e9:
                return f"{sign}{abs_val / 1e6:,.0f}"
            if abs_val >= 1e6:
                return f"{sign}{abs_val / 1e6:,.0f}"
            if abs_val >= 1e3:
                return f"{sign}{abs_val:,.2f}"
            return f"{sign}{abs_val:,.2f}"

        st.caption("USD in Millions except per share data. Blank cells mean the metric was not separately reported for that quarter.")
        display_qd = qd.apply(lambda col: col.map(_fmt_cell))
        st.dataframe(display_qd, use_container_width=True, height=550)

# ── Footer ───────────────────────────────────────────────────────────────────

st.divider()
st.caption(
    "Data sourced from SEC EDGAR XBRL filings. "
    "This is not investment advice. All figures are as reported in SEC filings."
)
