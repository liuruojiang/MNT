# V8.0 发版检查对抗性审计

**当前结论**：六处漏检均已修复，原始故障注入逐项被拦截。交叉复审发现的全透明单日标记也已补测并修复。[六项反例验收](#修复后的六项反例验收) · [多智能体交叉复审](#多智能体交叉复审) · [最终发版入口回执](<D:/Codex/test-lifecycle/records/91bbe3573bb6463db97a91dac68c5bfb/stdout.log>)

审计对象为[调仓前后日检查](../tests/test_v80_release_rebalance_prefix.py)及[表现、Excel 与净值图检查](../tests/test_v80_release_report_parity.py)。三组分别检查了调仓记录、报表展示和发版入口。所有故障均在独立进程中临时注入。正式策略脚本的 SHA-256 为 `2e24c9447a3eba190851614c270d238e56ef3ad15bfbde77b3e53ff4bb791ed1`。

原样从发版入口重跑，5 项通过，15 条警告，用时 72.19 秒。独立读取未注入故障的 Excel 和两种命令导出的四张图，单日样本有六条序列，五日样本只有 ADK，数据点均在坐标轴内，图例与曲线标签一致。五日 ADK 累计收益为 2.56475%，最大回撤为 −0.09923%。[发版入口复跑](<D:/Codex/test-lifecycle/records/5b3b3402499d46b896e89fe4e5f0f454/stdout.log>) · [原始输出核对](<D:/Codex/test-lifecycle/records/50180b87358d4f78b61ce3fe366aba08/stdout.log>)

## 发布前应补强的检查

| 优先级 | 注入的错误与观察结果 | 建议的验收条件 |
|---|---|---|
| P1 | **追加下一交易日后，真实信号附件丢掉前日调仓仍通过。** 仅在加入 2025-11-17 行情后，让“信号”入口漏掉 11-14 的 B7.9 记录。信号 Excel 的前日记录从四条降到三条，表现附件正常，五个专项用例全部通过。当前测试直接用表现或提取器的记录生成一份信号 Excel，跳过了信号入口自己的筛选。回放冻结时钟，并替换了受 2025 年日历限制的成交额提示板，调仓模型、筛选和附件导出均使用正式路径。[回执](<D:/Codex/test-lifecycle/records/ac9b01b2ab6041fc930410c1571bee96/stdout.log>) | 用相同输入分别运行正式“信号”和“表现”，在两个截止日读回各自发出的附件。按 T 日核对完整的记录集合、数量和每个字段。 |
| P1 | **整张图无可见数据仍通过。** 横轴移到一年后，表现和净值两个命令各自生成的两张 PNG 合计四张均把全部观测点裁在绘图区外。测试只核对曲线数据、可见标记和点大小。[回执](<D:/Codex/test-lifecycle/records/bc8ae3e9c68640f1a93fbf8eb0a349ba/stdout.log>) | 对实际导出的净值和回撤两个子图，把点转换为画布坐标，逐点核对是否落在绘图区；保留单点标记检查。 |
| P2 | **文字与 Excel 同时报错回撤仍通过。** 将最大回撤固定为 −91.23%，表现文字、净值文字和工作簿均给出错误数值，而曲线保留真实回撤。两个专项用例全部通过。[回执](<D:/Codex/test-lifecycle/records/4224ed3f0b1343a9864b70c56227fe3f/stdout.log>) | 从起始净值 1 和归档日收益计算峰值与回撤，同时比对两份文字、Excel 和图上的回撤序列。 |
| P2 | **可见图例认错策略仍通过。** 四张图最终显示的图例全部换成 `WRONG-STRATEGY (+99.9%)`，两项测试仍通过。曲线对象保留正确标签，导出时的图例已被改写。[回执](<D:/Codex/test-lifecycle/records/7e64d70ebe4f488eab9731c1743bf060/stdout.log>) | 读取最终图例的可见文字和对应线条，逐项核对策略、颜色及期末收益。 |
| P2 | **Excel 收益单位丢失仍通过。** 把累计收益单元格从百分数改为普通两位小数。ADK 单日的 1.31% 会显示为 0.01，五日的 2.56% 会显示为 0.03。单元格底层数值正确，所以两项测试都通过。[回执](<D:/Codex/test-lifecycle/records/8e5517d7495b4d7fbd1ef0823495c471/stdout.log>) | 对正式附件同时核对数值、有效数字格式和百分比显示精度。相同数据下，将 Excel 收益实际增加一个百分点，已有两项测试均能拦截。[正向对照](<D:/Codex/test-lifecycle/records/b725eed9f23c409fb7d3204d21a2f096/stdout.log>) |
| P3 | **下载文件的日期和编号可以全错。** 两个场景的六份附件名称全部改成 1999-01-01 和编号 `INVALID`，专项仍通过。另有[多区间测试](../tests/test_v80_reporting_repairs_20261015.py)检查表现附件的日期与唯一性。[回执](<D:/Codex/test-lifecycle/records/ea1ef2b8b62642049f90e29ebfcadc49/stdout.log>) | 在边界样本中直接比对实际附件名、请求日期、有效日期与同次报告标识，覆盖独立净值命令。 |

## 复现范围

美股离线夹具包含 722 行、47 列，已与两份原始归档按列名逐值核对。仓库默认测试发现能收集这五项。本次实际执行的是发版专项；各项注入反例的结论也限定于该专项。当前工作区的两个新测试文件和压缩行情夹具尚未纳入 Git 跟踪，发布 Git 版本时需一起包含。其他机器可用原生 `python -m pytest` 指定这两个文件，本机使用 README 记载的受管入口。[默认发现记录](<D:/Codex/test-lifecycle/records/7c170246359047f6b5cc9c1d7c9da843/stdout.log>)

## 修复后的六项反例验收

两份发版测试已加强。下面的受管回执都要求正常走到故障注入点，并由指定的新断言拒绝错误输出。日志中的 pytest 失败是反例的预期结果，外层验证程序核对失败原因后返回成功。

| 原反例 | 修复后的拦截证据 |
|---|---|
| 次日“信号”漏掉前日 B7.9 | 两个截止日分别调用正式查询入口生成信号和表现附件。只删去第二次信号中的 11 月 14 日记录，两份 Excel 的前日行集合不再相等，检查失败。[回执](<D:/Codex/test-lifecycle/records/da001ff7a35c44a0b45986ec90c96a1a/stdout.log>) |
| 横轴整体移到一年后 | 两个场景均因净值或回撤观测点落到坐标轴外失败。[回执](<D:/Codex/test-lifecycle/records/2670eb78ea6c4cbe9eab7dadf83dd2f6/stdout.log>) |
| 最大回撤改为 −91.23% | 以初始净值 1 及归档逐日收益重算最大回撤。两个场景的表现文字均触发独立期望值断言，Excel 和净值文字也分别核对。[回执](<D:/Codex/test-lifecycle/records/791b1b5e9dd4461eadfdcd67a443abd2/stdout.log>) |
| 最终图例改为 WRONG-STRATEGY (+99.9%) | 两个场景均在最终图例文字与净值曲线的对应检查上失败。[回执](<D:/Codex/test-lifecycle/records/d21bbe9596a248fe8fe7510df5d7d0da/stdout.log>) |
| Excel 普通小数冒充百分比 | 保留底层收益不动，只去除百分比格式。两个场景均在实际工作簿单元格的格式检查上失败。[回执](<D:/Codex/test-lifecycle/records/a381f84fe00544b1a091408509457300/stdout.log>) |
| 附件名为 1999 年且编号 INVALID | 两个场景均在附件身份核对上失败。两种查询分别核对自己的报告编号；仅 ADK 样本还故意请求实际收益区间外的日期，以便区分文件名内的两组区间。[回执](<D:/Codex/test-lifecycle/records/275c95bbe23247a993cd3b46d5dfb732/stdout.log>) |

## 多智能体交叉复审

第一次从[发版入口](../README.md#v80-发版必检)执行，5 项通过，35 条警告，用时 121.70 秒。随后三个智能体交换审查对象，只改变单一输出或部件。[首次验收](<D:/Codex/test-lifecycle/records/9836a306976d47e0821ccd30d4a557f0/stdout.log>)

- 只将次日“信号”实际交付的 Excel 中前日国债价格从 231.096 改为 999.123，完整性核对抓到了这一格。源记录与表现附件仍然正确。[错价复审](<D:/Codex/test-lifecycle/records/a209704dd6bd4812a251d44ce4d13a78/stdout.log>)
- 仅改净值文字中的 ADK 回撤，或只交换净值 PNG 文件名中的请求日期和实际日期并保留合法编号，两种错误都被对应断言拦截。只改工作簿元数据中的合法编号、只改工作簿中的 ADK 回撤也均被拦截。[独立净值查询](<D:/Codex/test-lifecycle/records/dc55cb6471974eee9ebe3de78cb7cadc/stdout.log>) · [工作簿元数据与数值](<D:/Codex/test-lifecycle/records/61bff28d325f4fa79ca2a82e9289db77/stdout.log>)
- 单独裁切回撤子图、仅交换图例颜色均被拦截。这轮还发现单点标记的边框和填充同时透明时会漏检。修复后，使用 PNG 渲染器将每条净值及回撤序列独立画在透明缓冲区，要求该序列本身产生可见像素。全透明单点被拒绝，空心但有色描边的单点、只有实心标记的五日曲线均通过。[最初反例](<D:/Codex/test-lifecycle/records/91a8ad185b154b41bcb1db3550280f4c/stdout.log>) · [修复与有效样式对照](<D:/Codex/test-lifecycle/records/365ade4ba4424a98874807987b4255d2/stdout.log>) · [独立复验](<D:/Codex/test-lifecycle/records/3801362d17ea49d48d66ffe5baf03e28/stdout.log>)

修复透明标记后重新执行了上表的六个原反例。六项均被对应检查拒绝，再从正式入口无注入运行，**5 项通过，0 失败，35 条警告，112.34 秒**。此次范围为本地发版专项。2025 年冻结回放中，正式“信号”入口仅替换缺少当年日历的成交额提示板，调仓收集、筛选、导出和附件回读均使用正式代码。[最终验收](<D:/Codex/test-lifecycle/records/91bbe3573bb6463db97a91dac68c5bfb/stdout.log>)

正式验收后，三组再次交叉核对。调仓组外的复审者核对了信号错价、漏行和正常输出的证据；另两组重新注入净值文字单项错误、附件日期错位、回撤图裁切、图例错色及无色标记，全部在对应断言上被拒绝。报表测试 SHA-256 为 `eb7fc994800ac6b086c8e4cb4736591b9659628a8c55a459f4f7669e9bc97c59`，调仓测试为 `eab63cea3f33059e39591e6fd5e4b423d44cbadba942514fc78c4b921d320d6d`。[净值文字与附件终审](<D:/Codex/test-lifecycle/records/5391dcf2eb214f4394ec366239bd34f9/stdout.log>) · [图表与附件终审](<D:/Codex/test-lifecycle/records/c372baaf1ba44ca6be932d594ea7468b/stdout.log>)
