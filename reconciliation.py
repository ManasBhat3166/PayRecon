"""PayRecon reconciliation engine.

Pure business logic: no Streamlit imports, no AI, no randomness. All money is
handled with ``decimal.Decimal``. Matching is a deterministic comparison of
(transaction_id, transaction_type) between the platform and bank datasets.

Sign convention in the *results*: payments are positive, refunds are negative,
so that every column adds up to the platform / bank net totals.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd

import config as cfg

ZERO = Decimal("0")
RECONCILED = (cfg.MATCHED, cfg.ROUNDING_DIFFERENCE)
RESULT_COLUMNS = [
    "transaction_id",
    "transaction_type",
    "transaction_date",
    "settlement_date",
    "platform_amount",
    "bank_amount",
    "difference",
    "category",
    "explanation",
    "settlement_id",
    "original_transaction_id",
    "source",
]
AMOUNT_COLUMNS = ["platform_amount", "bank_amount", "difference"]
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class SchemaError(ValueError):
    """Raised when an input file is missing required columns or is unreadable."""


# ==========================================================================
# Money / parsing helpers
# ==========================================================================
def quantize_money(value: Decimal) -> Decimal:
    """Round to 2 decimal places using the documented ROUND_HALF_UP policy."""
    return value.quantize(cfg.MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def format_amount(value: Any) -> str:
    """Format for display/export. Sub-paise precision is preserved, never hidden."""
    if value is None or (not isinstance(value, Decimal) and pd.isna(value)):
        return ""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    q = quantize_money(d)
    if d == q:
        return f"{q:.2f}"
    return format(d.normalize(), "f")


def _clean(value: Any) -> str:
    if value is None or value is pd.NA:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def parse_date(value: Any) -> date:
    """Parse a strict ISO (YYYY-MM-DD) date. Raises ValueError otherwise."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _clean(value)
    if not _ISO_DATE.fullmatch(text):
        raise ValueError(f"'{text}' is not an ISO date (YYYY-MM-DD)")
    try:
        return datetime.strptime(text, cfg.DATE_FORMAT).date()
    except ValueError:
        raise ValueError(f"'{text}' is not a real calendar date") from None


def parse_amount(value: Any) -> Decimal:
    """Parse a positive, finite monetary amount. Raises ValueError otherwise."""
    text = _clean(value)
    if text == "":
        raise ValueError("amount is empty")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"'{text}' is not a number") from None
    if not amount.is_finite():
        raise ValueError(f"'{text}' is not a finite number")
    if amount <= 0:
        raise ValueError(f"'{text}' must be greater than zero")
    return amount


def month_bounds(month: str) -> tuple[date, date]:
    """Return (first_day, last_day) for a 'YYYY-MM' string."""
    try:
        year_s, month_s = str(month).split("-")
        year, mon = int(year_s), int(month_s)
        first = date(year, mon, 1)
        last = date(year, mon, calendar.monthrange(year, mon)[1])
    except (ValueError, TypeError):
        raise ValueError(f"Invalid reporting month '{month}'; expected YYYY-MM") from None
    return first, last


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, date) else (value or "")


