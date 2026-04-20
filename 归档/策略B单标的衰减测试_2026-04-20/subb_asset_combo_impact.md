# Sub-B overlay combo impact

- Base script: `mnt_bot V 6.8 plus.py`
- Data files: `mnt_strategy_data_cn.csv` / `mnt_strategy_data_us.csv`
- Sample: `2015-04-03 -> 2026-04-17`
- Replacement rule: only swap `Sub-B` into `asset overlay 25% / 65% / 0.5`; keep `Sub-A / ADK / Sub-C` on official `V6.8` logic.
- Combo logic: rebuilt with the same daily NAV path as the official NAV chart.

- `baseline_combo_v68`: annual `21.0873%` / max_dd `-12.1874%` / total_return `726.6592%` / sharpe `1.3658` / calmar `1.7303` / annual_delta `+0.0000%` / max_dd_delta `+0.0000%`
- `combo_v68_plus_subb_asset_overlay_25_65_0p5`: annual `24.6334%` / max_dd `-10.2235%` / total_return `1036.8717%` / sharpe `1.6475` / calmar `2.4095` / annual_delta `+3.5461%` / max_dd_delta `+1.9639%`

## Windows

- `baseline_combo_v68 1Y`: `2025-04-17 -> 2026-04-17` / annual `28.0514%` / max_dd `-12.8970%` / total_return `28.0297%` / annual_delta `+0.0000%` / max_dd_delta `+0.0000%`
- `combo_v68_plus_subb_asset_overlay_25_65_0p5 1Y`: `2025-04-17 -> 2026-04-17` / annual `49.7402%` / max_dd `-9.1383%` / total_return `49.6988%` / annual_delta `+21.6888%` / max_dd_delta `+3.7587%`
- `baseline_combo_v68 3Y`: `2023-04-17 -> 2026-04-17` / annual `20.0717%` / max_dd `-12.3478%` / total_return `73.1318%` / annual_delta `+0.0000%` / max_dd_delta `+0.0000%`
- `combo_v68_plus_subb_asset_overlay_25_65_0p5 3Y`: `2023-04-17 -> 2026-04-17` / annual `32.3714%` / max_dd `-9.9065%` / total_return `131.9884%` / annual_delta `+12.2997%` / max_dd_delta `+2.4413%`
- `baseline_combo_v68 5Y`: `2021-04-17 -> 2026-04-17` / annual `20.4387%` / max_dd `-11.5208%` / total_return `153.3814%` / annual_delta `+0.0000%` / max_dd_delta `+0.0000%`
- `combo_v68_plus_subb_asset_overlay_25_65_0p5 5Y`: `2021-04-17 -> 2026-04-17` / annual `25.5504%` / max_dd `-9.8486%` / total_return `211.9053%` / annual_delta `+5.1117%` / max_dd_delta `+1.6721%`
