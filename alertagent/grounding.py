"""Checks that the case narrative only states facts the tools returned.

Plain code, no LLM. For each statement:
  1. it must cite at least one evidence id,
  2. every cited id must come from a tool result the agent actually got in this case,
  3. every money amount in the text must be in the cited records
     (a total is fine when it is the sum of the cited amounts),
  4. every date (YYYY-MM-DD) in the text must be in the cited records.

Amounts from the bank's own procedure (the $10,000 CTR line, the $5,000 SAR line) are always allowed.
It cannot check words ("the customer seemed rushed"), only citations, money and dates.
"""

import re

MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s?([kKmM])?(?![\w])")
DATE = re.compile(r"(?<!\d)(20\d\d-\d\d-\d\d)(?!\d)")  # also inside timestamps like 2026-11-12T08:05:00
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
WORD_DATE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? (\d{1,2}),? (20\d\d)\b", re.I)
TOLERANCE = 0.5
POLICY_AMOUNTS = {10000.0, 5000.0}


def money_values(text):
    out = []
    for whole, frac, suffix in MONEY.findall(text or ""):
        v = float(whole.replace(",", "") + (frac or ""))
        if suffix in ("k", "K"):
            v *= 1000
        elif suffix in ("m", "M"):
            v *= 1000000
        out.append(v)
    return out


def dates_in_text(text):
    """ISO dates, and written dates like "November 7, 2026" turned into 2026-11-07."""
    found = set(DATE.findall(text or ""))
    for mon, day, year in WORD_DATE.findall(text or ""):
        found.add("%s-%02d-%02d" % (year, MONTHS.index(mon[:3].lower()) + 1, int(day)))
    return found


def _walk(rec, nums, dates):
    if isinstance(rec, dict):
        for v in rec.values():
            _walk(v, nums, dates)
    elif isinstance(rec, list):
        for v in rec:
            _walk(v, nums, dates)
    elif isinstance(rec, bool):
        return
    elif isinstance(rec, (int, float)):
        nums.add(round(float(rec), 2))
    elif isinstance(rec, str):
        dates.update(DATE.findall(rec))
        for v in money_values(rec):
            nums.add(round(v, 2))
        for m in re.findall(r"\b\d{1,3}(?:,\d{3})+\b|\b\d{4,}\b", rec):
            nums.add(float(m.replace(",", "")))


def facts_of(records):
    nums, dates = set(), set()
    for r in records:
        _walk(r, nums, dates)
    return nums, dates


def _amount_sums(records):
    amts = [r["amount"] for r in records if isinstance(r, dict) and isinstance(r.get("amount"), (int, float))]
    sums = set()
    if amts:
        sums.add(round(sum(amts), 2))
        for direction in ("in", "out"):
            part = [r["amount"] for r in records if isinstance(r, dict) and r.get("direction") == direction
                    and isinstance(r.get("amount"), (int, float))]
            if part:
                sums.add(round(sum(part), 2))
    return sums


def _has(value, nums):
    return any(abs(value - n) <= TOLERANCE for n in nums)


def check_statement(stmt, seen):
    """seen = {evidence_id: record} from this case's tool results. Returns a list of problems (empty = supported)."""
    problems = []
    text = stmt.get("text", "") if isinstance(stmt, dict) else ""
    ids = stmt.get("evidence_ids") or [] if isinstance(stmt, dict) else []
    if not ids:
        return ["no evidence cited"]
    unknown = [i for i in ids if i not in seen]
    if unknown:
        problems.append("cites ids no tool returned: %s" % ", ".join(unknown))
    cited = [seen[i] for i in ids if i in seen]
    nums, dates = facts_of(cited)
    nums |= _amount_sums(cited) | POLICY_AMOUNTS
    for v in money_values(text):
        if not _has(v, nums):
            problems.append("amount $%s not in the cited records" % format(v, ",.2f").replace(".00", ""))
    for dt in sorted(dates_in_text(text)):
        if dt not in dates:
            problems.append("date %s not in the cited records" % dt)
    return problems


def check_sar_draft(draft, seen, statements):
    """Money and dates in the SAR draft must appear in some record the agent saw, or be a sum of one statement's cited amounts."""
    if not draft:
        return []
    nums, dates = facts_of(list(seen.values()))
    nums |= POLICY_AMOUNTS
    for s in statements or []:
        cited = [seen[i] for i in (s.get("evidence_ids") or []) if i in seen]
        nums |= _amount_sums(cited)
    problems = []
    for v in money_values(draft):
        if not _has(v, nums):
            problems.append("amount $%s not in any record seen" % format(v, ",.2f").replace(".00", ""))
    for dt in sorted(dates_in_text(draft)):
        if dt not in dates:
            problems.append("date %s not in any record seen" % dt)
    return problems


def check_case(decision, seen):
    statements = (decision or {}).get("statements") or []
    results = []
    for s in statements:
        results.append({"text": s.get("text", "") if isinstance(s, dict) else str(s),
                        "evidence_ids": (s.get("evidence_ids") or []) if isinstance(s, dict) else [],
                        "problems": check_statement(s, seen)})
    sar = check_sar_draft((decision or {}).get("sar_draft", ""), seen, statements) if (decision or {}).get("decision") == "sar" else []
    return {
        "statements": len(results),
        "unsupported": sum(1 for r in results if r["problems"]),
        "details": [r for r in results if r["problems"]],
        "sar_draft_problems": sar,
    }
