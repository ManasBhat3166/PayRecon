# Testing

Run from the project root: `python -m pytest -v`

## Test cases

| ID | Test function(s) | Scenario | Expected outcome |
|---|---|---|---|
| TC01 | `test_tc01_normal_payment_matching` | Payment settled next day, same amount | MATCHED, difference 0 |
| TC02 | `test_tc02_next_month_settlement_is_timing_not_missing` | Recorded 30 Nov, settled 2 Dec | TIMING_DIFFERENCE, outstanding amount reported, not MISSING |
| TC03 | `test_tc03_duplicate_settlement_detection` | Two bank rows for one payment | Later row DUPLICATE_SETTLEMENT, names the original; original MATCHED |
| TC04 | `test_tc04_orphan_refund_detection` | Refund pointing to unknown payment | ORPHAN_REFUND, not matched |
| TC05 | `test_tc05_valid_refund_matching` | Refund of an existing payment | MATCHED; shown as negative; totals net |
| TC06 | `test_tc06_aggregate_rounding_discrepancy`, `..._tc06b_...` | 4 payments with x.xx5 amounts, bank rounds HALF_UP | Each diff -0.005 (<= tolerance) yet aggregate -0.020 > 0.01 and flagged visible; 06b: a single 0.004 gap is not flagged |
| TC07 | `test_tc07_missing_settlement_detection` | No bank record | MISSING_SETTLEMENT |
| TC08 | `test_tc08_amount_mismatch_detection` | 500.00 vs 450.00 | AMOUNT_MISMATCH, difference 50.00 |
| TC09 | `test_tc09_invalid_csv_schema`, `..._tc09b_...` | Missing column, empty frame, empty file | SchemaError |
| TC10 | `test_tc10_invalid_date_handling` (5 inputs) | `2026-13-45`, `11/05/2026`, text, `2026-02-30`, blank | INVALID_RECORD; other rows still reconciled |
| TC11 | `test_tc11_invalid_amount_handling` (7 inputs) | `abc`, `-5.00`, `0`, blank, `NaN`, `Infinity`, `1,000.00` | INVALID_RECORD; excluded from totals |
| TC12 | `test_tc12_duplicate_transaction_reference_handling` | Same transaction_id twice in platform file | First kept, second INVALID_RECORD |
| TC13 | `test_tc13_duplicate_settlement_excluded_from_totals` | Duplicate 1000.00 settlement | Bank total 1000.00 (not 2000.00); excluded amount 1000.00 |
| TC14 | `test_tc14_month_end_cutoff_calculation` | Cutoff 30 Nov / 2 Dec / 31 Dec; leap-year month end; bad month | Timing vs matched flips correctly; ValueError for invalid input |
| TC15 | `test_tc15_empty_dataset_handling` | Header-only files | Empty result, all-zero summary, no exception |

Additional tests: bank-only settlement, unsupported type/currency, refund without original ID,
out-of-scope month, exact amounts in CSV export, sample-dataset checks for each planted
anomaly (found via the manifest), bridge balance, generator determinism, and committed CSVs
matching a fresh generator run.

## Actual execution result

Environment: Linux, Python 3.12.3, pytest 9.2.0, pandas 3.0.6, Streamlit 1.67.0.
Result: **41 passed, 0 failed, 0 skipped** (0.54 s). Not run on native Windows.

<details><summary>Full <code>python -m pytest -v</code> output</summary>

