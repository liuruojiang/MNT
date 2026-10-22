# V8.0 模型参考显示修复：远端审计证据

本目录随源码、正式测试和[总审计报告](../../v80_live_reference_adversarial_audit_20261022.md)提交，保存无需本机 outputs 即可审阅的精简证据。

已验收生产源码原始字节 SHA256：
`c90184824bf3dae06d11c2f4afa532ba0f8f3a2cca04243b63df23ee08643f3b`

## 内容

- math_review.md、math_results.json、math_pool_results.json、math_thursday_result.json：独立原生对照、18 组完整链、6 组门槛和周四反例最终结论。
- query_review.md、query_results.json、query_tests.log：四入口查询/执行隔离矩阵，50 项通过。
- data_review.md、data_tests.log、data_tests.xml：56 项独立脚本及44项正式保留反例，100 项通过。
- full_tests.log、full_tests.xml、full_identity.json：681 项全仓库回归，失败/错误/跳过均为0，运行起止源码身份一致。
- scope_verification.json：与传入工作区基线相比，593 个原定义及其他顶层语句不变。
- delivery_summary.json、delivery_verification.json：审计结束时的本地交付身份和检查结果。后续文档为远端同步说明作了更新，因此其中原文档哈希不必与当前说明相同；生产源码及测试未改。
- cleanup_summary.json：仅清理可重建缓存/临时文件的结果，没有删除策略历史、原始数据或审计原件。
- manifest.json：当前随本次提交同步文件的原始 SHA256/Git blob 身份。

所有策略价格与调整后开盘输入为明确标注的合成诊断数据。全样本、10Y、5Y、3Y、1Y 年化收益及最大回撤均 N/A：本轮不是策略绩效测试或候选晋升。测试组存在重叠，不能把681、100、50相加作为独立用例总数。

## 复现和范围

正常检出可运行：

```powershell
python -B -X utf8 -m pytest tests -q -p no:cacheprovider
```

部分既有测试依赖本机被冻结的行情或历史证据；干净检出缺这些输入时可能跳过，跳过不等于验证通过。本次681项结论来自完整本地工作区，精确结果以 full_tests.xml 为准。完整原始日志、失败反例、不可变源码快照和独立脚本仍保留在总报告列明的本地 outputs 目录，没有将全部临时产物复制到 Git。

未发布 Poe。本目录不是最新行情、线上部署或实际资金执行认证。

Git 文本副本按项目换行规则统一 LF；原始审计日志保留在本地 outputs。manifest.json 同时记录换行归一化前的原始哈希，生产源码未改。
