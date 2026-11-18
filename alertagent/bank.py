"""Read-only access to the synthetic bank in data/*.json.

Each function plays one of the systems a bank analyst opens for an alert:
alert queue, KYC/CDD, core banking (cash, ACH, wires, P2P), counterparty
records, digital banking logins, case history (prior alerts, SARs, CTRs,
notes) and name screening.
"""

import json
import os
import re
from datetime import date, timedelta
from difflib import SequenceMatcher

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
MAX_ROWS = 100
DEFAULT_LOOKBACK_DAYS = 45


def _norm(name):
    name = re.sub(r"[^a-z ]", " ", name.lower())
    return " ".join(name.split())


def name_score(a, b):
    """Similarity of two names, 0..1. Word order does not matter."""
    a, b = _norm(a), _norm(b)
    plain = SequenceMatcher(None, a, b).ratio()
    sorted_ = SequenceMatcher(None, " ".join(sorted(a.split())), " ".join(sorted(b.split()))).ratio()
    return round(max(plain, sorted_), 2)


class Bank:
    def __init__(self, data_dir=DATA_DIR):
        with open(os.path.join(data_dir, "bank.json")) as f:
            bank = json.load(f)
        with open(os.path.join(data_dir, "alerts.json")) as f:
            alerts = json.load(f)
        self.meta = bank["meta"]
        self.today = date.fromisoformat(self.meta["bank_today"])
        self.customers = bank["customers"]
        self.counterparties = bank["counterparties"]
        self.transactions = bank["transactions"]
        self.logins = bank["logins"]
        self.case_history = bank["case_history"]
        self.watchlist = bank["watchlist"]
        self.alerts = {a["alert_id"]: a for a in alerts}

    # ---- the systems ------------------------------------------------------
    def get_alert(self, alert_id):
        a = self.alerts.get(alert_id)
        if not a:
            raise KeyError("No alert with id %s." % alert_id)
        return dict(a)

    def get_customer_profile(self, customer_id):
        c = self.customers.get(customer_id)
        if not c:
            raise KeyError("No customer with id %s." % customer_id)
        out = dict(c)
        if c.get("dob"):
            born = date.fromisoformat(c["dob"])
            out["age"] = self.today.year - born.year - ((self.today.month, self.today.day) < (born.month, born.day))
        return out

    def get_transactions(self, customer_id, start_date=None, end_date=None, types=None, counterparty_id=None):
        if customer_id not in self.customers:
            raise KeyError("No customer with id %s." % customer_id)
        end = date.fromisoformat(end_date) if end_date else self.today
        start = date.fromisoformat(start_date) if start_date else end - timedelta(days=DEFAULT_LOOKBACK_DAYS)
        if start > end:
            raise ValueError("start_date is after end_date.")
        rows = [t for t in self.transactions
                if t["customer_id"] == customer_id and start <= date.fromisoformat(t["date"]) <= end
                and (not types or t["type"] in types)
                and (not counterparty_id or t["counterparty_id"] == counterparty_id)]
        total_in = round(sum(t["amount"] for t in rows if t["direction"] == "in"), 2)
        total_out = round(sum(t["amount"] for t in rows if t["direction"] == "out"), 2)
        shown = rows[-MAX_ROWS:]
        out = {
            "customer_id": customer_id, "start_date": str(start), "end_date": str(end),
            "total_rows": len(rows), "returned": len(shown), "total_in": total_in, "total_out": total_out,
            "rows": [{k: v for k, v in t.items() if v not in (None, "") and k != "customer_id"} for t in shown],
        }
        if len(rows) > len(shown):
            out["note"] = "Only the newest %d rows are shown. Use a shorter date range or a type filter." % MAX_ROWS
        return out

    def get_counterparty(self, counterparty_id, customer_id=None):
        cp = self.counterparties.get(counterparty_id)
        if not cp:
            raise KeyError("No counterparty with id %s." % counterparty_id)
        out = {k: v for k, v in cp.items() if v not in (None, "")}
        if customer_id:
            rows = [t for t in self.transactions
                    if t["counterparty_id"] == counterparty_id and t["customer_id"] == customer_id]
            out["with_this_customer"] = {
                "payments_since_2026_08_01": len(rows),
                "first_payment_since_2026_08_01": rows[0]["date"] if rows else None,
                "last_payment": rows[-1]["date"] if rows else None,
                "total_amount_since_2026_08_01": round(sum(t["amount"] for t in rows), 2),
            }
        return out

    def get_login_activity(self, customer_id, days=30):
        if customer_id not in self.customers:
            raise KeyError("No customer with id %s." % customer_id)
        since = self.today - timedelta(days=int(days))
        rows = [dict(l) for l in self.logins
                if l["customer_id"] == customer_id and date.fromisoformat(l["timestamp"][:10]) >= since]
        for r in rows:
            r.pop("customer_id", None)
            shared = sorted({l["customer_id"] for l in self.logins if l["device_id"] == r["device_id"]} - {customer_id})
            r["other_customers_on_this_device"] = shared
        rows.sort(key=lambda r: r["timestamp"])
        return {"customer_id": customer_id, "since": str(since), "events": rows}

    def get_case_history(self, customer_id):
        if customer_id not in self.customers:
            raise KeyError("No customer with id %s." % customer_id)
        rows = [{k: v for k, v in r.items() if k != "customer_id"} for r in self.case_history if r["customer_id"] == customer_id]
        rows.sort(key=lambda r: r["date"])
        return {"customer_id": customer_id, "records": rows,
                "note": "Includes prior alerts, SARs, CTRs filed, KYC reviews, teller and call notes."}

    def screen_name(self, name, threshold=0.8):
        hits = []
        for e in self.watchlist:
            score = max([name_score(name, e["name"])] + [name_score(name, a) for a in e.get("aliases", [])])
            if score >= threshold:
                rec = {k: v for k, v in e.items() if v is not None}
                rec["name_score"] = score
                hits.append(rec)
        hits.sort(key=lambda h: -h["name_score"])
        return {"searched_name": name, "candidates": hits,
                "note": "Candidates are possible matches by name only. Compare date of birth, nationality and location before deciding."}

    # ---- used by the review gate (its own lookups, not the agent's) ---------
    def prior_sar(self, customer_id):
        return any(r["customer_id"] == customer_id and r["kind"] == "sar_filed" for r in self.case_history)

    def shared_devices(self, customer_id, days=30):
        since = self.today - timedelta(days=days)
        mine = {l["device_id"] for l in self.logins if l["customer_id"] == customer_id
                and date.fromisoformat(l["timestamp"][:10]) >= since}
        return sorted({l["customer_id"] for l in self.logins if l["device_id"] in mine} - {customer_id})

    def watchlist_dob_match(self, customer_id):
        c = self.customers[customer_id]
        name = c.get("name", "")
        for e in self.watchlist:
            score = max([name_score(name, e["name"])] + [name_score(name, a) for a in e.get("aliases", [])])
            if score >= 0.8 and e.get("dob") and e.get("dob") == c.get("dob"):
                return e["entry_id"]
        return None
