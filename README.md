# PayRecon - Payment Reconciliation and Discrepancy Detection System

PayRecon compares a payments platform's own transaction records with the bank's
settlement records for a reporting month (default: **November 2026**, currency **INR**)
and shows exactly where the two disagree, and why.

## Business problem

A payments company records a transaction the moment a customer pays. The bank settles
those transactions in batches, usually 1-2 business days later. At month-end the two
ledgers should agree, but they rarely do. PayRecon finds and explains four kinds of gap:

1. **Timing** - recorded in one month, settled in the next (outstanding, *not* missing).
2. **Aggregate rounding** - each record is within one paise, but the total is visibly off.
3. **Duplicate** - the bank settles the same transaction twice.
4. **Orphan refund** - a refund whose original payment does not exist.

The sample data also contains an amount mismatch and a missing settlement.

## Features
- Strict validation (columns, missing values, dates, amounts, types, currency, duplicate IDs)
- Matching on `transaction_id` + `transaction_type` (no AI or fuzzy logic - fully deterministic)
- Duplicate settlements detected and excluded from totals
- Configurable reporting month and cutoff date
- `Decimal` arithmetic with a documented `ROUND_HALF_UP` policy and a configurable one-paise tolerance
- Eight classifications: MATCHED, TIMING_DIFFERENCE, AMOUNT_MISMATCH, DUPLICATE_SETTLEMENT,
  MISSING_SETTLEMENT, ORPHAN_REFUND, ROUNDING_DIFFERENCE, INVALID_RECORD
- A "bridge" check: platform total - bank total is fully attributed to row-level differences
- Streamlit dashboard: summary cards, charts, filters, transaction drill-down, CSV download
- Reproducible sample data and 41 automated tests

## Technology stack
Python 3.10+, Streamlit, Pandas, `decimal.Decimal`, Pytest, CSV files.

## Folder structure
```
PayRecon/
  app.py                  Streamlit dashboard (UI only)
  reconciliation.py       All business logic (no Streamlit imports)
  data_generator.py       Deterministic sample-data generator
  config.py               Tolerance, currency, schemas, categories, paths
  requirements.txt
  README.md  ASSUMPTIONS.md  ARCHITECTURE.md  TESTING.md
  data/                   transactions.csv, settlements.csv, anomaly_manifest.json
  tests/                  test_reconciliation.py
  reports/                CSV reports saved from the app
  screenshots/            (see its README)
  submission/             Submission notes
```

## Installation on Windows (PowerShell)

Install Python 3.10 or newer from python.org (tick "Add python.exe to PATH"), then open
PowerShell **in the PayRecon folder**.

**1. Create a virtual environment**
```powershell
python -m venv .venv
```
**2. Activate it**
```powershell
.venv\Scripts\Activate.ps1
```
Your prompt should now start with `(.venv)`.

**3. Install dependencies**
```powershell
python -m pip install -r requirements.txt
```
**4. Generate the sample datasets** (optional - the files are already included, and the output is identical every time)
```powershell
python data_generator.py
```
**5. Run the tests**
```powershell
python -m pytest -v
```
**6. Launch the app**
```powershell
python -m streamlit run app.py
```
A browser tab opens at http://localhost:8501. The sample dataset is reconciled automatically.

## Example workflow
1. Launch the app; the sample dataset loads and reconciles immediately.
2. **Overview** tab: 40 transactions, 40 settlements, 35 matched, 5 unmatched, 1 duplicate,
   2 timing differences, 1 orphan refund. A banner points out that four rounding gaps
   (each 0.005) add up to -0.020, more than the 0.01 tolerance.
3. **Discrepancies** tab: filter by type, e.g. only `ORPHAN_REFUND`; read the explanation column.
4. **Transaction details**: pick `RFD-202611-0002` to see why it is an orphan and the raw CSV rows.
5. In the sidebar, set the cutoff to 2026-12-31 and click **Run reconciliation**: the two
   timing differences become MATCHED, because they have now settled.
6. **Download report** tab: export the full report or only the discrepancies.
7. To use your own data choose **Upload CSV files**, upload both files, and run.

## How the four anomalies are found
| Anomaly | Detection rule |
|---|---|
| Next-month settlement | Matching settlement exists, but its date is after the cutoff -> TIMING_DIFFERENCE, reported as outstanding |
| Aggregate rounding | Per-record `0 < abs(platform - bank) <= 0.01` -> ROUNDING_DIFFERENCE; the exact differences are then summed and flagged if `abs(sum) > 0.01` |
| Duplicate settlement | A second settlement for the same (transaction_id, type); the earliest is kept, later ones are DUPLICATE_SETTLEMENT and excluded from totals |
| Orphan refund | REFUND whose `original_transaction_id` is not a valid PAYMENT in the platform data -> ORPHAN_REFUND, never MATCHED |

**Rounding policy:** monetary values are `Decimal`. Display/rounding to paise uses
`ROUND_HALF_UP`. Per-record comparison uses the *exact* difference, so sub-paise gaps are
not hidden; the aggregate is the exact sum. Example: platform `899.995` vs bank `900.00`.

## CSV schemas
All dates are ISO `YYYY-MM-DD`; amounts are plain positive decimals (no commas); refunds are
stored as positive amounts with `transaction_type = REFUND`.

**transactions.csv** - `transaction_id, transaction_date, transaction_type, original_transaction_id, amount, currency, status`

**settlements.csv** - `settlement_id, transaction_id, settlement_date, transaction_type, original_transaction_id, amount, currency`

`transaction_type` is `PAYMENT` or `REFUND`; `currency` must be `INR`; `original_transaction_id`
is required for refunds and blank for payments.

## Troubleshooting
| Problem | Fix |
|---|---|
| `Activate.ps1 cannot be loaded because running scripts is disabled` | Run `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`, answer `Y`, activate again. Or only for this window: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`. Or use Command Prompt: `.venv\Scripts\activate.bat` |
| `python` is not recognized | Reinstall Python with "Add to PATH", or try `py -m venv .venv` |
| `No module named streamlit/pandas/pytest` | The venv is not active, or step 3 was skipped. Activate and re-run the install |
| Streamlit asks for an email on first launch | Press Enter to skip |
| Port 8501 busy | `python -m streamlit run app.py --server.port 8502` |
| "Input file problem: ... missing required column(s)" | Compare your header row with the schemas above |
| Rows appear under INVALID_RECORD | Open "Data quality" - each row says what is wrong (bad date, amount, type...) |
| `ModuleNotFoundError: config` when running tests | Run from the project root folder, using `python -m pytest` |

## Limitations
See ASSUMPTIONS.md. Notably: INR only; one reporting month at a time; refund amounts are not
checked against the original payment amount; tested on Linux/Python 3.12, not on a Windows machine.
