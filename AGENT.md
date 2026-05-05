# AGENT Rules

## Hard gate before any backtest

Every backtest or performance comparison must start by reading this `AGENT.md`.
This is not optional. If the file has not been read in the current turn, do not
publish CAGR, max drawdown, yearly returns, NAV curves, allocation advice, or
version comparisons.

Before publishing any result, create and keep an audit trail in the output
folder that records:

1. exact target script path and version;
2. official entrypoint used, preferably that script's own `_fetch_data` plus
   `_run_strategies`;
3. data sources and whether required `open` and `close` fields were present;
4. market calendar used by each sleeve;
5. return column used for each sleeve;
6. start date, end date, row count, monthly count, and duplicate-date count;
7. whether Sub-B used `T close signal -> T+1 open execution`, `us_open`,
   VolReg, costs, `EMXC/EEM` splice, and `IBIT/BTC-USD` splice;
8. whether all metric tables, daily returns, yearly returns, charts, and HTML
   report came from the same run.

If any audit item is missing, the result must be labeled "invalid / not formal"
and must not be used for strategy ranking or allocation decisions. If a user
points out that a result does not match Poe or an Excel export, stop publishing
new conclusions and reconcile the external file against the official script
path first.

## 回测铁律

1. 先确认目标版本脚本的正式入口，再做任何回测。
2. 回测必须优先复用目标版本脚本自己的正式数据路径和正式策略路径。
3. 不能因为方便就手工重建近似链路，然后把结果当正式结论。
4. 只要结果用于版本优劣、参数优劣、组合配比结论，必须先完成口径核对。

## 回测前强制检查

每次回测前，必须先确认以下事项：

1. 目标版本脚本文件是哪个。
2. 正式入口是 `_fetch_data + _run_strategies` 还是该版本另有正式绩效入口。
3. 使用的数据源是什么。
4. 数据字段是否满足正式执行需要。
5. 请求窗口和实际可用窗口是否一致。

只要有一项不明确，就不能下结论。

## 组合回测刷新铁律

以后凡是回测 V7.2 或任何四腿组合，必须先把所有子策略数据刷新到最新可用交易日，再合成组合：

1. `Sub-A` 和 `Sub-A-DK`：刷新本仓库 `mnt_strategy_data_cn.csv`，并确认正式脚本使用的 A 股字段最新日期。
2. `Sub-B`：刷新本仓库 `mnt_strategy_data_us.csv`，并确认美股 ETF 最新日期；不能让 `BTC-USD` 周末数据污染美股交易日历。
3. `Microcap`：先运行微盘仓库官方脚本刷新 `outputs/microcap_top100_mom16_biweekly_live_panel_refreshed.csv`、Top100 proxy index、turnover、costed NAV，再由组合脚本读取刷新后的官方输出。
4. 合成前必须打印或记录四条腿的可用起止日期；若任一腿落后，先刷新或明确标注结果不是最新正式结果。

## Sub-B 专项铁律

`Sub-B` 是最容易被口径污染的部分，必须额外检查：

1. 是否为 `T收盘信号 -> T+1开盘执行`。
2. 是否真的传入了 `us_open`。
3. 是否带了该版本默认的 `VolReg`。
4. 是否带了该版本默认的 `asset overlay`。
5. 是否正确处理了 `EMXC/EEM` 和 `IBIT/BTC-USD` 的正式拼接。
6. 没有 `open` 数据时，不能宣称结果是正式口径。

## Sub-A-DK 专项铁律

`Sub-A-DK` / `DK` 回测最容易被指数未上市前的供应商回填数据污染，必须额外检查：

1. DK 结果用于版本、参数、波动率缩放、配比或优劣判断前，必须先确认参与指数的正式发布日期/上市日期。
2. 禁止把指数正式发布前的历史回填价格纳入正式或准正式结论；这些早期数据只能作为无效样本或另行标注的代理研究。
3. 如果 DK 使用当前完整指数池 `SZ50 / HS300 / ZZ500 / ZZ1000 / CYB`，样本起点必须不早于最晚上市的参与指数日期；当前完整池至少要从 `ZZ1000` 正式发布日 `2014-10-17` 之后开始统计。
4. 如果某轮 DK 测试使用了缩减指数池，样本起点必须取该轮实际参与指数发布日期的最大值，并在输出中记录。
5. DK 临时研究脚本即使通过收益、权重、调仓日 parity，也不能越过上述上市日期约束；发现样本起点早于参与指数正式日期时，该轮 DK 绩效结论直接作废并重跑。

## 明确禁止

