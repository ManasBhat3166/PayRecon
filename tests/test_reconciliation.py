"""Automated tests for the PayRecon engine (TC01-TC15 + sample-data checks)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd
import pytest

import config as cfg
import data_generator
import reconciliation as rc

D = Decimal


# --------------------------------------------------------------------------
# Helpers: build tiny datasets
# --------------------------------------------------------------------------
def tx(tid, day, amount, ttype="PAYMENT", original="", currency="INR", status="COMPLETED"):
    return {"transaction_id": tid, "transaction_date": day, "transaction_type": ttype,
            "original_transaction_id": original, "amount": amount, "currency": currency, "status": status}


def st(sid, tid, day, amount, ttype="PAYMENT", original="", currency="INR"):
    return {"settlement_id": sid, "transaction_id": tid, "settlement_date": day,
            "transaction_type": ttype, "original_transaction_id": original,
            "amount": amount, "currency": currency}


def frames(tx_rows, st_rows):
    return (pd.DataFrame(tx_rows, columns=cfg.TRANSACTION_COLUMNS, dtype=str),
            pd.DataFrame(st_rows, columns=cfg.SETTLEMENT_COLUMNS, dtype=str))


def run(tx_rows, st_rows, **kw):
    t, s = frames(tx_rows, st_rows)
    return rc.reconcile(t, s, reporting_month="2026-11", **kw)


def cat_of(result, tid, source="PLATFORM"):
    df = result.results
    return df[(df.transaction_id == tid) & (df.source == source)].iloc[0]


# --------------------------------------------------------------------------
# TC01-TC15
# --------------------------------------------------------------------------
def test_tc01_normal_payment_matching():
    r = run([tx("T1", "2026-11-05", "1000.00")], [st("S1", "T1", "2026-11-06", "1000.00")])
    row = cat_of(r, "T1")
    assert row.category == cfg.MATCHED
    assert row.difference == D("0")
    assert r.summary["matched_count"] == 1
    assert r.summary["unmatched_count"] == 0
    assert r.summary["net_reconciliation_difference"] == 0


def test_tc02_next_month_settlement_is_timing_not_missing():
    r = run([tx("T1", "2026-11-30", "500.00")], [st("S1", "T1", "2026-12-02", "500.00")])
    row = cat_of(r, "T1")
    assert row.category == cfg.TIMING_DIFFERENCE
    assert row.settlement_date == "2026-12-02"
    assert "Outstanding" in row.explanation
    assert r.summary["missing_settlement_count"] == 0
    assert r.summary["total_outstanding_amount"] == D("500.00")
    assert r.summary["total_bank_amount"] == 0  # not yet received at cutoff


def test_tc03_duplicate_settlement_detection():
    r = run([tx("T1", "2026-11-05", "1000.00")],
            [st("S1", "T1", "2026-11-06", "1000.00"), st("S2", "T1", "2026-11-07", "1000.00")])
    dup = cat_of(r, "T1", source="BANK")
    assert dup.category == cfg.DUPLICATE_SETTLEMENT
    assert dup.settlement_id == "S2"            # the later record is the duplicate
    assert "S1" in dup.explanation              # ...and names the original
    assert cat_of(r, "T1").category == cfg.MATCHED
    assert r.summary["duplicate_count"] == 1


def test_tc04_orphan_refund_detection():
    r = run([tx("R1", "2026-11-10", "300.00", "REFUND", "T-GHOST")],
            [st("S1", "R1", "2026-11-11", "300.00", "REFUND", "T-GHOST")])
    row = cat_of(r, "R1")
    assert row.category == cfg.ORPHAN_REFUND      # never MATCHED, even though the bank paid it
    assert r.summary["matched_count"] == 0
    assert r.summary["orphan_refund_count"] == 1
    assert r.summary["orphan_refund_amount"] == D("300.00")


def test_tc05_valid_refund_matching():
    r = run([tx("T1", "2026-11-03", "1000.00"), tx("R1", "2026-11-10", "300.00", "REFUND", "T1")],
            [st("S1", "T1", "2026-11-04", "1000.00"),
             st("S2", "R1", "2026-11-11", "300.00", "REFUND", "T1")])
    row = cat_of(r, "R1")
    assert row.category == cfg.MATCHED
    assert row.platform_amount == D("-300.00") and row.bank_amount == D("-300.00")  # refunds are negative
    assert r.summary["orphan_refund_count"] == 0
    assert r.summary["refund_amount"] == D("300.00")
    assert r.summary["total_platform_amount"] == D("700.00")


def test_tc06_aggregate_rounding_discrepancy():
    """Each gap is 0.005 (<= 0.01 tolerance) but the four gaps add up to 0.020."""
    raws = ["1250.005", "899.995", "2340.505", "415.755"]
    assert D("899.995").quantize(D("0.01"), rounding=ROUND_HALF_UP) == D("900.00")  # policy check
    tx_rows, st_rows = [], []
    for i, raw in enumerate(raws, 1):
        bank = D(raw).quantize(D("0.01"), rounding=ROUND_HALF_UP)  # bank settles whole paise
        tx_rows.append(tx(f"T{i}", "2026-11-10", raw))
        st_rows.append(st(f"S{i}", f"T{i}", "2026-11-11", str(bank)))
    r = run(tx_rows, st_rows)
    rounding_rows = r.results[r.results.category == cfg.ROUNDING_DIFFERENCE]
    assert len(rounding_rows) == 4
    assert all(abs(d) <= cfg.ROUNDING_TOLERANCE for d in rounding_rows.difference)  # invisible one by one
    assert r.summary["amount_mismatch_count"] == 0
    assert r.summary["aggregate_rounding_difference"] == D("-0.020")                 # visible in aggregate
    assert abs(r.summary["aggregate_rounding_difference"]) > cfg.ROUNDING_TOLERANCE
    assert r.summary["rounding_aggregate_visible"] is True
    assert rc.quantize_money(r.summary["aggregate_rounding_difference"]) == D("-0.02")
    assert r.summary["net_reconciliation_difference"] == D("-0.020")


def test_tc06b_rounding_below_aggregate_threshold_is_not_visible():
    r = run([tx("T1", "2026-11-10", "100.004")], [st("S1", "T1", "2026-11-11", "100.00")])
    assert cat_of(r, "T1").category == cfg.ROUNDING_DIFFERENCE
    assert r.summary["rounding_aggregate_visible"] is False


def test_tc07_missing_settlement_detection():
    r = run([tx("T1", "2026-11-10", "750.00")], [])
    row = cat_of(r, "T1")
    assert row.category == cfg.MISSING_SETTLEMENT
    assert row.settlement_date == ""
    assert r.summary["total_missing_amount"] == D("750.00")


def test_tc08_amount_mismatch_detection():
    r = run([tx("T1", "2026-11-10", "500.00")], [st("S1", "T1", "2026-11-11", "450.00")])
    row = cat_of(r, "T1")
    assert row.category == cfg.AMOUNT_MISMATCH
    assert row.difference == D("50.00")
    assert r.summary["total_amount_mismatch"] == D("50.00")


def test_tc09_invalid_csv_schema():
    good_tx, good_st = frames([tx("T1", "2026-11-05", "10.00")], [])
    with pytest.raises(rc.SchemaError, match="amount"):
        rc.reconcile(good_tx.drop(columns=["amount"]), good_st, reporting_month="2026-11")
    with pytest.raises(rc.SchemaError, match="settlement_date"):
        rc.reconcile(good_tx, good_st.drop(columns=["settlement_date"]), reporting_month="2026-11")
    with pytest.raises(rc.SchemaError):
        rc.reconcile(pd.DataFrame(), pd.DataFrame(), reporting_month="2026-11")


def test_tc09b_empty_or_garbage_csv_file(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    with pytest.raises(rc.SchemaError):
        rc.load_csv(empty)


@pytest.mark.parametrize("bad_date", ["2026-13-45", "11/05/2026", "not-a-date", "2026-02-30", ""])
def test_tc10_invalid_date_handling(bad_date):
    r = run([tx("T1", bad_date, "100.00"), tx("T2", "2026-11-05", "200.00")],
            [st("S2", "T2", "2026-11-06", "200.00")])
    bad = cat_of(r, "T1")
    assert bad.category == cfg.INVALID_RECORD
    assert "date" in bad.explanation
    assert cat_of(r, "T2").category == cfg.MATCHED   # one bad row doesn't stop the run
    assert r.summary["invalid_record_count"] == 1


@pytest.mark.parametrize("bad_amount", ["abc", "-5.00", "0", "", "NaN", "Infinity", "1,000.00"])
def test_tc11_invalid_amount_handling(bad_amount):
    r = run([tx("T1", "2026-11-05", bad_amount), tx("T2", "2026-11-05", "200.00")],
            [st("S2", "T2", "2026-11-06", "200.00")])
    bad = cat_of(r, "T1")
    assert bad.category == cfg.INVALID_RECORD
    assert "amount" in bad.explanation
    assert r.summary["total_platform_amount"] == D("200.00")  # invalid rows stay out of totals


def test_tc12_duplicate_transaction_reference_handling():
    r = run([tx("T1", "2026-11-05", "100.00"), tx("T1", "2026-11-06", "999.00")],
            [st("S1", "T1", "2026-11-06", "100.00")])
    cats = list(r.results[r.results.source == "PLATFORM"].category)
    assert cats.count(cfg.MATCHED) == 1 and cats.count(cfg.INVALID_RECORD) == 1
    invalid = r.results[r.results.category == cfg.INVALID_RECORD].iloc[0]
    assert "duplicate transaction reference" in invalid.explanation
    assert r.summary["total_platform_amount"] == D("100.00")  # first occurrence wins


def test_tc13_duplicate_settlement_excluded_from_totals():
    r = run([tx("T1", "2026-11-05", "1000.00")],
            [st("S1", "T1", "2026-11-06", "1000.00"), st("S2", "T1", "2026-11-07", "1000.00")])
    assert r.summary["total_bank_amount"] == D("1000.00")          # not 2000
    assert r.summary["duplicate_amount_excluded"] == D("1000.00")
    assert r.summary["net_reconciliation_difference"] == D("0")
    assert r.summary["unexplained_difference"] == D("0")


def test_tc14_month_end_cutoff_calculation():
    t = [tx("T1", "2026-11-30", "500.00")]
    s = [st("S1", "T1", "2026-12-02", "500.00")]
    nov = run(t, s)  # default cutoff = 30 Nov
    assert nov.cutoff_date == date(2026, 11, 30)
    assert cat_of(nov, "T1").category == cfg.TIMING_DIFFERENCE
    assert nov.summary["total_outstanding_amount"] == D("500.00")

    later = run(t, s, cutoff_date=date(2026, 12, 31))  # settlement now inside the cutoff
    assert cat_of(later, "T1").category == cfg.MATCHED
    assert later.summary["total_outstanding_amount"] == D("0")

    edge = run(t, s, cutoff_date=date(2026, 12, 2))  # settled ON the cutoff counts as settled
    assert cat_of(edge, "T1").category == cfg.MATCHED

    assert rc.month_bounds("2026-11") == (date(2026, 11, 1), date(2026, 11, 30))
    assert rc.month_bounds("2028-02")[1] == date(2028, 2, 29)
    with pytest.raises(ValueError):
        rc.month_bounds("2026-13")
    with pytest.raises(ValueError):
        run(t, s, cutoff_date=date(2026, 10, 31))


def test_tc15_empty_dataset_handling():
    r = run([], [])
    assert r.results.empty
    assert list(r.results.columns) == rc.RESULT_COLUMNS
    assert r.summary["total_transactions"] == 0
    assert r.summary["total_platform_amount"] == 0 and r.summary["total_bank_amount"] == 0
    assert r.summary["net_reconciliation_difference"] == 0
    assert rc.report_to_csv(r.results).startswith("transaction_id,")


# --------------------------------------------------------------------------
# Extra engine behaviour
# --------------------------------------------------------------------------
def test_bank_only_settlement_is_flagged():
    r = run([], [st("S1", "GHOST", "2026-11-05", "250.00")])
    row = cat_of(r, "GHOST", source="BANK")
    assert row.category == cfg.INVALID_RECORD and "no matching platform" in row.explanation
    assert r.summary["net_reconciliation_difference"] == D("-250.00")


def test_unsupported_type_and_currency_rejected():
    r = run([tx("T1", "2026-11-05", "10.00", ttype="CHARGEBACK"),
             tx("T2", "2026-11-05", "10.00", currency="USD")], [])
    assert (r.results.category == cfg.INVALID_RECORD).sum() == 2


def test_refund_without_original_reference_is_invalid():
    r = run([tx("R1", "2026-11-05", "10.00", "REFUND", "")], [])
    assert cat_of(r, "R1").category == cfg.INVALID_RECORD


def test_transactions_outside_reporting_month_are_ignored():
    r = run([tx("T1", "2026-10-31", "100.00"), tx("T2", "2026-11-02", "50.00")],
            [st("S1", "T1", "2026-11-02", "100.00"), st("S2", "T2", "2026-11-03", "50.00")])
    assert r.summary["out_of_scope_transactions"] == 1
    assert r.summary["out_of_scope_settlements"] == 1
    assert r.summary["total_platform_amount"] == D("50.00")
    assert r.summary["unexplained_difference"] == 0


def test_report_csv_keeps_exact_amounts():
    r = run([tx("T1", "2026-11-10", "100.005")], [st("S1", "T1", "2026-11-11", "100.01")])
    csv_text = rc.report_to_csv(r.results)
    assert "100.005" in csv_text and "-0.005" in csv_text


# --------------------------------------------------------------------------
# Sample dataset: all four mandatory anomalies must be found independently
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def sample():
    tx_rows, st_rows, manifest = data_generator.generate_datasets()
    t, s = frames(tx_rows, st_rows)
    return rc.reconcile(t, s), manifest


def test_sample_size_and_currency():
    tx_rows, st_rows, _ = data_generator.generate_datasets()
    assert len(tx_rows) >= 30 and len(st_rows) >= 30
    assert {r["currency"] for r in tx_rows + st_rows} == {"INR"}


def test_sample_anomaly_1_timing(sample):
    result, manifest = sample
    for item in manifest["timing_difference"]:
        row = cat_of(result, item["transaction_id"])
        assert row.category == cfg.TIMING_DIFFERENCE
        assert row.transaction_date.startswith("2026-11") and row.settlement_date.startswith("2026-12")
    assert result.summary["timing_difference_count"] == len(manifest["timing_difference"])


def test_sample_anomaly_2_rounding(sample):
    result, manifest = sample
    assert len(manifest["rounding_difference"]) >= 3
    for item in manifest["rounding_difference"]:
        row = cat_of(result, item["transaction_id"])
        assert row.category == cfg.ROUNDING_DIFFERENCE
        assert abs(row.difference) <= cfg.ROUNDING_TOLERANCE
    assert result.summary["rounding_aggregate_visible"] is True
    assert result.summary["aggregate_rounding_difference"] == D("-0.020")


def test_sample_anomaly_3_duplicate(sample):
    result, manifest = sample
    m = manifest["duplicate_settlement"]
    dup = cat_of(result, m["transaction_id"], source="BANK")
    assert dup.category == cfg.DUPLICATE_SETTLEMENT and dup.settlement_id == m["duplicate_settlement_id"]
    assert m["original_settlement_id"] in dup.explanation
    assert cat_of(result, m["transaction_id"]).category == cfg.MATCHED
    assert result.summary["duplicate_amount_excluded"] == abs(dup.bank_amount)


def test_sample_anomaly_4_orphan_and_valid_refund(sample):
    result, manifest = sample
    assert cat_of(result, manifest["orphan_refund"]["transaction_id"]).category == cfg.ORPHAN_REFUND
    assert cat_of(result, manifest["valid_refund"]["transaction_id"]).category == cfg.MATCHED


def test_sample_supporting_anomalies(sample):
    result, manifest = sample
    assert cat_of(result, manifest["amount_mismatch"]["transaction_id"]).category == cfg.AMOUNT_MISMATCH
    assert cat_of(result, manifest["missing_settlement"]["transaction_id"]).category == cfg.MISSING_SETTLEMENT


def test_sample_totals_reconcile_exactly(sample):
    result, _ = sample
    s = result.summary
    assert s["unexplained_difference"] == 0  # every rupee of the gap is attributed to a row
    assert s["net_reconciliation_difference"] == s["total_platform_amount"] - s["total_bank_amount"]
    assert s["invalid_record_count"] == 0


# --------------------------------------------------------------------------
# Generator reproducibility and committed sample files
# --------------------------------------------------------------------------
def test_generator_is_deterministic():
    assert data_generator.generate_datasets() == data_generator.generate_datasets()
    assert data_generator.generate_datasets(1) != data_generator.generate_datasets(2)


def test_committed_csvs_match_generator(tmp_path):
    data_generator.write_datasets(tmp_path)
    for name in ("transactions.csv", "settlements.csv"):
        assert (cfg.DATA_DIR / name).read_bytes() == (tmp_path / name).read_bytes()
