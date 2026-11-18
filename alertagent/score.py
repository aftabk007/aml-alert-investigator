"""Scores saved traces against the answer key. Works offline: no model calls."""

from .grounding import check_case
from .review import review
from .tools import SUBMIT_TOOL, evidence_index


def seen_evidence(trace):
    seen = {}
    for s in trace.get("steps", []):
        if not s.get("is_error"):
            evidence_index(s.get("result"), seen)
    return seen


def score_case(trace, alert, key, bank):
    steps = [s for s in trace.get("steps", []) if s.get("tool") != SUBMIT_TOOL["name"]]
    tools_called = [s["tool"] for s in steps if not s.get("is_error")]
    decision = trace.get("decision")
    g = check_case(decision, seen_evidence(trace)) if decision else {
        "statements": 0, "unsupported": 0, "details": [], "sar_draft_problems": []}
    r = review(alert, decision, g, tools_called, bank)
    got = decision.get("decision") if decision else None
    auto = r["route"] == "auto_close"
    return {
        "alert_id": alert["alert_id"], "rule": alert["rule"], "expected": key["expected"], "got": got,
        "correct": got == key["expected"], "suspicious": key["suspicious"],
        "confidence": decision.get("confidence") if decision else None,
        "route": r["route"], "reason": r["reason"],
        "dangerous": key["suspicious"] and got == "close" and auto,
        "tool_calls": len(steps), "tool_errors": sum(1 for s in steps if s.get("is_error")),
        "statements": g["statements"], "unsupported": g["unsupported"], "unsupported_details": g["details"],
        "sar_draft_problems": g["sar_draft_problems"], "outcome": trace.get("outcome"), "error": trace.get("error"),
        "turns": trace.get("turns", 0), "usage": trace.get("usage", {}), "wall_ms": trace.get("wall_ms", 0),
    }


def summarize(agent, rows):
    n = len(rows)
    sus = [r for r in rows if r["suspicious"]]
    fps = [r for r in rows if not r["suspicious"]]
    return {
        "agent": agent, "alerts": n,
        "decisions_right": sum(r["correct"] for r in rows),
        "suspicious": len(sus),
        "suspicious_not_closed": sum(1 for r in sus if r["got"] in ("escalate", "sar")),
        "suspicious_closed": sum(1 for r in sus if r["got"] == "close"),
        "dangerous_auto_closes": sum(r["dangerous"] for r in rows),
        "false_positives": len(fps),
        "false_positives_closed": sum(1 for r in fps if r["got"] == "close"),
        "false_positives_auto_closed": sum(1 for r in fps if r["route"] == "auto_close"),
        "false_alarms": sum(1 for r in fps if r["got"] in ("escalate", "sar")),
        "statements": sum(r["statements"] for r in rows),
        "unsupported_statements": sum(r["unsupported"] for r in rows),
        "cases_with_unsupported": sum(1 for r in rows if r["unsupported"]),
        "sar_draft_problems": sum(len(r["sar_draft_problems"]) for r in rows),
        "avg_tool_calls": round(sum(r["tool_calls"] for r in rows) / n, 1) if n else 0,
        "sent_to_human": sum(1 for r in rows if r["route"] == "human"),
        "not_decided": sum(1 for r in rows if r["got"] is None),
        "tokens_input": sum(r["usage"].get("input", 0) for r in rows),
        "tokens_output": sum(r["usage"].get("output", 0) + r["usage"].get("thinking", 0) for r in rows),
        "avg_seconds": round(sum(r["wall_ms"] for r in rows) / 1000.0 / n, 1) if n else 0,
    }


def table_row(s):
    return "| %s | %d / %d | %d | %d | %d / %d | %d / %d | %s | %d / %d (%d%%) |" % (
        s["agent"], s["decisions_right"], s["alerts"], s["suspicious_closed"], s["dangerous_auto_closes"],
        s["false_positives_auto_closed"], s["false_positives"], s["unsupported_statements"], s["statements"],
        s["avg_tool_calls"], s["sent_to_human"], s["alerts"], round(100.0 * s["sent_to_human"] / s["alerts"]))


TABLE_HEADER = ("| Investigator | Decisions right | Suspicious alerts it closed | ...closed with no person (must be 0) "
                "| Clean alerts closed with no person | Unsupported facts | Tool calls per alert | Sent to a person |\n"
                "|---|---|---|---|---|---|---|---|")