1. 不能把本地 `close-only` CSV 直接当成 `Sub-B` 正式口径。
2. 不能把手工拼的 `official_like_*` 路径直接当成正式 `_fetch_data`。
3. 不能把全样本年化说成某个窗口年化。
4. 不能在子策略口径没对齐前先做组合配比分析。

## 结果分级

以后所有回测结果都必须标明属于哪一类：

1. 正式结果：正式入口、正式数据、正式执行假设全部满足。
2. 近似结果：逻辑接近正式路径，但缺少正式字段或用了离线重建。
3. 无效结果：关键字段缺失、窗口说错、样本起点说错、或入口路径不一致。

如果不是“正式结果”，必须显式标注。

## 2026-04-21 回测错误复盘

今天在 `Sub-B` 目标波动率和 Model B 杠杆规则测试中，犯过以下错误，后续必须避免：

1. 错误使用 `close-only` 宽表做正式回测。
   - `Sub-B` 正式逻辑是 `T收盘信号 -> T+1开盘执行`，必须有 `open` 数据并传入 `us_open`。
   - 只有 `close` 的本地 CSV 只能做近似研究，不能作为正式绩效结论。
   - 如果宽表被 `BTC-USD` 带入周末日期，不能直接当作美股交易日历使用。

2. 错误混用了不同轮次生成的指标文件和 daily 明细文件。
   - 指标表、daily 明细、参数、数据源、样本窗口必须来自同一次运行。
   - 发现指标表起点、daily 起点、行数或文件时间不一致时，必须立刻废弃该轮结果。
   - 不能用旧文件补解释新结论。

3. 错误处理 `EMXC/EEM` 代理。
   - 使用 `EEM` 拉长历史时，只能补 `EMXC` 可用前的历史段。
   - `EMXC` 有真实数据之后必须切回真实 `EMXC`，并按正式拼接规则处理。
   - 禁止把整个现代样本都替换成 `EEM` 后再声称是 `EMXC` 代理长样本结果。
   - 长历史代理回测必须检查重叠窗口：如果 1Y/3Y/5Y 与未拉长版本明显不同，先查代理拼接，不得直接汇报结论。

4. 没有先证明自写研究脚本与正式路径等价。
   - 任何临时研究脚本必须先和正式 `run_us_rotation()` / `_fetch_data + _run_strategies` 在同一数据片段上做 parity check。
   - 至少核对：日期范围、行数、收益序列、权重、调仓日、`VolReg`、交易成本、样本起止。
   - 未通过 parity check 的结果只能标为“无效结果”或“近似结果”，不能用于策略优劣判断。

5. 回测结论发布前没有足够快地停下来复核。
   - 用户指出结果不一致、收益异常、样本起点异常时，必须先暂停结论，做根因排查。
   - 发现错误后，必须明确标记旧结果作废，并给出新旧差异的具体原因。

## 回测发布前强制验收

以后凡是给出 CAGR、最大回撤、Sharpe、换手率、单一资产最大权重、窗口收益等回测指标，必须先完成并在回复中说明：

1. 目标版本脚本和正式函数入口。
2. 数据源、复权方式、字段是否包含 `open/close`。
3. 交易日历是否为目标市场日历，是否排除了 BTC 周末污染。
4. 执行假设是否与正式策略一致，尤其是 `T+1 open`、费用、`VolReg`、代理拼接、BTC/IBIT 拼接。
5. 指标表和 daily 明细是否来自同一次运行。
6. 如果使用代理拉长历史，必须说明代理只影响哪一段样本，并验证重叠窗口没有被意外改写。
7. 如果是临时脚本结果，必须说明是否已通过正式路径 parity check。

回测准确性优先于速度。宁可先说“这轮结果无效，需要重跑”，也不能为了继续讨论而输出未经核验的绩效结论。

## 作图发布铁律

## Codex 可见图片输出硬规则

给用户看的图，第一展示方式必须采用已经验证可见的格式：

1. 先把 PNG 复制到纯英文、无空格、无中文的路径，例如：
   `C:/Users/Administrator.DESKTOP-95I7VVU/Desktop/codex_nav_charts/<name>.png`
2. 回复里必须直接用 Markdown 图片标签嵌入这个英文路径：
   `![chart](C:/Users/Administrator.DESKTOP-95I7VVU/Desktop/codex_nav_charts/<name>.png)`
3. 路径必须使用正斜杠 `/`，不能使用中文路径、空格路径或反斜杠 Windows 路径。
4. 自包含 HTML 和 `http://127.0.0.1:<port>/...` 链接只能作为补充，不能替代上面的可见 Markdown 图片。
5. 如果用户明确说某种图片输出方式“可以看了”，以后同类图优先沿用该方式。

