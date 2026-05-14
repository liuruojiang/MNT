# V7.6 Poe 固定组合权重展示清理同步记录

日期：2026-05-14

## 范围

- 目标文件：`poe_v76_level8_advisory_bot.py`
- 测试文件：
  - `tests/test_poe_v76_level8_status_summary.py`
  - `tests/test_v76_source_returns_freshness.py`
- 变更目的：移除 V7.6 Poe 端组合层动态仓位展示，避免 Poe 无法获取 Advisory 侧数据时呈现错误或无意义的动态权重。

## 当前 Poe 展示口径

Poe 端只展示固定组合权重：

| 策略 | 权重 |
|---|---:|
| Sub-A | 15% |
| Sub-A-DK | 15% |
| Microcap | 10% |
| Sub-D | 20% |
| Sub-B | 40% |

组合层可变预算、动态仓位、active budget 细节不再由 Poe 展示。如需查询，应直接去 Advisory 端。

## 实现摘要

- 新增 `FIXED_PORTFOLIO_SLEEVES`，作为 Poe 端唯一权重展示来源。
- `parse_snapshot_from_csv_texts(...)` 不再把远端 dashboard 的动态权重列映射到 Poe 输出。
- `render_level8_advisory(...)`、`render_status_summary(...)`、`render_weights(...)`、`render_governance(...)`、`render_rollback(...)` 移除动态仓位/active budget 展示文案。
- 补充回归测试，确保 Poe 查询输出不再包含动态仓位面板关键词，并锁定固定 15/15/10/20/40 口径。
- 补齐 `tests/test_v76_source_returns_freshness.py` 的 repo-root import 路径，使该测试可按单文件方式直接运行。

## 备份

编辑前文件系统备份：

`C:\Users\Administrator.DESKTOP-95I7VVU\Desktop\动量策略\A股美股动量组合策略\.codex_backups\20260514_172153`

## 验证

已执行：

```powershell
python tests\test_poe_v76_level8_status_summary.py -v
python tests\test_v76_source_returns_freshness.py -v
python tests\test_v76_advisory_action_summary.py -v
python -m py_compile 'poe_v76_level8_advisory_bot.py' 'tests\test_poe_v76_level8_status_summary.py' 'tests\test_v76_source_returns_freshness.py'
git diff --check -- poe_v76_level8_advisory_bot.py tests\test_poe_v76_level8_status_summary.py tests\test_v76_source_returns_freshness.py
```

结果：全部通过。`fastapi_poe` 在 freshness 测试中输出 Pydantic v2 弃用警告，属于依赖自身警告，非本次变更引入。
