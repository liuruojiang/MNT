# V8.0 模型参考：独立数学复审最终报告

结论：**PASS，限于本次模型参考计算修复的审计范围，无剩余未闭合发现。**

最终源码：round4/candidate.py，SHA256 `c90184824bf3dae06d11c2f4afa532ba0f8f3a2cca04243b63df23ee08643f3b`。

独立原生预期使用传入基线 baseline.py，SHA256 `cd5c9592ba7da0b2ab68b7b30f59219955996a23296fc834f917aca5b5bb14a7`。

audit_model_math 独立编写并启动三条最终审计进程，退出码均为 0。最终 JSON 因读取通道中断，由主代理逐文件代读并交回原始字段；审计代理据脚本断言、退出状态及原始数据独立判读。没有把代读表述为审计代理成功直接打开了全部最终文件。

## 最终结果

- **18 组原生完整链比较通过。** 两版分别覆盖周三、周四、周五、周一，392/540 行历史、VolReg 进入与恢复、BTC 上限及宏观资产池。逐资产最大目标绝对差均为 **0**，有效合成输入下新旧原生账户 DataFrame 保持一致。
- **6 组门槛检查通过。** 两版分别检查 0.000999、0.001、0.001001，严格保持原生 >0.001。在位者规则与 B7.8 Top3／1.05 Buffer、B7.9 Top2／1.00 Buffer 保持独立。
- **周四完整链反例闭合。** 决策前实际 DBC=0.05711775162257459，新目标 DBC=0.0002575615460577185，跨越门槛。round2 读取本日目标后重算，曾有约 0.2185 个百分点的混合目标偏差；最终读取本行 ema_actual_w_* 后，与原生目标差为 **0**。该问题受周度日参考表门控限制，未证实曾导致线上错误调仓。
- **BTC／资产池分离通过。** BTC 场景 B7.8=30%，B7.9 约 27.58%；宏观场景 B7.8 持有 UUP，B7.9 UUP=0。各自与独立原生预期完全一致。

## 撤回早期 Friday 推断

原生 ema_w_* 保存的是目标，周四行已经包含周四新目标；ema_actual_w_* 才表示实际分腿持仓。真实合成价格触发周四切换、周五执行后，原始 helper 在该周五场景也与原生目标一致。

因此撤回“周五读取上一行必然取得旧组合”的推断，不把早期手工状态探针当作生产缺陷证据。最终修改有正确字段语义和真实周四价格反例支撑，未改变原生模型。

## 复现与证据

以下文件位于本目录：

- audit_math.py、final_math.log、final_round4.json：14 组完整链、6 组门槛，assertion_failures 为空，status=PASS。
- extra_pools.py、final_extra_pools.log、final_round4_extra_pools.json：4 组 BTC／宏观池比较，difference 全部 0，status=PASS。
- probe_thursday.py、final_thursday.log、probe_thursday_final_round4.json：周四反例最终 target_state_difference 与 actual_state_difference 均为 0。

绑定 V80_AUDIT_SOURCE、V80_AUDIT_EXPECTED_SHA256 及 V80_AUDIT_RUN_LABEL=final_round4 可按对应脚本复现。旧轮次反例证据保留在 round2/model_math/，不覆盖。

## 限制

使用合成价格和合成调整后开盘验证计算合同，不认证真实行情、ETF 上市边界、线上 Poe、真实账户或实盘执行。全样本、10Y、5Y、3Y、1Y 年化收益和最大回撤均 N/A：本次没有进行策略绩效测试或候选晋升。