```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.2.0, pluggy-1.7.0 -- /usr/bin/python
cachedir: .pytest_cache
rootdir: /home/claude/PayRecon
plugins: platformdirs-4.13.0, anyio-4.16.0
collecting ... collected 41 items

tests/test_reconciliation.py::test_tc01_normal_payment_matching PASSED   [  2%]
tests/test_reconciliation.py::test_tc02_next_month_settlement_is_timing_not_missing PASSED [  4%]
tests/test_reconciliation.py::test_tc03_duplicate_settlement_detection PASSED [  7%]
tests/test_reconciliation.py::test_tc04_orphan_refund_detection PASSED   [  9%]
tests/test_reconciliation.py::test_tc05_valid_refund_matching PASSED     [ 12%]
tests/test_reconciliation.py::test_tc06_aggregate_rounding_discrepancy PASSED [ 14%]
tests/test_reconciliation.py::test_tc06b_rounding_below_aggregate_threshold_is_not_visible PASSED [ 17%]
tests/test_reconciliation.py::test_tc07_missing_settlement_detection PASSED [ 19%]
tests/test_reconciliation.py::test_tc08_amount_mismatch_detection PASSED [ 21%]
tests/test_reconciliation.py::test_tc09_invalid_csv_schema PASSED        [ 24%]
tests/test_reconciliation.py::test_tc09b_empty_or_garbage_csv_file PASSED [ 26%]
tests/test_reconciliation.py::test_tc10_invalid_date_handling[2026-13-45] PASSED [ 29%]
tests/test_reconciliation.py::test_tc10_invalid_date_handling[11/05/2026] PASSED [ 31%]
tests/test_reconciliation.py::test_tc10_invalid_date_handling[not-a-date] PASSED [ 34%]
tests/test_reconciliation.py::test_tc10_invalid_date_handling[2026-02-30] PASSED [ 36%]
tests/test_reconciliation.py::test_tc10_invalid_date_handling[] PASSED   [ 39%]
tests/test_reconciliation.py::test_tc11_invalid_amount_handling[abc] PASSED [ 41%]
tests/test_reconciliation.py::test_tc11_invalid_amount_handling[-5.00] PASSED [ 43%]
tests/test_reconciliation.py::test_tc11_invalid_amount_handling[0] PASSED [ 46%]
tests/test_reconciliation.py::test_tc11_invalid_amount_handling[] PASSED [ 48%]
tests/test_reconciliation.py::test_tc11_invalid_amount_handling[NaN] PASSED [ 51%]
tests/test_reconciliation.py::test_tc11_invalid_amount_handling[Infinity] PASSED [ 53%]
tests/test_reconciliation.py::test_tc11_invalid_amount_handling[1,000.00] PASSED [ 56%]
tests/test_reconciliation.py::test_tc12_duplicate_transaction_reference_handling PASSED [ 58%]
tests/test_reconciliation.py::test_tc13_duplicate_settlement_excluded_from_totals PASSED [ 60%]
tests/test_reconciliation.py::test_tc14_month_end_cutoff_calculation PASSED [ 63%]
tests/test_reconciliation.py::test_tc15_empty_dataset_handling PASSED    [ 65%]
tests/test_reconciliation.py::test_bank_only_settlement_is_flagged PASSED [ 68%]
tests/test_reconciliation.py::test_unsupported_type_and_currency_rejected PASSED [ 70%]
tests/test_reconciliation.py::test_refund_without_original_reference_is_invalid PASSED [ 73%]
tests/test_reconciliation.py::test_transactions_outside_reporting_month_are_ignored PASSED [ 75%]
tests/test_reconciliation.py::test_report_csv_keeps_exact_amounts PASSED [ 78%]
tests/test_reconciliation.py::test_sample_size_and_currency PASSED       [ 80%]
tests/test_reconciliation.py::test_sample_anomaly_1_timing PASSED        [ 82%]
tests/test_reconciliation.py::test_sample_anomaly_2_rounding PASSED      [ 85%]
tests/test_reconciliation.py::test_sample_anomaly_3_duplicate PASSED     [ 87%]
tests/test_reconciliation.py::test_sample_anomaly_4_orphan_and_valid_refund PASSED [ 90%]
tests/test_reconciliation.py::test_sample_supporting_anomalies PASSED    [ 92%]
tests/test_reconciliation.py::test_sample_totals_reconcile_exactly PASSED [ 95%]
tests/test_reconciliation.py::test_generator_is_deterministic PASSED     [ 97%]
tests/test_reconciliation.py::test_committed_csvs_match_generator PASSED [100%]

============================== 41 passed in 0.54s ==============================
```
</details>

## UI / launch verification
- `streamlit.testing.v1.AppTest` ran `app.py` with the sample data: no exceptions, 6 tabs, the
  8 summary metrics rendered (40 / 40 / 35 / 5 / 1 / 2 / 1 / INR 25,228.02), the rounding warning
  and bridge-balanced message appeared. Changing the cutoff to 2026-12-31 and re-running gave
  0 timing differences.
- `python -m streamlit run app.py --server.headless true` started; `/_stcore/health` returned `ok`
  and `/` returned HTTP 200.
- **Not verified:** visual appearance in a real browser, CSV file upload via the widget, and
  the download buttons (no browser was available).
