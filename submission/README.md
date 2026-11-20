# Submission notes - Onelab AI Native Engineer Intern assessment (November 2026)

**Project:** PayRecon - Payment Reconciliation and Discrepancy Detection System

## Checklist
- [x] Source: `app.py`, `reconciliation.py`, `data_generator.py`, `config.py`
- [x] Sample data: `data/transactions.csv`, `data/settlements.csv` (+ `data/anomaly_manifest.json`, the answer key used by tests)
- [x] Tests: `tests/test_reconciliation.py` (run `python -m pytest -v`)
- [x] Docs: `README.md`, `ASSUMPTIONS.md`, `ARCHITECTURE.md`, `TESTING.md`
- [ ] Screenshots: not bundled (see `screenshots/README.md`)

## The four mandatory anomalies (sample data)
| # | Anomaly | Where | Detected as |
|---|---|---|---|
| 1 | Recorded Nov, settled Dec | TXN-202611-0037, TXN-202611-0038 | TIMING_DIFFERENCE |
| 2 | Rounding visible only in aggregate | TXN-202611-0012, -0020, -0022, -0028 | ROUNDING_DIFFERENCE (aggregate -0.020 > 0.01) |
| 3 | Duplicate bank settlement | STL-202611-0014 repeats STL-202611-0011 | DUPLICATE_SETTLEMENT |
| 4 | Refund with no original payment | RFD-202611-0002 -> TXN-202610-0412 | ORPHAN_REFUND |

Full explanation: see `README.md` and `TESTING.md`.
