# V7.8 回移 V7.9 外部审核修复记录（2026-08-11）

## 结论

V7.9 在 2026-08-07 外部评审后落地的通用正确性修复，已回移到 `mnt_bot V 7.8 plus.py`。本次不改变 V7.8 的策略池、参数、组合权重和费用设定；维护口径可称为 **V7.8.1**，程序内既有 `V7.8` 展示名保持不变，以免影响查询和历史记录兼容性。

用户指出的乖离动量回看边界确属 off-by-one：

- 修复前：`bias_n + mom_day - 1`
- 修复后：`bias_n + mom_day - 2`

`mom_day` 个收益差只需要 `mom_day + 1` 个乖离值，最长 `bias_n` 均线又需要在此基础上向前 `bias_n - 1` 行，因此首个合法位置为两者相加再减 2。V7.8 的 Sub-A、NewA、ADK 及 R2 同类实现已统一修正。

## 回移内容

### 影响信号、收益或数据完整性的修复

1. 统一修正全部乖离动量函数的 warm-up 边界，最长窗口不足时保持 `NaN`。
2. Bias 与 LogVol 多窗口评分改为要求全部配置窗口有效，缺失窗口不再按零分参与排名。
3. Sub-A 混合结果明确区分当日实际持仓敞口与收盘目标敞口；V7.7A 行内目标先移位后再作为当日持仓，`is_signal` 比较 target 与 current。
4. Sub-A 成交额特征不可判定时，两条腿采用对称的 unresolved 策略；正式绩效路径仍中止，允许降级的查询路径保持原仓位并显示警告。
5. SPY 成交量 gate 增加 Stooq 备用源和本地持久缓存，失败模式只作用于真实数据未覆盖的尾部，不再用网络故障覆盖整段历史。
6. Sub-B 同日发生模型调仓和 VolReg 切换时分别保留两类记录；模型记录优先读取 `model_target_w_*`。
7. A 股 proxy 拼接在官方 base 更新时保留较新的官方尾部，只追加 proxy 独有的新日期。
8. A 股补收盘价改用交易日历与实时快照判定；平盘不再被误判为休市。
9. 创业板成交额优先使用 Sohu/EastMoney 真实 amount，QQ/Sina volume proxy 仅作显式标注的兜底。
10. Sub-A 杠杆变化的历史记录时间改为收盘执行口径。

### 查询语义与可靠性修复

1. ADK 信号页区分“当前已生效双腿持仓”和“本日收盘目标”，不再把已执行状态重复提示成新指令。
2. ADK 混合结果不再展示伪造的单一 VolScale，改为逐腿展示已实现波动率、raw VolScale、生效 VolScale、overlay 乘数、腿内最终敞口和组合贡献。
3. `signal`、`live signal`、`params`、`live params` 的 V7.8 双腿状态与时间口径同步。
4. ADK Top-3 明确为基础排名而非最终执行清单；Top-1 同行展示 score-hot/过热/VolScale 后的最终执行结论，被过滤为 0 时明确写为“不执行”。
5. 删除未接入生产链路的微盘 `883418.TI` 直接口径宣传。
6. 无年份跨年日期区间正确解释为“上一年开始、当前年结束”。
7. CSIndex 临时 Session 使用上下文管理器，确保重试后关闭连接。
8. pending 状态在短路分支前初始化；score-hot 的指示性成本字段改名为 `v78_score_overheat_cost_indicative`。

## 固定数据回测影响

使用 `outputs/v78_v79_proxy_compare_20260810/market_cache` 的同一份缓存重新运行，避免数据更新混入修复影响。正式 DK/组合窗口遵守当前全池不早于 ZZ1000 正式发布日 `2014-10-17` 的约束；实际共同起点为 `2015-04-20`。Sub-B 独立袖套按其自身可用数据从 `2008-12-15` 开始。

### 修复前 V7.8 → 修复后 V7.8.1（正式样本）

