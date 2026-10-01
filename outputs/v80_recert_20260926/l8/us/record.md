# L8 B/C 交接记录

结论：最终五袖**冻结纸面组合**的 B7.8/B7.9/C 参数组与逐腿映射通过，**历史可执行融资准确性未认证**。正式 B 借款计息出现负值；C 连续证券数量账仍未闭合。未修改正式源码、参数或生产状态。

- 最终源码 `06b69d328b41416f7aaf350371a17b5839deb0339e06ad57af09fb77ecbed3b4`，冻结输入 `182a5c54d5c81699d8e93038695a76febd15312aa48b5864e47a46318eeba00f`；共同组合 2020-12-03 至 2026-09-25，A/ADK 的 9 月 25 日收益按正式口径填零。
- 130 条组合路径 = 全开 1 + B7.8/B7.9 各 28 + C 68 + 两两交互 5；五窗 650 行，10Y 为历史不足 N/A。正式 Full 年化/回撤 `23.3297%/−7.7768%`。L2 与独立 NAV 基线零差，B/C 最终源码代表路径重跑对 L6 在浮点误差内。
- B 正式负融资成本 B7.8 **790** 日、B7.9 **700** 日。零下限诊断使两版 Full 年化分别减少 **0.1092/0.0898 个百分点**，五袖减少 **0.0163 个百分点**；只改变融资公式，信号和执行事件不变。券商真实融资利率未核准，诊断不作为正式修复。
- 完整说明：`summary.md`；逐日与五窗：`daily_combo_paths.csv.gz`、`window_metrics.csv`；各臂事件/费用/资源：`case_summary.csv`；融资诊断：`funding_floor_status.json`、`funding_floor_window_metrics.csv`、`funding_floor_daily.csv.gz`；清单与哈希：`status.json`。
- 复现：`python -X utf8 outputs/v80_recert_20260926/l8/us/audit_us_combo.py`，随后 `python -X utf8 outputs/v80_recert_20260926/l8/us/audit_financing_floor.py`，最后 `python -X utf8 outputs/v80_recert_20260926/l8/us/finalize_us.py`。
