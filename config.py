"""Central configuration for PayRecon.

All tunable business rules live here so that reconciliation.py never contains
magic numbers or hardcoded expected results.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

# --------------------------------------------------------------------------
# Paths (pathlib keeps everything Windows-safe)
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"
TRANSACTIONS_FILE = DATA_DIR / "transactions.csv"
SETTLEMENTS_FILE = DATA_DIR / "settlements.csv"
MANIFEST_FILE = DATA_DIR / "anomaly_manifest.json"

# --------------------------------------------------------------------------
# Application
# --------------------------------------------------------------------------
APP_NAME = "PayRecon"
DEFAULT_REPORTING_MONTH = "2026-11"  # YYYY-MM
RANDOM_SEED = 20261130  # makes the sample data reproducible

# --------------------------------------------------------------------------
# Business rules
# --------------------------------------------------------------------------
DEFAULT_CURRENCY = "INR"
SUPPORTED_CURRENCIES = frozenset({"INR"})

PAYMENT = "PAYMENT"
REFUND = "REFUND"
SUPPORTED_TRANSACTION_TYPES = frozenset({PAYMENT, REFUND})

# Per-record tolerance: one paise. A difference whose absolute value is at or
# below this is "within tolerance" and is reported as ROUNDING_DIFFERENCE.
ROUNDING_TOLERANCE = Decimal("0.01")
# Money is presented / rounded to 2 decimal places with ROUND_HALF_UP.
MONEY_QUANTUM = Decimal("0.01")

DATE_FORMAT = "%Y-%m-%d"  # ISO dates only

# --------------------------------------------------------------------------
# CSV schemas
# --------------------------------------------------------------------------
TRANSACTION_COLUMNS = [
    "transaction_id",
    "transaction_date",
    "transaction_type",
    "original_transaction_id",
    "amount",
    "currency",
    "status",
]
SETTLEMENT_COLUMNS = [
    "settlement_id",
    "transaction_id",
    "settlement_date",
    "transaction_type",
    "original_transaction_id",
    "amount",
    "currency",
]

# --------------------------------------------------------------------------
# Discrepancy classifications
# --------------------------------------------------------------------------
MATCHED = "MATCHED"
TIMING_DIFFERENCE = "TIMING_DIFFERENCE"
AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
DUPLICATE_SETTLEMENT = "DUPLICATE_SETTLEMENT"
MISSING_SETTLEMENT = "MISSING_SETTLEMENT"
ORPHAN_REFUND = "ORPHAN_REFUND"
ROUNDING_DIFFERENCE = "ROUNDING_DIFFERENCE"
INVALID_RECORD = "INVALID_RECORD"

ALL_CATEGORIES = (
    MATCHED,
    TIMING_DIFFERENCE,
    AMOUNT_MISMATCH,
    DUPLICATE_SETTLEMENT,
    MISSING_SETTLEMENT,
    ORPHAN_REFUND,
    ROUNDING_DIFFERENCE,
    INVALID_RECORD,
)
