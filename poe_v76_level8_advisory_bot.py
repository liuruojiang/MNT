# poe: name=V76-Level8-Advisory
# poe: privacy_shield=half
"""Single-file Poe bot for V7.6 Level-8 portfolio advisory display."""

try:
    from fastapi_poe.types import SettingsResponse
except Exception:
    class SettingsResponse:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)


if "poe" not in globals():
    try:
        import fastapi_poe as poe
    except Exception:
        class _LocalMessage:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def write(self, text):
                print(text, end="")

        class _LocalPoe:
            class BotError(Exception):
                pass

            query = type("Query", (), {"text": "", "attachments": []})()
            default_chat = []

            @staticmethod
            def update_settings(settings):
                return None

            @staticmethod
            def start_message():
                return _LocalMessage()

        poe = _LocalPoe()


def _install_local_poe_compat(poe_module):
    required = ("update_settings", "start_message", "query", "BotError")
    if all(hasattr(poe_module, attr) for attr in required):
        return poe_module

    class _LocalMessage:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def write(self, text):
            print(text, end="")

    class _CompatPoe:
        def __init__(self, wrapped):
            self._wrapped = wrapped
            self.BotError = getattr(wrapped, "BotError", RuntimeError)
            self.query = getattr(wrapped, "query", type("Query", (), {"text": "", "attachments": []})())
            self.default_chat = getattr(wrapped, "default_chat", [])

        def update_settings(self, settings):
            update = getattr(self._wrapped, "update_settings", None)
            if update is None:
                return None
            return update(settings)

        def start_message(self):
            start = getattr(self._wrapped, "start_message", None)
            if start is None:
                return _LocalMessage()
            return start()

    return _CompatPoe(poe_module)


poe = _install_local_poe_compat(poe)


LEVEL8_ADVISORY_SNAPSHOT = {
    "snapshot_date": "2026-05-12",
    "latest_data_date": "2026-05-08",
    "status": "ACTIVE_DEFAULT",
    "scenario": "advisory_suba_microcap_dd_3_10_month_end",
    "active_scenario": "advisory_suba_microcap_dd_3_10_month_end",
    "dynamic_sleeves": "Sub-A,Microcap",
    "primary_action": "Use stacked Sub-A 5/8 weekly + Microcap 3/10 month-end as the active portfolio-level dynamic budget; keep fixed weights as benchmark and rollback.",
    "source_note": "Embedded from the local Level-8 dashboard run verified on 2026-05-12.",
    "sleeves": [
        {"name": "Sub-A", "weight": 0.15, "role": "dynamic"},
        {"name": "Sub-A-DK", "weight": 0.15, "role": "fixed"},
        {"name": "Microcap", "weight": 0.10, "role": "dynamic"},
        {"name": "Sub-D", "weight": 0.20, "role": "fixed"},
        {"name": "Sub-B", "weight": 0.40, "role": "absorber"},
    ],
    "metrics": {
        "full_annual_delta": 0.021750906860742825,
        "full_max_dd_delta": 0.007155533526533697,
        "full_sharpe_delta": 0.16753581735735779,
        "last_1y_annual_delta": 0.043492369292941646,
        "last_1y_max_dd_delta": 0.0037853338198617983,
        "last_1y_sharpe_delta": 0.4040127267262026,
        "latest_excess_nav_vs_fixed": 0.269270132887075,
    },
    "governance": {
        "status": "ACTIVE_OK",
        "relative_nav_drawdown": "current -0.18%, worst -2.54%",
        "execution_load": "switches 123, turnover 13.9",
        "review_line": "> -5.00%",
        "rollback_line": "<= -10.00%",
    },
}


def _pct(value: float) -> str:
    return f"{float(value):.2%}"


def _weight(value: float) -> str:
    return f"{float(value):.0%}"


