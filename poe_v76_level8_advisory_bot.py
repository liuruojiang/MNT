# poe: name=V76-Level8-Advisory
# poe: privacy_shield=half
"""Single-file Poe bot for V7.6 Level-8 portfolio advisory display."""
from __future__ import annotations

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


def render_help() -> str:
    return "\n".join(
        [
            "# V76-Level8-Advisory",
            "",
            "可问：",
            "- 现在组合建议是什么",
            "- 当前 ACTIVE_DEFAULT 状态",
            "- 当前 ACTIVE_OK 治理状态",
            "- 五个袖珍组合权重",
            "- 这个是不是执行默认",
            "",
            "这个机器人只展示已验证的 Level-8 组合建议快照，不运行 V7.6 主策略，也不读取本地 CSV。",
        ]
    )


def answer_query(query_text: str | None = None) -> str:
    text = (query_text or "").strip().lower()
    if not text or any(token in text for token in ("help", "帮助", "怎么用")):
        return render_help()
    return render_level8_advisory()


_BOT_SETTINGS = SettingsResponse(
    server_bot_dependencies={},
    introduction_message="V7.6 Level-8 advisory snapshot bot. Ask for the current portfolio advisory.",
)
poe.update_settings(_BOT_SETTINGS)


class V76Level8AdvisoryBot:
    def run(self):
        with poe.start_message() as msg:
            msg.write(answer_query(getattr(poe.query, "text", "")))


if __name__ == "__main__":
    V76Level8AdvisoryBot().run()
