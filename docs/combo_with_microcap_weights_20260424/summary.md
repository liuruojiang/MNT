## 组合权重测试记录

日期：2026-04-24

### 口径

- 主仓库策略逻辑：`mnt_bot V 7.1 plus.py`
- 微盘主线逻辑：`微盘股对冲策略/microcap_top100_mom16_biweekly_live.py`
- 数据：
  - `mnt_strategy_data_cn.csv`
  - `mnt_strategy_data_us.csv`
  - `微盘股对冲策略/outputs/wind_microcap_top_100_biweekly_thursday_16y_cached.csv`
  - `微盘股对冲策略/outputs/microcap_top100_mom16_biweekly_live_proxy_turnover.csv`
- 组合共同样本：`2019-05-09 ~ 2026-03`
- 说明：
  - 月度组合收益用于和仓库现有 performance 口径保持一致。
  - 组合最大回撤、日度 Sharpe、日度年化以 `daily_*` 字段为准。
  - 早先用月度组合收益算出的组合回撤偏小，不再使用。

### 测试方案

1. 当前组合：`15 / 25 / 40 / 20`
   - `Sub-A / Sub-A-DK / Sub-B / Sub-C`
2. 提案：`10 / 15 / 15 / 40 / 20`
   - `Sub-A / Sub-A-DK / Microcap / Sub-B / Sub-C`
3. 邻近：`10 / 10 / 20 / 40 / 20`
   - `Sub-A / Sub-A-DK / Microcap / Sub-B / Sub-C`

### 日度口径核心结果

| 方案 | 近3年日度年化 | 近3年日度Sharpe | 近3年日度MaxDD | 全共同样本日度年化 | 全共同样本日度Sharpe | 全共同样本日度MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| 当前 `15/25/40/20` | 30.67% | 1.83 | -10.05% | 26.26% | 1.75 | -10.05% |
| 提案 `10/15/15/40/20` | 30.20% | 2.34 | -6.55% | 25.72% | 2.09 | -6.55% |
| 邻近 `10/10/20/40/20` | 30.00% | 2.46 | -5.64% | 25.31% | 2.14 | -6.06% |

### 结论

- `10/15/15` 是有效改善：
  - 年化仅小幅回落
  - 日度 Sharpe 明显提升
  - 最大回撤从约 `-10.1%` 降到约 `-6.6%`
- `10/10/20` 更偏稳健：
  - 回撤更浅
  - Sharpe 更高
  - 但收益再让一步
- 如果以第一版过渡权重为目标，`10/15/15` 可作为主候选。

### 文件

- `combo_with_microcap_weights_summary.csv`
- `combo_with_microcap_weights_sleeves.csv`
- `combo_with_microcap_weights_meta.json`
- `analyze_combo_with_microcap_weights.py`
