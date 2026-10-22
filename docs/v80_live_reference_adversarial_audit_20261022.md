# V8.0 实时信号显示修复：多智能体对抗审计

审计日期：2026-10-22。结论：**本地修复与三路对抗复审完成；完整回归 681 passed，0 failed，0 errors。尚未更新 Poe。**

## 用户看到“仓位没有变化”的原因

旧表在非周度日显示的是 `execution_target_w_*`，但标题写作“参考目标（不执行）”。没有周度事件、也没有 VolReg 切换时，下一执行目标按规则等于当前持仓。这个结果不能说明按今日价格计算的模型参考也没有变化。

此前只读核对的 [Poe 历史回复](https://poe.com/chat/adao4o1jpikhmku3w4) 属于 2026-10-21 周三。B7.9 当前/旧参考均为 PDBC 59.7%、QQQM 14.4%、EMXC 14.0%、IBIT 11.9%；该快照两版 VolReg 比率为 0.74，未触发 >1.80 的进入防守线。该现场没有理由产生新的执行目标；旧表却没有提供独立的今日模型参考。

本地修复保留“下一执行目标（非周度日）”，另加“今日模型参考｜假设今天是周度信号日”，分别显示 B7.8/B7.9 的当前已生效、模型参考、参考差额、价格日期及盘中/收盘状态。四个查询入口共用此实现。参考不生成指令、不写入 Excel 执行目标。

## 被审计的准确版本

| 对象 | SHA256 |
| --- | --- |
| 本次最终源码及冻结副本 round4/candidate.py | `c90184824bf3dae06d11c2f4afa532ba0f8f3a2cca04243b63df23ee08643f3b` |
| 传入工作区基线 baseline.py | `cd5c9592ba7da0b2ab68b7b30f59219955996a23296fc834f917aca5b5bb14a7` |

正式脚本：`D:\动量策略\A股美股动量组合策略\mnt_bot V 8.0 plus.py`。Git 中的根目录正式脚本是交付版本；本地冻结副本保存在 outputs/v80_live_reference_adversarial_audit_20261021/round4/candidate.py（未纳入 Git）。

比较基线是传入工作区版本，保留其中已经存在的报表截止日修复及相关测试，未把它们算作本轮新增变更。原有 593 个定义与全部其他顶层语句保持一致；仅两个原展示定义修改，新增两个参考计算/显示函数。原生策略参数、模型、执行、成本、收益计算均未改动。

## 对抗发现、修复与更正

| 发现 | 独立证据 | 最终处理 |
| --- | --- | --- |
| EMA Buffer 重算读取当日 target，而非决策前实际分腿持仓 | 原生完整链的周四边界：实际 DBC=0.05711775 >0.001，新 target=0.00025756 <0.001；中间候选的四腿参考与原生目标相差约 0.2185 个百分点 | 读取本行 ema_actual_w_*，严格保留原生 >0.001 门槛；最终同一反例差异为 0 |
| 异常价格被评分逻辑忽略后仍出正常参考表 | 两版各 6 类坏价格共 12 项修前失败：最新 NaN/Inf/0/负价、近期 NaN/Inf | 在私有价格副本验证有限正价及首个有效值后的连续性，异常明确显示参考不可用；12 项原断言通过并进入正式 tests |
| 防守后账户为现金时，底层仍持有资产的全空报价未被识别 | 只保留 model_w_ 或 official_actual_w_ 正持仓的两版反例共 4 项修前失败 | 同时检查账户、底层模型及实际分腿持有信息；原反例全部通过 |
| VolReg 破坏字段被默认值/bool 静默解释 | 缺状态、NaN 状态、字符串“False”、缺比率、Inf 比率注入 | 仅参考 helper 增加字段/类型检查；明确 NaN 比率仍继承已知状态，不改原生政策 |

周四数学反例的 `subb_pending_model_rebalance=True`，概览通常不会显示额外假设参考表。因此该项是重算合同缺口，不能宣称已经造成线上错误调仓。坏价格、全空报价、VolReg 字段破坏也只在参考合同边界被复现，未证明真实供应商响应能穿过整条正式取数链触发它们。

**撤回早期“周五读取上一行必然拿到旧持仓”的推断。** 原生 `ema_w_*` 存的是目标，`ema_actual_w_*` 才是实际持仓；周四行的目标已包含周四新决定。早期手工探针混淆字段含义，不能作为生产缺陷证据。独立真实价格回放中，旧 helper 的正常周五结果与原生目标一致。最终修复采用正确字段语义及真实周四反例，不保留错误归因。

## 独立验证结果

| 验证路线 | 执行与判读 | 最终结果 |
| --- | --- | --- |
| 原生数学对照 | audit_model_math 独立运行；预期来自传入基线的原生模型 | 18 组完整链比较、6 组阈值探针、另一个周四完整链回归均通过；所有目标最大差异 0 |
| 查询和执行边界 | audit_query_execution 独立脚本；最终由主代理代跑并交回原始结果供独立判读 | 50 passed / 0 failed |
| 数据及诊断边界 | audit_test_adversary 独立设计；主代理代跑、代理独立复审 | 56 项独立 + 44 项正式保留反例 = 100 passed / 0 failed，13.57 秒 |
| 全仓库回归 | 主代理运行 tests/，包含新增正式回归 | **681 passed，66 warnings，162.07 秒，exit 0** |
| 编译与变更检查 | Python 编译、git diff --check、基线 AST 核对 | 通过；最终源码运行前后 SHA256 一致 |

上述组存在覆盖重叠，不能相加作为独立测试总数。此前 667 项全量和 86 项数据专项的记录保留；最终计数分别为 681 和 100。

数学覆盖两版独立池、Top-N/Buffer、周三/周四/周五/周一、392/540 行、VolReg 进入与恢复、BTC 上限、宏观池差异。查询覆盖实际 run 分发、请求缓存、四处理器、_compute_signal_data、概览、B 历史及 XLSX；包括周度盘中/确认、假期提前确认、参考失败仍保留有效风险指令、同一 bot 连续请求的价格刷新。

账户 DataFrame、嵌套 attrs、执行目标、收益及费用未受参考查询污染。领先 NaN、BTC 参与开始日前过滤、未持有且尚不可用资产的原生排除行为得到保留；这些不是基金上市资格认证。

## 证据、复现与边界

随本次 Git 提交保存的精简证据见 [远端审计证据](evidence/v80_live_reference_20261022/README.md)，包含三份独立报告、机器结果和最终测试日志。下列完整原始证据保留在本地。

统一本地证据根目录：`outputs/v80_live_reference_adversarial_audit_20261021/`。

- 数学：round4/model_math/final_round4.json、final_round4_extra_pools.json、probe_thursday_final_round4.json 及对应脚本/日志。
- 查询：round4/query_execution/results.json、各场景文本、run/stdout.log、stderr.log、process.json。
- 数据：round4/test_adversary/retained_expanded/ 的 stdout、stderr、process.json、result.xml；观察矩阵为同层上级 observations.json。
- 最终全量：round4/main/full_expanded/stdout.log、stderr.log、result.xml、identity.json、process.json。
- 代码范围及编译：round4/main/scope_verification.json、verification/ 的日志。
- 修前失败保留于 round2/test_adversary/ 及 round3/test_adversary/retained_before/；未通过删除原断言获得通过。

精确执行 argv/cwd 保存在相应 process.json/run_manifest.json。最终原生脚本与测试使用 Python 3.14；因中途普通执行通道登录故障，主代理改用同机直接 execFile 完成代跑。旧全量曾有 3 个 pytest 默认临时目录权限错误，最终使用仓库 outputs 内新的 basetemp 后全部通过；未更改系统权限。

正式保留回归：

- tests/test_v80_live_model_reference_20261021.py
- tests/test_v80_reference_native_state_20261022.py
- tests/test_v80_reference_data_boundaries_20261022.py
- tests/test_v78_cn_live_freshness.py 中非周度显示断言同步更新，原执行隔离断言保留。

这是软件正确性审计。行情和调整后开盘为合成数据；未认证供应商实时报价、真实账户、实际成交、真实 US/crypto 原始日历或 ETF 上市历史。全样本、10Y、5Y、3Y、1Y 年化收益和最大回撤均 **N/A：没有开展策略历史绩效测试或候选晋升**。

## 交付状态

修改已保存于本地正式脚本及上述最终副本，**本次同步 GitHub 的范围为源码、测试、报告和精简证据；未发布到 Poe**。在线历史回复不会因本地修复而更新。只有 Poe 服务载入这份最终源码后，新查询才会显示新增模型参考；目前不能宣称线上修复验收完成。
