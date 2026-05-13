# poe: name=V76-Level8-Advisory
# poe: privacy_shield=half
"""Single-file Poe bot for V7.6 Level-8 portfolio advisory display."""

import csv
from datetime import datetime, timedelta, timezone
import io

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


GITHUB_RAW_BASE = "https://raw.githubusercontent.com/liuruojiang/MNT/main/"
GITHUB_API_CONTENTS_BASE = "https://api.github.com/repos/liuruojiang/MNT/contents/"
REMOTE_DASHBOARD_PATH = "outputs/portfolio_v76_current/level8_decision_dashboard.csv"
REMOTE_GOVERNANCE_PATH = "outputs/portfolio_v76_current/level8_risk_governance.csv"
STACKED_SCENARIO = "advisory_suba_microcap_dd_3_10_month_end"


LEVEL8_ADVISORY_SNAPSHOT = {
    "snapshot_date": "2026-05-14",
    "latest_data_date": "2026-05-13",
    "status": "ACTIVE_DEFAULT",
    "scenario": "advisory_suba_microcap_dd_3_10_month_end",
    "active_scenario": "advisory_suba_microcap_dd_3_10_month_end",
    "dynamic_sleeves": "Sub-A,Microcap",
    "primary_action": "Use stacked Sub-A 5/8 weekly + Microcap 3/10 month-end as the active portfolio-level dynamic budget; keep fixed weights as benchmark and rollback.",
    "source_note": "Embedded from the local Level-8 dashboard run verified on 2026-05-13.",
    "sleeves": [
        {"name": "Sub-A", "weight": 0.15, "role": "dynamic"},
        {"name": "Sub-A-DK", "weight": 0.15, "role": "fixed"},
        {"name": "Microcap", "weight": 0.15, "role": "dynamic"},
        {"name": "Sub-D", "weight": 0.20, "role": "fixed"},
        {"name": "Sub-B", "weight": 0.35, "role": "absorber"},
    ],
    "metrics": {
        "full_annual_delta": 0.0221513990876998,
        "full_max_dd_delta": 0.0074693853012305,
        "full_sharpe_delta": 0.1756014830007823,
        "last_1y_annual_delta": 0.0390101322884282,
        "last_1y_max_dd_delta": 0.0014198890391455,
        "last_1y_sharpe_delta": 0.375830048628277,
        "latest_excess_nav_vs_fixed": 0.2745850450197049,
    },
    "governance": {
        "status": "ACTIVE_OK",
        "relative_nav_drawdown": "current -0.38%, worst -3.37%",
        "execution_load": "switches 128, turnover 14.3",
        "review_ok_condition": "> -5.00%",
        "review_trigger": "<= -5.00%",
        "rollback_line": "<= -10.00%",
    },
}


def _csv_rows(text):
    return list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))


def _float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _status_priority(status):
    return {
        "ROLLBACK_FIXED": 0,
        "REVIEW": 1,
        "ACTIVE_OK": 2,
        "INFO": 3,
    }.get(status, 9)


