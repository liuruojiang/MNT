# V8.0 L8 最终组合条件复测记录

## Run Metadata

- Run id: `20260930_v80_l8_final_combo`; created 2026-09-30 22:24:51 CST.
- Project: `D:\动量策略\A股美股动量组合策略`; strategy: V8.0; branch `main`, commit `a7353eebc17c94e0d3566404d72fb395776fc54f` with preexisting uncommitted L0-L7 work.
- Entrypoint: `mnt_bot V 8.0 plus.py`, SHA-256 `06b69d328b41416f7aaf350371a17b5839deb0339e06ad57af09fb77ecbed3b4`.
- Scan type: L8 frozen-path artifact normalization of official, group-off, local-neighborhood and pair-interaction runs. **No source or production parameter change.**

## Research Question

把 L6 的已采用规则及邻域逐个放回正式五袖组合，其他四袖保持正式路径，检验经济表现、触发和资金边界是否发生抵消或反转。逐组必须先对 L2 正式基准逐日对齐；候选只供诊断，不因更高年化自动晋级。

## Implementation Anchor

- 正式组合函数：`_performance_combined_daily_returns`。A/ADK/B7.8/B7.9/C 的初始资本权重分别为 15/15/20/20/30%；每袖净值独立复利，再按**初始资本**加总。不是每日固定权重再平衡，也没有共享现金、保证金、借券或外汇账户。
- 候选单袖路径来自同一冻结输入上已验证的 L6 逐日正式入口扫描；L8 对若干关键交互另跑正式源码。独立组合审计在 `outputs/v80_recert_20260926/l8/cross/`；A/ADK、B/C 二次运行在对应 `cn/`、`us/`；主审独立正式复算在 `root/`。
- 194 个标签（189 个全开/单组路径，5 个跨袖配对），每个均保存 Full、10Y、5Y、3Y、1Y 五窗。多个标作 `same_formal_control` 的标签用于证明本窗无差异，不能当成互相独立的改进机会。

## Data Snapshot

- L1 冻结输入：`outputs/v80_recert_20260926/l1_final/formal_inputs.pkl`，SHA-256 `182a5c54d5c81699d8e93038695a76febd15312aa48b5864e47a46318eeba00f`；L2 正式逐日收益 SHA-256 `fbcf4c3abe297c792e732d356e7378b6e3bbfc33e87bb035bbf6f17ba7e15299`。
- 组合共同样本 2020-12-03 至 2026-09-25，1,509 个并集收益日。A/ADK 收盘止于 2026-09-24；9 月 25 日在纸面组合填 0。C 的 2024-01-12 前含 ETF/BTC 代理，B 的 BTC-USD 使用 UTC 日线代理；此冻结样本不是 9 月 30 日收盘后的刷新。
- 时间按各自 A 股/美股交易日历与正式 T/T+1 约定。跨市场缺日填零是**纸面持有净值**约定，不是经纪商估值或实际跨币种结算。
- 本轮只读冻结文件，不写市场缓存。工作树本来有未提交的分层报告和源码改动；详细状态留在 `scan_meta.json`。

## Cost and Execution Assumptions

- A 同日收盘目标、单边换手 10bp；ADK 多空腿同日收盘目标、每腿 5bp。两者有 L5 连续数量/资金账缺口。
- B T 收盘信号、下一美股交易日调整开盘执行，单边换手 10bp，独立证券数量、债务和费用账。正式融资为 `debt × (BIL 当日调整价收益 + 100bp/252)`，可能出现负融资成本；L8 另外做了零下限**诊断**，正式规则未变。
- C 年末基础组合收盘重配，股票/黄金缩放下一交易日调整开盘；十资产与 C 连续数量/重置费用缺口继承 L5。滑点、经纪商成交、借券可得性及共享账户均未认证。
- 后续同一冻结输入的源码核查还确认 C 缩放层借款代理为 BIL 日价格收益+100bp/252，稳定缩放日有 105 个日期出现正借款对应负费率；仅做符号/逐日贡献探针，未做 C 完整零下限重跑。见 `outputs/v80_recert_20260926/l8/root/audit_c_financing_sign.json`。
- 成本数据单位分袖：A/ADK/C 为收益分数，B 为初始一单位账户货币额，不跨袖直接相加。

## Runtime Override Plan