# ==========================================================================
# Loading & validation
# ==========================================================================
def load_csv(source: Union[str, Path, Any]) -> pd.DataFrame:
    """Read a CSV as text (no type guessing, no NaN coercion)."""
    try:
        df = pd.read_csv(source, dtype=str, keep_default_na=False, skipinitialspace=True)
    except pd.errors.EmptyDataError:
        raise SchemaError("The CSV file is empty (no header row).") from None
    except (pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise SchemaError(f"The CSV file could not be parsed: {exc}") from None
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _check_schema(df: pd.DataFrame, required: list[str], name: str) -> None:
    if not isinstance(df, pd.DataFrame):
        raise SchemaError(f"{name} must be a pandas DataFrame.")
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise SchemaError(f"{name} is missing required column(s): {', '.join(missing)}")


@dataclass(frozen=True)
class Record:
    """A validated platform transaction or bank settlement."""

    row_number: int  # CSV line number (header = line 1)
    transaction_id: str
    transaction_type: str
    amount: Decimal
    currency: str
    original_transaction_id: str
    record_date: date  # transaction_date (platform) or settlement_date (bank)
    settlement_id: str = ""
    status: str = ""


def _validate_rows(df: pd.DataFrame, source: str) -> tuple[list[Record], list[dict]]:
    """Validate every row. Returns (valid records, invalid-row descriptors)."""
    is_platform = source == "PLATFORM"
    date_col = "transaction_date" if is_platform else "settlement_date"
    required = ["transaction_id", date_col, "transaction_type", "amount", "currency"]
    required.append("status" if is_platform else "settlement_id")

    valid: list[Record] = []
    invalid: list[dict] = []
    for pos, (_, row) in enumerate(df.iterrows()):
        raw = {c: _clean(row[c]) for c in df.columns}
        errors: list[str] = []

        for col in required:  # missing values
            if raw[col] == "":
                errors.append(f"missing value in '{col}'")

        ttype = raw["transaction_type"].upper()
        if ttype and ttype not in cfg.SUPPORTED_TRANSACTION_TYPES:
            errors.append(f"unsupported transaction type '{raw['transaction_type']}'")
        if ttype == cfg.REFUND and raw["original_transaction_id"] == "":
            errors.append("refund is missing 'original_transaction_id'")

        currency = raw["currency"].upper()
        if currency and currency not in cfg.SUPPORTED_CURRENCIES:
            errors.append(f"unsupported currency '{raw['currency']}'")

        parsed_date: Optional[date] = None
        if raw[date_col]:
            try:
                parsed_date = parse_date(raw[date_col])
            except ValueError as exc:
                errors.append(f"invalid date in '{date_col}': {exc}")

        amount: Optional[Decimal] = None
        if raw["amount"]:
            try:
                amount = parse_amount(raw["amount"])
            except ValueError as exc:
                errors.append(f"invalid amount: {exc}")

        row_number = pos + 2
        if errors:
            invalid.append(
                {
                    "source": source,
                    "row_number": row_number,
                    "transaction_id": raw["transaction_id"],
                    "transaction_type": raw["transaction_type"],
                    "transaction_date": raw.get("transaction_date", ""),
                    "settlement_date": raw.get("settlement_date", ""),
                    "settlement_id": raw.get("settlement_id", ""),
                    "original_transaction_id": raw["original_transaction_id"],
                    "reasons": "; ".join(errors),
                }
            )
            continue

        valid.append(
            Record(
                row_number=row_number,
                transaction_id=raw["transaction_id"],
                transaction_type=ttype,
                amount=amount,  # type: ignore[arg-type]
                currency=currency,
                original_transaction_id=raw["original_transaction_id"],
                record_date=parsed_date,  # type: ignore[arg-type]
                settlement_id=raw.get("settlement_id", ""),
                status=raw.get("status", ""),
            )
        )
    return valid, invalid


def _drop_duplicate_references(records: list[Record]) -> tuple[list[Record], list[dict]]:
    """Platform transaction_ids must be unique; later repeats are rejected."""
    seen: dict[str, int] = {}
    unique: list[Record] = []
    rejected: list[dict] = []
    for rec in records:
        if rec.transaction_id in seen:
            rejected.append(
                {
                    "source": "PLATFORM",
                    "row_number": rec.row_number,
                    "transaction_id": rec.transaction_id,
                    "transaction_type": rec.transaction_type,
                    "transaction_date": rec.record_date,
                    "settlement_date": "",
                    "settlement_id": "",
                    "original_transaction_id": rec.original_transaction_id,
                    "reasons": (
                        f"duplicate transaction reference '{rec.transaction_id}' "
                        f"(first seen at row {seen[rec.transaction_id]})"
                    ),
                }
            )
        else:
            seen[rec.transaction_id] = rec.row_number
            unique.append(rec)
    return unique, rejected


# ==========================================================================
# Result container
# ==========================================================================
@dataclass
class ReconciliationResult:
    results: pd.DataFrame
    summary: dict[str, Any]
    reporting_month: str
    month_start: date
    month_end: date
    cutoff_date: date
    tolerance: Decimal

    @property
    def matched(self) -> pd.DataFrame:
        """Records reconciled exactly or within the per-record tolerance."""
        return self.results[self.results["category"].isin(RECONCILED)]

    @property
    def discrepancies(self) -> pd.DataFrame:
        """Everything that is not an exact match."""
        return self.results[self.results["category"] != cfg.MATCHED]


def _row(**kw: Any) -> dict:
    """Build one result row; dates become ISO strings, missing values None."""
    row = {col: kw.get(col) for col in RESULT_COLUMNS}
    for col in ("transaction_date", "settlement_date"):
        row[col] = _iso(row[col])
    for col in ("settlement_id", "original_transaction_id"):
        row[col] = row[col] or ""
    return row


def _sign(txn_type: str) -> Decimal:
    return Decimal(-1) if txn_type == cfg.REFUND else Decimal(1)


# ==========================================================================
# Main entry point
# ==========================================================================
def reconcile(
    transactions: pd.DataFrame,
    settlements: pd.DataFrame,
    reporting_month: Optional[str] = None,
    cutoff_date: Optional[date] = None,
    tolerance: Optional[Decimal] = None,
) -> ReconciliationResult:
    """Reconcile platform transactions against bank settlements.

    * Platform transactions dated inside ``reporting_month`` are in scope.
    * A settlement dated after ``cutoff_date`` (default: month end) is not yet
      received at cutoff, so the transaction is a TIMING_DIFFERENCE (outstanding).
    * ``tolerance`` is the per-record rounding tolerance (default: one paise).
    """
    reporting_month = reporting_month or cfg.DEFAULT_REPORTING_MONTH
    tol = cfg.ROUNDING_TOLERANCE if tolerance is None else Decimal(str(tolerance))
    month_start, month_end = month_bounds(reporting_month)
    cutoff = cutoff_date or month_end
    if isinstance(cutoff, datetime):
        cutoff = cutoff.date()
    if cutoff < month_start:
        raise ValueError("Cutoff date cannot be before the start of the reporting month.")

    _check_schema(transactions, cfg.TRANSACTION_COLUMNS, "Transactions file")
    _check_schema(settlements, cfg.SETTLEMENT_COLUMNS, "Settlements file")

    valid_tx, invalid_tx = _validate_rows(transactions, "PLATFORM")
    valid_st, invalid_st = _validate_rows(settlements, "BANK")
    valid_tx, duplicate_refs = _drop_duplicate_references(valid_tx)
    invalid_tx += duplicate_refs

    # --- bank side: keep the earliest settlement per key, flag the rest -----
    originals: dict[tuple[str, str], Record] = {}
    duplicates: list[tuple[Record, Record]] = []
    for rec in sorted(valid_st, key=lambda r: (r.record_date, r.row_number)):
        key = (rec.transaction_id, rec.transaction_type)
        if key in originals:
            duplicates.append((rec, originals[key]))
        else:
            originals[key] = rec

    platform_keys = {(r.transaction_id, r.transaction_type) for r in valid_tx}
    tx_by_key = {(r.transaction_id, r.transaction_type): r for r in valid_tx}
    payment_ids = {r.transaction_id for r in valid_tx if r.transaction_type == cfg.PAYMENT}

    rows: list[dict] = []
    in_scope_keys: set[tuple[str, str]] = set()
    total_platform = total_bank = refund_amount = orphan_refund_amount = ZERO
    out_of_scope_tx = out_of_scope_st = 0

    # --- platform side -------------------------------------------------------
    for tx in valid_tx:
        if not (month_start <= tx.record_date <= month_end):
            out_of_scope_tx += 1
            continue
        key = (tx.transaction_id, tx.transaction_type)
        in_scope_keys.add(key)
        sign = _sign(tx.transaction_type)
        plat = sign * tx.amount
        total_platform += plat
        if tx.transaction_type == cfg.REFUND:
            refund_amount += tx.amount

        st = originals.get(key)
        settled_by_cutoff = st is not None and st.record_date <= cutoff
        bank = sign * st.amount if (st is not None and settled_by_cutoff) else None
        if bank is not None:
            total_bank += bank
        diff = plat - (bank or ZERO)

        if tx.transaction_type == cfg.REFUND and tx.original_transaction_id not in payment_ids:
            category = cfg.ORPHAN_REFUND
            orphan_refund_amount += tx.amount
            if st is None:
                bank_note = "No bank settlement was found for it either."
            elif settled_by_cutoff:
                bank_note = f"The bank nevertheless settled it on {st.record_date}."
            else:
                bank_note = f"A bank settlement dated {st.record_date} falls after the cutoff."
            explanation = (
                f"Refund of {format_amount(tx.amount)} references original payment "
                f"'{tx.original_transaction_id}', which does not exist in the platform "
                f"transactions. It cannot be treated as a successful reconciliation. {bank_note}"
            )
        elif st is None:
            category = cfg.MISSING_SETTLEMENT
            explanation = (
                f"No bank settlement exists for this {tx.transaction_type.lower()} "
                f"recorded on {tx.record_date}; it is missing as of cutoff {cutoff}."
            )
        elif not settled_by_cutoff:
            category = cfg.TIMING_DIFFERENCE
            explanation = (
                f"Recorded on {tx.record_date} but the bank settled it on {st.record_date}, "
                f"after the cutoff {cutoff}. Outstanding at period end, not missing."
            )
        else:
            raw_diff = tx.amount - st.amount  # unsigned, exact
            if raw_diff == 0:
                category = cfg.MATCHED
                explanation = f"Platform and bank amounts agree (settled {st.record_date})."
                if tx.transaction_type == cfg.REFUND:
                    explanation += f" Refund validated against original payment '{tx.original_transaction_id}'."
            elif abs(raw_diff) <= tol:
                category = cfg.ROUNDING_DIFFERENCE
                explanation = (
                    f"Platform {format_amount(tx.amount)} vs bank {format_amount(st.amount)}: "
                    f"difference {format_amount(diff)} is within the {tol} per-record tolerance, "
                    f"so it is accepted here but counted in the aggregate rounding total."
                )
            else:
                category = cfg.AMOUNT_MISMATCH
                explanation = (
                    f"Platform recorded {format_amount(tx.amount)} but the bank settled "
                    f"{format_amount(st.amount)} (difference {format_amount(diff)}), "
                    f"beyond the {tol} tolerance."
                )

        rows.append(
            _row(
                transaction_id=tx.transaction_id,
                transaction_type=tx.transaction_type,
                transaction_date=tx.record_date,
                settlement_date=st.record_date if st else None,
                platform_amount=plat,
                bank_amount=bank,
                difference=diff,
                category=category,
                explanation=explanation,
                settlement_id=st.settlement_id if st else "",
                original_transaction_id=tx.original_transaction_id,
                source="PLATFORM",
            )
        )

    # --- duplicate settlements (excluded from every total) -------------------
    duplicate_amount = ZERO
    for dup, orig in duplicates:
        sign = _sign(dup.transaction_type)
        duplicate_amount += dup.amount
        tx = tx_by_key.get((dup.transaction_id, dup.transaction_type))
        rows.append(
            _row(
                transaction_id=dup.transaction_id,
                transaction_type=dup.transaction_type,
                transaction_date=tx.record_date if tx else None,
                settlement_date=dup.record_date,
                platform_amount=None,
                bank_amount=sign * dup.amount,
                difference=sign * dup.amount,
                category=cfg.DUPLICATE_SETTLEMENT,
                explanation=(
                    f"Bank settlement {dup.settlement_id} (row {dup.row_number}) repeats "
                    f"settlement {orig.settlement_id} dated {orig.record_date} for the same "
                    f"transaction. The original is kept; the duplicate amount "
                    f"{format_amount(dup.amount)} is excluded from settlement totals."
                ),
                settlement_id=dup.settlement_id,
                original_transaction_id=dup.original_transaction_id,
                source="BANK",
            )
        )

    # --- bank settlements with no platform transaction ------------------------
    for key, st in originals.items():
        if key in in_scope_keys:
            continue
        if key in platform_keys:  # platform txn exists but outside the period
            out_of_scope_st += 1
            continue
        if not (month_start <= st.record_date <= cutoff):
            out_of_scope_st += 1
            continue
        bank = _sign(st.transaction_type) * st.amount
        total_bank += bank
        rows.append(
            _row(
                transaction_id=st.transaction_id,
                transaction_type=st.transaction_type,
                transaction_date=None,
                settlement_date=st.record_date,
                platform_amount=None,
                bank_amount=bank,
                difference=-bank,
                category=cfg.INVALID_RECORD,
                explanation=(
                    f"Bank settlement {st.settlement_id} of {format_amount(st.amount)} has no "
                    f"matching platform transaction (transaction ID + type)."
                ),
                settlement_id=st.settlement_id,
                original_transaction_id=st.original_transaction_id,
                source="BANK",
            )
        )

    # --- rows rejected by validation ------------------------------------------
    for bad in invalid_tx + invalid_st:
        rows.append(
            _row(
                transaction_id=bad["transaction_id"] or "(missing)",
                transaction_type=bad["transaction_type"],
                transaction_date=bad["transaction_date"],
                settlement_date=bad["settlement_date"],
                platform_amount=None,
                bank_amount=None,
                difference=None,
                category=cfg.INVALID_RECORD,
                explanation=f"{bad['source'].title()} file row {bad['row_number']} rejected: {bad['reasons']}.",
                settlement_id=bad["settlement_id"],
                original_transaction_id=bad["original_transaction_id"],
                source=bad["source"],
            )
        )

    results = pd.DataFrame(rows, columns=RESULT_COLUMNS)
    summary = _build_summary(
        rows=rows,
        n_transactions=len(transactions),
        n_settlements=len(settlements),
        total_platform=total_platform,
        total_bank=total_bank,
        refund_amount=refund_amount,
        orphan_refund_amount=orphan_refund_amount,
        duplicate_amount=duplicate_amount,
        out_of_scope_tx=out_of_scope_tx,
        out_of_scope_st=out_of_scope_st,
        tol=tol,
        reporting_month=reporting_month,
        cutoff=cutoff,
    )
    return ReconciliationResult(results, summary, reporting_month, month_start, month_end, cutoff, tol)


def _build_summary(
    *,
    rows: list[dict],
    n_transactions: int,
    n_settlements: int,
    total_platform: Decimal,
    total_bank: Decimal,
    refund_amount: Decimal,
    orphan_refund_amount: Decimal,
    duplicate_amount: Decimal,
    out_of_scope_tx: int,
    out_of_scope_st: int,
    tol: Decimal,
    reporting_month: str,
    cutoff: date,
) -> dict[str, Any]:
    def total(field: str, cats: tuple[str, ...]) -> Decimal:
        return sum(
            (r[field] for r in rows if r["category"] in cats and r[field] is not None), ZERO
        )

    counts = {c: sum(1 for r in rows if r["category"] == c) for c in cfg.ALL_CATEGORIES}

    # Per-category sum of row differences. Duplicates never enter the net figure.
    diff_by_cat = {
        c: total("difference", (c,)) for c in cfg.ALL_CATEGORIES if c != cfg.DUPLICATE_SETTLEMENT
    }
    explained = sum(diff_by_cat.values(), ZERO)
    net = total_platform - total_bank
    rounding_agg = diff_by_cat[cfg.ROUNDING_DIFFERENCE]
    flagged = (
        cfg.TIMING_DIFFERENCE, cfg.AMOUNT_MISMATCH, cfg.MISSING_SETTLEMENT,
        cfg.ORPHAN_REFUND, cfg.ROUNDING_DIFFERENCE, cfg.INVALID_RECORD,
    )
    gross_flagged = sum(
        (abs(r["difference"]) for r in rows if r["category"] in flagged and r["difference"] is not None),
        ZERO,
    )

    return {
        "reporting_month": reporting_month,
        "cutoff_date": cutoff.isoformat(),
        "tolerance": tol,
        # counts
        "total_transactions": n_transactions,
        "total_settlements": n_settlements,
        "out_of_scope_transactions": out_of_scope_tx,
        "out_of_scope_settlements": out_of_scope_st,
        "matched_count": counts[cfg.MATCHED],
        "rounding_count": counts[cfg.ROUNDING_DIFFERENCE],
        "reconciled_count": counts[cfg.MATCHED] + counts[cfg.ROUNDING_DIFFERENCE],
        "unmatched_count": sum(
            1 for r in rows if r["source"] == "PLATFORM" and r["category"] not in RECONCILED
        ),
        "duplicate_count": counts[cfg.DUPLICATE_SETTLEMENT],
        "timing_difference_count": counts[cfg.TIMING_DIFFERENCE],
        "missing_settlement_count": counts[cfg.MISSING_SETTLEMENT],
        "amount_mismatch_count": counts[cfg.AMOUNT_MISMATCH],
        "orphan_refund_count": counts[cfg.ORPHAN_REFUND],
        "invalid_record_count": counts[cfg.INVALID_RECORD],
        "category_counts": counts,
        # money (all Decimal)
        "total_platform_amount": total_platform,
        "total_bank_amount": total_bank,
        "total_matched_amount": total("platform_amount", RECONCILED),
        "total_outstanding_amount": total("platform_amount", (cfg.TIMING_DIFFERENCE,)),
        "total_missing_amount": total("platform_amount", (cfg.MISSING_SETTLEMENT,)),
        "total_amount_mismatch": diff_by_cat[cfg.AMOUNT_MISMATCH],
        "duplicate_amount_excluded": duplicate_amount,
        "refund_amount": refund_amount,
        "orphan_refund_amount": orphan_refund_amount,
        "aggregate_rounding_difference": rounding_agg,
        "rounding_aggregate_visible": abs(rounding_agg) > tol,
        "net_reconciliation_difference": net,
        "unresolved_difference": net - diff_by_cat[cfg.TIMING_DIFFERENCE],
        "total_financial_discrepancy": gross_flagged,
        "difference_by_category": diff_by_cat,
        # integrity check: row-level differences must add up to the net figure
        "explained_difference": explained,
        "unexplained_difference": net - explained,
    }


# ==========================================================================
# Export helpers
# ==========================================================================
def to_display_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Copy with Decimal amount columns turned into exact strings."""
    out = df.copy()
    for col in AMOUNT_COLUMNS:
        if col in out.columns:
            out[col] = out[col].map(format_amount)
    return out


def report_to_csv(df: pd.DataFrame) -> str:
    """Serialise a results frame to CSV text (exact amounts, no float noise)."""
    return to_display_frame(df).to_csv(index=False, lineterminator="\n")


def save_report(df: pd.DataFrame, path: Union[str, Path]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_to_csv(df), encoding="utf-8", newline="")
    return path