| 袖套 | 窗口 | 修复前年化 | 修复后年化 | 年化差异 | 修复前最大回撤 | 修复后最大回撤 |
|---|---:|---:|---:|---:|---:|---:|
| Sub-A | Full | 25.52% | 26.81% | +1.30pp | -20.98% | -20.34% |
| Sub-A-DK | Full | 17.02% | 17.02% | 0.00pp | -15.81% | -15.81% |
| Sub-B | Full | 12.33% | 12.12% | -0.21pp | -12.50% | -11.64% |
| Combined | Full | 17.46% | 17.74% | +0.28pp | -7.30% | -7.32% |
| Combined | 10Y | 19.35% | 19.61% | +0.26pp | -7.30% | -7.32% |
| Combined | 5Y | 24.48% | 24.96% | +0.48pp | -6.27% | -5.97% |
| Combined | 3Y | 32.18% | 32.78% | +0.60pp | -6.27% | -5.97% |
| Combined | 1Y | 43.71% | 44.43% | +0.71pp | -6.27% | -5.97% |

主要变化来自 Sub-A 的持仓/目标时序修正；正式样本中 Sub-A 有 198 个交易日收益发生变化。ADK 正式收益逐日不变。Sub-B 有 221 个交易日发生变化，Full 年化略降但最大回撤改善。组合是按各袖套累计 NAV 配置的路径依赖组合，因此袖套早期收益改变会影响后续全部组合 NAV 权重，不能把组合逐日差异数直接解释为每日都有新信号。

### 修复后 V7.8.1 与 V7.9（正式组合）

| 窗口 | V7.8.1 年化 | V7.9 年化 | V7.8.1 最大回撤 | V7.9 最大回撤 |
|---|---:|---:|---:|---:|
| Full | 17.74% | 21.06% | -7.32% | -8.57% |
| 10Y | 19.61% | 23.42% | -7.32% | -8.57% |
| 5Y | 24.96% | 30.15% | -5.97% | -8.24% |
| 3Y | 32.78% | 40.66% | -5.97% | -8.24% |
| 1Y | 44.43% | 44.94% | -5.97% | -8.24% |

修复后，V7.8.1 与 V7.9 的 **Sub-A 和 Sub-A-DK 在 Full/10Y/5Y/3Y/1Y 五个正式窗口全部逐项一致**。剩余组合差异来自 Sub-B 的版本策略差异，而不是这批通用 bug：V7.9 的 Sub-B 收益更高，同时承担更深回撤。

代理样本仅用于更长历史的研究校验，不作为正式结论。完整结果见：

- `outputs/v781_v79_proxy_compare_20260811/report.md`
- `outputs/v781_v79_proxy_compare_20260811/window_metrics.csv`
- `outputs/v781_v79_proxy_compare_20260811/formal_daily_returns.csv`
- `outputs/v781_v79_proxy_compare_20260811/proxy_daily_returns.csv`
- `outputs/v781_v79_proxy_compare_20260811/audit.json`

## 验证与回滚

- 一次性回移验收文件 `tests/test_v78_external_audit_backports.py` 已在完成全量验证后清理；长期回归继续按功能保留在 `test_v78_adk_subb_blend_display.py`、`test_v78_cn_live_freshness.py`、`test_v78_overlay_freshness_and_volreg.py`、`test_v78_suba_new_signal_display.py` 和 `test_v79_external_audit_repairs.py`。
- V7.8 定向测试与仓库完整测试均通过；准确数量以本记录下方命令的当次输出为准，避免后续新增测试造成静态计数失真。
- `python -m py_compile "mnt_bot V 7.8 plus.py"`：通过。
- `git diff --check`：通过，仅有仓库既有的 LF/CRLF 提示。
- 修复前备份：`.codex_backups/20260811_104651`。

持续验证命令：

```powershell
python -m pytest tests/test_v78_overlay_freshness_and_volreg.py tests/test_v78_adk_subb_blend_display.py tests/test_v78_cn_live_freshness.py tests/test_v78_suba_new_signal_display.py tests/test_v79_external_audit_repairs.py -q
python -m pytest tests -q
python -m py_compile "mnt_bot V 7.8 plus.py" "mnt_bot V 7.9 plus.py"
git diff --check
```

测试中的唯一 warning 来自 `fastapi_poe` 依赖的 Pydantic V2 兼容提示；长周期回测另有 pandas 的 FutureWarning/PerformanceWarning，均未影响计算完成或结果落盘。