def _read_url_text(path):
    from urllib.parse import quote
    from urllib.request import Request, urlopen

    api_url = f"{GITHUB_API_CONTENTS_BASE}{quote(path, safe='/')}?ref=main"
    request = Request(
        api_url,
        headers={
            "Accept": "application/vnd.github.raw",
            "User-Agent": "v76-level8-advisory-bot",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.read().decode("utf-8-sig")
    except Exception:
        with urlopen(GITHUB_RAW_BASE + path, timeout=15) as response:
            return response.read().decode("utf-8-sig")


def parse_snapshot_from_csv_texts(dashboard_csv, governance_csv):
    dashboard = _csv_rows(dashboard_csv)
    governance_rows = _csv_rows(governance_csv)
    active_rows = [
        row
        for row in dashboard
        if row.get("scenario") == STACKED_SCENARIO and row.get("candidate_status") == "ACTIVE_DEFAULT"
    ]
    if not active_rows:
        active_rows = [row for row in dashboard if row.get("candidate_status") == "ACTIVE_DEFAULT"]
    if not active_rows:
        raise ValueError("missing ACTIVE_DEFAULT row in dashboard")
    active = active_rows[0]

    governance_statuses = [row.get("status", "") for row in governance_rows if row.get("status")]
    governance_status = (
        sorted(governance_statuses, key=_status_priority)[0]
        if governance_statuses
        else "UNKNOWN"
    )
    governance_by_rule = {row.get("rule", ""): row for row in governance_rows}
    relative_dd = governance_by_rule.get("relative_nav_drawdown", {})
    execution_load = governance_by_rule.get("execution_load", {})

    return {
        "snapshot_date": "GitHub main",
        "latest_data_date": active.get("latest_date", "n/a"),
        "status": active.get("candidate_status", "UNKNOWN"),
        "scenario": active.get("scenario", "n/a"),
        "active_scenario": active.get("scenario", "n/a"),
        "dynamic_sleeves": active.get("dynamic_sleeves", "n/a"),
        "primary_action": active.get(
            "primary_action",
            "Use the active Level-8 portfolio budget; keep fixed weights as benchmark and rollback.",
        ),
        "source_note": "Loaded live from GitHub main outputs/portfolio_v76_current. Freshness depends on the latest committed refresh.",
        "sleeves": [
            {"name": "Sub-A", "weight": _float(active.get("latest_suba")), "role": "dynamic"},
            {"name": "Sub-A-DK", "weight": _float(active.get("latest_subadk")), "role": "fixed"},
            {"name": "Microcap", "weight": _float(active.get("latest_microcap")), "role": "dynamic"},
            {"name": "Sub-D", "weight": _float(active.get("latest_subd")), "role": "fixed"},
            {"name": "Sub-B", "weight": _float(active.get("latest_subb")), "role": "absorber"},
        ],
        "metrics": {
            "full_annual_delta": _float(active.get("full_annual_delta")),
            "full_max_dd_delta": _float(active.get("full_max_dd_delta")),
            "full_sharpe_delta": _float(active.get("full_sharpe_delta")),
            "last_1y_annual_delta": _float(active.get("last_1y_annual_delta")),
            "last_1y_max_dd_delta": _float(active.get("last_1y_max_dd_delta")),
            "last_1y_sharpe_delta": _float(active.get("last_1y_sharpe_delta")),
            "latest_excess_nav_vs_fixed": _float(active.get("latest_excess_nav_vs_fixed")),
        },
        "governance": {
            "status": governance_status,
            "relative_nav_drawdown": relative_dd.get("value", "n/a"),
            "execution_load": execution_load.get("value", "n/a"),
            "review_ok_condition": "> -5.00%",
            "review_trigger": "<= -5.00%",
            "rollback_line": "<= -10.00%",
        },
    }


def load_snapshot():
    try:
        dashboard_csv = _read_url_text(REMOTE_DASHBOARD_PATH)
        governance_csv = _read_url_text(REMOTE_GOVERNANCE_PATH)
        return _with_snapshot_freshness(parse_snapshot_from_csv_texts(dashboard_csv, governance_csv))
    except Exception as exc:
        fallback = dict(LEVEL8_ADVISORY_SNAPSHOT)
        fallback["source_note"] = (
            f"Embedded fallback snapshot because GitHub main output load failed: {exc}"
        )
        return _with_snapshot_freshness(fallback)


def _coerce_date(value=None):
    if value is None:
        return (datetime.now(timezone.utc) + timedelta(hours=8)).date()
    if hasattr(value, "date"):
        return value.date()
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _latest_required_close_date(current_date=None):
    day = _coerce_date(current_date)
    required = day - timedelta(days=1)
    while required.weekday() >= 5:
        required -= timedelta(days=1)
    return required


def _with_snapshot_freshness(snap, current_date=None):
    checked = dict(snap)
    required = _latest_required_close_date(current_date)
    checked["required_close_date"] = required.isoformat()
    try:
        latest = _coerce_date(checked.get("latest_data_date"))
    except Exception:
        latest = None
    is_stale = latest is None or latest < required
    checked["is_stale"] = bool(is_stale)
    if is_stale:
        latest_text = checked.get("latest_data_date", "n/a")
        checked["status"] = "STALE_SNAPSHOT"
        checked["primary_action"] = (
            f"Do not use this as a current execution instruction. "
            f"Latest data date {latest_text} is older than required close {required.isoformat()}."
        )
        checked["source_note"] = (
            f"STALE: latest data date {latest_text} < required close {required.isoformat()}. "
            f"{checked.get('source_note', '')}"
        ).strip()
    return checked


def _pct(value: float) -> str:
    return f"{float(value):.2%}"


def _weight(value: float) -> str:
    return f"{float(value):.0%}"


def _status_weight_text(snap) -> str:
    ordered = ["Sub-A", "Sub-A-DK", "Microcap", "Sub-D", "Sub-B"]
    weights = {sleeve["name"]: sleeve["weight"] for sleeve in snap.get("sleeves", [])}
    return ", ".join(f"{name} {_weight(weights[name])}" for name in ordered if name in weights)


def render_level8_advisory(snap=None) -> str:
    snap = snap or load_snapshot()
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
            f"| Review line | {governance['review_ok_condition']} |",
            f"| Rollback line | {governance['rollback_line']} |",
            "",
            "This is the active portfolio-level dynamic budget snapshot. Fixed 10/15/15/20/40 remains the benchmark and rollback line.",
            "",
            f"Snapshot note: {snap['source_note']}",
        ]
    )
    return "\n".join(lines)


