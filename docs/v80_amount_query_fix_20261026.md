# V8.0 绩效查询成交额截止日修复

已修复本地 `mnt_bot V 8.0 plus.py`；未部署或验收 Poe 线上实例，也未生成或认证最新五袖组合收益。

## 原因与改动

2026-10-26 北京时间 16:35 实测，中证2000官方成交额及搜狐创业板成交额均覆盖至 2026-10-23。当 A 股价格已到 10 月 26 日、美股确认收盘仍为 10 月 23 日时，报告先确定共同截止日为 23 日，却把包含 26 日的 A 股价格传入策略，进而要求报告范围之外的 26 日成交额。历史区间查询也存在同类问题。

绩效和净值曲线现在在调用策略前，复制并裁掉报告截止日之后的 Sub-A / Sub-A-DK 价格；保留此前全部历史和预热数据、完整性标记及原始请求缓存。美股计算路径保持原样。未关闭成交额规则，也不允许报告范围内的缺失数据通过。

成交额失败现在保留所需截止日、不可判定日期和来源错误。删除“进入策略前发生运行时错误”的错误归因；数据不可用时明确未生成绩效报告。

用户提供的 Poe 错误未包含底层来源详情，且线上源码版本未核对，因此本次已确认的是本地可复现的日期依赖缺陷，不能断言它解释了线上每一次失败。

## 验证

- 相关回归：**163 passed，12 subtests passed**。覆盖两类报告、最近一年/指定历史区间、完整历史保留、原始缓存不变、成交额缺失及空返回阻断和来源错误展示，以及两种 Poe 加载接口场景。
- 真实来源：CSIndex 中证2000原始成交额 3114 行；搜狐创业板成交额 3978 行，并沿用已有国证核实的 2018-12-14 补点。原始中证2000发布前回填行由正式 loader 排除；没有将原始接口全部行认证为正式历史。
- 正式价格可用起点 2017-05-26 至 2026-10-23 的 2284 个 A 股交易日，成交额规则组合不可判定行数为 **0**。
- 真实冻结价格 2017-05-26 至 2026-09-24，使用相同捕获的成交额历史，原生 Sub-A 策略及正式成交额 overlay 的 **2189 行、全部列逐值完全一致**。这是隔离回归验证，不是当前完整组合收益验收。
- 361 项顶层赋值完全不变；语法检查和 `git diff --check` 通过。

测试命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -B -m pytest -q -p no:cacheprovider tests/test_v80_reporting_repairs_20261015.py tests/test_v80_cn_repair_20261023.py tests/test_v80_review_cn_20261023.py tests/test_v80_l1_input_boundaries.py tests/test_v80_verified_data_repairs.py
python -B outputs/v80_amount_query_fix_20261026/verify_real_amount.py
# 使用已捕获的数据离线复核，避免重复联网：
python -B outputs/v80_amount_query_fix_20261026/verify_real_amount.py --captured
```

真实来源捕获、校验结果、冻结回归脚本保存在 `outputs/v80_amount_query_fix_20261026/`。复现脚本会重新联网获取成交额，之后在同一份捕获数据上进行前后比较。

兼容性补修后的脚本 SHA256：`6403d344e77d5781e4257611f4739c974601420d99bf79e751859ceeaa1a8161`。

远端交付按现有 Poe pruner 规范化格式，规范化前后语法树完全相同。最终发布脚本 SHA256（LF 统一换行）：`bf64b334274a37b2b2b735ca78da8c5e16fb52aeeec2d2ece1a8c7056ef4d76b`。

回退文件：`.codex_backups/20261026_163040/mnt_bot V 8.0 plus.py`；SHA256：`726e201c4ef7a8480296c9bc7813819d3a6e5e9e2ce3aaccca5f65232b23a44c`。备份同时包含修改前的报告测试文件。

## Poe 加载兼容性补修

用户回传的堆栈确认：上一版新增的 `class SubaVolumeDataError(poe.BotError)` 在定义异常类时访问 Poe 仅运行阶段可用的 `BotError`，导致脚本在查询前加载失败。这是本次修改引入的错误，本地 SDK 常规导入测试未覆盖 Poe 的该限制。

已将该类改为继承 Python 内置 `RuntimeError`，其自身仍由查询入口识别并显示完整成交额错误，不再需要在加载阶段读取 `poe.BotError`。原有日期修复、缺数据阻断和策略参数保持不变。

用明确拒绝 `BotError` 的 Poe 模拟接口执行整份脚本：修前出现与用户一致的 `AttributeError`，修后加载通过；新增完整接口/兼容代理两种情形测试，并验证该异常仍能送达用户提示。此为本地模拟验证，不能替代线上 Poe 验收。证据：`outputs/v80_amount_query_fix_20261026/bootstrap_reproduction.json`；测试日志：同目录 `pytest_bootstrap.txt`。

本次补修前的备份位于 `.codex_backups/20261026_164214/`，包含上一版脚本、测试和本文；该脚本仍含已确认的启动错误，恢复时应注意。完整原始版本回退点仍为上文的 `20261026_163040`。

## 远端交付与复现

提交源脚本、回归测试、本文，以及 [离线证据包](../research/data_quality/20261026_amount_query/README.md)。证据包含来源金额、从完整冻结输入中精确提取的 Sub-A 价格、文件哈希和独立复核入口；不依赖本机 `.codex_backups` 或完整组合 pickle。

```powershell
python -B research/data_quality/20261026_amount_query/verify_offline.py
```

本机原始输出与回退备份保留。发布规范化前的完整状态备份为 `.codex_backups/20261026_165111/`。工作区清理仅处理可再生成的测试/字节码缓存，保留研究产物和行情缓存。远端提交与推送不等于 Poe 部署。

同步时只更新共享数据服务 `combo_v80` 的正式入口和 README 版本哈希；该项目字段合同、来源质量门与其他项目登记不变。另将 `test_cn_source_audit.py` 的 JSON 读取明确为 UTF-8，解决 Windows 默认编码下收集及报告读取失败；完整测试运行使用 `PYTHONUTF8=1`。

共享日历按整份 V8.0 源码锁定版本。已逐项核对其抽取的 5 个纯函数和 2 项赋值与基线 AST 完全一致，再更新该版本哈希；完整源码校验门保留。证据包的 `calendar_scope_review.json` 记录所核对符号及前后哈希。

最终全库测试：**1079 passed，12 subtests passed，0 failed，0 skipped**，耗时 525.01 秒；110 条库弃用/性能警告不影响通过状态。命令为 `PYTHONUTF8=1`、`PYTHONDONTWRITEBYTECODE=1` 下执行 `python -B -m pytest tests -q -x -p no:cacheprovider`。完整日志和汇总分别保存在证据包的 `pytest_full.txt`、`validation_summary.json`；Poe pruner、Python 3.11 语法、离线真实输入回归及暂存差异检查均通过。

缓存删除被平台以 `blocked by policy` 拒绝，未改用其他命令重试。`.pytest_cache` 及 `归档/策略A延后入场回测_2026-04-17/__pycache__` 保留，需由用户在 Windows 文件资源管理器中检查并清理。这两项目录未跟踪，不影响 Git 工作树同步核验；不得把磁盘缓存清理写成已完成。
