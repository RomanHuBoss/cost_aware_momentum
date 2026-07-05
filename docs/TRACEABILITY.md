# Traceability

## Work package: execution-entry alignment

| Acceptance criterion | Production implementation | Tests |
|---|---|---|
| LONG entry adverse above next-hour open | `app/ml/training.py::make_barrier_dataset` | `test_training_labels_use_direction_specific_executable_entry_stress` |
| SHORT entry adverse below next-hour open | `app/ml/training.py::make_barrier_dataset` | same test |
| Invalid spread fails closed | `app/config.py`, `make_barrier_dataset` | `test_training_entry_spread_must_be_finite_and_nonnegative`, config test |
| Trainer and CLI pass configured spread | `app/workers/trainer.py`, `scripts/train.py` | Full suite/compile/static checks |
| Backtest uses artifact spread | `scripts/backtest.py` | Runtime/backtest contract covered by existing suite plus artifact tests |
| Artifact stores and validates execution metadata | `app/ml/lifecycle.py`, `app/ml/runtime.py` | runtime incompatible-semantics tests |
| Promotion gate rejects missing/mismatched metadata | `evaluate_quality_gate` | `test_quality_gate_rejects_missing_or_mismatched_entry_execution_model` |
| Incumbent comparison requires compatible entry geometry | `build_model_candidate` | incumbent geometry regression test |

## Schema changes

- Label path: `decision-open-directional-spread-entry-ohlc-path-v3`.
- Policy metrics: `decision-open-directional-spread-entry-exit-time-cohort-v13`.
- Entry execution: `directional-half-spread-on-next-hour-open-v1`.
