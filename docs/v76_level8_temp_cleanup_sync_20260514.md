# V7.6 Level-8 Temporary Test Cleanup Sync - 2026-05-14

## Scope

This cleanup ran on `main` before syncing the current V7.6 Level-8 portfolio-advisory work to GitHub.

## Removed Temporary Artifacts

Backed up and removed these local-only test artifacts:

- `quant_param_scan_runs/20260514_v76_level8_*`
- `quant_param_scan_runs/20260514_v77_research_*`
- `quant_param_scan_runs/20260514_v7_7_candidate_*`
- `run_v76_suba_microcap_subd_dynamic_budget_validation.py`
- `run_v76_suba_microcap_subd_rule_grid_since2020.py`
- `tests/test_v76_subd_advisory_integration.py`
- `.pytest_cache/`
- root and test `__pycache__/` directories

## Preserved

- Production V7.6 strategy and Level-8 builder changes.
- `outputs/portfolio_v76_current/` current advisory outputs.
- Existing tracked `docs/`, historical archives, data files, and `.codex_backups/`.
- Remaining tracked regression tests under `tests/`.

## Backup

Deleted non-cache artifacts were backed up under:

`C:\Users\Administrator.DESKTOP-95I7VVU\Desktop\动量策略\A股美股动量组合策略\.codex_backups\20260514_235332`

The first backup attempt created a partial backup at `.codex_backups/20260514_235253` before failing on nested `__pycache__`; the successful backup above is the usable rollback point for the removed artifacts.

One later-discovered `20260514_v7_7_candidate_*` scan directory was backed up separately under `.codex_backups/20260514_235608` before removal.

## Verification

Run after cleanup:

```powershell
python -m unittest discover -s tests -v
python -m py_compile 'mnt_bot V 7.6 plus.py' build_v76_portfolio_nav.py build_v76_level8_decision_dashboard.py build_v76_level8_risk_governance.py tests\test_v76_review_round2_regressions.py tests\test_v76_advisory_action_summary.py tests\test_v76_source_returns_freshness.py
```

Result:

- `unittest`: 18 tests OK.
- `py_compile`: OK.
- Regenerated `__pycache__/` directories were removed after verification.
