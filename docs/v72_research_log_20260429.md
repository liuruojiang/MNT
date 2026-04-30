# V7.2 研究留档 2026-04-29

## 目的

本文件记录 2026-04-29 围绕 V7.2 做过的几项组合级测试，供后续继续研究、复跑或调整权重时引用。

V7.2 当前口径仍然是组合资金分配口径，不是新生产脚本：

```text
Sub-A 10% + Sub-A-DK 15% + Microcap 15% + Sub-B 60% + Sub-C 0%
```

底层正式路径：

- `mnt_bot V 7.1 plus.py`: Sub-A / Sub-A-DK / Sub-B
- `PLUS 6/microcap_top100_mom16_biweekly_live.py`: Microcap，使用 `run_signal + apply_cost_model`

共同日度样本：`2015-10-13` 至 `2026-04-17`，共 `3840` 行。

## 1. 组合回撤 Overlay 测试

留档目录：

- `docs/v72_combo_drawdown_overlay_20260429/`

保留文件：

- `summary.md`
- `meta.json`
- `v72_overlay_summary.csv`
- `v72_overlay_windows.csv`

测试内容：

- 用组合净值回撤触发整体降仓。
- 触发信号使用前一日组合净值回撤，避免当天未来函数。
- overlay 额外成本按每 `100%` 仓位变化 `10bp` 计入。

核心结果：

| 方案 | 年化 | Sharpe | MaxDD |
|---|---:|---:|---:|
| baseline_v72 | 28.59% | 2.31 | -7.20% |
| dd4_scale80_cost10bp | 27.40% | 2.30 | -6.62% |
| dd4_scale60_cost10bp | 26.05% | 2.29 | -6.24% |
| dd4_scale50_cost10bp | 24.81% | 2.24 | -6.06% |

结论：

- 回撤 overlay 有温和控回撤效果，但年化损失大于回撤改善带来的收益。
- 不纳入 V7.2 默认规则。
- `dd4_scale80` 只保留为后续风险工具箱候选。

## 2. 四腿权重扫描

留档目录：

- `docs/v72_weight_scan_20260429/`

主要文件：

- `summary.md`
- `meta.json`
- `v72_weight_scan_picks.csv`
- `v72_weight_scan_windows.csv`
- `v72_weight_scan_recent_picks.csv`
- `v72_weight_scan_practical.csv`
- `v72_weight_scan_all.csv`

测试内容：

- 四腿非负权重合计 `100%`。
- 步长 `2.5%`。
- 实用约束：Sub-A >= `5%`，ADK >= `5%`，Microcap >= `5%`，Sub-B 在 `30%~70%`。
- 同时看全样本和近期加权窗口，近期加权窗口为 `1Y 15% / 3Y 35% / 5Y 35% / 10Y 15%`。

关键候选：

| 定位 | A / ADK / Microcap / B | 年化 | Sharpe | MaxDD | Calmar |
|---|---|---:|---:|---:|---:|
| 当前 V7.2 | 10.0 / 15.0 / 15.0 / 60.0 | 28.59% | 2.31 | -7.20% | 3.97 |
| 全样本 Sharpe 候选 | 12.5 / 20.0 / 32.5 / 35.0 | 31.48% | 2.70 | -6.76% | 4.66 |
| 回撤约束候选 | 22.5 / 10.0 / 25.0 / 42.5 | 29.66% | 2.59 | -5.99% | 4.95 |
| 近期 Sharpe 候选 | 27.5 / 12.5 / 20.0 / 40.0 | 29.02% | 2.54 | -5.86% | 4.96 |

结论：

- 当前 `10/15/15/60` 偏向 Sub-B，整体表现不差，但不是风险最均衡。
- 比起增加组合净值回撤 overlay，降低 Sub-B 权重并提高 Microcap / A / ADK 的风险预算更有研究价值。
- 偏进攻候选：`12.5 / 20 / 32.5 / 35`。
- 偏稳健候选：`22.5 / 10 / 25 / 42.5`。

## 3. 风险监控快照

留档目录：

- `docs/v72_risk_monitor_20260429/`

主要文件：

- `summary.md`
- `meta.json`
- `v72_risk_snapshot.csv`
- `v72_risk_window_metrics.csv`
- `v72_risk_contribution.csv`
- `v72_recent_correlation_252d.csv`
- `v72_drawdown_episodes.csv`

关键观测：

