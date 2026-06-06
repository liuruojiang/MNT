# V7.7 ADK Param Scan Cleanup Sync - 2026-06-05

## Scope

This record preserves the reusable conclusions from the 2026-06-05 V7.7 Sub-A-DK research scans before scratch scan artifacts are removed.

All scans used `mnt_bot V 7.7 plus.py` with `mnt_strategy_data_cn.csv`, formal ADK window no earlier than the ZZ1000 publication constraint, V7.7 R2 quality filtering, Top1 pair selection, same-side overheat overlay, target-vol defaults unless explicitly disabled, and execution-cost rebuilds. No production strategy file was changed.

## Findings

- R2 quality threshold: the V7.7 default `CN_DK_R2_QUALITY_THRESHOLD = 0.05` remained the best full-sample Sharpe point among the scanned production-semantics thresholds. Stronger R2 thresholds reduced activity and generally hurt returns.
- Strict raw Top1 R2-fail-to-cash behavior did not clearly improve the strategy relative to current production semantics, where R2 filters pair ranking scores before Top1 selection.
- ADK DD Gate with target-vol enabled: the best balanced candidate was roughly `enter=10%`, `exit=8%`, `defense_scale=50%`, which cut full-sample max drawdown from about `-21.34%` to `-15.68%` with annual return around `16.56%`.
- ADK DD Gate with target-vol disabled: the naked ADK baseline had higher annual return but much larger drawdown; the balanced candidate shifted toward `enter=12%`, `exit=6%`, `defense_scale=25%`, with full-sample annual return around `17.78%` and max drawdown around `-14.48%`.
- Bias-momentum entry/exit hysteresis did not beat DD Gate as a drawdown-control mechanism. `entry=4`, `exit=2` improved full-sample return but did not reduce drawdown enough; drawdown-oriented entries hurt recent windows.
- Ratio absolute-momentum entry filter: directional 20-day confirmation alone was not worth promoting. The `>0%` threshold only slightly improved full-sample drawdown and reduced Sharpe.
- Ratio absolute-momentum window plus independent long/short thresholds: the best coarse-scan region concentrated around a 10-day ratio momentum window. The strongest full-sample candidate was approximately `window=10`, `long_threshold=0.5%`, `short_threshold=2%`; a more drawdown-oriented candidate was `window=10`, `long_threshold=2%`, `short_threshold=2%`. Recent 5Y/3Y/1Y drawdowns were not consistently better than the original, so this filter is research-only.

## Cleanup

The following scratch scan folders were removed after conclusions were recorded:

- `quant_param_scan_runs/20260605_a_us_momentum_combo_v7_7_sub_a_dk_bias_momentum_entry_exit`
- `quant_param_scan_runs/20260605_a_us_momentum_combo_v7_7_sub_a_dk_bias_momentum_plus_ratio_abs_momentum_entry`
- `quant_param_scan_runs/20260605_a_us_momentum_combo_v7_7_sub_a_dk_dd_risk_gate`
- `quant_param_scan_runs/20260605_a_us_momentum_combo_v7_7_sub_a_dk_no_target_vol_dd_risk_gate`
- `quant_param_scan_runs/20260605_a_us_momentum_combo_v7_7_sub_a_dk_r2_quality_threshold`
- `quant_param_scan_runs/20260605_a_us_momentum_combo_v7_7_sub_a_dk_ratio_abs_momentum_window_long_short_threshold`
- `quant_param_scan_runs/20260605_a_us_momentum_combo_v7_7_sub_a_dk_top1_r2_fail_cash`
- `quant_param_scan_runs/20260605_a_us_momentum_combo_v7_7_sub_a_dk_top1_r2_fail_cash_threshold`
