"""Rule-based baseline: the kind of if-then disposition script a team writes without an LLM.

It calls the same tools (so tool calls are counted the same way) and decides with one
fixed rule per alert type. It writes a short template narrative with citations.
"""

from datetime import date, timedelta

from .tools import call_tool

NEAR_LOW, NEAR_HIGH = 8000, 10000


def _d(s):
    return date.fromisoformat(s)


def _money(v):
    return "$" + format(v, ",.2f").replace(".00", "")


def run_baseline(alert_id, bank):
    steps = []

    def tool(tool_name, **args):
        result, is_err = call_tool(bank, tool_name, args)
        steps.append({"turn": 1, "tool": tool_name, "args": args, "is_error": is_err, "result": result})
        return result

    alert = tool("get_alert", alert_id=alert_id)
    cid, rule, when = alert["customer_id"], alert["rule"], _d(alert["date"])
    profile = tool("get_customer_profile", customer_id=cid)
    txs = tool("get_transactions", customer_id=cid, start_date="2026-08-01")["rows"]
    tool("get_case_history", customer_id=cid)
    logins = tool("get_login_activity", customer_id=cid)["events"] if rule in ("RAPID_MOVEMENT", "FAN_OUT", "NEW_DEVICE_TRANSFER") else []

    def window(days):
        return [t for t in txs if when - timedelta(days=days) <= _d(t["date"]) <= when]

    decision, typology, facts = "close", "none (no rule hit)", []
    a_ev = alert["evidence_id"]
    if rule in ("CASH_NEAR_CTR", "CASH_AGGREGATE"):
        near = [t for t in window(15) if t["type"] in ("cash_deposit", "cash_withdrawal") and NEAR_LOW <= t["amount"] < NEAR_HIGH]
        if near:
            decision, typology = "sar", "structuring"
            facts.append(("%d cash transactions in the 8,000-9,999 band in 15 days: %s." % (
                len(near), ", ".join("%s on %s" % (_money(t["amount"]), t["date"]) for t in near)), [t["evidence_id"] for t in near]))
        else:
            facts.append(("No cash transactions in the 8,000-9,999 band in the 15 days before the alert.", [a_ev]))
    elif rule == "FAN_OUT":
        outs = [t for t in window(7) if t["direction"] == "out" and t.get("counterparty_id")]
        payees = {t["counterparty_id"] for t in outs}
        if len(payees) >= 8:
            decision, typology = "sar", "fan-out"
        facts.append(("Payments to %d different payees in 7 days." % len(payees), [t["evidence_id"] for t in outs][:12] or [a_ev]))
    elif rule == "FAN_IN":
        ins = [t for t in window(30) if t["direction"] == "in" and t.get("counterparty_id")]
        senders = {t["counterparty_id"] for t in ins}
        if len(senders) >= 25:
            decision, typology = "sar", "fan-in"
        facts.append(("Payments from %d different senders in 30 days." % len(senders), [t["evidence_id"] for t in ins][:12] or [a_ev]))
    elif rule == "RAPID_MOVEMENT":
        for t in window(7):
            if t["direction"] != "in":
                continue
            outs = [o for o in txs if o["direction"] == "out" and 0 <= (_d(o["date"]) - _d(t["date"])).days <= 2]
            total = sum(o["amount"] for o in outs)
            if total >= 0.9 * t["amount"]:
                decision, typology = "sar", "rapid movement"
                facts.append(("%s came in on %s and %s went out within 2 days." % (_money(t["amount"]), t["date"], _money(total)),
                              [t["evidence_id"]] + [o["evidence_id"] for o in outs]))
                break
        if decision == "close":
            facts.append(("No incoming payment was 90% sent out within 2 days.", [a_ev]))
    elif rule == "FUNNEL":
        deps = [t for t in window(7) if t["type"] == "cash_deposit" and t.get("channel") == "shared_branch"]
        places = {t.get("location") for t in deps}
        if len(places) >= 3:
            decision, typology = "sar", "funnel account"
        facts.append(("Cash deposits at %d out-of-area locations in 7 days." % len(places), [t["evidence_id"] for t in deps] or [a_ev]))
    elif rule == "WATCHLIST_HIT":
        hits = tool("screen_name", name=profile["name"])["candidates"]
        if hits and hits[0]["name_score"] >= 0.85:
            decision, typology = "escalate", "possible watchlist match"
            facts.append(("Name score %.2f against list entry %s." % (hits[0]["name_score"], hits[0]["entry_id"]), [hits[0]["evidence_id"]]))
        else:
            facts.append(("No list entry with a name score of 0.85 or more.", [a_ev]))
    elif rule == "ELDER_OUTFLOW":
        recent = window(30)
        older_payees = {t.get("counterparty_id") for t in txs if _d(t["date"]) < when - timedelta(days=30)}
        new_out = [t for t in recent if t["direction"] == "out" and t.get("counterparty_id") not in older_payees]
        total = sum(t["amount"] for t in new_out)
        if profile.get("age", 0) >= 70 and total >= 20000:
            decision, typology = "sar", "elder exploitation"
        facts.append(("Customer is %s; %s sent to new payees in 30 days." % (profile.get("age"), _money(total)),
                      [profile["evidence_id"]] + [t["evidence_id"] for t in new_out]))
    elif rule == "PROFILE_MISMATCH":
        ins = [t for t in window(30) if t["direction"] == "in"]
        total = sum(t["amount"] for t in ins)
        expected = profile["expected_monthly"]["total_in"]
        if total > 3 * expected:
            decision, typology = "escalate", "profile mismatch"
        facts.append(("%s came in over 30 days." % _money(total), [t["evidence_id"] for t in ins]))
    elif rule == "NEW_DEVICE_TRANSFER":
        new_dev = [l for l in logins if _d(l["device_first_seen"]) >= when - timedelta(days=7)]
        outs = [t for t in window(7) if t["direction"] == "out" and t["amount"] >= 5000]
        if new_dev and outs:
            decision, typology = "escalate", "new device + transfer"
            facts.append(("New device %s and a transfer of %s." % (new_dev[0]["device_id"], _money(outs[0]["amount"])),
                          [new_dev[0]["evidence_id"], outs[0]["evidence_id"]]))
    elif rule == "HIGH_RISK_WIRE":
        decision, typology = "escalate", "high-risk jurisdiction"
        facts.append(("Wire to a high-risk jurisdiction.", alert["triggering_transaction_ids"] or [a_ev]))

    facts.insert(0, ("Alert %s fired on %s (rule %s)." % (alert_id, alert["date"], rule), [a_ev]))
    out = {
        "decision": decision, "confidence": 0.9, "typology": typology,
        "statements": [{"text": t, "evidence_ids": ids} for t, ids in facts],
        "next_steps": "Rule-based disposition.",
    }
    if decision == "sar":
        out["sar_draft"] = "Rule %s fired for customer %s. %s" % (rule, profile["name"], facts[-1][0])
    return {"alert_id": alert_id, "agent": "rule-based baseline", "model": None, "outcome": "decided", "error": None,
            "turns": 1, "steps": steps, "decision": out, "usage": {"input": 0, "output": 0, "thinking": 0}, "wall_ms": 0}
