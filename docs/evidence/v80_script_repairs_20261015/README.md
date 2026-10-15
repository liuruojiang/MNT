# V8.0 脚本修复：远端验收证据

本目录随本轮修复一起纳入 Git，保存可直接审阅的机器结果；对应[修复报告](../../v80_script_repairs_20261015.md)和[原始审计](../../v80_strategy_and_script_adversarial_audit_20261013.md)。

生产脚本仍为根目录 `mnt_bot V 8.0 plus.py`。已验收源文件与 Git blob 的 SHA256 均为 `c76e4764e1273ebf70f447533df191d77e8f1aabe481885e98e5874d5c1e7930`。Windows 导出或检出若启用 `core.autocrlf`，CRLF 字节哈希可能不同；核对时同时记录原始哈希和 LF 归一化后的哈希。

## 内容

- `full_local_test_results.json`：修复后本地全仓 603 项测试结果，以及原始日志和 JUnit 文件的哈希。
- `clean_export_test_results.json`：从暂存 Git 树导出的副本测试结果；不含本机忽略的冻结输入和审计产物，缺失依赖的测试明确跳过。
- `frozen_replay_verification.json`：固定真实输入的正式计算链、292 项既有配置一致性、收益差异及 8 条实际查询结果。
- `formal_fetch_verification.json`：真实取数入口正常对照，以及休市日、历史截短、BTC 周末缺口、IBIT 首日和上市前数据五类异常注入。
- `artifact_reconciliation.json`、`chart_parity.json`：4 本实际 Excel 的独立对账和两个查询入口的 PNG 字节一致性。
- `window_metrics.csv`、`window_metric_deltas.csv`：同次冻结重放的五窗口指标及修前差异。
- `syntax_check.json`、两份日历/历史覆盖证据：解释器语法检查及验证事实来源。
- `evidence_origins.json`：复制前本地证据的路径和原始哈希；文本副本统一 LF。
- `manifest.json`：本目录文件和交付源码、测试、文档的 Git 内容哈希。

## 运行与范围

在仓库根目录、已安装项目运行和测试依赖的 Python 环境运行：

```powershell
python -B -X utf8 -m pytest tests -q -rs -p no:cacheprovider
```

本轮新增的三份测试源码位于 `tests/test_v80_*_repairs_20261015.py`。其中 DBMF 的三个真实历史控制依赖本机 `outputs/v80_recert_20260926/l1_final/us_raw_ohlc.pkl`；其他既有证据测试也有本地依赖。跳过表示输入缺失，不表示该项验证通过。

冻结正式重放的数据截至 2026-09-25；A 股确认收盘为 09-24，美股为 09-25。正式取数异常测试另固定在北京时间 09-25 上午，两个市场均只使用 09-24 已确认收盘。两类试验的截止不能混用。

本目录包含证据摘要，未复制被冻结的行情 pickle、完整日志、Excel/PNG 原件、前轮工具和回退备份。完整冻结重放仍按修复报告所列本地路径执行；干净检出可运行回归测试，但不因此获得完整行情重放能力。静态证据不是最新行情、GitHub CI、Poe 部署或实盘执行认证。
