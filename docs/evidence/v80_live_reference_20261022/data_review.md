# V8.0 今日模型参考：数据边界独立对抗复审

## 结论与身份

最终源码 SHA256：`c90184824bf3dae06d11c2f4afa532ba0f8f3a2cca04243b63df23ee08643f3b`。

审计代理 audit_test_adversary 独立设计测试与判读标准；因其执行通道失效，由主代理使用同一 Python 3.14 解释器直接 execFile 代跑，并交回原始输出、XML 与观察矩阵，由审计代理独立复审。没有将代跑表述为审计代理亲自执行。

**本专项复审 PASS。** 初次最终复验：56 项独立脚本 + 30 项保留反例，86 passed / 0 failed，13 warnings，13.01 秒。随后把原始坏价格反例及未持有资产全空正控制保留进正式 tests：56 + 44 = **100 passed / 0 failed**，20 warnings，13.57 秒，exit 0。100 项包含原有覆盖，不能与 86 项相加，也不能混用耗时。

主代理的全仓库回归另列于总报告；本专项结论不替代全量结果。

## 已确认发现及复验

| 发现 | 影响与证据 | 修复及最终状态 |
| --- | --- | --- |
| 参考 helper 未验证有限正价及连续性（P2） | Round2 两版各 6 类输入：最新 NaN/Inf/0/负价、近期 NaN/Inf；均返回有限权重并出表。独立脚本原为 44 passed / 12 failed | BTC 开始日过滤后验证数值、有限正价及首个有效值后的连续性；原 12 个断言通过，另保留进正式 tests |
| 防守期间底层仍持有资产，整列价格丢失被当作未可用成员（P2） | Round3 保留 30 项中 26 passed / 4 failed：仅 model_w_、仅 official_actual_w_ 正持有的两版本反例均未拒绝全空价格；仅 ema_actual_w_ 持有时已能拒绝 | 最终同一 30 项全通过；隔离各个持有来源，避免另一正持有字段掩盖遗漏 |
| VolReg 缺失或错类型状态被 bool/default 静默解释（P3） | ratio=1.60 时 missing_state 被当 False，NaN 状态和字符串“False”被当 True，Inf 比率未被拒绝 | enabled 时要求 bool/np.bool_ 状态及比率列存在；缺列、错类型、Inf、负比率输出参考不可用；显式 NaN 比率继续继承已知状态 |

定位为 `_v80_subb_model_reference_weights` 的价格验证、全空池成员判断及末尾 VolReg 分支。异常由 `_write_v80_subb_model_reference` 明确显示“今日模型参考不可用”，不复制当前持仓伪装成参考。

## 正常行为和反证

- 允许 ETF 可用历史前的领先 NaN；未持有且尚不可用的 DBMF 全空列继续由原生排序排除。
- BTC 参与开始日之前的值先按各版本规则过滤；保留测试从正式 START 派生边界。
- 数值转换仅作用于私有 prices 副本。原始 DataFrame、嵌套 attrs 与账户结果不被污染。
- 同一对象、同一末日期内修改收盘/开盘内容，会改变各自策略缓存指纹；本项不认证供应商实时刷新频率。
- 最新价格扰动能进入两版参考。未来价格行、分腿尾日期错配和重复日期均被拒绝。
- 缺失/非法 EMA 实际分腿状态被拒绝。独立 56 项仅把该字段合同从 ema_w_ 更新为 ema_actual_w_，价格与日期拒绝断言未改弱。
- 显式 NaN 比率分别在已知 False/True 状态下保留原生滞回继承行为。

## 可达性和限制

这些确认问题限定于新增模型参考的输入/结果合同。末端正式价格新鲜度门的正负控制显示：它拒绝最新 NaN，却接受 Inf、0、负价；这只能说明该单一门不承担完整数值验证，不能证明损坏供应商响应穿过完整 fetch → strategy → handler。

VolReg 破坏字段同样未被证明会由正常 native 输出产生。本审计未将故障注入外推为线上错误交易、账户净值错误或策略收益。EMA 决策前状态的时点口径由独立数学审计的原生回放负责，不能用旧 Friday/Thursday 猜测替代。

未进行 Poe 发布或真实成交审计。全部行情及调整后开盘为合成诊断输入，无绩效结论。全样本、10Y、5Y、3Y、1Y 年化收益及最大回撤均 N/A：本次为软件正确性测试，不是策略历史测试。

## 复现与证据

独立脚本已核实保存于 `round4/test_adversary/test_data_boundaries.py`。保留测试为 `tests/test_v80_reference_data_boundaries_20261022.py`。通过 V80_AUDIT_SOURCE 指向最终冻结源码，主代理代跑的精确 argv/cwd、退出码保存在各运行目录的 process.json/run_manifest.json。

以下路径相对于 `outputs/v80_live_reference_adversarial_audit_20261021/`：

- 修前 12 个坏价失败：round2/test_adversary/pytest_first.log、XML、observations.json。
- 修前 4 个底层持有全空失败：round3/test_adversary/retained_before/stdout.log、result.xml。
- 86 项复验：round4/test_adversary/final_run/stdout.log、stderr.log、process.json、result.xml；原观察矩阵另存 observations_86.json。
- **100 项最终复验**：round4/test_adversary/retained_expanded/stdout.log、stderr.log、process.json、result.xml；最终观察矩阵为 round4/test_adversary/observations.json。

审计代理已对 100 项最终原始结果给出限定范围 PASS。旧轮次的失败证据保留。
