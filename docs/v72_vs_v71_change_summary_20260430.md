# V7.2 相对 V7.1 的变化总结

日期：2026-04-30

## 结论

V7.2 不是简单调参版，而是把组合结构从 V7.1 的四袖组合改成了“低 A、保留 ADK、加入独立微盘、提高 Sub-B”的主组合，并把成交额风控分成两类：

- 正式执行：只有 Sub-A 的中证2000/创业板成交额缩量规则。
- 黄灯提醒：Sub-A-DK 成交额规则、微盘成交额/成交量规则。

## 组合层变化

| 项目 | V7.1 | V7.2 |
|---|---:|---:|
| Sub-A | 15% | 10% |
| Sub-A-DK | 25% | 15% |
| Microcap / 微盘 | 不在主组合 | 15% |
| Sub-B | 40% | 60% |
| Sub-C | 20% | 0% |

V7.2 的主组合权重固定为：

```text
Sub-A 10% + Sub-A-DK 15% + Microcap 15% + Sub-B 60% + Sub-C 0%
```

Sub-C 没有删除，仍保留信号和参数展示，但不再进入 V7.2 主组合权重。

## 微盘股袖

V7.2 新增 Microcap 独立袖，收益从微盘股独立仓库脚本加载，而不是并入 Sub-B：

- 数据/逻辑入口：`_load_microcap_daily_ret(...)`
- 独立脚本：`microcap_top100_mom16_biweekly_live.py`
- 成本路径：`run_signal + apply_cost_model`

这样做的含义是：微盘仍然是独立 A 股小市值策略，不和美股 Sub-B 候选池混在一起。

## Sub-B 变化

V7.1 的 Sub-B 主池为：

```text
QQQ, EMXC, EFA, GLD, TLT, DBC, BTC-USD
```

V7.2 保留这个基础池，同时新增一个“通胀压力开启时才可进入”的宏观候选池：

```text
UUP, DBMF, KMLM
```

通胀开关不是主观开关，而是按信号日价格判断：

```text
DBC 126日动量 > 0
并且 TLT 126日动量 < 0
```

只有这个条件满足时，`UUP/DBMF/KMLM` 才进入 Sub-B 排名池；否则只作为参考行显示，不参与持仓计算。

保持不变的 Sub-B 主逻辑：

- 130 / 260 / 390 日动量混合。
- Top 3 + 绝对动量过滤。
- 1.05x 挑战者保护。
- 25% target-vol。
- `QQQ/GLD` 可放大，最高 2.0x。
- SPY 仍只作为 VolReg 风控参考，不进入 Sub-B 排名池。

## 成交额规则

### Sub-A：正式执行规则

V7.2 新增正式 Sub-A 成交额缩量规则：

```text
中证2000 成交额 < MA15 连续3天
OR 创业板成交额 < MA10 连续3天
=> Sub-A 权益敞口缩到 50%
```

实现位置：

- 常量：`CN_SA_VOLUME_*`
- 规则构造：`_load_suba_volume_signal(...)`
- 仓位重建：`apply_suba_volume_overlay(...)`
- 接入点：`_run_strategies(...)`

这个规则进入 Sub-A 的真实仓位、收益、成本和 vol-scaling 重建路径。

### Sub-A-DK：黄灯提醒

DK 成交额规则不参与仓位：

```text
沪深300成交额 < MA40 连续16天
=> 黄灯提醒
```

脚本中政策写死为：

```text
CN_DK_VOLUME_POLICY = "warning_only"
```

原因：参数在山脊内，但坚韧性不够强，适合作为风险提示，不适合直接做实盘降仓。

### 微盘：黄灯提醒

微盘成交额/成交量规则也不参与仓位：

```text
中证2000成交额缩量 AND 创业板成交额缩量
=> 黄灯提醒

同花顺/QVeris 微盘股指数 883418.TI 成交量
=> 黄灯观察
```

脚本中政策写死为：

```text
MICROCAP_VOLUME_POLICY = "warning_only"
```

原因：无论是中证2000+创业板，还是微盘股指数自身成交量，当前证据都更适合做提示面板，不适合作为正式实盘参数。

## 风险提醒面板

V7.2 保留 V7.1 已有的 S&P 500 风险等级提醒，并扩展为组合风险观察区：

- S&P 500 风险等级：仅提示，不直接改仓。
- 通胀压力：控制 `UUP/DBMF/KMLM` 是否进入 Sub-B。
- DK 成交额黄灯：仅提示。
- 微盘成交额/成交量黄灯：仅提示。

## 参数和展示变化

V7.2 已同步更新：

- Poe 名称：`Strategy-Signal-V72`
- 版本类：`CombinedStrategyV72`
- 参数页：显示 V7.2 主组合权重、Sub-A 成交额正式规则、DK/微盘黄灯政策。
- 信号页/实时信号页：增加成交额黄灯提醒面板。
- 资金配置说明：微盘 15% 由独立脚本处理，不在 Poe 资金配置里设置。
- 净值/表现统计：主组合口径包含 `Sub-A / Sub-A-DK / Microcap / Sub-B`，不再把 Sub-C 纳入主组合。

## 明确没有改的内容

- Sub-A 原始乖离动量、R2 过滤、Cash Overlay、同向过热防守仍保留。
- Sub-A-DK 多配对 Top-1、score 衰减、同向过热防守仍保留。
- Sub-B 的基础池和核心轮动逻辑仍保留。
- Sub-C 仍可独立查看，但 V7.2 主组合权重为 0。

## 验证

本次脚本变更后已运行：

```powershell
python -m unittest tests.test_v72_volume_policy
python -m py_compile "mnt_bot V 7.2 plus.py"
```

结果均通过。

注意：`docs/v72_weight_scan_20260429/summary.md` 中的组合扫描结果来自 2026-04-29 的 V7.2 结构研究；2026-04-30 新增的 Sub-A 成交额正式规则已经写入脚本，但尚未在本文档中重跑全组合收益统计。

## 相关文件

- `mnt_bot V 7.1 plus.py`
- `mnt_bot V 7.2 plus.py`
- `tests/test_v72_volume_policy.py`
- `docs/v72_weight_scan_20260429/summary.md`
- `docs/suba_volume_effect_20260430/decision_record.md`
- `docs/dk_volume_effect_20260430/`
