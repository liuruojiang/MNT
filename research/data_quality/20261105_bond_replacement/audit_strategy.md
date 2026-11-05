# 独立策略取数与实时边界对抗审计

最终复验结论：**本专项通过，初审3项阻断均已修复，未发现范围内新的阻断问题**。初审未修复版本不可提交为通过，以下保留原始反例和修复前证据。仅审查此次国债替换及其实际接入链；未修改生产文件。新增独立回归测试 `tests/test_bond_adversarial_strategy.py`。本次未联网，使用本任务保存的真实000012日线，故障注入只改变覆盖范围/可用性，不报告模拟收益。

## 阻断发现

1. **P2：查询截止日没有传至新国债取数分支。** 初审位置 `mnt_bot V 8.0 plus.py:1949`、`:2211`。`_fetch_data` 的绩效路径允许 `allow_last_confirmed_cn_close=True`，将各权益统一退至最近共同确认收盘；但 `_add_cn_bond_column` 调用 `fetch_cn_kline` 未传 `required_date`，新分支仍要求当前最新交易日。例如北京时间2026-11-05 18:30，输入和源均明确截至11月4日，合法历史查询会因无11月5日被拒绝。独立测试 `test_confirmed_previous_cutoff_is_accepted_for_explicit_history_query` 失败。修复应使历史取数尊重调用者目标截止日；盘中只要求上一已确认历史、再单独核验实时快照。

2. **P1：短历史来源会静默剔除国债腿的样本前缀。** 初审位置新分支`:2217`及对齐`:1969`。新分支仅检查超过50行及所需尾日；对齐的missing条件排除了源first_valid_index之前的缺失。将真实历史截为最后60行，针对2026年202交易日的strict请求仍成功，前142日国债NaN；`run_cn_strategy` 跳过NaN分数，会把此前样本当作少一条防御腿的组合。独立测试 `test_short_bond_history_cannot_silently_drop_defensive_leg_prefix` 失败。该对齐条件本已存在，但新双源直接标的路径继承此缺陷。必需国债在所需窗口中任何缺日应拒绝，或显式统一截公共起点并披露，不能保留权益-only前缀。

3. **P1：国债实时缺失可使实时信号改变资产池。** 初审位置`:1976`异常处理，调用`:13841`。live路径在盘中传strict=False。权益已有今日、国债仅到昨日且实时报价缺失时，缺日错误被捕获，然后返回没有国债列的DataFrame。后续正式策略把缺列跳过，可能给出权益-only实时信号。独立测试 `test_missing_intraday_bond_quote_never_changes_the_asset_universe` 失败。此为继承的fail-open集成风险；应明确拒绝当前实时信号，或将整个Sub-A统一退到上个确认日并标明非今日信号。

## 已通过检查

- 中间缺少一个交易日（2026-11-03）在strict路径被拒绝。
- CN_BOND_CODE、CN_ALL_CODES、CN_NAMES、CN_BOND_NAME和绩效口径说明统一指向000012及全期限名称。
- 源码检查：四种查询展示共同使用当前策略结果及CN_NAMES；参数表资产池由CN_EQUITY_CODES加CN_BOND_CODE产生，无本次新增硬编码旧10Y标签。
- 收盘后报价不能充当盘中确认、本次无盘中连续实时验收，这一限制在已有说明中如实保留。

## 可复现命令与证据

设置 `PYTHONUTF8=1`，通过统一生命周期入口：

`C:\Python314\python.exe -B D:\Codex\test-lifecycle\test_lifecycle.py run --workspace D:\动量策略\A股美股动量组合策略 --label bond-independent-strategy-audit --pytest -- C:\Python314\python.exe tests/test_bond_adversarial_strategy.py -q -p no:cacheprovider`

首次4项：2 failed / 2 passed，记录 `D:\Codex\test-lifecycle\records\79a46a79208643ed9ea54bf72e3b363b`。新增实时缺失专项随后单独运行，1 failed / 4 deselected。测试使用的临时目录由生命周期入口自动收尾；保留验收日志。失败不能标记PASS，等待主代理修复后再复验。

这是软件/数据边界审计，不是业绩或经济优劣认证。Full/10Y/5Y/3Y/1Y年化及最大回撤均N/A：本次未回测。

## 修复后独立复验

主代理修复后再次只读检查生产代码：国债历史请求采用调用者目标日与当前已确认日的较早值，非实时路径剔除今日未确认行；窗口内所有缺失（包含首个有效值前缀）和已有国债列NaN均拒绝；任何必需债券异常都显式抛出，不再退成权益-only。

独立8项测试全部通过：原3项故障反例恢复/拒绝行为正确；中间缺日、名称映射、合法实时快照、非实时路径拒绝未确认当日日线并允许上一共同确认日、已有列前缀NaN均符合要求。未改生产代码，不依赖主代理测试结果。

命令仍使用统一test-lifecycle，标签 `bond-independent-strategy-recheck`。结果 **8 passed**，记录 `D:\Codex\test-lifecycle\records\6836c69395cc42a58e0cfae12f683f6a`，临时空间清理成功。第三方Pydantic弃用提示不影响测试结果。

通过范围是此次替换的策略取数、完整性、异常回退和实时/确认边界；不是整个策略无缺陷证明，也不是盘中数据持续更新、Poe部署或历史业绩认证。

复验生产脚本LF规范SHA256：`2f7543e5fc77221b42aa99856978b75284d529ee27a67f165a88071e7e911725`。

## 全量回归中的旧测试时钟修复

主代理全量回归发现 `test_known_confirmed_adjustment_still_emits_signal` 的live_signal/live_params两种情形失败。我独立用替换前原脚本 `.codex_backups/20261105_181347/mnt_bot V 8.0 plus.py` 配合原测试复现同样2项失败（普通signal/params两项通过），证实不是此次国债修订回归。记录 `D:\Codex\test-lifecycle\records\2cd4d46213c945919a3ab5c4dcf27e4b`。

原因是测试固定2026-09-29收盘数据，却未固定beijing_now；到11月5日，该数据正确触发实时陈旧门禁，不能再断言可执行。只修改 `tests/test_v80_review_cn_20261023.py`：已确认有效与UNKNOWN风险两组测试均固定到9月29日18:00，使它们分别测试已确认信号可执行与UNKNOWN拒绝；另加两个固定11月5日时钟的陈旧数据拒绝断言。没有关闭或修改生产新鲜度规则。

修改前原件保存在 `.codex_backups/20261105_183827`。修改后该文件全部 **45 passed**，记录 `D:\Codex\test-lifecycle\records\068ed433034f45c6857226b0005bec7c`，临时夹具清理成功。此轮仅修改所要求的测试文件及本审计报告，未改生产源码。
