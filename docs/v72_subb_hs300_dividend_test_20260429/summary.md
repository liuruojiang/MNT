# V7.2 Sub-B HS300 and Dividend Candidate Test

Date: 2026-04-29

Scope: research only. No production strategy file changed.

## Setup

- Strategy file: `mnt_bot V 7.1 plus.py`
- Engine: `run_us_rotation_mix(...)` plus `apply_vol_regime_overlay(...)`
- Baseline Sub-B pool: `QQQ, EMXC, EFA, GLD, TLT, DBC, BTC-USD`, with `BIL` cash fallback.
- Rules preserved: 130/260/390 day momentum mix, top 3 selection, 4% absolute momentum gate, 1.05x challenger protection, inverse-vol weighting, target-vol scaling, 0.1% commission, and SPY VolReg overlay.
- Baseline sample: 2015-10-13 to 2026-04-17, rows=3840.

## Candidates

| Candidate | Data used | Notes |
|---|---|---|
| `CN_HS300` | `mnt_strategy_data_cn.csv: 1.000300` | 沪深300价格指数代理。不是全收益；按最近A股收盘价 forward-fill 到美股日历。 |
| `CN_ZZHL_TR` | `mnt_strategy_data_cn.csv: 1.H20955` | 生产脚本里 Sub-A 使用的中证红利低波100全收益指数代理。按最近A股收盘价 forward-fill 到美股日历。 |
| `SCHD`, `VIG`, `DGRO`, `DVY`, `SDY`, `NOBL` | `mnt.fetch_yahoo(...)` adjusted close | Yahoo adjusted close，同源于脚本的美股数据抓取逻辑。 |

A股候选只是“方向性池子测试”：没有 FX、没有A股ETF跟踪误差、没有涨跌停/T+1/交易时段约束，因此不能直接当作 Sub-B 美元实盘结论。

## Full Sample Result

| Candidate | Variant Annual | dAnnual | Variant Sharpe | dSharpe | Variant MaxDD | dMaxDD | Avg Weight |
|---|---:|---:|---:|---:|---:|---:|---:|
| `SDY` | 23.77% | -1.04% | 1.22 | -0.023 | -19.10% | -3.30% | 8.73% |
| `NOBL` | 23.60% | -1.21% | 1.21 | -0.035 | -16.20% | -0.41% | 7.10% |
| `CN_ZZHL_TR` | 22.45% | -2.36% | 1.17 | -0.071 | -17.22% | -1.42% | 11.22% |
| `SCHD` | 22.40% | -2.41% | 1.17 | -0.073 | -18.75% | -2.95% | 10.94% |
| `DVY` | 22.16% | -2.65% | 1.16 | -0.080 | -19.07% | -3.28% | 10.66% |
| `CN_HS300` | 22.16% | -2.64% | 1.14 | -0.104 | -15.91% | -0.11% | 6.03% |
| `VIG` | 21.90% | -2.90% | 1.13 | -0.113 | -16.29% | -0.49% | 8.99% |
| `DGRO` | 21.75% | -3.06% | 1.13 | -0.114 | -16.03% | -0.23% | 9.52% |

`dMaxDD` is variant max drawdown minus baseline max drawdown. Positive means shallower drawdown; negative means worse drawdown.

## Recent 3Y Check

| Candidate | dAnnual | dSharpe | dMaxDD |
|---|---:|---:|---:|
| `CN_ZZHL_TR` | +0.83% | +0.073 | +0.00% |
| `NOBL` | +0.01% | +0.009 | +0.00% |
| `SDY` | -0.33% | +0.002 | +0.00% |
| `CN_HS300` | -2.45% | -0.047 | -0.04% |
| `SCHD` | -2.64% | -0.069 | -1.07% |
| `DGRO` | -3.88% | -0.108 | -0.06% |
| `DVY` | -4.03% | -0.115 | -0.43% |
| `VIG` | -4.90% | -0.153 | +0.00% |

## 2022 Inflation Shock Check

| Candidate | dAnnual | dSharpe | dMaxDD |
|---|---:|---:|---:|
| `CN_HS300` | -0.18% | -0.012 | +0.00% |
| `VIG` | -1.58% | -0.162 | +1.55% |
| `CN_ZZHL_TR` | -2.82% | -0.240 | +2.47% |
| `NOBL` | -2.53% | -0.243 | +0.47% |
| `DGRO` | -3.83% | -0.380 | +1.16% |
| `SDY` | -4.39% | -0.384 | -1.54% |
| `SCHD` | -6.00% | -0.527 | -1.89% |
| `DVY` | -6.22% | -0.560 | -1.16% |

## Interpretation

1. 沪深300不适合加入 Sub-B 候选池。
   它全样本年化下降 2.64pct、Sharpe 下降 0.104；最近3年也明显拖累。它只轻微改变回撤，不足以抵消收益和Sharpe损失。

2. 红利低波不适合直接进入 Sub-B 正式池。
   最近3年红利低波全收益代理有小幅正贡献，但全样本年化下降 2.36pct、Sharpe 下降 0.071，2022冲击期也拖累。它更像 A股侧的风格资产，不适合硬塞进美股 Sub-B 排名池。

3. 美股红利 ETF 也不建议加入。
   `SDY` 和 `NOBL` 是这组里相对最不差的，但全样本仍低于原池。`SCHD/DVY/VIG/DGRO` 拖累更明显。红利 ETF 被选中时主要挤出 `QQQ/GLD/EMXC/EFA`，并没有补出新的有效风险因子。

4. 这组候选没有通过“先改善 Sub-B 本身”的门槛。
   如果要研究红利因子，更合理的方向是独立风格 sleeve 或 A股/美股红利组合层配置，而不是放进 Sub-B 的动量候选池。

## Files

- `metrics.csv`
- `weight_usage.csv`
- `full_sample_weight_displacement.csv`
- `latest_variant_weights.csv`
- `meta.json`
