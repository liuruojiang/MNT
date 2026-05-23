# V7.7 ADK ZZ500 成交额警告栏更新与同步记录

日期：2026-05-23

## 结论

V7.7 的 Sub-A-DK 成交额警告栏已从原来的沪深300 `MA40 / 16天`，替换为中证500 `MA28 / 5天`。该规则只进入警告栏，不参与 ADK 仓位、收益或净值曲线计算。

## 选择依据

本次依据 `quant_param_scan_runs/20260523_a_us_momentum_combo_v7_7_sub_a_dk_multi_index_amount_filter` 的同口径扫描结果选择 `ZZ500 MA28 / 5天`：

| 窗口 | 基准年化 | 基准最大回撤 | ZZ500 MA28/5 年化 | ZZ500 MA28/5 最大回撤 | 年化变化 | 回撤变化 |
|---|---:|---:|---:|---:|---:|---:|
| 10Y | 19.99% | -15.49% | 17.93% | -15.50% | -2.06pp | -0.01pp |
| 5Y | 23.79% | -13.80% | 22.92% | -11.82% | -0.86pp | +1.98pp |
| 3Y | 23.48% | -13.80% | 25.13% | -11.82% | +1.65pp | +1.98pp |
| 1Y | 19.86% | -13.80% | 25.43% | -11.39% | +5.57pp | +2.41pp |

`MA34 / 4天` 的综合分更高，但 5Y 年化损失达到 `-1.28pp`，10Y 年化损失达到 `-2.61pp`。`MA28 / 5天` 的近年回撤改善仍然明显，且年化损失更小，更适合 warning-only 显示。

## 代码范围

- `mnt_bot V 7.7 plus.py`
  - `CN_DK_VOLUME_YELLOW_SECID = "1.000905"`
  - `CN_DK_VOLUME_YELLOW_LABEL = "中证500"`
  - `CN_DK_VOLUME_YELLOW_MA = 28`
  - `CN_DK_VOLUME_YELLOW_DAYS = 5`
  - UNKNOWN 文案改为引用当前标签，避免继续写死沪深300。

未改动：

- ADK 实际敞口计算。
- ADK return / NAV 计算。
- DK 成交额 warning-only 策略定位。

## 测试文件清理

本轮清理了临时 `tests/` 目录，包括：

- `tests/test_h20955_proxy_guard.py`
- `tests/test_v77_dk_volume_warning_rule.py`
- `tests/__pycache__/`

删除前已备份到：

- `.codex_backups/20260523_1222_test_cleanup/tests/`

## 验证

测试目录已清理，因此按本仓库规则使用实际脚本编译和扫描产物检查验证：

- `python -m py_compile "mnt_bot V 6.5 plus.py" ... "mnt_bot V 7.7 plus.py"`
- `python C:\Users\Administrator.DESKTOP-95I7VVU\.codex\skills\quant-param-scan\scripts\check_quant_param_scan_artifacts.py --phase complete --strict quant_param_scan_runs\20260523_a_us_momentum_combo_v7_7_sub_a_dk_multi_index_amount_filter`
- `git diff --check`

## 同步范围

计划同步到 GitHub 的内容：

- V6.5 到 V7.7 的 H20955 官方数据源保护改动。
- V7.7 Sub-A 展示层绝对动量过滤说明同步。
- V7.7 ADK 中证500 `MA28 / 5天` 成交额 warning-only 条件。
- `20260523` 多指数成交额扫描完整产物与 ZZ500 focus 记录。
- 本说明文档。

测试目录不保留到云端。
