# V7.9 外部评审修复设计

## 目标

审核外部专家对 `mnt_bot V 7.9 plus.py` 的意见，只修复能够由当前代码路径证明的问题；统一 Sub-A、ADK 与 Sub-B 的仓位、目标、调仓记录和展示语义，同时避免把死代码清理或性能重构混入正确性修复。

## 审查结论与范围

### 本轮修复

1. Sub-A 成交额风控不可判定时，V7.7A 与 NewA 两条腿都跳过 overlay，并保留相同的 unavailable/unresolved 标记。
2. SPY 成交量 gate 使用可持久化历史缓存与备用数据源。网络失败时，已缓存历史仍按真实数据计算；失败策略只作用于缓存未覆盖的尾部日期，避免整段历史净值受当次网络状态影响。
3. Bias 与 LogVol 分数要求全部配置窗口有效，缺失窗口不再按零分参与排名。
4. Sub-A 混合结果明确区分：
   - `final_exposure` / `weight`：该交易日实际持有、用于当日收益的敞口；
   - `target_exposure`：该日收盘确认、下一持有期使用的目标敞口。
   显示、Excel 和 `is_signal` 均基于这套统一语义，不再依赖局部 `pos-1` 补偿。
5. Sub-B 同日发生 VolReg 切换和模型调仓时，VolReg 记录与模型调仓记录分别保留。模型记录比较 `model_target_w_*`，不把 VolReg 后的有效权重误当模型目标。
6. ADK 明确区分“当日已持有状态”和“当日收盘新目标”。历史调仓记录继续按真实执行日记载，信号页面不再把前一收盘已执行的持仓变化重复标成今日新指令。
7. 删除未接入生产查询链路的微盘 `883418.TI` 直接口径宣传，仅保留实际显示的宽口径参考规则。
8. `_stitch_cn_proxy_returns` 在官方 base 比 proxy 更新时保留较新的官方数据，只从最后有效重叠锚点向后补齐 proxy 独有尾部。
9. Sub-A 杠杆变化记录按状态机真实的收盘成交口径标记，不再写成 09:30 开盘执行。
10. A 股当日补价以维护中的交易日历和实时快照有效性判断是否应补行；平盘不再被当作休市。
11. 创业板成交额优先使用真实 amount 数据源，volume proxy 只作兜底且继续显式标注来源。
12. 统一修正乖离动量同类函数的首个可计算位置，最长窗口不足时保持 NaN；该修订只影响 warm-up 边界，不改变正式样本起点约束。
13. 无年份跨年日期区间将开始日期归到上一年、结束日期保留当前年；普通未来区间仍整体解释为上一年。
14. ADK 综合结果不再伪造单一 VolScale。实时参数按 V7.7 ADK 与 New ADK 两条腿分别展示已实现波动率、原始/阈值后 scale、overlay 与最终腿内敞口，综合层只展示加权净敞口。
15. 对容易受短路逻辑影响的 pending 标记先统一初始化为 `False`。
16. CSIndex 重试中的临时 `requests.Session` 使用上下文管理器，确保每次尝试关闭连接。
17. `v78_score_overheat_cost` 改名为 `v78_score_overheat_cost_indicative`，明确最终成本由 effective leg turnover 重建结果提供。

### 本轮不改

- 严格 T+1 adjusted-open 执行政策不放宽。当前 `_us_open_row` 已报告具体缺失日期和资产；全历史预检与按查询袖套惰性计算属于运维架构增强，单独处理。
- 不提前编造 2027 年 A 股休市日。保留超出已维护年份的显式 warning，待官方日历发布后更新常量。
- 不删除第三部分列出的死代码，也不进行第四部分的向量化或缓存性能重构。
- 不改变策略池、参数、费用、上市日起点或正式样本窗口。

## 数据流与字段语义

### Sub-A 成交额风控

`_load_suba_volume_signal` 产出 signal 与 feature。两条腿分别通过同一 unresolved 判定：正式查询抛出 `poe.BotError`；允许降级的信号查询保持原仓位并写入 unavailable/unresolved 字段。只有 feature 完整可判定时才应用 overlay。

### Sub-A 双腿混合

V7.7A 的行内 `weight` 是该行收盘后的目标状态，因此当日持有敞口使用其前一行；NewA 的 `weight` 已是当日持有状态，`target_weight` 是收盘目标。混合层先把两条腿标准化为 `holding_*` 与 `target_*` 两套字段，再分别计算实际敞口和目标敞口。收益序列保持 component-net 混合，不重算 NAV。

### Sub-B SPY 成交量

优先抓取 Yahoo SPY volume，并把有效历史合并写入仓库旁的专用缓存。Yahoo 失败时尝试 Stooq volume，再读取缓存。gate 对有真实 volume 的日期正常计算；仅对仍无数据的日期使用 `warn_open`、`fail_closed` 或 `raise`。缓存写入失败不得覆盖已经抓取到的内存数据，但要在 source 文案中体现降级。

### ADK 与 Sub-B 调仓记录

ADK 结果行表示当日收益期间的已持有头寸，来源是前一交易日收盘信号。历史记录使用执行日，而信号页面使用每条组件腿的实时未 shift 排名构建收盘目标。

Sub-B 模型调仓记录使用 `model_target_w_*`；VolReg 记录继续使用 `effective_w_*`。同一天两类事件可以同时出现，互不吞掉。

## 错误处理

- 正式绩效路径遇到 Sub-A 成交额不可判定仍中止，避免以降级结果生成正式净值。
- SPY volume 缓存与备用源均不可用时，仅未覆盖日期服从配置的失败模式；已有历史不得被常量 gate 覆盖。
- 缓存文件格式不合法时视为不可用，不静默伪造 volume。
- 日期拼接、补价和 session 关闭修复不得吞掉原有 schema 或 HTTP 异常语义。

## 测试设计

每个生产改动先增加能够在当前版本失败的回归测试，再实施最小修复：

- unresolved feature 不得改变 NewA `target_weight`；完整 feature 仍正常应用。
- SPY 抓取失败但缓存完整时，历史 gate 与成功抓取一致；缓存只覆盖部分日期时，失败模式只作用于缺口尾部。
- Bias/LogVol 在最长窗口满足前保持 NaN，满足后才产生分数。
- Sub-A 实际敞口、目标敞口、`weight`、`is_signal` 在换仓日具备一致语义，NAV 与 component returns 不变。
- VolReg 切换与模型调仓同日时，两种记录都存在，且模型记录读取 pre-VolReg 目标。
- ADK 信号页面和辅助状态不把已执行持仓变化当成当日新目标。
- 官方 base 晚于 proxy、平盘交易日、创业板 source 顺序、跨年日期、首个可计算位置、pending 初始化、Session 关闭和 indicative 成本字段均有聚焦测试。
- ADK live params 不出现伪造的综合 VolScale，并展示分腿 scale 信息。

完成后运行 V7.9 相关 pytest 文件、完整 `tests/`、`python -m py_compile "mnt_bot V 7.9 plus.py"` 与 `git diff --check`。涉及数据抓取的测试使用确定性本地 DataFrame 和受控 fake session，不依赖实时网络结果。

## 回滚

修改前使用 quant-research 提供的 `backup_paths.py` 备份 `mnt_bot V 7.9 plus.py` 和将修改的测试文件。若验证失败，可从生成的 `.codex_backups` 目录恢复；Git 历史同时保留设计文档与后续实现差异。
