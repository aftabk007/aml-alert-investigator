"""The review rule: which finished cases may be applied automatically and which go to a person.

Only "close" can be automatic. An escalation or a SAR draft always goes to a person,
because a person has to act on it (the BSA officer edits and files every SAR).

A close is applied automatically only if every check below passes. The first check
that fails gives the reason the analyst sees. The gate does its own lookups in the
bank data (prior SAR, shared device, watchlist date of birth); it does not trust
what the agent says it found.
"""

AUTO_CLOSE_MIN_CONFIDENCE = 0.85
HIGH_IMPACT_AMOUNT = 25000

BASE_REQUIRED = ["get_alert", "get_customer_profile", "get_transactions", "get_case_history"]
REQUIRED_BY_RULE = {
    "WATCHLIST_HIT": ["screen_name"],
    "NEW_DEVICE_TRANSFER": ["get_login_activity"],
    "RAPID_MOVEMENT": ["get_login_activity"],
    "FAN_OUT": ["get_login_activity"],
}


def required_tools(rule):
    return BASE_REQUIRED + REQUIRED_BY_RULE.get(rule, [])


def review(alert, decision, grounding, tools_called, bank):
    """Returns {"route": "auto_close" | "human", "reason": str}."""
    if not decision:
        return {"route": "human", "reason": "no decision: the agent did not finish"}
    kind = decision.get("decision")
    if kind == "sar":
        return {"route": "human", "reason": "SAR draft: the BSA officer reviews, edits and files"}
    if kind == "escalate":
        return {"route": "human", "reason": "escalation: an analyst acts on it"}

    if grounding.get("unsupported"):
        return {"route": "human", "reason": "narrative has %d fact(s) not backed by evidence" % grounding["unsupported"]}
    missing = [t for t in required_tools(alert["rule"]) if t not in tools_called]
    if missing:
        return {"route": "human", "reason": "investigation incomplete: did not call %s" % ", ".join(missing)}
    cid = alert["customer_id"]
    if alert.get("amount_total", 0) >= HIGH_IMPACT_AMOUNT:
        return {"route": "human", "reason": "high impact: $%s or more" % format(HIGH_IMPACT_AMOUNT, ",")}
    if bank.prior_sar(cid):
        return {"route": "human", "reason": "high impact: customer has a prior SAR"}
    shared = bank.shared_devices(cid)
    if shared:
        return {"route": "human", "reason": "device shared with other customers: %s" % ", ".join(shared)}
    wl = bank.watchlist_dob_match(cid)
    if wl:
        return {"route": "human", "reason": "watchlist entry %s has the same date of birth" % wl}
    conf = decision.get("confidence")
    if not isinstance(conf, (int, float)) or conf < AUTO_CLOSE_MIN_CONFIDENCE:
        return {"route": "human", "reason": "agent confidence %s is below %.2f" % (conf, AUTO_CLOSE_MIN_CONFIDENCE)}
    return {"route": "auto_close", "reason": "all checks passed"}
