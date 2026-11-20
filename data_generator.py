"""Deterministic sample-data generator for PayRecon (November 2026, INR).

Run:  python data_generator.py

The same seed always produces byte-identical CSV files. Four mandatory anomalies
(plus two supporting ones) are planted on purpose; an "anomaly manifest" records
exactly where, so tests can check the engine *found* them. The reconciliation
engine never reads the manifest.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import pandas as pd

import config as cfg

CENT = Decimal("0.01")


def add_business_days(start: date, days: int) -> date:
    """Bank settlement runs Monday-Friday only."""
    current = start
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days -= 1
    return current


def _fmt(amount: Decimal) -> str:
    """Keep sub-paise precision when present, otherwise 2 decimals."""
    q = amount.quantize(CENT, rounding=ROUND_HALF_UP)
    return f"{q:.2f}" if q == amount else str(amount)


def _scenario(tag, txn_date, platform_amount, bank_amount, settle_date, txn_type=cfg.PAYMENT, original=""):
    return {
        "tag": tag, "date": txn_date, "type": txn_type, "platform": platform_amount,
        "bank": bank_amount, "settle": settle_date, "original": original,
    }


def generate_datasets(seed: int = cfg.RANDOM_SEED) -> tuple[list[dict], list[dict], dict[str, Any]]:
    """Return (transaction rows, settlement rows, anomaly manifest)."""
    rng = random.Random(seed)
    nov = lambda day: date(2026, 11, day)  # noqa: E731

    # ---- 30 ordinary payments, settled 1-2 business days later --------------
    payments = []
    for _ in range(30):
        d = nov(rng.randint(1, 25))  # <=25 so settlement lands on/before 30 Nov
        amount = Decimal(rng.randint(19900, 2_500_000)) / 100
        payments.append(_scenario("normal", d, amount, amount, add_business_days(d, rng.choice([1, 2]))))

    # ---- planted anomalies ---------------------------------------------------
    # (1) Timing: recorded in November, settled in December.
    for day, amt in ((27, "6499.00"), (30, "15250.00")):
        a = Decimal(amt)
        payments.append(_scenario("timing", nov(day), a, a, add_business_days(nov(day), 2)))

    # (2) Rounding: platform keeps 3 decimals (e.g. tax-inclusive price); the bank
    #     settles whole paise using ROUND_HALF_UP. Each gap is 0.005 (inside the
    #     0.01 tolerance) but all four go the same way, so the total is 0.020.
    for day, raw in ((9, "1250.005"), (12, "899.995"), (16, "2340.505"), (20, "415.755")):
        a = Decimal(raw)
        payments.append(_scenario("rounding", nov(day), a, a.quantize(CENT, rounding=ROUND_HALF_UP),
                                  add_business_days(nov(day), 1)))

    # Supporting anomalies: amount mismatch (digits transposed) and missing settlement.
    payments.append(_scenario("mismatch", nov(13), Decimal("8750.00"), Decimal("8570.00"),
                              add_business_days(nov(13), 1)))
    payments.append(_scenario("missing", nov(18), Decimal("3299.00"), None, None))

    payments.sort(key=lambda s: (s["date"], str(s["platform"])))
    for i, s in enumerate(payments, 1):
        s["id"] = f"TXN-202611-{i:04d}"

    # ---- refunds ---------------------------------------------------------------
    parent = next(s for s in payments if s["tag"] == "normal" and s["date"] <= nov(14))
    refunds = [
        # Valid partial refund of an existing payment.
        _scenario("valid_refund", nov(20), Decimal("500.00"), Decimal("500.00"),
                  add_business_days(nov(20), 1), cfg.REFUND, parent["id"]),
        # (4) Orphan: the original payment does not exist anywhere.
        _scenario("orphan_refund", nov(23), Decimal("1499.00"), Decimal("1499.00"),
                  add_business_days(nov(23), 2), cfg.REFUND, "TXN-202610-0412"),
    ]
    refunds.sort(key=lambda s: s["date"])
    for i, s in enumerate(refunds, 1):
        s["id"] = f"RFD-202611-{i:04d}"

    scenarios = payments + refunds
    transactions = [
        {
            "transaction_id": s["id"], "transaction_date": s["date"].isoformat(),
            "transaction_type": s["type"], "original_transaction_id": s["original"],
            "amount": _fmt(s["platform"]), "currency": cfg.DEFAULT_CURRENCY, "status": "COMPLETED",
        }
        for s in scenarios
    ]

    # ---- bank settlements --------------------------------------------------------
    bank_rows = [
        {"tid": s["id"], "date": s["settle"], "type": s["type"], "original": s["original"],
         "amount": s["bank"], "dup": 0}
        for s in scenarios if s["settle"] is not None
    ]
    # (3) Duplicate: the bank pays out one ordinary payment twice, a business day apart.
    victim = [s for s in payments if s["tag"] == "normal"][9]
    bank_rows.append({"tid": victim["id"], "date": add_business_days(victim["settle"], 1),
                      "type": cfg.PAYMENT, "original": "", "amount": victim["bank"], "dup": 1})
    bank_rows.sort(key=lambda r: (r["date"], r["tid"], r["dup"]))

    settlements = []
    for i, r in enumerate(bank_rows, 1):
        r["sid"] = f"STL-202611-{i:04d}"
        settlements.append({
            "settlement_id": r["sid"], "transaction_id": r["tid"],
            "settlement_date": r["date"].isoformat(), "transaction_type": r["type"],
            "original_transaction_id": r["original"], "amount": _fmt(r["amount"]),
            "currency": cfg.DEFAULT_CURRENCY,
        })

    dup = next(r for r in bank_rows if r["dup"])
    first = next(r for r in bank_rows if r["tid"] == dup["tid"] and not r["dup"])
    by_tag = lambda tag: [s for s in scenarios if s["tag"] == tag]  # noqa: E731
    manifest = {
        "note": "Answer key for tests/documentation only. The engine never reads this file.",
        "reporting_month": cfg.DEFAULT_REPORTING_MONTH,
        "timing_difference": [
            {"transaction_id": s["id"], "transaction_date": s["date"].isoformat(),
             "settlement_date": s["settle"].isoformat()} for s in by_tag("timing")],
        "rounding_difference": [
            {"transaction_id": s["id"], "platform_amount": str(s["platform"]),
             "bank_amount": str(s["bank"])} for s in by_tag("rounding")],
        "duplicate_settlement": {
            "transaction_id": dup["tid"], "original_settlement_id": first["sid"],
            "duplicate_settlement_id": dup["sid"]},
        "orphan_refund": {
            "transaction_id": by_tag("orphan_refund")[0]["id"],
            "missing_original_transaction_id": by_tag("orphan_refund")[0]["original"]},
        "valid_refund": {
            "transaction_id": by_tag("valid_refund")[0]["id"],
            "original_transaction_id": by_tag("valid_refund")[0]["original"]},
        "amount_mismatch": {"transaction_id": by_tag("mismatch")[0]["id"]},
        "missing_settlement": {"transaction_id": by_tag("missing")[0]["id"]},
    }
    return transactions, settlements, manifest


def generate_dataframes(seed: int = cfg.RANDOM_SEED) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Same data as DataFrames of strings (used as a fallback by the app)."""
    tx, st, _ = generate_datasets(seed)
    return (pd.DataFrame(tx, columns=cfg.TRANSACTION_COLUMNS, dtype=str),
            pd.DataFrame(st, columns=cfg.SETTLEMENT_COLUMNS, dtype=str))


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_datasets(output_dir: Path = cfg.DATA_DIR, seed: int = cfg.RANDOM_SEED) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tx, st, manifest = generate_datasets(seed)
    _write_csv(output_dir / "transactions.csv", cfg.TRANSACTION_COLUMNS, tx)
    _write_csv(output_dir / "settlements.csv", cfg.SETTLEMENT_COLUMNS, st)
    (output_dir / "anomaly_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"transactions": len(tx), "settlements": len(st), "manifest": manifest}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate PayRecon sample datasets.")
    parser.add_argument("--output-dir", default=str(cfg.DATA_DIR))
    parser.add_argument("--seed", type=int, default=cfg.RANDOM_SEED)
    args = parser.parse_args()
    info = write_datasets(Path(args.output_dir), args.seed)
    print(f"Wrote {info['transactions']} transactions and {info['settlements']} settlements "
          f"to {args.output_dir} (seed={args.seed}).")
    print("Planted anomalies: timing, rounding, duplicate, orphan refund "
          "(+ amount mismatch, missing settlement). See anomaly_manifest.json.")


if __name__ == "__main__":
    main()