以后凡是给用户看净值曲线、回撤曲线、指标对比图或任何研究图表，必须遵守：

1. 不能只给本地 PNG 路径，用户在 Codex 对话里经常看不到。
2. 不能把 `view_image` 工具输出当成用户已经看到；该工具可能只在 agent 侧可见。
3. 不能只依赖 Markdown 图片标签展示本地文件，尤其是中文路径、Windows 路径或空格路径下容易失败。
4. 必须同时生成：
   - 原始 PNG 图片文件。
   - 指标 CSV 或明细 CSV，作为数值结论的准绳。
   - 一个自包含 HTML 报告，把图片用 base64 嵌入 HTML。
5. HTML 报告生成后，必须启动本地只读 HTTP 服务，并给用户 `http://127.0.0.1:<port>/xxx.html` 链接。
6. 发布前必须用 `Invoke-WebRequest` 或等价命令验证该链接返回 `StatusCode = 200`。
7. 回复中必须说明：图只是辅助观察，正式数值结论以同次运行生成的 CSV/表格为准。

推荐做法：

1. 每个窗口单独出图，例如 `1Y / 3Y / 5Y / 10Y` 分开保存，避免一张大图过密。
2. 图表标题不要同时使用 `title` 和 `suptitle` 后再 `tight_layout()`，容易在渲染时重叠；日期范围和口径说明可以放在图内左上角小字或 HTML 文本区。
3. 自包含 HTML 优先放在同一输出目录，例如 `*_report.html`。
4. 本地服务优先绑定 `127.0.0.1`，例如：
   `python -m http.server 8765 --bind 127.0.0.1 --directory <output_dir>`
5. 如果端口被占用，换一个端口，但必须重新验证链接可访问。

## 测试数据与 outputs 纪律

以下纪律从微盘策略仓库同步过来，适用于本仓库所有 Sub-A / Sub-A-DK / Sub-B / Microcap / 四腿组合测试：

1. 不能把旧的比较 CSV、导出 CSV、临时 scan 结果或 `outputs/` 里的旧文件当成新结论的数据源。
   - 新结论必须从当前目标版本的正式函数、正式脚本入口或当前官方输出重新生成。
   - 若必须引用旧文件做诊断，必须先说明它只是诊断材料，并和当前官方基准做日期级核对。
2. 做版本对比、参数对比、组合权重对比时，所有候选必须共享同一套口径：
   - 同一基准；
   - 同一日期索引；
   - 同一收益列；
   - 同一成本模型；
   - 同一窗口定义。
3. 发布 CAGR、年化波动、Sharpe、最大回撤、总收益、年度收益等指标前，必须至少内部确认并在必要时汇报：
   - source script/function/file；
   - return column；
   - start/end date；
   - row count；
   - duplicate-date count；
   - common-index row count。
4. 不能静默混用 `gross`、`return`、`return_net`、`nav`、`nav_net`。
   - 实盘/可执行口径默认使用扣费后的收益和净值。
   - 如果某条腿只有近似或未扣费口径，必须显式标注，不能混入正式结论。
5. 目标波动率、杠杆、风控 overlay、现金 overlay、成本 overlay 的测试必须从同一个 freshly rebuilt base return stream 生成。
   - 不得把旧的 target-vol CSV 和新生成的 base/v1.x 文件混在同一张表里比较。
   - 若复算结果与旧表差异明显，先停下来查 data lineage，不得继续发布新的绩效表。
6. 接受 overlay 或 target-vol 结果前必须做成本 sanity check：
   - 同一 base return stream 上，costed NAV 不应高于 no-cost NAV；
   - entry/exit cost columns 必须实际影响 `return_net`；
   - `cash -> long` 入场日即使当日执行 scale 为 0，也必须按策略约定扣除入场成本。
7. `outputs/` 视为可再生导出空间。
   - 当前正式产物、必要缓存和已写入 docs 的结论证据可以保留。
   - stale comparison、scan、custom、corrected、temporary exports 在结论被替代或写入文档后应清理。
   - 清理前若文件可能还有复核价值，先备份到 `.codex_backups`。

## 2026-05-03 V7.3旧版 POE 回测事故复盘

这次在核对 `performance_20260503.xlsx` 和 V7.3 旧版/新版近10年收益时，出现过多轮错误。以后遇到 POE、Excel、备份脚本、本地当前脚本之间的回测对账，必须按下面纪律执行。

### 本次实际错误

