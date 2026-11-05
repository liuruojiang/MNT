# 独立对抗审计：国债核验服务

最终结论：本审计范围内6类已复现问题均已修复，11项独立对抗测试全部通过，无未关闭的服务审计发现。此结论不等同盘中行情时效或历史策略收益验收。

审计者：audit_service 子Agent。范围为000012替换的共享核验服务、研究快照、字段合同，并复核拟随提交保存的11月3日依赖变更。生产源码、机器配置、原始市场证据均未由本审计者修改；只新增独立回归测试与本报告。

## 初轮结论：存在需修复的问题，不能直接提交

修前对抗测试：`tests/test_bond_adversarial_service.py`，8项失败、1项通过。真实来源为2026-11-05已存新浪/腾讯响应；反例只修改测试副本或临时SQLite，不将其作为行情事实。统一生命周期记录：`D:\Codex\test-lifecycle\records\df611d9b619449e9b121ac03040be2c6`，临时空间已自动清理。

### P2：仅收盘合同仍依赖无关OHLC字段

`alternative_sources.parse_prices` 对000012仍按股票式OHLC做正数及bar校验。已声明只准入close，但将冻结原件的open/high/low改为null、保持日期/close完全不变后，评估在float(None)处失败。若债券上游只发布有效收盘、其他字段留空，会重新发生与原H11077类似的无关字段阻断。应按合同字段解析；000012只需要有效日期和有限正收盘，原股票/ETF完整OHLC校验保留。反例：`test_close_only_contract_does_not_require_equity_ohlc`。

### P2：未来采集回执通过24小时新鲜度门禁

`alternative_sources._run_asset` 的缓存年龄只校验小于24小时，没有下界。把新浪回执采集时间设为当前时刻加1天，真实行情body不变，离线评估仍发布合格快照。应要求时区明确且0<=age<阈值，未来/无时区时间不能被当作新鲜证据。反例：`test_invalid_receipt_cannot_qualify_real_prices[future]`。

### P2：回执来源身份与当前品种没有绑定

在独立临时存储内保留真实000012行情body，但分别将新浪回执URL改为sh000905、provider改为tencent、symbol改为000905.SH，三个反例都仍发布000012合格快照。store的body哈希验证只能证明body未变，不能证明请求属于正确来源/证券。应核对回执provider、URL中的证券与当前请求合同；若symbol字段存在也必须匹配。新浪日线本身没有证券代码尤其依赖URL来源绑定。反例为上述参数化测试三个wrong_*情形。原生产原件没有被修改，本问题不是指原件已遭篡改。

### P2：禁用替代源仍可退休原国债必需项

`cn_run`在suba_bond_symbol=000012时只验证alternative_cn_symbols含000012和项目合同，却不检查enabled_alternative_sources。将enabled置空或只保留腾讯，cn_run仍移除H11077；空enabled随后让alternative_sources.run直接返回NOT_ENABLED，原/新国债都不核验。应在退休前核对必要来源全部启用、品种集合合法且不重复，并与当前合同绑定。反例：`test_retirement_requires_both_replacement_sources`两种配置。

### P2：双源国债合同仍强制启用无关第三源

`alternative_sources.run`的全局来源集合固定要求tencent/eastmoney/sina全部存在。只请求000012且启用tencent/sina时仍拒绝，而该品种source_urls与合同明确只需双源。应按本次资产集合计算必需来源，不能因此放宽黄金或中证500的三源合同。反例：`test_bond_only_configuration_needs_only_its_two_reviewed_sources`。

## 已通过的对抗路径

`test_qualified_bond_snapshot_revoked_after_missing_source`：先用真实双源响应发布，随后删掉新浪最后交易日，第二次评估被阻断，旧合格快照不可读。检查到Store.begin_run先撤销全量旧资格、gate失败删除对应snapshot、publish绑定本轮run_id、read_asset限制研究目的/声明品种/获准字段；这些路径没有观察到本次引入的绕过。

## 11月3日依赖变更补审

逐项阅读了calendar AST指纹替代整文件哈希、runtime_dependencies哈希验证、audit_cn_sources重叠范围与冻结候选处理、official_reference不可变目录与冲突拒绝、independent_cash原件哈希/CUSIP/分类合计/精确事件提取。未发现该组diff中的新增明确阻断项。此结论为对应源码检查，不替代主Agent全量回归、远端提交验收或新市场时段实测。

文案问题已修复：cn_bond_close.point_in_time由“independent official closes”改为准确的双源vendor closes，避免声称有额外官方独立原件。

## 首次修复复验与迁移补充发现

主Agent实施字段解析、完整配置、回执绑定和时间范围修复后，同组9项测试全部通过，记录 `D:\Codex\test-lifecycle\records\cbcb6973fad642c18a7be0512413e67c`，临时夹具清理成功。复核源码确认网络新采集后也执行_valid_head，不仅检查旧缓存。

追加发现P2：旧机器配置没有suba_bond_symbol或明确仍为H11077.SH时，cn_run跳过000012分支的当前字段合同检查。仓库代码更新而本机config未迁移会继续核验旧H11077、漏掉当前策略需要的000012。两个独立反例均失败，记录 `D:\Codex\test-lifecycle\records\0f29483ecb6e498c999c96aa256764cd`。应所有非skip国债分支均比对当前combo_v80的cn_bond_close.instruments，旧config拒绝执行而不静默按旧范围核验。主Agent已修复：所有非skip的cn_run分支均读取当前项目合同并核对配置；旧配置不匹配时明确要求迁移。


## 最终独立复验通过

`tests/test_bond_adversarial_service.py` 全11项通过，命令经统一测试生命周期运行，已设置PYTHONUTF8=1并使用-B及-p no:cacheprovider。记录：`D:\Codex\test-lifecycle\records\d92a4969ea484ce4934e71995378c546`，临时空间清理成功；退出码0。已读回最终cn_run源码确认旧/新两个配置分支均在请求前验证当前国债合同。

最终覆盖：close-only不依赖OHL、未来时间/错URL/错provider/错symbol拒绝、缺日撤销旧快照、双源独立合同可用、禁用/单源配置拒绝退役、缺字段与旧H11077机器配置不能漏核当前000012。源码及测试SHA256见audit_service_final.json，仅用于绑定本次复验范围。
