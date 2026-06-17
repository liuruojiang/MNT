# V7.8 外部审核修复清理与同步记录（2026-06-17）

## 范围

- 主文件：`mnt_bot V 7.8 plus.py`
- 回归测试：
  - `tests/test_v78_adk_subb_blend_display.py`
  - `tests/test_v78_cn_live_freshness.py`
  - `tests/test_v78_suba_new_signal_display.py`
- 本次清理删除根目录临时输出文件，只保留代码、测试与本记录。

## 已确认并修复的高风险项

- Yahoo 日线时间戳统一按 UTC 解析，避免 BTC-USD 00:00 UTC 在非 UTC 服务器上回退一天。
- ADK DK 乖离动量 R2 质量门控改为复用与斜率一致的 `linspace(1, 10)` 加权核。
- `run_v78_adk_new_primary` 不再临时写全局变量，改为通过 `run_dk_strategy(..., official_pair_order=..., r2_quality_enabled=...)` 传参，避免并发串改。
- SPY 成交量门控默认改为 `fail_closed`，并让 `_v78_fetch_spy_volume` 使用带重试的 `_session.get`。
- Sub-B BTC 起始过滤在各 `run_subb_*` 路径生效；删除了 `_fetch_data` 层的重复过滤，避免职责重复。
- 删除脆弱的模块级 `del _bt_remaining, _n, _c, ...`。
- S&P 风险快照不再回落到硬编码未来日期数值，缺数据时按不可用处理。
- New A TV1.0 在杠杆上限大于 1 且融资成本未实现时直接拒绝运行，避免未来口径漂移。
- V7.8 Sub-B 混合收益增加 component-net 成本口径说明：回测 NAV 是单腿各自扣成本后混合，展示综合目标权重用于实盘净额下单，不是生成该 NAV 的逐腿成本权重。

## 回测影响口径

曾有一版诊断脚本误把组合按原始 `15% / 15% / 40% = 70%` 权重计算，相当于隐含 30% 空仓；这不是 V7.8 收益页/PV 口径。正式展示口径应使用 `_performance_combo_weights()` 对 Sub-A / Sub-A-DK / Sub-B 做归一化，且不含微盘/Sub-D。

基于 `v78_revision_perf_compare_multi_baseline_live_20260617.csv` 的正确口径，修复前后影响如下：

| 策略 | 区间 | 修复前年化 | 修复后年化 | 年化差异 | 修复前最大回撤 | 修复后最大回撤 | 回撤差异 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Combined | Full 2015-04-21~2026-06-17 | 24.20% | 24.11% | -0.09pp | -6.82% | -6.88% | -0.06pp |
| Combined | 10Y 2016-06-17~2026-06-17 | 26.18% | 25.99% | -0.19pp | -6.82% | -6.88% | -0.06pp |
| Combined | 5Y 2021-06-17~2026-06-17 | 27.25% | 26.97% | -0.27pp | -6.54% | -6.56% | -0.02pp |
| Combined | 3Y 2023-06-19~2026-06-17 | 34.63% | 34.49% | -0.14pp | -6.54% | -6.56% | -0.02pp |
| Combined | 1Y 2025-06-17~2026-06-17 | 48.72% | 48.88% | +0.16pp | -5.88% | -5.93% | -0.05pp |
| Sub-A | Full 2015-02-10~2026-06-17 | 25.96% | 25.51% | -0.46pp | -20.49% | -20.98% | -0.49pp |
| Sub-A-DK | Full 2015-04-20~2026-06-17 | 17.41% | 17.41% | 0.00pp | -16.36% | -16.36% | 0.00pp |
| Sub-B | Full 2008-12-15~2026-06-16 | 19.08% | 19.08% | 0.00pp | -13.44% | -13.44% | 0.00pp |

结论：整批外部审核修复对官方 V7.8 历史回测影响很小，主要来自 Sub-A 年化轻微下降；ADK 与 Sub-B 在这批正式对比中不变。Combined 全样本年化约下降 0.09 个百分点，最大回撤约加深 0.06 个百分点。

## 清理记录

删除根目录临时输出：

- `v78_external_audit_before_after_delta_20260617.csv`
- `v78_external_audit_before_after_metrics_20260617.json`
- `v78_revision_perf_compare_20260617.csv`
- `v78_revision_perf_compare_multi_baseline_live_20260617.csv`

保留 `tests/` 下回归测试文件，因为它们覆盖了本次修复后的关键不变量，不属于一次性测试输出。

## 验证记录

- `python -m py_compile "mnt_bot V 7.8 plus.py"`：通过。
- `python -m pytest tests/test_v78_adk_subb_blend_display.py tests/test_v78_cn_live_freshness.py tests/test_v78_suba_new_signal_display.py -q`：通过，`103 passed, 1 warning`。
- `git diff --check`：通过，仅保留既有 CRLF 提示。
