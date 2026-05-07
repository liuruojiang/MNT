# 2026-05-07 清理与同步记录

## 范围

- 仓库: A股美股动量组合策略
- 分支: `codex/subb-turnover-cost-cloud`
- 目标: 清理测试文件、缓存和已废弃的一次性研究产物，并把保留的正式脚本、研究结果和文档同步到远端。

## 已删除

- `tests/`
- `analyze_subb_sp500_regime_equity_derisk.py`
- `build_v76_microcap_v16_10y_combo.py`
- `docs/adk_top5_pair_reselect_drawdown_20260507/`
- `docs/adk_top5_reselect_filter_param_scan_20260507/`
- `docs/adk_top5_reselect_risk_filter_scan_20260507/`

## 删除原因

- `tests/` 按本次要求清理。
- 两个根目录分析脚本是一次性生成研究输出的临时脚本，正式结果已保留在 `docs/`。
- 三个 `reselect` ADK 目录对应“不空仓、继续往下选”的口径，已被当前决策排除，避免后续误用。

## 已保留

- 7.x 正式策略脚本。
- ADK 空仓白名单、盈利概率、持仓时间、V7.5/V7.6 对比、Sub-B 研究等正式 `docs/` 输出。
- `.codex_backups/` 备份目录。
- 已跟踪的本地行情缓存文件，作为当前工作树中的数据更新保留。

## 备份

- 删除前备份目录: `.codex_backups/20260507_210215`

## 验证

- 清理后执行正式入口语法检查。
- 清理后删除 `py_compile` 重新生成的 `__pycache__/`。
- 推送前执行 `git diff --check`。
