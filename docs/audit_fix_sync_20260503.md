# V7.x 与微盘脚本审查修复同步记录

日期: 2026-05-03

## 同步范围

- A股美股组合: `mnt_bot V 7.0 plus.py`, `mnt_bot V 7.1 plus.py`, `mnt_bot V 7.2 plus.py`, `mnt_bot V 7.3 plus.py`, `mnt_bot V 7.5 plus.py`
- 微盘脚本: `microcap_top100_mom16_biweekly_live_v1_4.py`, `microcap_top100_mom16_biweekly_live_v1_6.py`
- 测试文件: `test_v1_4_output_compatibility.py`, `test_v1_6_output_compatibility.py`

## A股美股 V7.x 已同步修复

- Sub-C 关闭时的信号崩溃保护: `extract_prod_rebalances` / `extract_subc_vs_rebalances` 增加空输入保护，避免 Sub-C 权重为 0 时信号查询崩溃。
- 删除 Sub-A `await_fresh_entry_signal` 死代码，避免未来读者误以为仍有清仓后等待重新入场的冷却机制。
- P1 重要 bug: `apply_suba_same_side_overheat_overlay` 在底层 `pre_holding` 换仓时重置 `overheat_state`，避免旧资产的过热状态污染新资产。
- A股实时补价: 未变化判断改用相对阈值；非 `close` 列补 `NaN`，不再把 `volume` / `amount` 等列填成价格。
- 美股实时日期: `regularMarketTime` 统一按 UTC 转 `America/New_York` 后取交易日，避免服务器本地时区造成 off-by-one。
- VolReg overlay: 首日不再从假设全 CASH 计算一次虚假换手成本；调仓显示过滤 BIL/CASH 虚拟资产。
- `is_cn_market_open` 增加午休窗口判断。
- 国债数据拉取失败时给出 warning，不再静默退化为权益-only Sub-A。
- Excel 文件名日期使用 `beijing_now()`，避免服务器时区影响。
- 早周美股信号压制改为只压制当前美股数据日上的未确认早周信号。
- Sub-A 杠杆显示增加 NaN / 零除保护。
- V7.2 / V7.3 组合表现标签标注“不含微盘”。

## Sub-B EMA 修复

以下修复只适用于带 EMA 腿的 V7.3 / V7.5:

- 实时 hypothetical 权重改为官方腿 + EMA 腿混合后的目标权重。
- 官方腿 hypothetical 的 vol-scale 使用 `official_return` 口径，而不是混合后 `return`。
- EMA hypothetical 的 vol-scale 使用 T-1 口径，避免多看今日收益。
- EMA prev-risky 只读取 `ema_w_` / `ema_actual_w_`，不再回退到混合 `w_` / `actual_w_`，避免把官方腿持仓误当作 EMA 腿持仓。

V7.0 / V7.1 / V7.2 没有 V7.3 / V7.5 的 EMA Sub-B 混合腿，因此这些 EMA 修复不适用。

## 微盘 v1.4 / v1.6 已同步修复

- v1.4 hedge ratio 校验改为严格失败: 缺少 `base_mod` 或 `FIXED_HEDGE_RATIO` 时直接报错。
- v1.4 输出生成不再先删旧文件；新结果成功写出后才清理未重写的 stale 文件。
- v1.4 增加对上游内部 API 依赖的维护注释。
- v1.6 保留严格 hedge ratio 校验、`current_base_fingerprint` dict copy、防重复索引检查、target-vol return-source fallback 标记、融资成本复利处理、输出生成不先删旧文件等修复。

## 未纳入本轮的低优先级项

- V7.x 未做大规模死代码删除。删除未调用函数会扩大回归面，建议另开清理任务。
- A股节假日判断未接交易所日历。本轮只修复午休窗口。
- 微盘 v1.4 没有 target-vol scaling，因此 v1.6 的 return-source / financing 逻辑不适用。

## P1 回测影响记录

- P1 Sub-A same-side overheat 修复使用真实数据对比过 V7.5 当前版与修复前备份。
- 影响集中在 2015-05-25 到 2015-09-14，共 44 个 Sub-A 交易日。
- Sub-A 期末 NAV: 50.8081 -> 52.2540，约 +2.85% 相对提升。
- 脚本月度口径的三策略组合，不含微盘，期末 NAV: 20.4852 -> 20.6553，约 +0.83% 相对提升。
- 临时明细输出已在云端同步前清理；关键影响结论保留在本文档。

## 备份

- A股美股本轮同步备份: `.codex_backups/20260503_222522`
- 微盘本轮同步备份: `../微盘股对冲策略/.codex_backups/20260503_222530`

## 验证命令

```powershell
python -m py_compile "mnt_bot V 7.0 plus.py" "mnt_bot V 7.1 plus.py" "mnt_bot V 7.2 plus.py" "mnt_bot V 7.3 plus.py" "mnt_bot V 7.5 plus.py"
git diff --check -- "mnt_bot V 7.0 plus.py" "mnt_bot V 7.1 plus.py" "mnt_bot V 7.2 plus.py" "mnt_bot V 7.3 plus.py" "mnt_bot V 7.5 plus.py" docs/audit_fix_sync_20260503.md
python -m py_compile microcap_top100_mom16_biweekly_live_v1_4.py microcap_top100_mom16_biweekly_live_v1_6.py
python -m unittest test_v1_4_output_compatibility.py test_v1_6_output_compatibility.py
git diff --check -- microcap_top100_mom16_biweekly_live_v1_4.py microcap_top100_mom16_biweekly_live_v1_6.py test_v1_4_output_compatibility.py test_v1_6_output_compatibility.py
```

## 最终确认

- V7.0 / V7.1 / V7.2 / V7.3 / V7.5 均已包含 P1 overheat 状态重置修复。
- V7.3 / V7.5 已包含 Sub-B EMA hypothetical 相关修复。
- 微盘 v1.4 / v1.6 已包含本轮适用的防御性修复。

## 2026-05-03 追加漏同步修补

- V7.3 “实时参数”分支补齐 Sub-B EMA 修复: official 腿 vol-scale 展示使用 `official_return` T-1 口径；hypothetical 权重使用官方腿 + EMA 腿混合；早周美股信号压制也同步到该分支。
- V7.2 `_performance_combo_weight_label()` 改为 `归一(不含微盘15%)`。
- V7.2 / V7.3 Excel 与 PV/收益查询表头统一改为 `PV三策略组合(不含微盘)`。
- 追加备份: `.codex_backups/20260503_realtime_params_label_sync`。