def render_level8_advisory() -> str:
    snap = LEVEL8_ADVISORY_SNAPSHOT
    metrics = snap["metrics"]
    governance = snap["governance"]
    lines = [
        "# V7.6 Level-8 Advisory",
        "",
        f"- Status: **{snap['status']}**",
        f"- Latest data date: `{snap['latest_data_date']}`",
        f"- Scenario: `{snap['scenario']}`",
        f"- Dynamic sleeves: **{snap['dynamic_sleeves']}**",
        f"- Primary action: {snap['primary_action']}",
        "",
        "| Sleeve | Advisory weight | Role |",
        "|---|---:|---|",
    ]
    for sleeve in snap["sleeves"]:
        lines.append(f"| {sleeve['name']} | {_weight(sleeve['weight'])} | {sleeve['role']} |")
    lines.extend(
        [
            "",
            "| Evidence vs fixed default | Value |",
            "|---|---:|",
            f"| Full annual delta | {_pct(metrics['full_annual_delta'])} |",
            f"| Full maxDD delta | {_pct(metrics['full_max_dd_delta'])} |",
            f"| Full Sharpe delta | {metrics['full_sharpe_delta']:.2f} |",
            f"| 1Y annual delta | {_pct(metrics['last_1y_annual_delta'])} |",
            f"| 1Y maxDD delta | {_pct(metrics['last_1y_max_dd_delta'])} |",
            f"| 1Y Sharpe delta | {metrics['last_1y_sharpe_delta']:.2f} |",
            f"| Excess NAV vs fixed | {_pct(metrics['latest_excess_nav_vs_fixed'])} |",
            "",
            "| Governance | Value |",
            "|---|---:|",
            f"| Status | {governance['status']} |",
            f"| Relative NAV drawdown | {governance['relative_nav_drawdown']} |",
            f"| Execution load | {governance['execution_load']} |",
            f"| Review line | {governance['review_line']} |",
            f"| Rollback line | {governance['rollback_line']} |",
            "",
            "This is the active portfolio-level dynamic budget snapshot. Fixed 10/15/15/20/40 remains the benchmark and rollback line.",
            "",
            f"Snapshot note: {snap['source_note']}",
        ]
    )
    return "\n".join(lines)


def render_status_summary() -> str:
    snap = LEVEL8_ADVISORY_SNAPSHOT
    metrics = snap["metrics"]
    governance = snap["governance"]
    return "\n".join(
        [
            "## 当前建议",
            "",
            f"- 状态: **{snap['status']}** / governance **{governance['status']}**",
            f"- 数据日期: `{snap['latest_data_date']}`",
            "- 执行权重: Sub-A 15%, Sub-A-DK 15%, Microcap 10%, Sub-D 20%, Sub-B 40%",
            "- 动态袖珍: Sub-A + Microcap",
            "- 回滚基准: 固定 10/15/15/20/40",
            f"- 相对固定超额 NAV: {_pct(metrics['latest_excess_nav_vs_fixed'])}",
            f"- 相对 NAV 回撤: {governance['relative_nav_drawdown']}",
        ]
    )


def render_weights() -> str:
    snap = LEVEL8_ADVISORY_SNAPSHOT
    lines = [
        "## 当前执行权重",
        "",
        "| 袖珍组合 | 权重 | 角色 |",
        "|---|---:|---|",
    ]
    role_labels = {
        "dynamic": "动态调整",
        "fixed": "固定",
        "absorber": "吸收权重差",
    }
    for sleeve in snap["sleeves"]:
        lines.append(
            f"| {sleeve['name']} | {_weight(sleeve['weight'])} | {role_labels.get(sleeve['role'], sleeve['role'])} |"
        )
    lines.extend(
        [
            "",
            "固定 10/15/15/20/40 仍保留为 benchmark / rollback。",
        ]
    )
    return "\n".join(lines)


def render_evidence() -> str:
    metrics = LEVEL8_ADVISORY_SNAPSHOT["metrics"]
    return "\n".join(
        [
            "## 相对固定权重证据",
            "",
            "| 指标 | 数值 |",
            "|---|---:|",
            f"| Full annual delta | {_pct(metrics['full_annual_delta'])} |",
            f"| Full maxDD delta | {_pct(metrics['full_max_dd_delta'])} |",
            f"| Full Sharpe delta | {metrics['full_sharpe_delta']:.2f} |",
            f"| 1Y annual delta | {_pct(metrics['last_1y_annual_delta'])} |",
            f"| 1Y maxDD delta | {_pct(metrics['last_1y_max_dd_delta'])} |",
            f"| 1Y Sharpe delta | {metrics['last_1y_sharpe_delta']:.2f} |",
            f"| Excess NAV vs fixed | {_pct(metrics['latest_excess_nav_vs_fixed'])} |",
        ]
    )


