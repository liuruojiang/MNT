# V7.7 Sub-B Recent-Weighted Momentum Sync - 2026-05-16

## 结论

V7.7 的 Sub-B 正式采用近端权重更大的 160/260/390 动量窗口混合：

- 官方宏观门控腿：`160/260/390 = 60%/30%/10%`
- EMA 同池候选腿：继续使用 EWMA 动量，本身是近端权重更大的时间衰减口径
- Sub-B 最终仍按官方腿和 EMA 腿的既有比例混合

这次同步覆盖策略逻辑、用户查询展示、必要单元测试、研究复现脚本和本说明文档。三组本地 `quant_param_scan_runs` 大结果目录只作为本次结论的本地证据，不上传云端。

## 正式代码同步

- `mnt_bot V 7.7 plus.py`
  - 新增 `US_ROT_WINDOW_WEIGHTS = {160: 0.60, 260: 0.30, 390: 0.10}`
  - 新增 `US_ROT_WINDOW_WEIGHT_LABEL = "160/260/390=60%/30%/10%"`
  - 官方腿三个窗口的目标仓位从等权平均改为按 `US_ROT_WINDOW_WEIGHTS` 加权平均
  - 用户查询展示同步为 V7.7 和 `60%/30%/10%` 加权口径
  - `信号`、`实时信号`、`参数`、`实时参数`、bot introduction 和仓位解析提示均显示加权口径
  - 表格中原先容易误导的“均值/平均动量”口径改为“加权动量”

## 全部测试文件

### 单元测试

- `tests/test_v77_subb_window_weights.py`
  - 验证正式参数为 `60%/30%/10%`
  - 验证 `_us_mix_target_weights()` 实际按窗口权重合成目标仓位
  - 验证用户查询文案不再残留 V7.6 Sub-B / 等权平均字样，并包含 V7.7、`US_ROT_WINDOW_WEIGHT_LABEL` 和加权动量展示

### 研究测试脚本

- `analyze_subb_momentum_signal_weighting_no_filters.py`
  - 去掉官方过滤条件的原始动量窗口测试
  - 当时仍保留逆波动率配权和目标波动率缩放，用于第一轮隔离比较
- `analyze_subb_momentum_weighting_full_conditions.py`
  - 加回官方条件后的测试
  - 恢复绝对动量、通胀宏观门控、EMA 腿、官方/EMA 混合、VolReg、switch buffer、最小调仓门槛和成本
- `analyze_subb_pure_momentum_weighting_no_filters_no_vol_sizing.py`
  - 纯原始动量测试
  - 进一步去掉逆波动率配权和目标波动率缩放，回应“原始动量也应该去掉这两组”的校正

### 已清理的本地研究结果目录

- `quant_param_scan_runs/20260516_a_v7_7_sub_b_momentum_window_signal_weighting_no_filters/`
- `quant_param_scan_runs/20260516_a_v7_7_sub_b_momentum_window_weighting_full_conditions/`
- `quant_param_scan_runs/20260516_a_v7_7_sub_b_pure_momentum_weighting_no_filters_no_vol_sizing/`

这些结果目录曾用于生成下方摘要表。为避免把大体积研究产物推到云端，并按清理要求移除无用测试产物，本次只同步可复现脚本和本文件中的核心结果摘要。需要重建时，运行对应 `analyze_subb_*` 脚本并指定新的 `--out-dir`。

## 测试结果摘要

### 原始动量隔离测试

结果目录：`quant_param_scan_runs/20260516_a_v7_7_sub_b_momentum_window_signal_weighting_no_filters/`

主口径 `window_target` 中，`60/30/10` 相比等权：

| 区间 | 等权年化 | 60/30/10 年化 | 等权最大回撤 | 60/30/10 最大回撤 |
|:-|--:|--:|--:|--:|
| Full | 21.88% | 22.93% | -17.84% | -17.26% |
| 10Y | 32.85% | 36.02% | -17.84% | -17.26% |
| 5Y | 31.64% | 33.53% | -17.62% | -17.26% |
| 3Y | 44.05% | 44.93% | -13.68% | -14.06% |
| 1Y | 60.56% | 64.91% | -9.72% | -8.94% |

