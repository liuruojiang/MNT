"""Check completed native query receipts and export a small public summary (no raw HTTP)."""
import argparse
import json
from pathlib import Path
import re
import openpyxl


HANDLERS = {"signal": "信号", "live_signal": "实时信号", "params": "参数", "live_params": "实时参数",
            "history": "信号历史", "chart": "净值曲线", "perf19": "表现", "perf18": "表现", "recent": "表现"}
ATTACHMENTS = {"signal": [".xlsx"], "live_signal": [], "params": [], "live_params": [],
               "history": [], "chart": [".png"], "perf19": [".png", ".xlsx"],
               "perf18": [".png", ".xlsx"], "recent": [".png", ".xlsx"]}
TICKERS = {"QQQM", "GLDM", "PDBC", "IBIT", "AVUV", "AVDV", "EMXC", "DBMF", "KMLM"}


def summarize(store, name):
    r = json.loads((store / (name + ".json")).read_text(encoding="utf-8"))
    private = store / "online_final" if name == "online_final_perf19" else store
    text = (private / "messages" / (name + ".txt")).read_text(encoding="utf-8")
    case = r["case"]
    assert not r["missing_replay_inputs"], (name, r["missing_replay_inputs"])
    assert r["headings"] and HANDLERS[case] in r["headings"][0], (name, r["headings"])
    assert all(x not in text for x in ("查询入口失败", "信号计算/展示失败", "信号查询失败")), name
    expected_exts = ATTACHMENTS[case]
    assert sorted(Path(a["name"]).suffix for a in r["attachments"]) == expected_exts, name
    packages = []
    metadata = {}
    metrics = {}
    for att in r["attachments"]:
        packages.append({k: att[k] for k in ("name", "bytes", "sha256", "sheets", "size") if k in att})
        if "报告元数据" in att:
            metadata = dict(att["报告元数据"])
        if "绩效概览" in att:
            for row in att["绩效概览"]:
                if row[0] in ("累计收益", "年化收益", "最大回撤"):
                    metrics[row[0]] = row[1:]
            yearly = att.get("标准窗口指标", [])
            if yearly:
                metrics["标准1Y组合（年化/最大回撤）"] = yearly[0][-1]
    repaired = set()
    matched = re.search(r"美股已核验补齐[^\n]+?：([^\n]+)", text)
    if matched:
        repaired = set(matched[1].split("、"))
    if name.startswith(("verified", "final_")) or name == "online_final_perf19":
        assert repaired == TICKERS, (name, repaired)
    if name.startswith("no_key"):
        assert not any("tiingo.com" in host for host in r["http"])
        assert "美股回退至共同确认收盘 2026-11-18" in text, name
        if case in ("signal", "live_signal", "params", "live_params"):
            assert "美股本次无可执行信号" in text and text.count("2026-11-18 历史持仓") >= 3, name
        if case == "signal":
            file = private / "attachments" / name / packages[0]["name"]
            workbook = openpyxl.load_workbook(file, read_only=True, data_only=True)
            overview = {row[0]: row[1:] for row in list(workbook["信号概览"].values)[1:]}
            for sleeve in ("B7.8", "B7.9", "Sub-C"):
                assert overview[sleeve][0] == "否" and "2026-11-18 历史持仓" in overview[sleeve][1]
            assert all(row[2] in ("Sub-A", "ADK策略 (100%)") for row in list(workbook["调仓记录"].values)[1:])
            workbook.close()
    if name == "healthy_perf18_early":
        assert not repaired and not any("tiingo.com" in host for host in r["http"])
        assert round(metrics["累计收益"][-1] * 100, 2) == 10.87
        assert round(metrics["年化收益"][-1] * 100, 2) == 10.88
        assert round(metrics["最大回撤"][-1] * 100, 2) == -8.87
    if name in ("verified_perf19", "online_final_perf19"):
        assert metadata["actual_end"] == "2026-11-19" and metadata["requested_end"] == "2026-11-19"
        assert [round(x * 100, 2) for x in metrics["累计收益"]] == [19.81, -0.94, 13.82, 17.40, 6.24, 10.95]
        assert round(metrics["年化收益"][-1] * 100, 2) == 10.95
        assert round(metrics["最大回撤"][-1] * 100, 2) == -8.91
        assert metrics["标准1Y组合（年化/最大回撤）"] == "11.78% / -8.95%"
    excerpt_keys = ("请求区间：", "美股本次无可执行信号", "美股 B7.8 / B7.9 / Sub-C：", "报价时间：",
                    "本次无完整", "历史数据截至", "可用截至")
    evidence = list(dict.fromkeys(line.strip()[:155] for line in text.splitlines()
                                  if any(key in line for key in excerpt_keys)))
    result = {"query": r["query"], "source_sha256": r["source_sha256"], "mode": r["mode"],
              "test_clock_bj": r["start_bj"], "seconds": r["seconds"], "message_title": r["headings"][0],
              "attachments": packages, "verified_tickers": sorted(repaired), "evidence": evidence,
              "network_calls": sum(n for key, n in r["http"].items() if key.startswith("online:")),
              "replayed_calls": sum(n for key, n in r["http"].items() if key.startswith("replay:"))}
    if metadata:
        result["report_dates"] = {k: metadata[k] for k in ("requested_start", "requested_end", "actual_start", "actual_end", "run_id")}
    if metrics:
        result["metrics_A_ADK_B78_B79_C_PV"] = metrics
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    requests = ["healthy_perf18_early", "online_final_perf19", "verified_recent"]
    cases = ("signal", "live_signal", "params", "live_params", "perf19", "chart", "history")
    requests += [("final_" if case in ("signal", "live_signal", "history") else "verified_") + case
                 for case in cases]
    requests += ["no_key_" + case for case in cases]
    receipts = {name: summarize(args.store, name) for name in requests}
    args.output.write_text(json.dumps(receipts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(receipts)} verified native query receipts: {args.output}")
