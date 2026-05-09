# Sub-D 六 ETF 轮动策略 V1.1 升级文档

生成日期：2026-05-09
工作目录：`C:\Users\Administrator.DESKTOP-95I7VVU\Desktop\动量策略\新策略学习`

## 1. 升级结论

V1.1 是当前六 ETF 加权斜率轮动策略的正式候选升级版。升级后默认数据源从 Sina raw close 切换为 QVeris 连续价 `cps=3`，并在原有 Top1 轮动信号上加入两条规则：

1. 新 Top1 换入时先进入 50%，等待该资产首次收盘阴线后补齐剩余 50%。
2. MA60 乖离过热过滤：持仓资产 `price / MA60 - 1 >= 20%` 且乖离动量仍为正时清仓，回落到 `18%` 或同向条件消失后恢复。

QVeris 连续价口径下，V1.1 从 2020-01-02 到 2026-05-08 的结果：

| 版本 | 年化收益 | 最大回撤 | Sharpe | 年化波动 |
|---|---:|---:|---:|---:|
| V1.0 原版 | 54.60% | -21.36% | 1.706 | 27.78% |
| V1.1 QVeris 连续价 | 60.46% | -16.54% | 1.932 | 26.27% |

结论：V1.1 同时提高收益、降低回撤、提高 Sharpe，具备作为下一版主候选的条件。

## 2. V1.0 基准定义

V1.0 保持当前六 ETF 主基准：

| 项目 | 参数 |
|---|---|
| 资产池 | `159915.SZ`, `159941.SZ`, `513030.SH`, `513520.SH`, `159985.SZ`, `518880.SH` |
| 主信号 | 25 日加权 log 价格斜率 |
| score 年化 | `exp(slope * 252) - 1` |
| 合格条件 | `0 < score < 5`, `R2 >= 0.20` |
| 选择规则 | 选合格资产中 Top1 |
| Top1 切换 buffer | `1.00` |
| 目标波动 | 25% |
| 最大杠杆 | 1.5x |
| 单边成本 | 0.10% |
| 资产止损 | 关闭 |
| 回测执行 | 日频 close-confirmed / close-executed |
| warmup | 从 2010-01-01 开始 |
| 评估窗口 | 2020-01-02 到 2026-05-08 |

## 3. 数据源升级

### 3.1 问题

Sina raw close 和 CNFin raw kline 在 `159941.SZ` 上存在 2022-07-05 价格层级跳变：

| 日期 | Sina/CNFin raw close |
|---|---:|
| 2022-07-04 | 2.384 |
| 2022-07-05 | 0.604 |

如果直接用 raw close 计算收益，会得到约 `-74.66%` 的虚假单日跌幅。

### 3.2 交叉验证

QVeris `cps=0` 显示：

| 日期 | preClose | close | changeRatio |
|---|---:|---:|---:|
| 2022-07-05 | 0.596 | 0.604 | +1.3423% |

QVeris `cps=3` 连续价显示：

| 日期 | preClose | close | changeRatio |
|---|---:|---:|---:|
| 2022-07-05 | 2.384 | 2.416 | +1.3423% |

判断：2022-07-05 是拆分/除权类价格层级变化，不是经济意义上的 -74.66% 下跌。

### 3.3 正式数据口径

V1.1 后续研究默认使用：

- 数据源：QVeris
- endpoint：`cn_financial_pro.history_quotation.v1`
- indicators：`stock_common`
- interval：`D`
- cps：`3`
- fill：`Blank`

数据质量检查结果：QVeris `cps=3` 后，`159941.SZ` 最大单日绝对收益降到约 `10.01%`，当前六 ETF 池内没有 `>30%` 单日跳变。

## 4. V1.1 规则

### 4.1 新 Top1 先进 50%

当信号切换到一个新的 Top1 资产时：

1. 当日收盘切入新 Top1 的 50% 仓位。
2. 若后续仍持有该资产且尚未补齐，则等待该资产首次 `curr_close < prev_close`。
3. 首次阴线出现时，在当日收盘补齐到 100% 基础仓位。
4. 若等待期间信号切到另一个新 Top1，则重新按新 Top1 进入 50%。

注意：这比 A 策略源码更宽。A 策略源码中的 `CN_ENTRY_INITIAL_FRACTION = 0.5` 只在从现金进入时生效；V1.1 将该规则扩展到所有新 Top1 换入。

### 4.2 MA60 乖离过热过滤

对当前持仓资产计算：

- `bias = price / MA60 - 1`
- `bias_momentum`：A 策略式乖离率动量，即对最近 20 日 `price / MA60` 归一化后拟合斜率

触发规则：

- 触发：`bias >= 20%` 且 `bias_momentum > 0`
- 防守：下一段 close-to-close 收益按 0 仓位，即清仓
- 恢复：`bias <= 18%` 或同向过热条件消失

这条规则不是主 log-slope score 自带的过热，而是额外的 MA60 乖离过热过滤。

## 5. 参数稳健性

### 5.1 过热阈值重扫

数据源：QVeris `cps=3`
固定：新 Top1 先进 50%、`R2 >= 0.20`、25% target vol、1.5x max leverage

