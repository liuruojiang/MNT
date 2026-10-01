# V8.0 ADK 第六层参数依据扫描

## 本层结论

**保留现行正式参数；该结论只针对冻结真实指数价格上的现有纸面模型。** 十个配对在每个候选臂都至少有一次实际多空持有；MA60/20 的四个邻近排名候选均未优于正式值。score-hot 70/35 在本次全样本及各追踪窗口改善年化且回撤未恶化，但缺独立验证，不能据此晋级。A/ADK 的连续证券数量账、同收盘成交与借券可用性仍未获认证。

## Run Metadata

- Run id: `20260930_l6_adk`；运行时间：2026-09-30T19:53:57.608756+08:00（北京时区）。
- Repo: `D:\动量策略\A股美股动量组合策略`；入口：`mnt_bot V 8.0 plus.py::run_v80_adk_new_only`，原文件 SHA-256 `b2ce48847b14f78f6790ddde824e16980e40f0c5db059274a8dfee771bb32d22`。
- Git branch/commit: `main` / `a7353eebc17c94e0d3566404d72fb395776fc54f`；启动前工作树含既有修改，详见 `scan_meta.json`。
- Scan type: single_parameter_with_module_off；decision: keep_default；stability_label: data_sensitive；source-change rule: `research_only_no_source_change`。

## Research Question

逐组复测正式 Top-1 的排名 MA/动量、score-hot、目标波动/窗口/杠杆和缩放 deadband。比较关停、正式值与紧邻候选在相同真实数据、同一费用与五个完整窗口的纸面风险收益、交易费用及十配对覆盖。不会因一个指标变好自动更换正式值；若现行价格/执行规则或数据源改变则须重跑。

## Implementation Anchor
**正式值单独核点：**公共窗 20 次热度进入和 20 次恢复，360 天零风险敞口，518 个正换手交易日，多空名义额各至 1.5x（毛名义 3.0x）；模型收益/费用可核，资金与借券不可据此视为已落实。

## Stability Classification

- `data_sensitive`：本组不是独立留出/步进验证；价格指数替代可交易证券、同收盘成交与借券成本均未获认证，L5 已证明 ADK 连续证券数量账与纸面日收益不一致。
- 排名 MA60/20 在四个局部候选上有优势。score-hot 70/35 只有一个改善点，90/45、0.25 乘数均反向；其局部形状为 `peak_only`，不据此挑参数。风险规模/窗口/deadband 各有收益回撤或近期窗口取舍。

## Decision

**keep_default**：完成 ADK 纸面参数依据层的受控扫描，保留正式参数。若要把 70/35 或其他候选列为晋级候选，先预设目标并在独立日期、真实可交易多空证券及自融资账户中检验，再按项目决策链审批；本次未改生产源码或实际交易。

## User-Facing Summary

ADK 十个配对在每个参数臂都被测到。正式 MA60/20 比这次四个邻域候选更稳；70/35 热度阈值虽在同一历史样本略好，尚不具备可执行及样本外证据。第六层完成前，须将本组与其他子策略各分腿结果合并审计。