- 最新日期：`2026-04-17`
- 最新 NAV：`14.0551`
- 当前回撤：`-2.82%`
- 距离历史高点：`65` 个自然日
- 全样本指标：年化 `28.59%`，Sharpe `2.31`，MaxDD `-7.20%`
- 最近 `252` 日风险贡献最高的是 Sub-B，方差贡献约 `67.19%`
- 最近 `252` 日最高相关性组合是 `Sub-A / Sub-A-DK = 0.58`

结论：

- 这份报告适合作为 V7.2 风险仪表盘。
- 不建议把监控指标直接变成交易开关。
- 若后续 Microcap 改用 1.6 或其他新口径，必须重跑该报告。

## 4. 组合诊断补充测试

留档目录：

- `docs/v72_portfolio_diagnostics_20260429/`

脚本：

- `analyze_v72_portfolio_diagnostics.py`

主要文件：

- `summary.md`
- `meta.json`
- `v72_full_correlation.csv`
- `v72_recent_252d_correlation.csv`
- `v72_rolling_252d_correlation_summary.csv`
- `v72_variance_contribution.csv`
- `v72_drawdown_attribution.csv`
- `v72_weight_case_metrics.csv`

测试内容：

- 四腿全样本相关性矩阵。
- 最近 `252` 日相关性矩阵。
- 滚动 `252` 日相关性摘要。
- 最近 `60/252` 日和全样本方差贡献。
- 最大回撤片段的各腿峰谷贡献。
- 当前权重与三个候选权重的窗口绩效对比。

关键结果：

全样本相关性：

| 组合 | 相关性 |
|---|---:|
| Sub-A / Sub-A-DK | 0.36 |
| Sub-A / Sub-B | 0.03 |
| Sub-A / Microcap | -0.07 |
| Sub-A-DK / Sub-B | -0.02 |
| Sub-A-DK / Microcap | -0.06 |
| Sub-B / Microcap | -0.06 |

最近 `252` 日相关性：

| 组合 | 相关性 |
|---|---:|
| Sub-A / Sub-A-DK | 0.58 |
| Sub-A / Sub-B | 0.20 |
| Sub-A / Microcap | -0.08 |
| Sub-A-DK / Sub-B | -0.01 |
| Sub-A-DK / Microcap | -0.03 |
| Sub-B / Microcap | -0.20 |

最近 `252` 日风险贡献：

| 腿 | 当前有效权重 | 252日波动 | 对组合相关性 | 方差贡献 |
|---|---:|---:|---:|---:|
| Sub-B | 42.85% | 17.13% | 0.77 | 67.19% |
| Sub-A-DK | 20.14% | 16.90% | 0.48 | 17.78% |
| Microcap | 30.77% | 11.32% | 0.22 | 8.56% |
| Sub-A | 6.25% | 18.05% | 0.50 | 6.47% |

最差回撤归因：

- 最差回撤：`2015-12-25 -> 2016-01-15`
- 组合回撤：`-7.20%`

| 腿 | 峰谷收益 | 加权贡献 | 对线性亏损占比 |
|---|---:|---:|---:|
| Sub-B | -14.06% | -8.44% | 115.07% |
| Sub-A | -1.14% | -0.11% | 1.55% |
| Microcap | 3.08% | 0.46% | -6.30% |
| Sub-A-DK | 5.04% | 0.76% | -10.32% |

诊断结论：

- V7.2 的分散化是真实存在的，尤其是 Sub-B 与 Microcap、ADK 的相关性较低。
- 但 V7.2 的主要风险来源仍然集中在 Sub-B。
- 最差回撤几乎由 Sub-B 单腿贡献，ADK 和 Microcap 在该段反而对冲了部分亏损。
- 后续优化优先级应是权重层面的风险预算，而不是新增净值回撤开关。

## 5. 后续研究建议

优先级从高到低：

1. 复跑 Microcap 1.6 或其他新微盘口径下的同一套诊断，确认风险贡献和权重候选是否稳定。
2. 对 `12.5 / 20 / 32.5 / 35` 与 `22.5 / 10 / 25 / 42.5` 做更细窗口检验，尤其看最近 `1Y/3Y/5Y` 与压力段表现。
3. 若要正式调整 V7.2，优先考虑文档化权重口径变化，不新增生产脚本。
4. 只有当实盘或最新样本回撤显著扩大时，再重新评估 `dd4_scale80` 这类组合级风险工具。

## 复现命令

```powershell
python analyze_v72_portfolio_diagnostics.py
python -m py_compile analyze_v72_portfolio_diagnostics.py
```

已有留档来自同日运行结果；如底层数据、微盘口径或 V7.2 权重定义变化，以上数值必须重跑，不能沿用。