def render_governance() -> str:
    governance = LEVEL8_ADVISORY_SNAPSHOT["governance"]
    return "\n".join(
        [
            "## 治理状态",
            "",
            f"- 状态: **{governance['status']}**",
            f"- 相对 NAV 回撤: {governance['relative_nav_drawdown']}",
            f"- 执行负担: {governance['execution_load']}",
            f"- 复核线: {governance['review_line']}",
            f"- 回滚线: {governance['rollback_line']}",
            "",
            "解释:",
            "",
            "- ACTIVE_OK: 所有治理规则通过，stacked 动态仓位可以继续作为 active budget。",
            "- relative NAV DD: 动态方案相对固定 10/15/15/20/40 的超额 NAV，从自身高点回撤了多少；不是组合自身最大回撤。",
            "- current -0.18%: 当前超额优势只比自己的历史高点低 0.18%。",
            "- worst -2.54%: 历史最差相对回撤是 -2.54%，还没有碰到 -5% 复核线。",
            "- switches 123: 样本期动态预算切换/再平衡次数。",
            "- turnover 13.9: 样本期组合层权重调整的累计负担；当前阈值是 switches <= 140 且 turnover <= 15.0。",
            "- review line > -5.00%: 相对回撤保持在 -5% 以内就继续执行；跌到 <= -5% 进入复核。",
        ]
    )


def render_rollback() -> str:
    governance = LEVEL8_ADVISORY_SNAPSHOT["governance"]
    return "\n".join(
        [
            "## 回滚线",
            "",
            "- 正常: governance 保持 ACTIVE_OK，继续使用 stacked 动态仓位。",
            f"- 复核: 相对 NAV 回撤到 {governance['review_line']} 时，暂停新增 Level-8 晋级并检查规则。",
            f"- 回滚: 相对 NAV 回撤到 {governance['rollback_line']} 时，回到固定 10/15/15/20/40。",
            "- 固定权重一直保留为 benchmark / rollback，不删除。",
        ]
    )


def render_help() -> str:
    return "\n".join(
        [
            "# V76-Level8-Advisory",
            "",
            "关键词：建议、状态、治理、权重、证据、回滚",
            "",
            "直接发送一个关键词即可；也支持自然语言，比如“现在是不是 ACTIVE_OK”“这次回滚线是多少”。",
            "",
            "- `建议` / `状态`: 当前执行结论",
            "- `治理`: ACTIVE_OK、相对 NAV 回撤、执行负担、复核线、回滚线",
            "- `权重`: 五个袖珍组合的当前执行权重",
            "- `证据`: 相对固定权重的收益、回撤、Sharpe 证据",
            "- `回滚`: 什么时候复核、什么时候回到固定 10/15/15/20/40",
            "- `完整`: 展示完整快照",
            "",
            "这个机器人只展示已验证的 Level-8 组合建议快照，不运行 V7.6 主策略，也不读取本地 CSV。",
        ]
    )


def answer_query(query_text: str | None = None) -> str:
    text = (query_text or "").strip().lower()
    compact = "".join(text.split())
    if not compact or any(token in compact for token in ("help", "帮助", "怎么用", "用法")):
        return render_help()
    if any(token in compact for token in ("完整", "全部", "full", "detail", "详细")):
        return render_level8_advisory()
    if any(token in compact for token in ("治理", "active_ok", "activeok", "review", "复核")):
        return render_governance()
    if any(token in compact for token in ("权重", "仓位", "weight", "weights", "配置")):
        return render_weights()
    if any(token in compact for token in ("证据", "收益", "回撤", "夏普", "sharpe", "evidence", "表现")):
        return render_evidence()
    if any(token in compact for token in ("回滚", "rollback", "固定", "benchmark", "基准")):
        return render_rollback()
    return render_status_summary()


_BOT_SETTINGS = SettingsResponse(
    server_bot_dependencies={},
    introduction_message="V7.6 Level-8 advisory snapshot bot. Send: 建议 / 状态 / 治理 / 权重 / 证据 / 回滚.",
)
poe.update_settings(_BOT_SETTINGS)


class V76Level8AdvisoryBot:
    def run(self):
        with poe.start_message() as msg:
            msg.write(answer_query(getattr(poe.query, "text", "")))


if __name__ == "__main__":
    V76Level8AdvisoryBot().run()
