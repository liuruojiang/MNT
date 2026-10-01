# L7 Sub-B7.8 / B7.9 独立运行链审计

## 裁决

- **冻结纸面模型的批量/截断重放、事件时序、四腿和本地查询展示：PASS。** 首差：无。
- **同一实例跨请求恢复：修复后本地 PASS。** `run()` 进入时清空两种请求缓存；没有 Poe 远端运行日志，真实服务进程的恢复/交付记为 **N/A**。
- **真实可执行收益、经纪商成交及账户权限：本层未认证。** L1 代理历史和 L5 其他袖账户限制继续有效；B 的模型成交不是经纪商回执。

## 身份与数据

- 最终源 `mnt_bot V 8.0 plus.py` SHA256 `06b69d328b41416f7aaf350371a17b5839deb0339e06ad57af09fb77ecbed3b4`。与 L5 源快照相比，顶层 AST 变化仅在 Sub-A 流水、两个 adjusted-open 错误文案、`CombinedStrategyV78.run()` 缓存初始化；最后一项由独立缓存反例检查。
- L1 冻结 `formal_inputs.pkl` SHA256 `182a5c54d5c81699d8e93038695a76febd15312aa48b5864e47a46318eeba00f`。B 美国市场价格帧 2007-05-30 至 2026-09-25，4,863 行；美股调整开盘字典按 2026-09-24 截断。比较基准为 L2 正式 `formal_results.pkl` 中 B7.8/B7.9 全量纸面结果。
- 两版正式结果各 4,472 个收益日，2008-12-15 至 2026-09-25；各有 2,280 个不在 A 股帧中的日期。BTC-USD/IBIT 使用冻结的美股交易日拼接代理，早期代理不等于实际 ETF 成交。

## 对抗证据

1. 按 2026-09-24 收盘截断真实输入及调整开盘，以正式 `_run_v80_subb_variants(..., strict_open_execution=True)` 从头重放。B7.8/B7.9 完整账户以及官方+EMA、Bias、LogVol 的 8 个结果帧，对 L2 全量结果在共同 4,471 或 4,541 个日期的 26–153 个数值列逐日比较，所有数值列首差均为零（绝对容差 `1e-10`）；含收益、净值、实际/目标权重、VolReg、费用和证券账户字段。见 `runtime_chain_results.json`。
2. 从冻结账本独立检查上一美股收益日的待执行标志到下一美股日的执行标志：B7.8/B7.9 各 928 次周模型、36 次 VolReg 完全对齐；正换手日 953/942，未标记交易、零换手带费、账户实际费用与 10bp 开盘成交额不符均 0。首个周信号 2008-12-18 收盘，首次模型执行 2008-12-19 开盘。把执行标志故意再错开一日，每版检测到 1,855 处不一致；故意漏掉首次费用也被拒。见 `event_shift_results.json`。
3. 同一实例相同输入复用策略缓存；改变收盘价或调整开盘值则重新计算。故意在同一实例第二次直接调用 `_cached_fetch_data` 会取旧值；本轮正式源码在每次 `run()` 开始清空两个请求缓存后，再次调用会重新获取，验证结果 `1 → 3`。新实例也会重新获取。见 `cache_contract_results.json`。这是本地函数路径的验证，不等于 Poe 远端生命周期实测。
4. 截断到 2026-09-24 的周四收盘，`signal`、`live_signal`、`params`、`live_params` 四种展示均分别显示 B7.8/B7.9 和官方/EMA/Bias/LogVol 四腿及下一美股日开盘时序。收盘信号两版确认，盘中信号两版均不确认。2026-09-25 周五执行日的盘中展示两版均不发新信号，并提示周五不是新信号日。见 `runtime_chain_results.json` 和 `friday_display_results.json`。
5. 本地报告导出函数 `_v80_extract_subb_rebalances` 在 2026-09-01 至 09-25 生成 7 条 B 流水，B7.8 四条、B7.9 三条；记录区分版本与模型类型，2026-09-24 信号行标示 09-25 北京时间开盘执行。见 `recent_delivery_records.json`。没有 Poe 附件发送回执。

复现：

```powershell
python -X utf8 outputs/v80_recert_20260926/l7/subb/audit_b_runtime_chain.py
python -X utf8 outputs/v80_recert_20260926/l7/subb/audit_b_event_shift.py
python -X utf8 outputs/v80_recert_20260926/l7/subb/audit_b_cache_contract.py
```

上述检查仅核冻结、离线、纸面运行链；未向生产系统发信号、下单或改参数。
