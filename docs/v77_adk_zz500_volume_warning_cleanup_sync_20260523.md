# V7.7 成交量警告牌更新与清理同步记录

日期：2026-05-23

## 结论

本轮 V7.7 只更新成交量“警告牌/参考提醒”显示，不改变 ADK、微盘、组合仓位、收益或 NAV 计算。

- ADK DK 成交额警告牌：保留 2026-05-23 已落地的中证500 `MA28 / 5天` warning-only 条件。
- 微盘成交量参考提醒：把宽口径条件从中证2000/创业板 `MA53 / 13天 AND` 替换为 `MA35 / 18天 AND`，并在展示层标出参考 `scale=25%`。
- 微盘成交量政策仍为 `warning_only_reference`：仅提示复核，不自动改写微盘仓位，也不参与微盘净值曲线。

## 微盘警告牌参数

代码路径：`mnt_bot V 7.7 plus.py`

| 项目 | 当前值 |
|---|---:|
| 中证2000成交额口径 | `2.932000` |
| 中证2000 MA / 连续天数 | `35 / 18` |
| 创业板成交额口径 | `0.399006` |
| 创业板 MA / 连续天数 | `35 / 18` |
| 触发逻辑 | 两者都连续低于各自 MA 达到 18 天 |
| 参考 scale | `25%` |
| 执行影响 | 无，仅展示 |

展示同步范围：

- `_write_volume_warning_panel(...)`：信号和实时信号面板文案加入 `参考scale=25%`。
- `_handle_params(...)`：参数页的“微盘成交量参考提醒”和“微盘成交量政策”同步为 `MA35 / 18天 AND` 与 `参考scale=25%`。
- `_handle_live_params(...)`：实时参数页组合权重区同步展示微盘宽口径 `MA35 / 18天 AND` 与 `参考scale=25%`，避免静态参数页和实时参数页不一致。

## ADK 警告牌记录

2026-05-23 的多指数成交额扫描保留为研究证据，来源目录：

`quant_param_scan_runs/20260523_a_us_momentum_combo_v7_7_sub_a_dk_multi_index_amount_filter`

该扫描结论为：不把任何 ADK 成交额过滤器提升为生产交易规则；中证500 `MA28 / 5天` 仅作为 warning-only 展示。核心原因是近年窗口有回撤改善，但 10Y 维度没有通过稳健性要求，且存在年化收益拖累。

## 测试文件清理

本轮清理了最近两天运行验证时生成的可再生测试/缓存文件：

- `.pytest_cache/`
- `__pycache__/`

清理前已备份到：

- `.codex_backups/20260523_135650/`

未删除内容：

- `quant_param_scan_runs/20260523_a_us_momentum_combo_v7_7_sub_a_dk_multi_index_amount_filter/`：该目录是已跟踪的研究证据，不作为临时测试文件删除。
- `docs/` 下的研究记录：作为结论和同步说明保留。
- `.cn_official_cache/` 与 `mnt_strategy_data_cn.csv`：属于数据缓存/基础数据，不作为测试文件清理。

## 验证

本轮同步前使用以下命令验证：

- `python -m py_compile "mnt_bot V 7.7 plus.py"`
- 常量导入检查：`MA35 / 18天 / reference_scale=0.25 / warning_only_reference`
- `git diff --check -- "mnt_bot V 7.7 plus.py" "docs/v77_adk_zz500_volume_warning_cleanup_sync_20260523.md"`
- `git status --short --ignored`

`py_compile` 会重新生成 `__pycache__/`，验证后再次删除该缓存目录，确保工作区不保留测试缓存。