该轮结论：近端权重在隔离测试中有效，`60/30/10` 是最强候选之一。

### 加回完整条件测试

结果目录：`quant_param_scan_runs/20260516_a_v7_7_sub_b_momentum_window_weighting_full_conditions/`

加回正式过滤和 overlay 后，`60/30/10` 相比等权：

| 区间 | 等权年化 | 60/30/10 年化 | 等权最大回撤 | 60/30/10 最大回撤 |
|:-|--:|--:|--:|--:|
| Full | 20.56% | 20.64% | -14.65% | -13.03% |
| 10Y | 31.96% | 32.79% | -14.65% | -12.31% |
| 5Y | 29.52% | 30.20% | -12.27% | -12.31% |
| 3Y | 41.59% | 42.58% | -11.31% | -10.97% |
| 1Y | 59.48% | 60.93% | -11.08% | -10.47% |

该轮结论：完整条件下收益提升变小，但近端权重仍改善 10Y/3Y/1Y 最大回撤，且近期窗口收益更高；Full-sample Sharpe 没有相对等权提升。

### 纯动量无配权/无缩放测试

结果目录：`quant_param_scan_runs/20260516_a_v7_7_sub_b_pure_momentum_weighting_no_filters_no_vol_sizing/`

去掉逆波动率配权和目标波动率缩放后，`60/30/10` 相比等权：

| 区间 | 等权年化 | 60/30/10 年化 | 等权最大回撤 | 60/30/10 最大回撤 |
|:-|--:|--:|--:|--:|
| Full | 25.01% | 26.42% | -26.60% | -24.60% |
| 10Y | 41.25% | 44.00% | -26.60% | -24.60% |
| 5Y | 25.97% | 29.61% | -20.80% | -19.41% |
| 3Y | 41.03% | 44.24% | -14.20% | -14.19% |
| 1Y | 37.40% | 46.45% | -11.03% | -10.80% |

该轮结论：即使去掉逆波动率配权和目标波动率缩放，`60/30/10` 在 `window_target` 结构中仍改善收益和最大回撤；但绝对回撤明显更深，所以不能把纯动量结果直接当作正式策略风险水平。

## 验证命令

```powershell
python tests\test_v77_subb_window_weights.py -v
python -m py_compile "mnt_bot V 7.7 plus.py" analyze_subb_momentum_weighting_full_conditions.py analyze_subb_pure_momentum_weighting_no_filters_no_vol_sizing.py
python -m unittest discover -s tests -v
```

验证结果：

- `tests/test_v77_subb_window_weights.py`: 3 tests passed
- 全量 `tests`: 21 tests passed
- `py_compile`: passed

运行中只出现 `fastapi_poe` 的 Pydantic v2 deprecation warning，和本次策略逻辑无关。

## 数据和成本假设

- 数据入口：`mnt_bot V 7.7 plus.py` 中的 `fetch_yahoo()` 生产路径，带 Yahoo/Stooq fallback
- 测试区间：合并数据覆盖 `2007-05-30` 到 `2026-05-15`
- 信号时点：T 日收盘信号
- 执行时点：有 open 数据时按 T+1 adjusted open 近似
- 成本：沿用 repo `US_ROT_COMMISSION`
- 额外滑点/开盘冲击：未额外加入，只使用 repo 当前成本模型

## 同步范围说明

本次云端同步包含：

- `mnt_bot V 7.7 plus.py`
- `tests/test_v77_subb_window_weights.py`
- 三个 `analyze_subb_*` 研究测试脚本
- `docs/subb_v77_recent_weighted_momentum_sync_20260516.md`

本次云端同步不包含：

- `.cn_official_cache/*`
- `mnt_strategy_data_cn.csv`
- 头像生成脚本和图片
- 三个 `quant_param_scan_runs/20260516_a_v7_7_sub_b_*` 大结果目录（已清理）
- 其他 20260514/20260515 的 Sub-A/Sub-D/ADK 历史扫描目录
- 其他未关联 V7.7 Sub-B 窗口加权的本地工作区文件
