# A-Share / US Momentum Combo Strategy

This workspace contains the A-share / US momentum combo strategy family, including the V7.x `mnt_bot` production signal path.

## Current Stage

V7.9 is the current production bot. It preserves the formal V7.8 execution and
freshness rules, while combining the Sub-B official and EMA legs at 50/50.
The Sub-B overlay scope is:

- VolReg scales `QQQ/EMXC` only and moves the released weight to `BIL`.
- `DBC/PDBC` is excluded from VolReg and is managed by its own price-only profit guard.

The V7.8 audit P0/P1/P2 remediation baseline remains fixed in commit `dc2bec38`:

- Sub-B formal execution uses `T close signal -> T+1 adjusted open execution -> T+1 close return`.
- Sub-B formal runs fail if a required T+1 adjusted open price is missing instead of falling back to same-day close.
- Sub-B VolReg uses the same open-execution rule for cash entry and cash exit transitions.
- Sub-B external gates and ADK allowed tables must cover the full target index before forward-fill.
- V7.8 display text and production docs now match the formal execution rule.

## Main Files

- `mnt_bot V 7.9 plus.py`: current production bot and strategy implementation.
- `mnt_bot V 7.8 plus.py`: preserved V7.8 production baseline.
- `run_v78_substrategy_poe_overlay_test.py`: V7.8 overlay comparison runner.
- `docs/V7.8_PRODUCTION_SPEC.md`: production assumptions, execution policy, external-gate freshness policy, and manual run checklist.
- `docs/V7.8_AUDIT_RESOLUTION.md`: P0/P1/P2 audit resolution record and required revalidation commands.
- `tests/test_v78_overlay_freshness_and_volreg.py`: regression tests for stale gates, VolReg open execution, strict Sub-B open execution, and display/documentation guardrails.

Research-only reproducibility utilities:

- `backtest_v78_v79_proxy_compare.py`: matched V7.8/V7.9 formal-window and long-proxy comparison runner; proxy output is not a formal conclusion.
- `research_suba_fallback_symmetry_v79.py`: symmetric Sub-A fallback-rule comparison without changing production defaults.
- `research_v79_inflation_compass_50_50.py`: reconciled 50/50 V7.9 core plus frozen Inflation Compass study.
- `research_v79_inflation_compass_weight_scan.py`: 0%-30% Inflation Compass allocation scan built on the reconciled runner.

## Verification

Run these commands after touching V7.9 production behavior:

```powershell
python -m py_compile "mnt_bot V 7.9 plus.py"
git diff --check
```

Run these additional commands after touching the V7.8 production baseline:

```powershell
python -m py_compile "mnt_bot V 7.8 plus.py" "run_v78_substrategy_poe_overlay_test.py"
python -m pytest tests/test_v78_overlay_freshness_and_volreg.py -q
python -m pytest tests/test_v78_overlay_freshness_and_volreg.py tests/test_v78_adk_subb_blend_display.py tests/test_v78_cn_live_freshness.py tests/test_v78_suba_new_signal_display.py -q
python -m pytest tests -q
git diff --check
```

## Manual Execution Notes

V7.8 is a signal and manual-execution workflow. It does not submit broker orders.

- Sub-A and ADK intentionally use near-close live signal -> same-day close manual execution.
- Sub-B uses T close signal -> T+1 adjusted open execution -> T+1 close return.
- Before using four-sleeve or five-sleeve portfolio decisions, refresh and review Microcap/Sub-D through their independent official paths.

See `docs/V7.8_PRODUCTION_SPEC.md` for the full manual run checklist.

## Dependency Note

This repository currently does not include a pinned `requirements.txt`, `pyproject.toml`, or lockfile. The verified commands above were run in the local project environment. If this workspace is moved to another machine, create a dependency snapshot before relying on formal runs.