def render_status_summary(snap=None) -> str:
    snap = snap or load_snapshot()
    metrics = snap["metrics"]
    governance = snap["governance"]
    return "\n".join(
        [
            "## 当前建议",
            "",
            f"- 状态: **{snap['status']}** / governance **{governance['status']}**",
            f"- 数据日期: `{snap['latest_data_date']}`",
            f"- 执行权重: {_status_weight_text(snap)}",
            "- 动态袖珍: Sub-A + Microcap",
            "- 回滚基准: 固定 10/15/15/20/40",
            f"- 相对固定超额 NAV: {_pct(metrics['latest_excess_nav_vs_fixed'])}",
            f"- 相对 NAV 回撤: {governance['relative_nav_drawdown']}",
            f"- 数据来源: {snap['source_note']}",
        ]
    )


def render_weights(snap=None) -> str:
    snap = snap or load_snapshot()
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
            f"数据来源: {snap['source_note']}",
        ]
    )
    return "\n".join(lines)


def render_evidence(snap=None) -> str:
    snap = snap or load_snapshot()
    metrics = snap["metrics"]
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
            "",
            f"数据来源: {snap['source_note']}",
        ]
    )


def render_governance(snap=None) -> str:
    snap = snap or load_snapshot()
    governance = snap["governance"]
    return "\n".join(
        [
            "## 治理状态",
            "",
            f"- 状态: **{governance['status']}**",
            f"- 相对 NAV 回撤: {governance['relative_nav_drawdown']}",
            f"- 执行负担: {governance['execution_load']}",
            f"- 复核线: {governance['review_ok_condition']}",
            f"- 回滚线: {governance['rollback_line']}",
            "",
            "解释:",
            "",
            "- ACTIVE_OK: 所有治理规则通过，stacked 动态仓位可以继续作为 active budget。",
            "- relative NAV DD: 动态方案相对固定 10/15/15/20/40 的超额 NAV，从自身高点回撤了多少；不是组合自身最大回撤。",
            "- current: 当前超额优势比自己的历史高点低多少。",
            "- worst: 样本期最差相对回撤。",
            "- switches: 样本期动态预算切换/再平衡次数。",
            "- turnover: 样本期组合层权重调整的累计负担；当前阈值是 switches <= 140 且 turnover <= 15.0。",
            f"- review line {governance['review_ok_condition']}: 相对回撤保持在 -5% 以内就继续执行；跌到 {governance['review_trigger'].replace('.00%', '%')} 进入复核。",
            f"- 数据来源: {snap['source_note']}",
        ]
    )


def render_rollback(snap=None) -> str:
    snap = snap or load_snapshot()
    governance = snap["governance"]
    return "\n".join(
        [
            "## 回滚线",
            "",
            "- 正常: governance 保持 ACTIVE_OK，继续使用 stacked 动态仓位。",
            f"- 复核: 相对 NAV 回撤到 {governance['review_trigger']} 时，暂停新增 Level-8 晋级并检查规则。",
            f"- 回滚: 相对 NAV 回撤到 {governance['rollback_line']} 时，回到固定 10/15/15/20/40。",
            "- 固定权重一直保留为 benchmark / rollback，不删除。",
            f"- 数据来源: {snap['source_note']}",
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
            "这个机器人默认读取 GitHub main 已提交的 Level-8 输出；如果网络失败，才回退到内置快照。它不在 Poe 内部运行完整 V7.6 主策略。",
        ]
    )


def answer_query(query_text: str | None = None) -> str:
    text = (query_text or "").strip().lower()
    compact = "".join(text.split())
    if not compact or any(token in compact for token in ("help", "帮助", "怎么用", "用法")):
        return render_help()
    snap = load_snapshot()
    if any(token in compact for token in ("完整", "全部", "full", "detail", "详细")):
        return render_level8_advisory(snap)
    if any(token in compact for token in ("治理", "active_ok", "activeok", "review", "复核")):
        return render_governance(snap)
    if any(token in compact for token in ("权重", "仓位", "weight", "weights", "配置")):
        return render_weights(snap)
    if any(token in compact for token in ("证据", "收益", "回撤", "夏普", "sharpe", "evidence", "表现")):
        return render_evidence(snap)
    if any(token in compact for token in ("回滚", "rollback", "固定", "benchmark", "基准")):
        return render_rollback(snap)
    return render_status_summary(snap)


_BOT_SETTINGS = SettingsResponse(
    server_bot_dependencies={},
    introduction_message="V7.6 Level-8 advisory bot. Reads GitHub main outputs; send: 建议 / 状态 / 治理 / 权重 / 证据 / 回滚.",
)
poe.update_settings(_BOT_SETTINGS)


class V76Level8AdvisoryBot:
    def run(self):
        with poe.start_message() as msg:
            msg.write(answer_query(getattr(poe.query, "text", "")))


if __name__ == "__main__":
    V76Level8AdvisoryBot().run()