| 过热触发/恢复 | 年化收益 | 最大回撤 | Sharpe | 过热天数 |
|---|---:|---:|---:|---:|
| 18% / 16% | 57.67% | -16.54% | 1.876 | 30 |
| 20% / 18% | 60.46% | -16.54% | 1.932 | 17 |
| 22% / 20% | 59.09% | -18.95% | 1.887 | 7 |
| 24% / 22% | 56.98% | -18.95% | 1.828 | 3 |

结论：`20% / 18%` 是当前默认。

### 5.2 R2 x target vol 扫描

固定：新 Top1 先进 50%、MA60 过热 `20% / 18%`、1.5x max leverage

| R2 | 目标波动 | 年化收益 | 最大回撤 | Sharpe |
|---:|---:|---:|---:|---:|
| 0.10 | 20% | 47.42% | -14.19% | 1.915 |
| 0.10 | 25% | 60.10% | -16.42% | 1.922 |
| 0.10 | 30% | 69.19% | -18.11% | 1.904 |
| 0.20 | 20% | 47.74% | -14.30% | 1.925 |
| 0.20 | 25% | 60.46% | -16.54% | 1.932 |
| 0.20 | 30% | 69.65% | -19.14% | 1.923 |
| 0.30 | 20% | 44.11% | -14.44% | 1.819 |
| 0.30 | 25% | 54.80% | -17.20% | 1.812 |
| 0.30 | 30% | 62.48% | -19.41% | 1.808 |

结论：

- 默认保留 `R2 >= 0.20`。
- 默认保留 25% target vol。
- 30% target vol 可作为进攻版本，但不是默认：年化更高，回撤也更深，Sharpe 略低。
- 20% target vol 可作为防守版本：回撤更低，但年化下降明显。

## 6. V1.1 默认参数

| 参数 | 默认值 |
|---|---:|
| 数据源 | QVeris `cps=3` |
| 主信号 lookback | 25 |
| R2 阈值 | 0.20 |
| target vol | 25% |
| max leverage | 1.5x |
| Top1 switch buffer | 1.00 |
| 新 Top1 首笔仓位 | 50% |
| 补齐条件 | 首次收盘阴线 |
| MA60 过热触发 | 20% |
| MA60 过热恢复 | 18% |
| 过热后仓位 | 0% |
| 单边成本 | 0.10% |
| 资产止损 | 关闭 |

## 7. 版本输出

正式入口：

- `run_subd_six_etf_v1_1.py`

研究与验证脚本：

- `analyze_subd_six_etf_combo_effective_rules.py`
- `analyze_subd_six_etf_v1_1_qveris_robustness.py`

正式输出：

- `outputs/subd_six_etf_v1_1_20260509_summary.csv`
- `outputs/subd_six_etf_v1_1_20260509_daily.csv`
- `outputs/subd_six_etf_v1_1_qveris_overheat_scan_20260509_summary.csv`
- `outputs/subd_six_etf_v1_1_qveris_r2_targetvol_scan_20260509_summary.csv`
- `outputs/subd_six_etf_159941_data_source_check_20260509.csv`
- `outputs/subd_six_etf_qveris_cps3_data_quality_20260509.csv`

## 8. 验证记录

已执行：

```powershell
python -m py_compile .\run_subd_six_etf_v1_1.py
python .\run_subd_six_etf_v1_1.py
python -m py_compile .\analyze_subd_six_etf_v1_1_qveris_robustness.py
python .\analyze_subd_six_etf_v1_1_qveris_robustness.py
```

验证结果：

- `run_subd_six_etf_v1_1.py` 编译通过。
- QVeris 稳健性脚本编译通过。
- QVeris 过热扫描 daily：13,984 行，4 组，无重复 `scenario_tag/date`，无 `return/nav` 空值。
- QVeris R2/target-vol 扫描 daily：31,464 行，9 组，无重复 `scenario_tag/date`，无 `return/nav` 空值。
- 数据源校验确认 `159941.SZ` 的 Sina raw close 跳点不是经济收益。

## 9. 已测但不作为默认的方向

| 方向 | 结论 |
|---|---|
| Top1 switch buffer | `1.01` 稍好，但提升小，不如 V1.1 两条规则有效 |
| 主 log-slope score 过热 | 高 score 更像趋势强度，过滤会砍掉盈利段 |
| rolling score percentile 过滤 | 过早砍趋势，收益损失明显 |
| A 源码原版只从现金入场 50% | 触发少，六 ETF 上效果不如“所有新 Top1 换入 50%” |
| 过热 18/16 | 防守更频繁，但收益和 Sharpe 低于 20/18 |
| 过热 22/20、24/22 | 触发过少，回撤控制变弱 |
| R2 0.30 | 过严，收益和 Sharpe 均下降 |

## 10. 下一步建议

优先级从高到低：

1. 用 QVeris `cps=3` 重新生成正式 V1.1 daily/summary 入口，避免生产版本继续依赖 Sina raw close。
2. 扫先进比例 `40% / 50% / 60% / 70%`，确认 50% 不是单点峰值。
3. 扫补齐条件：首次阴线、首次 `-0.5%`、首次 `-1.0%`、等待 `3/5/10` 天强制补齐。
4. 扫 max leverage `1.2x / 1.5x / 2.0x`，因为 target vol 已确认 25% 最均衡，但杠杆上限还未重扫。
5. 做资产池稳健性：保留 V1.1 规则，只比较 no-soymeal、替代商品 ETF、五 ETF/六 ETF 差异。

当前不建议继续优化主 score 过热和 rolling percentile 过滤，它们已经显示为弱方向。
