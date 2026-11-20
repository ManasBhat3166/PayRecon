# Architecture

PayRecon is deliberately small: one engine module, one UI module, one generator, one config.

```
 CSV upload / sample files
          |
          v
   load_csv()  (text only: dtype=str, no NaN coercion)
          |
          v
 _check_schema()  -- missing columns --> SchemaError (shown as an error in the UI)
          |
          v
 _validate_rows()  per row: missing values, type, currency, ISO date, Decimal amount
   |-- invalid rows ---------------------------------------------> INVALID_RECORD
   v
 _drop_duplicate_references()  (platform IDs must be unique)
          |
          v
 Bank side: sort by date, keep earliest per (id, type) --> originals / duplicates
          |
          v
 Platform side: for each in-scope transaction
     orphan refund?  -> ORPHAN_REFUND
     no settlement?  -> MISSING_SETTLEMENT
     settled > cutoff-> TIMING_DIFFERENCE
     diff == 0       -> MATCHED
     |diff| <= tol   -> ROUNDING_DIFFERENCE
     else            -> AMOUNT_MISMATCH
 + duplicates -> DUPLICATE_SETTLEMENT     + bank-only -> INVALID_RECORD
          |
          v
 _build_summary()  Decimal totals, counts, aggregate rounding, bridge check
          |
          v
 ReconciliationResult(results DataFrame, summary dict)
          |
          +--> app.py: cards, charts, filters, drill-down
          +--> report_to_csv(): downloadable CSV report (exact amounts)
```

## Modules
| File | Responsibility |
|---|---|
| `config.py` | Constants: tolerance, schemas, categories, paths, seed |
| `reconciliation.py` | All validation, matching, classification, totals, export. No UI code |
| `data_generator.py` | Reproducible sample data + anomaly manifest |
| `app.py` | Streamlit UI; calls `reconcile()` and renders the result |
| `tests/` | Pytest suite exercising the engine and generator, not the UI |

## Design decisions
- **Business logic is independent of Streamlit**, so it is testable and reusable.
- **Decimal everywhere** for money; amounts stay exact in the results table and in the CSV export.
- **Every row gets a category and a plain-English explanation**, built from the actual values.
- **Bridge check:** `net_reconciliation_difference == sum of row differences` (duplicates excluded). `unexplained_difference` must be 0; the dashboard and tests verify it.
- **One bad row never stops a run.** Only a broken schema aborts, with a clear message.
- No hardcoded expected figures: all totals are computed from the input at run time.
