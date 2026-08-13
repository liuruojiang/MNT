# A-Share / US Momentum Combo Strategy

This workspace contains the A-share / US momentum combo strategy family, including the V7.x `mnt_bot` production signal path.

## Current Stage

V7.9 is the current production bot; V7.8 remains a supported production baseline.
Both scripts contain four sleeves only: Sub-A 15%, Sub-A-DK 15%, Sub-B 40%, and
Sub-C 30%.

The shared production invariants are:

- Sub-B uses `T close signal -> T+1 adjusted open execution -> T+1 close return`.
- The final Sub-B account rebuild nets target changes once, charges transaction
  costs once, and charges BIL plus 100 bps financing on gross exposure above 1.0.
- Formal US history is checked against XNYS sessions. Yahoo gaps are retried and
  may be repaired only with same-ticker Nasdaq history after a scale check; a
  remaining required gap fails closed and is never hidden by forward-fill.
- Proxy/live pairs use the live ETF after listing, including BTC-USD/IBIT. A
  missing required live ETF price is not replaced by a proxy price.
- Sub-C scales only the equity and gold sleeves, executes scale changes at the
  next adjusted open, and uses a 0.35 scale-change deadband. BTC, bonds, and CTA
  remain unscaled.

V7.9 combines the Sub-B official and EMA legs at 50/50. Its VolReg scales
`QQQ/EMXC` only, while `DBC/PDBC` remains under its price-only profit guard. UUP
is an optional observation series in V7.9, not a required trading input.

## Main Files

- `mnt_bot V 7.9 plus.py`: current production bot and strategy implementation.
- `mnt_bot V 7.8 plus.py`: supported V7.8 production baseline.
- `poe_adk_16_spread_v1_0_bot.py`: Poe-native online ADK 16-leg bot.
- `run_v78_substrategy_poe_overlay_test.py`: V7.8 overlay comparison runner.
- `docs/V7.8_PRODUCTION_SPEC.md`: production assumptions, execution policy, external-gate freshness policy, and manual run checklist.
- `docs/V7.8_AUDIT_RESOLUTION.md`: P0/P1/P2 audit resolution record and required revalidation commands.
- `docs/subc_v78_v79_sleeve_vol_promotion_20260812.md`: Sub-C 0.35 deadband decision, formal window, and real-data evidence.
- `tests/test_v78_v79_adversarial_repairs.py`: consolidated cross-version execution, calendar, live-price, retry, financing, and fail-closed regressions.
- `tests/test_v78_v79_subc_sleeve_vol.py`: cross-version Sub-C production parity and accounting tests.
- `tests/test_poe_adk_16_spread_decay.py`: retained ADK online-rebuild and query-surface regression suite.

Research-only reproducibility utilities:

- `backtest_v78_v79_proxy_compare.py`: matched V7.8/V7.9 formal-window and long-proxy comparison runner; proxy output is not a formal conclusion.
- `research_suba_fallback_symmetry_v79.py`: symmetric Sub-A fallback-rule comparison without changing production defaults.
- `research_v79_inflation_compass_50_50.py`: reconciled 50/50 V7.9 core plus frozen Inflation Compass study.
- `research_v79_inflation_compass_weight_scan.py`: 0%-30% Inflation Compass allocation scan built on the reconciled runner.

## Verification

Run these commands after touching production behavior:

```powershell
python -m py_compile "mnt_bot V 7.8 plus.py" "mnt_bot V 7.9 plus.py" "poe_adk_16_spread_v1_0_bot.py"
python -m pytest tests/test_v78_v79_adversarial_repairs.py tests/test_v78_v79_subc_sleeve_vol.py -q
python -m pytest tests/test_poe_adk_16_spread_decay.py -q
python -m pytest tests -q
git diff --check
```

For the Sub-C promotion evidence, `python verify_subc_v78_v79_production.py`
performs a real Yahoo-data parity run. It is network-dependent and is separate
from the deterministic regression suite.

## Manual Execution Notes

V7.8 is a signal and manual-execution workflow. It does not submit broker orders.

- Sub-A and ADK intentionally use near-close live signal -> same-day close manual execution.
- Sub-B uses T close signal -> T+1 adjusted open execution -> T+1 close return.
- Sub-C scale changes preserve the old scale overnight and use the new scale from T+1 open to close.
- Before using the four-sleeve portfolio, refresh every sleeve and record its usable start and end dates.

See `docs/V7.8_PRODUCTION_SPEC.md` for the full manual run checklist.

## Dependency Note

This repository currently does not include a pinned `requirements.txt`, `pyproject.toml`, or lockfile. The verified commands above were run in the local project environment. If this workspace is moved to another machine, create a dependency snapshot before relying on formal runs.
