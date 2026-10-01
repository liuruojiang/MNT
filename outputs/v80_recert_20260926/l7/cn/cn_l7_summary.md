# L7 CN 子策略运行链独立审计（2026-09-30）

## 结论

- **Sub-A / Sub-A-DK 本地纸面计算及展示路由：PASS（限定范围）**。最终 `mnt_bot V 8.0 plus.py` SHA-256 `06b69d328b41416f7aaf350371a17b5839deb0339e06ad57af09fb77ecbed3b4`；L1 冻结输入 SHA-256 `182a5c54d5c81699d8e93038695a76febd15312aa48b5864e47a46318eeba00f`。真实/代理混合行情，未核经纪商实际成交。
- 本层发现并由主审修复两处运行链问题：正式单一 A 的调仓流水误走旧双腿 extractor 而全空；同一 bot 实例跨 `run()` 调用会复用旧行情。修复后下述复验通过。未改正式参数、回报公式、成本或生产部署。

## 实测证据

1. [a_adk_chain_audit.json](a_adk_chain_audit.json)：当前正式源在冻结输入上 A 2189 日、ADK 2783 日，对 L2 的日收益、NAV、holding、ADK pair/多空腿均零差；2020-03-18、2024-01-12、2026-09-24 三个截点重新由完整前史建链，重叠日期收益/NAV/holding 零差。全部十配对有实际入选日；A 六资产有实际持有日。四种 A/ADK 总览 `signal/live_signal/params/live_params` 的最终目标一致，参数页披露 A 的 R²门槛、ADK 全十对 Top-1 和 score-hot，ADK R²明确只供诊断。
2. [a_rebalance_probe.json](a_rebalance_probe.json)：修复后正式 A 的流水 786 条，对应 `trade_cost>1e-12` 的 786 日，漏报/零费记录均为零。最近 60 天 14 条。首次交易 2017-09-25 15:00 北京时间，Cash→10Y 国债。旧双腿 attrs 的路由构造样本仍按原阈值产生 598 条；这是分支回归检验，不是完整旧版重跑。
3. [adk_rebalance_probe.json](adk_rebalance_probe.json)：ADK 展示流水 518 条，其中 481 个多空方向/配对切换、37 个显著缩放；配对切换记录均归于前一个收盘信号日，无遗漏/额外日期，无非 15:00 北京时间记录。冻结 L2 帧用于此单项事件核对；附件探针直接重跑最终 ADK 源，数量同为 518。
4. [excel_attachment_probe.json](excel_attachment_probe.json)：最终源码在内存中生成并重新读取 XLSX 字节。信号附件最近 60 天有 A 14 + ADK 5 条；绩效附件全历史有 A 786 + ADK 518 条。该探针只核附件序列化，绩效指标单元刻意为 N/A；完整绩效沿用 L2 正式产物。没有访问 Poe 或上传附件。
5. [cache_lifecycle_probe.json](cache_lifecycle_probe.json)：同一实例请求内缓存复用；两次 `run()` 分别读到变化后的第 3、第 4 版行情，证明 `run()` 起始清空 `_request_data_cache`，源码同时清空 `_request_strategy_cache`。Poe 部署是否复用实例及已部署哈希无本地回执。

## 限制与复现

- 上述 prefix 测试是“完整历史截至某日重建”的确定性恢复；仓库没有独立的逐条增量持久化引擎，因此批量对独立增量存储的同值性 **N/A**。
- A/ADK 同日收盘纸面模型、A/ADK 实体账户缺口及上市前代理等继承 L1/L2 限制。查询总览与 Excel helper 在本地运行；Poe 真实接口交付/附件上传 **未认证**。
- 从仓库根目录执行：`python -X utf8 outputs/v80_recert_20260926/l7/cn/a_adk_chain_audit.py`、`a_rebalance_probe.py`、`adk_rebalance_probe.py`、`excel_attachment_probe.py`、`cache_lifecycle_probe.py`（同目录）。