- L8 主表来自 L6 同源码、同冻结数据的逐日候选路径，把其余四袖固定正式。关键两两交互由各代理另外运行或组合重算。无正式全局变量持久变更。
- 全开基准在主审和独立审计的组合逐日净收益最大误差 `0` / `4.44e-16`；候选正式臂与 L2 每袖逐日差在浮点误差内。基线失败则候选不得作为正式结果，本轮未触发该条件。
- 若正式源码、L1 输入、费用/成交时钟、组合权重或 L5 账户规则变化，必须重跑受影响结果。

## Commands

从仓库根目录运行：

```powershell
python -X utf8 outputs/v80_recert_20260926/l8/root/audit_formal_combined.py
python -X utf8 outputs/v80_recert_20260926/l8/cn/run_cn_l8.py
python -X utf8 outputs/v80_recert_20260926/l8/us/audit_us_combo.py
python -X utf8 outputs/v80_recert_20260926/l8/cross/audit_l8_cross.py
python -X utf8 outputs/v80_recert_20260926/l8/root/normalize_combo_scan.py
```

各代理的独立复算与负融资诊断命令见 `outputs/v80_recert_20260926/l8/{cn,us,cross}/record.md`；完整命令记录同时见本目录 `command_log.txt`。

## Output Files

- `scan_summary.csv`: 194 标签 × 五窗 = 970 行；净年化、日频 252 年化波动、零无风险利率 Sharpe、最大回撤。
- `window_metrics.csv`: 同 194 标签的五窗宽表。
- `scan_meta.json`: 源/输入哈希、候选网格、N/A 原因及口径；`command_log.txt`: 命令和验证记录。
- `outputs/v80_recert_20260926/l8/cross/one_group_daily_returns.csv.gz`、`pair_daily_returns.csv.gz`: 候选组合逐日净收益。各袖成本/事件/资源见 `cn/`、`us/` 表。

## Full-Sample Results

正式纸面组合年化 **23.3297%**、最大回撤 **−7.7768%**、期末净值 **3.383194**，峰/谷 2024-07-16→2024-08-05。A 的 R²窗口 15/30 日组合年化 **21.7378%/21.2802%**，最大回撤 **−8.6780%/−8.5920%**；ADK 动量 15/25 日 **22.2631%/22.8285%**，回撤 **−8.0552%/−8.5514%**。C 移除 VGIT 后组合年化 **23.9874%**，但回撤加深到 **−8.2344%**。这些均为同窗纸面结果，不是参数晋级依据。

## Window Results

正式组合 Full/5Y/3Y/1Y 年化分别为 **23.3297/22.8938/34.9316/22.7587%**，最大回撤分别为 **−7.7768/−7.7768/−7.7768/−7.6230%**。10Y 因 C 最早正式收益日 2020-12-03 而 **N/A**；全部 194 标签均有同一原因记录在 `scan_meta.json.unavailable_segments`。逐候选五窗和峰谷见 L8 机器表。

## Stability Classification

- A R²窗口和 ADK 排名动量窗口仍是双侧敏感点；组合层缓冲了幅度，但未消除排序风险。B/C 邻域存在收益与回撤取舍，不能以单一最高年化选参。
- A/ADK/C 的实体账户及统一资金账不闭合，故组合纸面计算可复算，**历史可执行净收益不可认证**。B 负融资成本新增经济假设缺口；零下限诊断对组合 Full 年化影响约 −0.0163 个百分点，不会自动更改正式模型。
- 本轮的局部邻域均为已暴露历史，独立未来样本不足。稳定性标签：`fragile_A_R2_ADK_momentum; executable_account_unverified`。

## Decision

- **keep_formal_research_only**：不晋级任何参数、不更改正式源码或生产；L8 的纸面条件复测可核算，严格可执行组合认证维持 FAIL。
- 后续若要解决历史准确性缺口，需要另行确定 A/ADK/C 数量、资金、借券/抵押与价格时钟，以及可验证的 B 融资利率来源；随后重跑受影响层。第八层是手册最后一层，此记录不触发自动交易或部署。

## User-Facing Summary

正式纸面组合、逐组关停/邻域及关键交互均在冻结输入下复现；参数敏感点和融资模型风险已显露。组合收益只可称纸面模型，不能据此宣称真实历史可执行收益已认证。

## Finalization

- Finalized at: 2026-09-30T22:56:24+08:00
- Decision: keep_formal_research_only
- Stability label: fragile_A_R2_ADK_momentum_executable_account_unverified
- Complete checker: PASS
