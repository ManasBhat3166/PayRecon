"""PayRecon - Streamlit dashboard. All business logic lives in reconciliation.py."""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st

import config as cfg
import data_generator
import reconciliation as rc

st.set_page_config(page_title="PayRecon", layout="wide")

# Minimal, theme-friendly styling: bordered metric cards, nothing decorative.
st.markdown(
    """
    <style>
    div[data-testid="stMetric"] {
        border: 1px solid rgba(128,128,128,0.35);
        border-radius: 8px;
        padding: 0.75rem 1rem;
    }
    div[data-testid="stMetricValue"] { font-size: 1.45rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

DISPLAY_COLUMNS = [
    "transaction_id", "transaction_type", "transaction_date", "settlement_date",
    "platform_amount", "bank_amount", "difference", "category", "explanation",
]


def money(value: Decimal) -> str:
    return f"{cfg.DEFAULT_CURRENCY} {rc.quantize_money(value):,.2f}"


def table(df: pd.DataFrame, columns: list[str] | None = None) -> None:
    shown = rc.to_display_frame(df)
    st.dataframe(shown[columns] if columns else shown, hide_index=True, width="stretch")


@st.cache_data(show_spinner=False)
def load_sample() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Use the committed CSVs; regenerate in memory if they are missing."""
    if cfg.TRANSACTIONS_FILE.exists() and cfg.SETTLEMENTS_FILE.exists():
        return rc.load_csv(cfg.TRANSACTIONS_FILE), rc.load_csv(cfg.SETTLEMENTS_FILE)
    return data_generator.generate_dataframes()


# ---------------------------------------------------------------- sidebar
st.sidebar.title("PayRecon")
st.sidebar.caption("Payment reconciliation & discrepancy detection")

source = st.sidebar.radio("Data source", ["Sample dataset", "Upload CSV files"])
tx_upload = st_upload = None
if source == "Upload CSV files":
    tx_upload = st.sidebar.file_uploader("Platform transactions CSV", type="csv", key="tx_up")
    st_upload = st.sidebar.file_uploader("Bank settlements CSV", type="csv", key="st_up")

default_year, default_month = (int(x) for x in cfg.DEFAULT_REPORTING_MONTH.split("-"))
year = int(st.sidebar.number_input("Year", min_value=2000, max_value=2100, value=default_year, step=1))
month = st.sidebar.selectbox(
    "Reporting month", list(range(1, 13)), index=default_month - 1,
    format_func=lambda m: calendar.month_name[m],
)
month_key = f"{year}-{month:02d}"
m_start, m_end = rc.month_bounds(month_key)
cutoff = st.sidebar.date_input(
    "Settlement cutoff date", value=m_end, min_value=m_start, key=f"cutoff_{month_key}",
    help="Bank settlements dated after this day count as outstanding, not received.",
)
st.sidebar.caption(f"Per-record tolerance: {cfg.ROUNDING_TOLERANCE} {cfg.DEFAULT_CURRENCY}")
run_clicked = st.sidebar.button("Run reconciliation", type="primary")


def run_reconciliation() -> None:
    try:
        if source == "Sample dataset":
            tx_df, st_df = load_sample()
            label = "Sample dataset"
        else:
            if tx_upload is None or st_upload is None:
                st.sidebar.warning("Upload both CSV files first.")
                return
            tx_df, st_df = rc.load_csv(tx_upload), rc.load_csv(st_upload)
            label = f"{tx_upload.name} + {st_upload.name}"
        result = rc.reconcile(tx_df, st_df, reporting_month=month_key, cutoff_date=cutoff)
        st.session_state["bundle"] = {"result": result, "tx": tx_df, "st": st_df, "label": label}
    except rc.SchemaError as exc:
        st.session_state.pop("bundle", None)
        st.error(f"Input file problem: {exc}")
    except ValueError as exc:
        st.error(f"Invalid settings: {exc}")
    except Exception as exc:  # unexpected - show it rather than crash the page
        st.session_state.pop("bundle", None)
        st.error(f"Reconciliation failed: {exc}")


if run_clicked or ("bundle" not in st.session_state and source == "Sample dataset"):
    run_reconciliation()

# ---------------------------------------------------------------- main page
st.title("PayRecon")
st.caption("Platform transactions vs bank settlements - month-end reconciliation")

bundle = st.session_state.get("bundle")
if not bundle:
    st.info("Choose a data source in the sidebar and click **Run reconciliation**.")
    st.stop()

result: rc.ReconciliationResult = bundle["result"]
s = result.summary
st.markdown(
    f"**Source:** {bundle['label']} &nbsp;|&nbsp; **Period:** {result.reporting_month} "
    f"&nbsp;|&nbsp; **Cutoff:** {result.cutoff_date} &nbsp;|&nbsp; **Currency:** {cfg.DEFAULT_CURRENCY}"
)

tab_overview, tab_matched, tab_disc, tab_detail, tab_quality, tab_download = st.tabs(
    ["Overview", "Matched transactions", "Discrepancies", "Transaction details",
     "Data quality", "Download report"]
)

# ---------------------------------------------------------------- overview
with tab_overview:
    c = st.columns(4)
    c[0].metric("Total transactions", s["total_transactions"])
    c[1].metric("Total settlements", s["total_settlements"])
    c[2].metric("Matched transactions", s["reconciled_count"],
                help=f"{s['matched_count']} exact + {s['rounding_count']} within per-record tolerance")
    c[3].metric("Unmatched transactions", s["unmatched_count"])
    c = st.columns(4)
    c[0].metric("Duplicate entries", s["duplicate_count"])
    c[1].metric("Timing differences", s["timing_difference_count"])
    c[2].metric("Orphan refunds", s["orphan_refund_count"])
    c[3].metric("Total financial discrepancy", money(s["total_financial_discrepancy"]),
                help="Sum of absolute differences on every flagged record (duplicates excluded).")

    st.subheader("Financial summary")
    cards = [
        ("Platform total (net)", s["total_platform_amount"]),
        ("Bank total (net, valid)", s["total_bank_amount"]),
        ("Matched amount", s["total_matched_amount"]),
        ("Outstanding (timing)", s["total_outstanding_amount"]),
        ("Amount mismatch", s["total_amount_mismatch"]),
        ("Duplicate amount excluded", s["duplicate_amount_excluded"]),
        ("Refund amount", s["refund_amount"]),
        ("Aggregate rounding difference", s["aggregate_rounding_difference"]),
        ("Net reconciliation difference", s["net_reconciliation_difference"]),
        ("Unresolved (excl. timing)", s["unresolved_difference"]),
    ]
    for start in (0, 5):
        cols = st.columns(5)
        for col, (label, value) in zip(cols, cards[start:start + 5]):
            if label == "Aggregate rounding difference":
                col.metric(label, f"{cfg.DEFAULT_CURRENCY} {rc.format_amount(value)}")
            else:
                col.metric(label, money(value))

    if s["rounding_aggregate_visible"]:
        st.warning(
            f"{s['rounding_count']} records each differ by less than the {cfg.ROUNDING_TOLERANCE} "
            f"tolerance, but together they differ by {rc.format_amount(s['aggregate_rounding_difference'])}, "
            "which exceeds the tolerance."
        )
    if s["unexplained_difference"] == 0:
        st.success("Reconciliation bridge balances: every unit of the net difference is attributed to a record.")
    else:
        st.error(f"Unattributed difference of {rc.format_amount(s['unexplained_difference'])} - investigate.")

    left, right = st.columns(2)
    with left:
        st.markdown("**Records by category**")
        counts = pd.Series(s["category_counts"]).rename("records")
        st.bar_chart(counts[counts > 0])
    with right:
        st.markdown("**Net difference by category** (platform minus bank)")
        bridge = pd.Series({k: float(v) for k, v in s["difference_by_category"].items() if v != 0})
        if bridge.empty:
            st.caption("No differences to chart.")
        else:
            st.bar_chart(bridge.rename("difference"))
    if s["out_of_scope_transactions"] or s["out_of_scope_settlements"]:
        st.caption(
            f"Ignored as outside the reporting window: {s['out_of_scope_transactions']} platform "
            f"transaction(s), {s['out_of_scope_settlements']} bank settlement(s)."
        )

# ---------------------------------------------------------------- matched
with tab_matched:
    matched = result.matched
    st.write(f"{len(matched)} records reconciled "
             f"({s['matched_count']} exact, {s['rounding_count']} within rounding tolerance).")
    table(matched, DISPLAY_COLUMNS)

# ---------------------------------------------------------------- discrepancies
with tab_disc:
    disc = result.discrepancies
    present = [c for c in cfg.ALL_CATEGORIES if c != cfg.MATCHED and c in set(disc["category"])]
    chosen = st.multiselect("Filter by discrepancy type", present, default=present)
    view = disc[disc["category"].isin(chosen)] if chosen else disc.iloc[0:0]
    st.write(f"Showing {len(view)} of {len(disc)} discrepancy records.")
    table(view, DISPLAY_COLUMNS)

# ---------------------------------------------------------------- details
with tab_detail:
    ids = sorted({i for i in result.results["transaction_id"] if i})
    if not ids:
        st.caption("No transactions loaded.")
    else:
        pick = st.selectbox("Transaction ID", ids)
        rows = result.results[result.results["transaction_id"] == pick]
        for _, r in rows.iterrows():
            st.markdown(f"**{r['category']}** ({r['source'].lower()} record)")
            st.write(r["explanation"])
        st.markdown("**Reconciliation rows**")
        table(rows, DISPLAY_COLUMNS + ["settlement_id", "original_transaction_id"])
        st.markdown("**Raw platform record(s)**")
        st.dataframe(bundle["tx"][bundle["tx"]["transaction_id"].str.strip() == pick],
                     hide_index=True, width="stretch")
        st.markdown("**Raw bank settlement record(s)**")
        st.dataframe(bundle["st"][bundle["st"]["transaction_id"].str.strip() == pick],
                     hide_index=True, width="stretch")

# ---------------------------------------------------------------- data quality
with tab_quality:
    bad = result.results[result.results["category"] == cfg.INVALID_RECORD]
    if bad.empty:
        st.success("No invalid records.")
    else:
        st.write(f"{len(bad)} invalid record(s) were excluded from totals.")
        table(bad, ["source", "transaction_id", "transaction_type", "transaction_date",
                    "settlement_date", "explanation"])

# ---------------------------------------------------------------- download
with tab_download:
    stamp = f"{result.reporting_month}_cutoff_{result.cutoff_date}"
    st.download_button("Download full reconciliation report (CSV)",
                       rc.report_to_csv(result.results),
                       file_name=f"payrecon_report_{stamp}.csv", mime="text/csv")
    st.download_button("Download discrepancies only (CSV)",
                       rc.report_to_csv(result.discrepancies),
                       file_name=f"payrecon_discrepancies_{stamp}.csv", mime="text/csv")
    if st.button("Save a copy to the reports/ folder"):
        path = rc.save_report(result.results, cfg.REPORTS_DIR / f"payrecon_report_{stamp}.csv")
        st.success(f"Saved {path}")