1. 把“旧版”说得不够精确。
   - 不能只说旧版或新版，必须写清楚具体文件路径、备份目录、生成时间和入口函数。
   - 例如 `.codex_backups/20260503_084518/mnt_bot V 7.3 plus.py`、当前 `mnt_bot V 7.3 plus.py`、POE 上传脚本不是天然等价。
   - 若无法拿到 POE 上传的原始脚本，只能说“最接近某备份”，不能说“已复现 POE 旧版”。
2. Sub-B 曾被错误压到 A股/DK 共同交易日。
   - `Sub-B` 是美股/加密混合日历，不能为了组合或对比方便压到 A股交易日。
   - 近10年 `Sub-B` 应保留完整美股/策略可用日频；若只剩约 2429 个 A股交易日，结果直接作废。
3. Sub-B 曾被错误算成 close-to-close。
   - V7.3 旧版 POE 的 `Sub-B` 正式口径是 `T日收盘信号 -> T+1 adjusted open 调仓 -> T+1 close 收益`。
   - 本地复刻若没有传入 `us_open`，就不是正式口径，不能拿来和 POE Excel 比较。
   - 缺 `us_open` 时跑出的 B 年化只能标为“无效/近似 close-to-close”，不能标为旧版正式收益。
4. 混淆了成本修复前后脚本。
   - 当前脚本和 `20260503_084518` 旧备份的 A/ADK/B 成本路径不同。
   - 成本修复会改变 A、ADK、B，尤其 ADK；不能把当前脚本结果拿去解释 POE 未修订前 Excel。
5. 混用了日频绩效口径和月频绩效口径。
   - POE 绩效 Excel 的展示表虽有月度收益，但累计收益、年化收益、最大回撤会被日频区间重新覆盖。
   - 对账时必须同时检查：月收益乘积、日频累计、日频年化、日频最大回撤；不能只用月表年化下结论。
6. 没有先做外部 Excel 对账就发布判断。
   - 外部 Excel 必须逐月 diff、相关系数、MAE、最大单月差异、起止月份、日频行数一起核对。
   - 只看 CAGR 接近或不接近都不够；必须定位差异集中在哪些月份、哪些数据源、哪个执行假设。

### 以后强制对账流程

1. 先冻结四个身份：
   - 外部结果文件，例如 `performance_20260503.xlsx`；
   - 目标脚本，例如 POE 上传脚本或具体 `.codex_backups/<timestamp>/...py`；
   - 当前本地脚本；
   - 数据文件和生成时间，例如 `mnt_strategy_data_cn.csv`、`mnt_strategy_data_us.csv`。
2. 再打印每条腿的最小审计信息：
   - return column 名称；
   - start/end date；
   - row count；
   - monthly count；
   - 是否有 duplicate dates；
   - 是否有 `open` 数据；
   - 是否使用 `us_open`；
   - 是否启用该版本默认 `VolReg`、成本、overlay、代理拼接。
3. 对 Sub-B 必须额外打印执行口径：
   - signal timing；
   - execution price；
   - 是否 `T+1 open`；
   - 是否使用 adjusted open；
   - `BTC-USD/IBIT` 拼接方式；
   - `EMXC/EEM` 拼接方式；
   - 是否排除 BTC 周末日期对美股日历的污染。
4. 对 A/ADK 必须额外打印：
   - A 股输入字段；
   - DK 输入字段；
   - 是否使用全收益指数或价格指数；
   - 近期最后可用日期；
   - 成本修复前后路径；
   - 成交额/过热/衰减 overlay 是否真的参与收益。
5. 对外部 Excel 复现必须输出三层证据：
   - `overview` 指标差异；
   - 月收益逐月差异；
   - 日频收益重算后的累计、年化、最大回撤。
6. 若发现某条腿对不上，先暂停结论，按顺序排查：
   - 版本是否同一份；
   - 数据是否同一份；
   - 窗口是否同一段；
   - 交易日历是否同一套；
   - 执行价是否同一口径；
   - 成本/overlay 是否同一顺序；
   - 绩效函数是否同一计算方式。

### 发布纪律

1. 任何“新旧版本收益对比”必须在表头写清：
   - old script；
   - new script；
   - data files；
   - date window；
   - execution assumption；
   - performance function。
2. 若旧版本不能复现 POE 上传文件，必须明确说：
   - “本地旧备份结果”；
   - “POE Excel 结果”；
   - “两者尚未证明同源”。
3. 若结果后来被证明口径错误，必须直接标注为作废，不得继续引用。
4. 用户指出结果和 POE/Excel 不一致时，第一反应必须是对账和复现，不能先解释策略原因。
