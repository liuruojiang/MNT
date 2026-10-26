# 成交额查询修复的离线证据包

配合 [修复记录](../../../docs/v80_amount_query_fix_20261026.md) 使用。

包含 2026-10-26 16:35 北京时间捕获的中证2000/创业板成交额，以及已有真实冻结输入中单独提取的 Sub-A 价格。没有增加或替换生产数据源。原始中证2000接口包含发布前回填，正式 loader 继续按 2023-08-11 发布日排除；创业板沿用既有国证核实的单日修复。

`manifest.json` 记录源脚本、基线提交、各文件 SHA256、来源和提取记录。正式源脚本按 LF 统一换行后计算 SHA256，兼容 Windows checkout；金额 CSV 与压缩价格文件按原始字节校验。`cn_prices.csv.gz` 经浮点 round-trip 读取核实与本地原始价格 frame 逐值一致；无需复制完整组合 pickle 或本机备份。校验脚本会读取 Git 历史中的基线，不会访问网络，也不会写入文件。

```powershell
python -B research/data_quality/20261026_amount_query/verify_offline.py
```

浅克隆需先取得 `manifest.json` 中记录的基线提交；其他依赖与正式脚本一致。验证应得到 2284 个成交额消费交易日无不可判定项、2189 行原生 Sub-A 结果全部字段与基线精确相同，以及模拟 Poe 加载通过。

`real_amount_acceptance.json` 保留本机原始采集/隔离回归记录；其中 Windows 路径仅是历史来源标识。`bootstrap_reproduction.json` 记录修前启动失败和兼容性补修通过，源哈希对应当时版本；最后发布规范化不改语法树，最终源哈希以 manifest 和 `offline_verification.json` 为准。

此包证明冻结输入下的修复回归，不是当前五袖收益认证或 Poe 线上验收。
