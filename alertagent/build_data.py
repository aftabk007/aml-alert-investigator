"""Builds the synthetic bank used by the demo and writes data/*.json.

Everything here is made up: the bank, the people, the companies, the countries
on the watchlist and the watchlist itself. Run it again to rebuild the files:

    python3 -m alertagent.build_data

The answer key (data/answer_key.json) is only read by the scorer. The agent's
tools never read it.
"""

import json
import os
from datetime import date, timedelta

BANK_NAME = "Cedar Valley Community Bank (fictional)"
BANK_TODAY = date(2026, 11, 16)
DATA_START = date(2026, 8, 1)

IN_TYPES = {"cash_deposit", "ach_in", "wire_in", "p2p_in", "transfer_in", "check_deposit"}
OUT_TYPES = {"cash_withdrawal", "ach_out", "wire_out", "p2p_out", "transfer_out", "check_return"}

HOME_BRANCHES = ["Millbrook Main branch", "Millbrook North branch", "Harlow branch", "Eastport branch"]


def d(s):
    return date.fromisoformat(s)


def fridays(start, end, every=14):
    out, x = [], start
    while x <= end:
        out.append(x)
        x += timedelta(days=every)
    return out


def month_days(day, start=DATA_START, end=BANK_TODAY):
    out, y, m = [], start.year, start.month
    while True:
        x = date(y, m, day)
        if x > end:
            break
        if x >= start:
            out.append(x)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


class Builder:
    def __init__(self):
        self.customers = {}
        self.counterparties = {}
        self.transactions = []
        self.logins = []
        self.case_history = []
        self.watchlist = []
        self.alerts = []
        self.answer_key = {}

    # ---- records -------------------------------------------------------
    def customer(self, cid, **kw):
        rec = {"customer_id": cid, "evidence_id": "KYC-" + cid}
        rec.update(kw)
        rec.setdefault("linked_accounts", [])
        rec.setdefault("authorized_agents", [])
        self.customers[cid] = rec
        return cid

    def cp(self, name, kind, **kw):
        cid = "CP-%03d" % (len(self.counterparties) + 1)
        rec = {"counterparty_id": cid, "evidence_id": cid, "name": name, "type": kind}
        rec.update(kw)
        self.counterparties[cid] = rec
        return cid

    def tx(self, cust, day, kind, amount, channel="online", location=None, cp=None, memo=""):
        tid = "T-%04d" % (len(self.transactions) + 1)
        if kind not in IN_TYPES and kind not in OUT_TYPES:
            raise ValueError(kind)
        self.transactions.append({
            "transaction_id": tid, "evidence_id": tid, "customer_id": cust,
            "date": str(day), "type": kind, "direction": "in" if kind in IN_TYPES else "out",
            "amount": float(amount), "channel": channel, "location": location,
            "counterparty_id": cp, "memo": memo,
        })
        return tid

    def login(self, cust, ts, device, first_seen, ip, city, country="US", event="login"):
        lid = "LG-%04d" % (len(self.logins) + 1)
        self.logins.append({
            "login_id": lid, "evidence_id": lid, "customer_id": cust, "timestamp": ts,
            "event": event, "device_id": device, "device_first_seen": first_seen,
            "ip": ip, "ip_city": city, "ip_country": country,
        })
        return lid

    def case(self, cust, day, kind, text, **kw):
        hid = "CH-%03d" % (len(self.case_history) + 1)
        rec = {"record_id": hid, "evidence_id": hid, "customer_id": cust, "date": str(day), "kind": kind, "text": text}
        rec.update(kw)
        self.case_history.append(rec)
        return hid

    def wl(self, list_name, name, **kw):
        wid = "WL-%02d" % (len(self.watchlist) + 1)
        rec = {"entry_id": wid, "evidence_id": wid, "list": list_name, "name": name}
        rec.update(kw)
        self.watchlist.append(rec)
        return wid

    def alert(self, aid, day, rule, cust, amount_total, summary, txns=(), expected=None, typology="", trap="", why=""):
        self.alerts.append({
            "alert_id": aid, "evidence_id": "ALERT-" + aid, "date": str(day), "rule": rule,
            "customer_id": cust, "amount_total": float(amount_total), "summary": summary,
            "triggering_transaction_ids": list(txns),
        })
        self.answer_key[aid] = {
            "expected": expected, "suspicious": expected in ("escalate", "sar"),
            "typology": typology, "trap": trap, "why": why,
        }

    # ---- common background activity -----------------------------------
    def salaried(self, cust, employer_cp, pay, rent, rent_cp, util_cp, first_payday="2026-08-07", rent_memo="RENT"):
        for f in fridays(d(first_payday), BANK_TODAY):
            self.tx(cust, f, "ach_in", pay, cp=employer_cp, memo="PAYROLL")
        for x in month_days(1):
            self.tx(cust, x, "ach_out", rent, cp=rent_cp, memo=rent_memo)
        for i, x in enumerate(month_days(12)):
            self.tx(cust, x, "ach_out", [142.17, 156.40, 131.88, 149.02][i % 4], cp=util_cp, memo="UTILITIES")

    def usual_logins(self, cust, device, first_seen, ip, city="Millbrook, OH", days=(3, 9, 15, 21, 27)):
        for k in days:
            day = BANK_TODAY - timedelta(days=k)
            self.login(cust, "%sT19:%02d:00" % (day, 10 + k), device, first_seen, ip, city)


def build():
    b = Builder()

    # shared counterparties ------------------------------------------------
    util = b.cp("Millbrook Power & Water", "business", relationship_since="2001-01-01", notes="Local utility company.")
    landlord = b.cp("Oakridge Apartments LLC", "business", relationship_since="2010-03-01", notes="Apartment landlord in Millbrook.")
    mortgage = b.cp("Cedar Valley Community Bank mortgage", "own_bank", relationship_since="2000-01-01", notes="Mortgage payments to this bank.")

    # A01: structuring just under $10,000 ----------------------------------
    c = b.customer("C01", name="Tomas Reyes-Hart", dob="1992-05-14", citizenship="US", city="Millbrook, OH",
                   occupation="Store clerk", employer="Northgate Hardware", segment="personal", customer_since="2019-02-11",
                   risk_rating="low", expected_monthly={"cash_in": 500, "total_in": 3200, "total_out": 3000},
                   kyc_last_review="2025-02-11")
    emp = b.cp("Northgate Hardware", "business", relationship_since="2019-02-15", notes="Employer. Pays wages by ACH.")
    b.salaried(c, emp, 1450.00, 1100.00, landlord, util)
    t1 = b.tx(c, d("2026-11-03"), "cash_deposit", 9400, "branch", HOME_BRANCHES[0])
    t2 = b.tx(c, d("2026-11-04"), "cash_deposit", 9200, "branch", HOME_BRANCHES[2])
    t3 = b.tx(c, d("2026-11-06"), "cash_deposit", 9800, "branch", HOME_BRANCHES[3])
    t4 = b.tx(c, d("2026-11-07"), "cash_deposit", 9500, "branch", HOME_BRANCHES[1])
    jax = b.cp("Jaxon Auto Exports LLC", "business", registered="2026-09-01", relationship_since="2026-11-09",
               notes="Registered 2026-09-01 in another state. No website on file.")
    b.tx(c, d("2026-11-09"), "wire_out", 36000, cp=jax, memo="vehicles")
    b.case(c, d("2026-11-03"), "teller_note", "Before depositing, customer asked the teller what amount 'triggers the government form'.")
    b.usual_logins(c, "DV-1A01", "2023-04-02", "73.41.10.2")
    b.alert("A01", d("2026-11-10"), "CASH_NEAR_CTR", c, 37900,
            "2 or more cash deposits between $8,000 and $9,999 within 10 days.", [t1, t2, t3, t4],
            "sar", "structuring", "", "Four deposits of $9,200-$9,800 at four branches in five days, customer asked about the CTR form, money wired out two days later. Cash does not fit a store clerk.")

    # A02: one near-threshold deposit with a documented reason --------------
    c = b.customer("C02", name="Priya Natarajan", dob="1985-08-22", citizenship="US", city="Millbrook, OH",
                   occupation="Dental hygienist", employer="Millbrook Family Dental", segment="personal",
                   customer_since="2014-06-03", risk_rating="low",
                   expected_monthly={"cash_in": 200, "total_in": 5200, "total_out": 4800}, kyc_last_review="2025-06-03")
    emp = b.cp("Millbrook Family Dental", "business", relationship_since="2014-06-10", notes="Employer.")
    b.salaried(c, emp, 2380.00, 1650.00, mortgage, util, rent_memo="MORTGAGE")
    t = b.tx(c, d("2026-11-05"), "cash_deposit", 9600, "branch", HOME_BRANCHES[0], memo="cash - vehicle sale")
    b.case(c, d("2026-11-05"), "teller_note", "Customer sold her 2017 sedan privately. Showed a signed bill of sale and title transfer for $9,600. Copies scanned to the file.")
    b.case(c, d("2025-06-03"), "kyc_review", "Annual review. No cash deposits over $1,000 in the last 12 months.")
    b.usual_logins(c, "DV-2B02", "2022-01-19", "73.41.22.9")
    b.alert("A02", d("2026-11-06"), "CASH_NEAR_CTR", c, 9600, "Single cash deposit between $8,000 and $9,999.", [t],
            "close", "none (explained)", "near-threshold amount alone",
            "One deposit, documented car sale, no other cash. Near $10,000 alone is not enough for a SAR (Oct 2025 FAQ).")

    # A03: structuring far under $10,000, then a wire out --------------------
    c = b.customer("C03", name="Marcus Ellery", dob="1997-03-02", citizenship="US", city="Millbrook, OH",
                   occupation="Rideshare driver (self-employed)", employer="self-employed", segment="personal",
                   customer_since="2023-09-18", risk_rating="low",
                   expected_monthly={"cash_in": 800, "total_in": 3500, "total_out": 3300}, kyc_last_review="2025-09-18")
    ride = b.cp("RideNow Driver Payouts", "business", relationship_since="2023-09-25", notes="Rideshare platform weekly payouts.")
    for f in fridays(d("2026-08-07"), BANK_TODAY, 7):
        b.tx(c, f, "ach_in", [612.40, 701.15, 655.80, 590.25][f.toordinal() % 4], cp=ride, memo="DRIVER PAYOUT")
    for x in month_days(1):
        b.tx(c, x, "ach_out", 1250, cp=landlord, memo="RENT")
    ts = [
        b.tx(c, d("2026-10-27"), "cash_deposit", 4800, "atm", "Millbrook North ATM"),
        b.tx(c, d("2026-10-28"), "cash_deposit", 4900, "branch", HOME_BRANCHES[2]),
        b.tx(c, d("2026-10-30"), "cash_deposit", 4700, "atm", "Eastport ATM"),
        b.tx(c, d("2026-11-01"), "cash_deposit", 4950, "branch", HOME_BRANCHES[0]),
        b.tx(c, d("2026-11-03"), "cash_deposit", 4850, "atm", "Harlow ATM"),
        b.tx(c, d("2026-11-05"), "cash_deposit", 4900, "branch", HOME_BRANCHES[3]),
    ]
    silver = b.cp("Silverline Trading Co", "business", registered="2026-08-20", relationship_since="2026-11-06",
                  notes="Registered 2026-08-20. Account at another bank in another state.")
    b.tx(c, d("2026-11-06"), "wire_out", 28000, cp=silver, memo="goods")
    b.usual_logins(c, "DV-3C03", "2023-09-18", "73.41.30.7")
    b.alert("A03", d("2026-11-07"), "CASH_AGGREGATE", c, 29100,
            "Cash deposits adding up to more than $25,000 within 15 days.", ts,
            "sar", "structuring", "amounts far below $10,000",
            "Six deposits of $4,700-$4,950 at four places in ten days ($29,100), then a $28,000 wire the next day. A filter that only looks near $10,000 misses it.")

    # A04: cash-heavy restaurant with CTRs filed -----------------------------
    c = b.customer("C04", name="Golden Wok Kitchen LLC", owner="Lin Zhao", citizenship="US", city="Millbrook, OH",
                   occupation="Restaurant (cash-intensive business)", segment="business", customer_since="2014-04-07",
                   risk_rating="medium", employees=11,
                   expected_monthly={"cash_in": 70000, "total_in": 95000, "total_out": 90000}, kyc_last_review="2025-04-07")
    supplier = b.cp("Lakeview Food Supply", "business", relationship_since="2014-05-01", notes="Restaurant food supplier.")
    amounts = [8650, 11240, 9900, 12880, 8400, 10650, 9300, 13120, 8800, 11470, 9650, 12300, 8950, 10980,
               9700, 12650, 8600, 11320, 9750, 12400, 9100, 13050, 9400, 11800, 8700, 12150, 9200, 10900, 9550, 12760]
    day, i, near = d("2026-08-03"), 0, []
    while day <= BANK_TODAY and i < len(amounts):
        if day.weekday() in (0, 3):
            amt = amounts[i]
            t = b.tx(c, day, "cash_deposit", amt, "branch", HOME_BRANCHES[0], memo="store receipts")
            if amt > 10000:
                b.case(c, day, "ctr_filed", "Currency transaction report filed for cash deposit of $%s." % format(amt, ","), amount=float(amt))
            elif day >= d("2026-10-17") and 8000 <= amt < 10000:
                near.append((t, amt))
            i += 1
        day += timedelta(days=1)
    for x in month_days(5) + month_days(20):
        b.tx(c, x, "ach_out", 14800, cp=supplier, memo="FOOD SUPPLY INVOICE")
    b.case(c, d("2025-04-07"), "kyc_review", "Annual review. Owner deposits weekend and mid-week takings twice a week. Volumes match the point-of-sale reports we reviewed. CTRs are filed on large days.")
    b.case(c, d("2024-10-21"), "alert_closed", "CASH_NEAR_CTR alert closed: deposits match point-of-sale totals; CTRs filed on days over $10,000.", disposition="closed")
    b.usual_logins(c, "DV-4D04", "2020-02-11", "73.41.44.1")
    b.alert("A04", d("2026-11-14"), "CASH_NEAR_CTR", c, sum(a for _, a in near),
            "3 or more cash deposits between $8,000 and $9,999 within 30 days.", [t for t, _ in near],
            "close", "none (explained)", "cash business near the threshold",
            "Cash fits the restaurant's profile and 2+ years of history, and the owner also deposits over $10,000 with CTRs filed, so there is no sign of avoiding the CTR.")

    # A05: payroll that looks like fan-out ----------------------------------
    c = b.customer("C05", name="Brightline Landscaping LLC", owner="Carla Mendes", citizenship="US", city="Harlow, OH",
                   occupation="Landscaping company", segment="business", customer_since="2019-03-04", risk_rating="low",
                   employees=12, expected_monthly={"cash_in": 0, "total_in": 60000, "total_out": 55000},
                   kyc_last_review="2026-03-02")
    staff = [("Ben Ortiz", 1520.00), ("Mia Sorensen", 1480.00), ("Andre Coleman", 1610.00), ("Lucia Ferraro", 1390.00),
             ("Hassan Idris", 1555.00), ("Jade Whitaker", 1440.00), ("Pavel Novak", 1690.00), ("Rosa Delgado", 1365.00),
             ("Owen Tate", 1505.00), ("Keiko Mori", 1470.00), ("Sam Achebe", 1580.00), ("Nora Lind", 1420.00)]
    staff_cps = [b.cp(n, "individual", relationship_since="2021-0%d-01" % (1 + k % 8), notes="Payee paid by this business with memo PAYROLL.") for k, (n, _) in enumerate(staff)]
    last_run = []
    for f in fridays(d("2026-08-07"), BANK_TODAY):
        last_run = []
        for (n, pay), cpid in zip(staff, staff_cps):
            last_run.append(b.tx(c, f, "ach_out", pay, cp=cpid, memo="PAYROLL"))
    parks = b.cp("Harlow Parks Department", "government", relationship_since="2019-05-01", notes="City parks department. Landscaping contract.")
    hoa = b.cp("Willow Creek HOA", "business", relationship_since="2020-04-01", notes="Homeowners association. Landscaping contract.")
    for x in month_days(10):
        b.tx(c, x, "ach_in", 34500, cp=parks, memo="INVOICE")
        b.tx(c, x + timedelta(days=5), "ach_in", 21800, cp=hoa, memo="INVOICE")
    b.case(c, d("2026-03-02"), "kyc_review", "Annual review. Payroll for 12 staff by ACH every second Friday. Same staff since 2021; seasonal hours vary.")
    b.usual_logins(c, "DV-5E05", "2021-06-01", "73.41.50.5", city="Harlow, OH")
    b.alert("A05", d("2026-11-13"), "FAN_OUT", c, sum(p for _, p in staff),
            "Payments to 10 or more different payees within 7 days.", last_run,
            "close", "none (explained)", "payroll looks like fan-out",
            "Same 12 payees, same amounts, every second Friday since 2021, memo PAYROLL, matches the KYC file.")

    # A06: fan-out mule ------------------------------------------------------
    c = b.customer("C06", name="Kayla Brennan", dob="2004-07-09", citizenship="US", city="Millbrook, OH",
                   occupation="Student (part-time cafe job)", employer="Bean There Cafe", segment="personal",
                   customer_since="2024-01-15", risk_rating="low",
                   expected_monthly={"cash_in": 100, "total_in": 1200, "total_out": 1100}, kyc_last_review="2025-01-15")
    emp = b.cp("Bean There Cafe", "business", relationship_since="2024-01-20", notes="Employer.")
    for f in fridays(d("2026-08-07"), BANK_TODAY):
        b.tx(c, f, "ach_in", 540.00, cp=emp, memo="PAYROLL")
    harbor = b.cp("Harbor Point Consulting", "business", registered="2026-10-02", relationship_since="2026-11-11",
                  notes="Registered 2026-10-02. Sent money to 3 other customers of this bank in November.", other_customers_paid=3)
    okafor = b.cp("R. Okafor", "individual", relationship_since="2026-11-11", notes="No other link to the customer on file.")
    w1 = b.tx(c, d("2026-11-11"), "wire_in", 9500, cp=harbor, memo="project payment")
    w2 = b.tx(c, d("2026-11-11"), "p2p_in", 8500, cp=okafor, memo="for you")
    outs = []
    payees = [("D. Fischer", 2050), ("L. Moreau", 1980), ("K. Adeyemi", 1950), ("P. Quinn", 2100), ("S. Varga", 1890),
              ("T. Holm", 2000), ("M. Ruiz", 1700), ("J. Castillo", 1930), ("E. Novak", 2050)]
    for n, amt in payees:
        p = b.cp(n, "individual", relationship_since="2026-11-12", notes="First payment from this customer on 2026-11-12.")
        outs.append(b.tx(c, d("2026-11-12"), "p2p_out", amt, cp=p))
    b.usual_logins(c, "DV-6F06", "2024-01-15", "73.41.60.3")
    b.login(c, "2026-11-10T23:41:00", "DV-6X99", "2026-11-10", "142.88.7.21", "Toronto", "CA")
    b.login(c, "2026-11-12T08:05:00", "DV-6X99", "2026-11-10", "142.88.7.21", "Toronto", "CA")
    b.alert("A06", d("2026-11-13"), "FAN_OUT", c, sum(a for _, a in payees),
            "Payments to 8 or more different payees within 2 days.", outs,
            "sar", "money mule (pass-through)", "",
            "$18,000 in from two unrelated new senders, $17,650 out to nine new people the next day, new device abroad the night before. Does not fit a student with $1,200/month.")

    # A07: sanctions near-match that is a different person -------------------
    c = b.customer("C07", name="Daniel Varga Moreno", dob="1991-04-12", citizenship="US", place_of_birth="Millbrook, OH",
                   city="Millbrook, OH", occupation="Nurse", employer="Millbrook General Hospital", segment="personal",
                   customer_since="2016-08-30", risk_rating="low",
                   expected_monthly={"cash_in": 100, "total_in": 5600, "total_out": 5200}, kyc_last_review="2025-08-30")
    emp = b.cp("Millbrook General Hospital", "business", relationship_since="2016-09-02", notes="Employer.")
    b.salaried(c, emp, 2610.00, 1820.00, mortgage, util, rent_memo="MORTGAGE")
    wl_dvm = b.wl("SANCTIONS (fictional)", "Daniel Vargas Moreno", aliases=["Dani Vargas"], dob="1967-09-30",
                  nationality="Kestovia (fictional)", program="KESTOVIA-RELATED (fictional)", added="2026-11-11",
                  notes="Former port official of Kestovia. Lives in Kestovia.")
    b.usual_logins(c, "DV-7G07", "2021-03-14", "73.41.70.8")
    b.alert("A07", d("2026-11-12"), "WATCHLIST_HIT", c, 0,
            "Name screening hit after a sanctions list update: customer name is similar to a list entry (score 0.97).", [],
            "close", "none (false match)", "name near-match is a different person",
            "Different surname spelling, DOB 1991 vs 1967, US-born nurse vs Kestovian official.")

    # A08: true sanctions match ---------------------------------------------
    c = b.customer("C08", name="Marat Oskolov", dob="1972-02-03", citizenship="Kestovia (fictional)", city="Eastport, OH",
                   occupation="Import consultant", employer="self-employed", segment="personal",
                   customer_since="2026-07-14", risk_rating="medium",
                   expected_monthly={"cash_in": 0, "total_in": 15000, "total_out": 12000}, kyc_last_review="2026-07-14")
    belf = b.cp("Belmora Freight Ltd", "business", country="Free Port of Belmora (fictional)", registered="2025-12-01",
                relationship_since="2026-10-20", notes="Freight company in Belmora (fictional).")
    kes = b.cp("Kestovia Port Services JSC", "business", country="Kestovia (fictional)", registered="2011-05-20",
               relationship_since="2026-10-24", notes="Port services company in Kestovia (fictional).")
    b.tx(c, d("2026-10-20"), "wire_in", 40000, cp=belf, memo="consulting")
    b.tx(c, d("2026-10-24"), "wire_out", 15000, cp=kes, memo="services")
    b.wl("SANCTIONS (fictional)", "Marat Oskolov", aliases=["M. Oskolov", "Marat Oskolow"], dob="1972-02-03",
         nationality="Kestovia (fictional)", program="KESTOVIA-RELATED (fictional)", added="2026-11-10",
         notes="Businessman linked to Kestovia Port Services JSC.")
    b.usual_logins(c, "DV-8H08", "2026-07-14", "73.41.80.4", city="Eastport, OH", days=(4, 11, 19))
    b.alert("A08", d("2026-11-11"), "WATCHLIST_HIT", c, 0,
            "Name screening hit after a sanctions list update: exact name match (score 1.00).", [],
            "escalate", "sanctions true match", "",
            "Same name, same DOB, same nationality, and he paid the company named in the list entry. Block and send to the sanctions officer.")

    # A09: mule with a new account, new device and shared device -------------
    c = b.customer("C09", name="Jordan Pike", dob="2007-01-28", citizenship="US", city="Millbrook, OH",
                   occupation="Student", employer="none", segment="personal", customer_since="2026-10-24",
                   risk_rating="low", opened_channel="online",
                   expected_monthly={"cash_in": 0, "total_in": 800, "total_out": 800}, kyc_last_review="2026-10-24")
    apex = b.cp("Apex Remote Staffing Inc", "business", registered="2026-10-15", relationship_since="2026-11-08",
                notes="Registered 2026-10-15. Sent 'payroll' to 2 other customers of this bank in November.", other_customers_paid=2)
    coin = b.cp("CoinVault Exchange", "crypto_exchange", relationship_since="2026-11-08", notes="Crypto exchange.")
    i1 = b.tx(c, d("2026-11-08"), "ach_in", 7500, cp=apex, memo="PAYROLL")
    b.tx(c, d("2026-11-08"), "wire_out", 7300, cp=coin, memo="")
    b.login(c, "2026-10-24T16:02:00", "DV-9J09", "2026-10-24", "73.41.90.6", "Millbrook, OH")
    b.login(c, "2026-11-08T11:20:00", "DV-55K9", "2026-11-08", "64.12.88.40", "Dallas, TX")
    b.login(c, "2026-11-08T14:31:00", "DV-55K9", "2026-11-08", "64.12.88.40", "Dallas, TX")
    b.customer("C30", name="Evan Marsh", dob="2006-11-02", citizenship="US", city="Harlow, OH", occupation="Student",
               segment="personal", customer_since="2026-10-29", risk_rating="low",
               expected_monthly={"cash_in": 0, "total_in": 700, "total_out": 700}, kyc_last_review="2026-10-29")
    b.customer("C31", name="Lena Brooks", dob="2005-06-17", citizenship="US", city="Eastport, OH", occupation="Student",
               segment="personal", customer_since="2026-10-30", risk_rating="low",
               expected_monthly={"cash_in": 0, "total_in": 700, "total_out": 700}, kyc_last_review="2026-10-30")
    b.login("C30", "2026-11-07T10:02:00", "DV-55K9", "2026-11-07", "64.12.88.40", "Dallas, TX")
    b.login("C31", "2026-11-09T09:47:00", "DV-55K9", "2026-11-07", "64.12.88.40", "Dallas, TX")
    b.alert("A09", d("2026-11-09"), "RAPID_MOVEMENT", c, 7500,
            "90% or more of incoming funds sent out within 48 hours.", [i1],
            "sar", "money mule (new account)", "",
            "Account 2 weeks old, $7,500 'payroll' from a 3-week-old company, $7,300 to crypto 3 hours later, from a new device in Dallas that 2 other new customers also use.")

    # A10: house purchase (legit rapid in/out) ------------------------------
    c = b.customer("C10", name="Robert Asante", dob="1981-10-05", citizenship="US", city="Millbrook, OH",
                   occupation="Civil engineer", employer="Millbrook Water Utility", segment="personal",
                   customer_since="2011-05-09", risk_rating="low",
                   expected_monthly={"cash_in": 0, "total_in": 7800, "total_out": 7000}, kyc_last_review="2025-05-09",
                   linked_accounts=["Brokerage account at Lakeshore Investments in the customer's own name (linked 2015)"])
    emp = b.cp("Millbrook Water Utility", "government", relationship_since="2011-05-15", notes="Employer.")
    b.salaried(c, emp, 3480.00, 1500.00, landlord, util)
    brok = b.cp("Robert Asante - Lakeshore Investments brokerage", "own_account", relationship_since="2015-02-10",
                notes="Customer's own brokerage account. Same name and address.")
    title = b.cp("Lakeside Title & Escrow LLC", "business", registered="2004-03-15", relationship_since="2026-11-10",
                 notes="Title and escrow company in Millbrook since 2004. 7 other customers paid it this year for home closings.", other_customers_paid=7)
    i1 = b.tx(c, d("2026-11-09"), "transfer_in", 85000, cp=brok, memo="transfer from brokerage")
    b.tx(c, d("2026-11-10"), "wire_out", 84500, cp=title, memo="closing funds 14 Birch Lane")
    b.case(c, d("2026-11-07"), "call_note", "Customer called: closing on a house on 2026-11-10 and will wire the closing funds to Lakeside Title & Escrow. Wire instructions confirmed by calling the title company's known number.")
    b.usual_logins(c, "DV-10K10", "2022-07-01", "73.41.100.2")
    b.alert("A10", d("2026-11-11"), "RAPID_MOVEMENT", c, 85000,
            "90% or more of incoming funds sent out within 48 hours.", [i1],
            "close", "none (explained)", "rapid in/out that is a home purchase",
            "Money came from his own brokerage account and went to a long-standing title company; he called ahead.")

    # A11: elder financial exploitation --------------------------------------
    c = b.customer("C11", name="Margaret Ellison", dob="1948-03-19", citizenship="US", city="Millbrook, OH",
                   occupation="Retired teacher", employer="retired", segment="personal", customer_since="1987-09-01",
                   risk_rating="low", expected_monthly={"cash_in": 0, "total_in": 3900, "total_out": 3000},
                   kyc_last_review="2026-10-25")
    pension = b.cp("Ohio Teachers Pension Fund (fictional)", "government", relationship_since="2008-07-01", notes="Pension payments.")
    for x in month_days(3):
        b.tx(c, x, "ach_in", 3900, cp=pension, memo="PENSION")
    for i, x in enumerate(month_days(14)):
        b.tx(c, x, "ach_out", [880.20, 910.45, 865.10, 902.33][i % 4], cp=util, memo="UTILITIES AND CARE")
    bith = b.cp("BitHarbor Digital Assets", "crypto_exchange", relationship_since="2026-10-30", notes="Crypto exchange.")
    gyp = b.cp("Global Yield Partners", "business", country="Free Port of Belmora (fictional)", registered="2026-09-12",
               relationship_since="2026-11-07", notes="Registered 2026-09-12 in Belmora (fictional). No license on file.")
    o1 = b.tx(c, d("2026-10-30"), "wire_out", 18000, cp=bith, memo="investment")
    o2 = b.tx(c, d("2026-11-03"), "wire_out", 21000, cp=bith, memo="investment")
    o3 = b.tx(c, d("2026-11-07"), "wire_out", 25000, cp=gyp, memo="investment fee")
    b.case(c, d("2026-10-25"), "kyc_update", "Joint owner added: Victor Lang, age 36. Not a relative listed on the account. Added online.")
    b.case(c, d("2026-11-03"), "branch_note", "Customer said she is helping a friend she met online with an investment that 'doubles in a month'. She seemed rushed.")
    b.usual_logins(c, "DV-11L11", "2019-04-10", "73.41.110.5", days=(30, 45, 60))
    b.login(c, "2026-10-24T21:15:00", "DV-11Z77", "2026-10-24", "102.66.4.19", "unknown", "unknown")
    b.alert("A11", d("2026-11-08"), "ELDER_OUTFLOW", c, 64000,
            "Customer aged 70+ sent $20,000 or more to new payees within 30 days.", [o1, o2, o3],
            "sar", "elder financial exploitation (scam)", "",
            "78-year-old, $64,000 to crypto and a new offshore company in 9 days, new joint owner, 'friend met online', 'doubles in a month'.")

    # A12: elderly customer, legit large payment -----------------------------
    c = b.customer("C12", name="Walter Kim", dob="1945-06-02", citizenship="US", city="Millbrook, OH",
                   occupation="Retired", employer="retired", segment="personal", customer_since="1979-02-14",
                   risk_rating="low", expected_monthly={"cash_in": 0, "total_in": 4200, "total_out": 3500},
                   kyc_last_review="2025-02-14",
                   authorized_agents=["Susan Kim-Park (daughter), power of attorney on file since 2019-05-20"])
    ss = b.cp("Social Security (fictional)", "government", relationship_since="2010-06-01", notes="Benefit payments.")
    for x in month_days(3):
        b.tx(c, x, "ach_in", 2700, cp=ss, memo="BENEFITS")
        b.tx(c, x, "ach_in", 1500, cp=pension, memo="PENSION")
    maple = b.cp("Maple Grove Senior Living", "business", registered="1998-06-01", relationship_since="2026-11-06",
                 notes="Licensed assisted-living home in Millbrook since 1998. 4 other customers pay it.", other_customers_paid=4)
    o = b.tx(c, d("2026-11-06"), "wire_out", 42000, cp=maple, memo="entrance fee W. Kim")
    b.case(c, d("2026-11-04"), "call_note", "Daughter Susan Kim-Park (power of attorney on file since 2019) called: her father is moving into Maple Grove Senior Living; entrance fee $42,000. Signed contract copy received and scanned.")
    b.usual_logins(c, "DV-12M12", "2019-05-20", "73.41.120.3")
    b.alert("A12", d("2026-11-07"), "ELDER_OUTFLOW", c, 42000,
            "Customer aged 70+ sent $20,000 or more to new payees within 30 days.", [o],
            "close", "none (explained)", "older customer, big payment, but documented",
            "Assisted-living entrance fee arranged by the daughter who has had POA since 2019, contract on file, licensed home.")

    # A13: unexplained income jump --------------------------------------------
    c = b.customer("C13", name="Nadia Petrova-Lowe", dob="1989-12-11", citizenship="US", city="Millbrook, OH",
                   occupation="Freelance graphic designer", employer="self-employed", segment="personal",
                   customer_since="2020-02-17", risk_rating="low",
                   expected_monthly={"cash_in": 0, "total_in": 4500, "total_out": 4200}, kyc_last_review="2025-02-17")
    clients = [b.cp(n, "business", relationship_since=s, notes="Design client.") for n, s in
               [("Pinecone Studio", "2021-03-01"), ("Harlow Brewing Co", "2022-06-01"), ("Bluebird Bakery", "2023-01-10")]]
    for k, x in enumerate(month_days(8) + month_days(22)):
        b.tx(c, x, "ach_in", [1850, 2200, 1400, 2050, 1600, 2300, 1750][k % 7], cp=clients[k % 3], memo="INVOICE")
    for x in month_days(1):
        b.tx(c, x, "ach_out", 1400, cp=landlord, memo="RENT")
    orion = b.cp("Orion Trade Holdings Ltd", "business", country="Free Port of Belmora (fictional)", registered="2026-06-03",
                 relationship_since="2026-11-02", notes="Registered 2026-06-03 in Belmora (fictional). No website on file.")
    i1 = b.tx(c, d("2026-11-02"), "wire_in", 22500, cp=orion, memo="consulting fees")
    i2 = b.tx(c, d("2026-11-09"), "wire_in", 22500, cp=orion, memo="consulting fees")
    b.usual_logins(c, "DV-13N13", "2020-02-17", "73.41.130.9")
    b.alert("A13", d("2026-11-10"), "PROFILE_MISMATCH", c, 45000,
            "Incoming funds in 30 days are more than 5 times the expected monthly amount.", [i1, i2],
            "escalate", "unexplained activity", "",
            "$45,000 'consulting fees' from a new offshore company, ten times her normal income, no outflow yet and no known typology. Needs a contract or invoices from the customer.")

    # A14: annual bonus --------------------------------------------------------
    c = b.customer("C14", name="Ethan Brooks", dob="1982-02-27", citizenship="US", city="Eastport, OH",
                   occupation="Sales manager", employer="Kestrel Logistics Inc", segment="personal",
                   customer_since="2015-10-01", risk_rating="low",
                   expected_monthly={"cash_in": 0, "total_in": 6800, "total_out": 6200}, kyc_last_review="2025-10-01")
    kl = b.cp("Kestrel Logistics Inc", "business", relationship_since="2021-01-15", notes="Employer since 2021.")
    b.salaried(c, kl, 3100.00, 2050.00, mortgage, util, rent_memo="MORTGAGE")
    i1 = b.tx(c, d("2026-11-06"), "ach_in", 18000, cp=kl, memo="ANNUAL BONUS 2026")
    b.case(c, d("2025-11-10"), "alert_closed", "PROFILE_MISMATCH alert closed: $16,500 ACH from employer Kestrel Logistics with memo ANNUAL BONUS 2025. Expected activity.", disposition="closed")
    b.usual_logins(c, "DV-14P14", "2021-08-09", "73.41.140.1", city="Eastport, OH")
    b.alert("A14", d("2026-11-07"), "PROFILE_MISMATCH", c, 18000,
            "Incoming funds in 30 days are more than 3 times the expected monthly amount.", [i1],
            "close", "none (explained)", "income spike that is a yearly bonus",
            "From his employer of 5 years, memo ANNUAL BONUS, same thing happened last November and was closed.")

    # A15: funnel account -------------------------------------------------------
    c = b.customer("C15", name="Luis Ortega Vance", dob="1995-04-30", citizenship="US", city="Millbrook, OH",
                   occupation="Warehouse worker", employer="Ridgeline Distribution", segment="personal",
                   customer_since="2025-06-02", risk_rating="low",
                   expected_monthly={"cash_in": 200, "total_in": 3300, "total_out": 3200}, kyc_last_review="2025-06-02")
    emp = b.cp("Ridgeline Distribution", "business", relationship_since="2025-06-06", notes="Employer.")
    b.salaried(c, emp, 1510.00, 1150.00, landlord, util)
    deps = [
        b.tx(c, d("2026-11-02"), "cash_deposit", 3200, "shared_branch", "Shared branch network - Phoenix, AZ", memo="depositor not the account holder"),
        b.tx(c, d("2026-11-03"), "cash_deposit", 2900, "shared_branch", "Shared branch network - Tucson, AZ", memo="depositor not the account holder"),
        b.tx(c, d("2026-11-04"), "cash_deposit", 3400, "shared_branch", "Shared branch network - El Paso, TX", memo="depositor not the account holder"),
        b.tx(c, d("2026-11-05"), "cash_deposit", 2800, "shared_branch", "Shared branch network - Phoenix, AZ", memo="depositor not the account holder"),
        b.tx(c, d("2026-11-06"), "cash_deposit", 3100, "shared_branch", "Shared branch network - Las Cruces, NM", memo="depositor not the account holder"),
    ]
    b.tx(c, d("2026-11-07"), "cash_withdrawal", 7500, "atm", "ATM network - Chicago, IL")
    b.tx(c, d("2026-11-08"), "cash_withdrawal", 7400, "atm", "ATM network - Chicago, IL")
    b.usual_logins(c, "DV-15Q15", "2025-06-02", "73.41.150.4")
    b.alert("A15", d("2026-11-09"), "FUNNEL", c, 15400,
            "Cash deposits at 3 or more out-of-area locations within 7 days.", deps,
            "sar", "funnel account", "",
            "Five cash deposits by other people in AZ/TX/NM ($15,400) for an Ohio warehouse worker, then $14,900 taken out by ATM in Chicago within two days.")

    # A16: online seller, many small payments -----------------------------------
    c = b.customer("C16", name="Ava Lindqvist", dob="1993-09-08", citizenship="US", city="Harlow, OH",
                   occupation="Sells handmade candles online (sole proprietor)", employer="self-employed",
                   segment="personal", customer_since="2022-03-21", risk_rating="low",
                   expected_monthly={"cash_in": 0, "total_in": 3000, "total_out": 2600}, kyc_last_review="2025-03-21")
    first = ["Amy", "Ben", "Cara", "Dev", "Eli", "Fay", "Gus", "Hana", "Ian", "Jo", "Kai", "Liv", "Max", "Nia", "Oli",
             "Pia", "Quin", "Raj", "Sia", "Tom", "Uma", "Vic", "Wes", "Xan", "Yara", "Zed", "Abe", "Bea", "Cy", "Dot"]
    buyers = [b.cp("%s %s." % (n, "BCDFGHJKLMNPRSTVWZ"[k % 18]), "individual", relationship_since="2026-%02d-01" % (6 + k % 5),
                   notes="Pays small amounts with memo 'candle order'.") for k, n in enumerate(first)]
    small_in, k = [], 0
    day = d("2026-08-20")
    while day <= d("2026-11-15"):
        for _ in range(2 if day.toordinal() % 2 else 1):
            amt = [24, 38, 18, 55, 42, 29, 61, 35, 47, 22, 80, 33][k % 12]
            t = b.tx(c, day, "p2p_in", amt, cp=buyers[(k * 7) % 30], memo="candle order #%d" % (4100 + k))
            if day >= d("2026-10-16"):
                small_in.append((t, amt))
            k += 1
        day += timedelta(days=1)
    wax = b.cp("Northern Wax Supply", "business", relationship_since="2022-04-01", notes="Candle wax supplier.")
    for x in month_days(6):
        b.tx(c, x, "ach_out", 640, cp=wax, memo="WAX ORDER")
    for x in month_days(1):
        b.tx(c, x, "ach_out", 1050, cp=landlord, memo="RENT")
    b.case(c, d("2025-03-21"), "kyc_review", "Annual review. Sells candles online; buyers pay small amounts by P2P. 60-90 small payments a month is normal.")
    b.usual_logins(c, "DV-16R16", "2022-03-21", "73.41.160.2", city="Harlow, OH")
    b.alert("A16", d("2026-11-15"), "FAN_IN", c, sum(a for _, a in small_in),
            "Payments from 25 or more different senders within 30 days.", [t for t, _ in small_in][:10],
            "close", "none (explained)", "fan-in that is a small online shop",
            "Many small 'candle order' payments, the same pattern for months, matches the KYC note.")

    # A17: account takeover -------------------------------------------------------
    c = b.customer("C17", name="Samuel Ortiz", dob="1974-01-21", citizenship="US", city="Millbrook, OH",
                   occupation="Plumber (self-employed)", employer="self-employed", segment="personal",
                   customer_since="2005-04-11", risk_rating="low",
                   expected_monthly={"cash_in": 300, "total_in": 6000, "total_out": 5600}, kyc_last_review="2025-04-11")
    jobs = [b.cp(n, "individual", relationship_since=s, notes="Plumbing customer.") for n, s in
            [("H. Grant", "2018-01-01"), ("Millbrook Rentals LLC", "2016-01-01")]]
    for k, x in enumerate(month_days(4) + month_days(18)):
        b.tx(c, x, "check_deposit", [2400, 3100, 2750, 2900][k % 4], "mobile", cp=jobs[k % 2], memo="plumbing job")
    for x in month_days(1):
        b.tx(c, x, "ach_out", 1380, cp=mortgage, memo="MORTGAGE")
    b.usual_logins(c, "DV-17S17", "2021-11-02", "73.41.170.6")
    b.login(c, "2026-11-12T02:14:00", "DV-17Y88", "2026-11-12", "185.220.9.33", "Amsterdam", "NL")
    b.login(c, "2026-11-12T02:16:00", "DV-17Y88", "2026-11-12", "185.220.9.33", "Amsterdam", "NL", event="password_reset")
    b.login(c, "2026-11-12T02:20:00", "DV-17Y88", "2026-11-12", "185.220.9.33", "Amsterdam", "NL", event="phone_number_changed")
    b.login(c, "2026-11-12T02:25:00", "DV-17Y88", "2026-11-12", "185.220.9.33", "Amsterdam", "NL", event="new_payee_added")
    mercer = b.cp("J. Mercer", "individual", relationship_since="2026-11-12", notes="Account at another bank. Added as a payee on 2026-11-12 at 02:25.")
    o = b.tx(c, d("2026-11-12"), "wire_out", 12000, "online", cp=mercer, memo="invoice")
    b.alert("A17", d("2026-11-12"), "NEW_DEVICE_TRANSFER", c, 12000,
            "New device, new payee and a transfer of $5,000 or more within 1 hour.", [o],
            "escalate", "account takeover", "",
            "Login from a new device abroad at 2am, password reset, phone changed, new payee, $12,000 wire within 17 minutes. Hold and call the customer on the old number.")

    # A18: new phone, money to own account -----------------------------------------
    c = b.customer("C18", name="Grace Whitfield", dob="1987-05-03", citizenship="US", city="Millbrook, OH",
                   occupation="Teacher", employer="Millbrook School District", segment="personal",
                   customer_since="2012-08-20", risk_rating="low",
                   expected_monthly={"cash_in": 0, "total_in": 4700, "total_out": 4300}, kyc_last_review="2025-08-20",
                   linked_accounts=["Savings account at Northfield Credit Union in the customer's own name (linked 2023)"])
    emp = b.cp("Millbrook School District", "government", relationship_since="2012-08-25", notes="Employer.")
    b.salaried(c, emp, 2150.00, 1290.00, landlord, util)
    sav = b.cp("Grace Whitfield - Northfield Credit Union savings", "own_account", relationship_since="2023-01-09",
               notes="Customer's own savings account. Same name and address.")
    for x, amt in [(d("2026-08-16"), 2500), (d("2026-09-16"), 3000), (d("2026-10-16"), 2000)]:
        b.tx(c, x, "transfer_out", amt, cp=sav, memo="to savings")
    o = b.tx(c, d("2026-11-10"), "transfer_out", 6000, "mobile", cp=sav, memo="to savings")
    b.usual_logins(c, "DV-18T18", "2021-09-01", "73.41.180.3", days=(12, 18, 25))
    b.login(c, "2026-11-09T18:40:00", "DV-18W21", "2026-11-09", "73.41.180.3", "Millbrook, OH")
    b.login(c, "2026-11-10T07:55:00", "DV-18W21", "2026-11-09", "73.41.180.3", "Millbrook, OH")
    b.case(c, d("2026-11-09"), "call_note", "Customer called: she got a new phone and set up the mobile app again. Identity verified with security questions.")
    b.alert("A18", d("2026-11-10"), "NEW_DEVICE_TRANSFER", c, 6000,
            "New device and a transfer of $5,000 or more within 24 hours.", [o],
            "close", "none (explained)", "new device that is just a new phone",
            "Same home IP, she called about the new phone, money went to her own savings account used every month since 2023.")

    # A19: structuring cash withdrawals ------------------------------------------
    c = b.customer("C19", name="Dale Hutchins", dob="1968-08-14", citizenship="US", city="Eastport, OH",
                   occupation="Contractor (self-employed)", employer="self-employed", segment="personal",
                   customer_since="2010-03-29", risk_rating="low",
                   expected_monthly={"cash_in": 1000, "total_in": 8000, "total_out": 7500}, kyc_last_review="2025-03-29")
    gc = b.cp("Eastport Builders Inc", "business", relationship_since="2012-01-01", notes="General contractor. Pays for subcontract work.")
    for k, x in enumerate(month_days(2) + month_days(16)):
        b.tx(c, x, "ach_in", [4200, 3900, 4600, 3700][k % 4], cp=gc, memo="SUBCONTRACT")
    ws = [
        b.tx(c, d("2026-11-02"), "cash_withdrawal", 9800, "branch", HOME_BRANCHES[0]),
        b.tx(c, d("2026-11-03"), "cash_withdrawal", 9700, "branch", HOME_BRANCHES[2]),
        b.tx(c, d("2026-11-04"), "cash_withdrawal", 9900, "branch", HOME_BRANCHES[3]),
    ]
    b.case(c, d("2026-11-02"), "teller_note", "Customer asked to withdraw $15,000 in cash, then changed it to $9,800 after the teller said a CTR would be filed.")
    b.usual_logins(c, "DV-19U19", "2020-05-05", "73.41.190.8", city="Eastport, OH")
    b.alert("A19", d("2026-11-05"), "CASH_NEAR_CTR", c, 29400,
            "2 or more cash withdrawals between $8,000 and $9,999 within 10 days.", ws,
            "sar", "structuring (withdrawals)", "",
            "Changed the amount after hearing about the CTR, then three withdrawals of $9,700-$9,900 at three branches on three days.")

    # A20: continuing activity after a prior SAR -----------------------------------
    c = b.customer("C20", name="Rina Castellano", dob="1980-11-25", citizenship="US", city="Millbrook, OH",
                   occupation="Nail salon owner (sole proprietor)", employer="Castellano Nail Studio", segment="personal",
                   customer_since="2018-07-16", risk_rating="high",
                   expected_monthly={"cash_in": 6000, "total_in": 9000, "total_out": 8500}, kyc_last_review="2026-06-12")
    for x in month_days(1):
        b.tx(c, x, "ach_out", 2600, cp=landlord, memo="SALON RENT")
    for k, x in enumerate(month_days(9) + month_days(23)):
        if x < d("2026-11-01"):
            b.tx(c, x, "cash_deposit", [2900, 3100, 2700, 3300, 2800, 3000][k % 6], "branch", HOME_BRANCHES[0], memo="salon receipts")
    cs = [
        b.tx(c, d("2026-11-03"), "cash_deposit", 9300, "branch", HOME_BRANCHES[1]),
        b.tx(c, d("2026-11-05"), "cash_deposit", 9650, "branch", HOME_BRANCHES[2]),
        b.tx(c, d("2026-11-10"), "cash_deposit", 9450, "branch", HOME_BRANCHES[3]),
    ]
    b.case(c, d("2026-06-10"), "sar_filed", "SAR filed for structuring: six cash deposits of $9,000-$9,900 at different branches in May 2026. Risk rating raised to high. Monitor for continuing activity.", disposition="sar_filed")
    b.usual_logins(c, "DV-20V20", "2019-02-02", "73.41.200.5")
    b.alert("A20", d("2026-11-11"), "CASH_NEAR_CTR", c, 28400,
            "2 or more cash deposits between $8,000 and $9,999 within 10 days.", cs,
            "sar", "structuring (continuing activity)", "",
            "Same pattern as the June 2026 SAR, again across branches, and far above her normal $2,700-$3,300 salon deposits.")

    # A21: adverse media about a different person ------------------------------
    c = b.customer("C21", name="John R. Pell", dob="1997-01-15", citizenship="US", city="Millbrook, OH",
                   occupation="Software tester", employer="Quillstone Software", segment="personal",
                   customer_since="2019-09-03", risk_rating="low",
                   expected_monthly={"cash_in": 0, "total_in": 5100, "total_out": 4700}, kyc_last_review="2025-09-03")
    emp = b.cp("Quillstone Software", "business", relationship_since="2019-09-10", notes="Employer.")
    b.salaried(c, emp, 2440.00, 1380.00, landlord, util)
    b.wl("ADVERSE MEDIA (fictional)", "John R. Pell", aliases=["Johnny Pell"], dob=None,
         age_at_article=62, city="Port Daley, FL (fictional)", article_date="2026-11-01",
         notes="News: 'Port Daley contractor John R. Pell, 62, charged with insurance fraud after hurricane repairs.'")
    b.usual_logins(c, "DV-21X21", "2022-12-12", "73.41.210.7")
    b.alert("A21", d("2026-11-13"), "WATCHLIST_HIT", c, 0,
            "Adverse media screening hit: exact name match (score 1.00).", [],
            "close", "none (false match)", "exact-name media hit about someone else",
            "Article is about a 62-year-old contractor in Florida; customer is 29, a software tester in Ohio with normal activity.")

    # A22: wires to a new shell company that does not fit the business -------------
    c = b.customer("C22", name="Harrow Home Imports LLC", owner="Peter Harrow", citizenship="US", city="Millbrook, OH",
                   occupation="Furniture importer (imports from Varonia (fictional))", segment="business",
                   customer_since="2016-01-11", risk_rating="medium", employees=6,
                   expected_monthly={"cash_in": 0, "total_in": 48000, "total_out": 45000}, kyc_last_review="2026-01-11")
    vw = b.cp("Varonia Woodworks Co", "business", country="Varonia (fictional)", registered="2003-02-01",
              relationship_since="2016-03-01", notes="Furniture maker. Paid monthly since 2016.")
    shops = b.cp("Home & Hearth Stores", "business", relationship_since="2017-01-01", notes="Retail buyer of the customer's furniture.")
    for k, x in enumerate(month_days(7)):
        b.tx(c, x, "wire_out", [28400, 31200, 26900, 30100][k % 4], cp=vw, memo="FURNITURE ORDER")
    for k, x in enumerate(month_days(15) + month_days(28)):
        b.tx(c, x, "ach_in", [22500, 24800, 23900, 21700][k % 4], cp=shops, memo="INVOICE")
    nim = b.cp("Nimbus Digital Services FZE", "business", country="Free Port of Belmora (fictional)", registered="2026-10-01",
               relationship_since="2026-11-04", notes="Registered 2026-10-01 in Belmora (fictional), a high-risk jurisdiction in bank policy. Registered-agent address shared by 200+ companies. No website on file.")
    h1 = b.tx(c, d("2026-11-04"), "wire_out", 38000, cp=nim, memo="software license")
    h2 = b.tx(c, d("2026-11-10"), "wire_out", 41000, cp=nim, memo="software license")
    b.usual_logins(c, "DV-22Y22", "2020-10-10", "73.41.220.4")
    b.alert("A22", d("2026-11-11"), "HIGH_RISK_WIRE", c, 79000,
            "Wires to a counterparty in a high-risk jurisdiction (bank policy list).", [h1, h2],
            "escalate", "unexplained activity (possible shell company)", "",
            "$79,000 for 'software' to a 6-week-old company at a shared address in a high-risk place; does not fit a furniture importer. Ask the customer for the contract and invoices.")

    # A23: own-account transfer to pay property tax -------------------------------
    c = b.customer("C23", name="Owen Gallagher", dob="1976-07-19", citizenship="US", city="Millbrook, OH",
                   occupation="Pharmacist", employer="Millbrook Pharmacy", segment="personal", customer_since="2009-04-06",
                   risk_rating="low", expected_monthly={"cash_in": 0, "total_in": 7400, "total_out": 6900},
                   kyc_last_review="2025-04-06",
                   linked_accounts=["Savings account at Northfield Credit Union in the customer's own name (linked 2017)"])
    emp = b.cp("Millbrook Pharmacy", "business", relationship_since="2009-04-10", notes="Employer.")
    b.salaried(c, emp, 3300.00, 2200.00, mortgage, util, rent_memo="MORTGAGE")
    osav = b.cp("Owen Gallagher - Northfield Credit Union savings", "own_account", relationship_since="2017-03-01",
                notes="Customer's own savings account. Same name and address.")
    tax = b.cp("Millbrook County Treasurer", "government", relationship_since="2010-05-01", notes="County property tax. Paid each May and November.")
    i1 = b.tx(c, d("2026-11-12"), "transfer_in", 14000, cp=osav, memo="from savings")
    b.tx(c, d("2026-11-13"), "ach_out", 13600, cp=tax, memo="PROPERTY TAX 2ND HALF 2026")
    b.case(c, d("2025-11-14"), "alert_closed", "RAPID_MOVEMENT alert closed: $13,900 moved from own savings and paid to Millbrook County Treasurer for property tax. Expected activity.", disposition="closed")
    b.usual_logins(c, "DV-23Z23", "2021-02-14", "73.41.230.1")
    b.alert("A23", d("2026-11-14"), "RAPID_MOVEMENT", c, 14000,
            "90% or more of incoming funds sent out within 48 hours.", [i1],
            "close", "none (explained)", "rapid in/out that is a tax payment",
            "From his own savings to the county treasurer for property tax, same as last November.")

    # A24: unwitting mule through a fake remote job --------------------------------
    c = b.customer("C24", name="Tyler Grant", dob="2000-03-09", citizenship="US", city="Harlow, OH",
                   occupation="Job seeker (updated 2026-09)", employer="none", segment="personal",
                   customer_since="2021-05-17", risk_rating="low",
                   expected_monthly={"cash_in": 0, "total_in": 900, "total_out": 900}, kyc_last_review="2026-09-02")
    ui = b.cp("Ohio Unemployment Benefits (fictional)", "government", relationship_since="2026-09-05", notes="Benefit payments.")
    for f in fridays(d("2026-09-11"), BANK_TODAY):
        b.tx(c, f, "ach_in", 410, cp=ui, memo="BENEFITS")
    crest = b.cp("Crestmont Payroll Services", "business", relationship_since="2026-11-04",
                 notes="Name printed on deposited checks. No account at this bank.")
    daniels = b.cp("R. Daniels", "individual", relationship_since="2026-11-05", notes="P2P payee at another bank. First paid 2026-11-05.")
    k1 = b.tx(c, d("2026-11-04"), "check_deposit", 4950, "mobile", cp=crest, memo="mobile check deposit")
    b.tx(c, d("2026-11-05"), "p2p_out", 4700, cp=daniels)
    k2 = b.tx(c, d("2026-11-06"), "check_deposit", 4980, "mobile", cp=crest, memo="mobile check deposit")
    b.tx(c, d("2026-11-07"), "p2p_out", 4750, cp=daniels)
    b.tx(c, d("2026-11-09"), "check_return", 4950, cp=crest, memo="returned deposited item - altered check")
    b.case(c, d("2026-11-07"), "call_note", "Customer said his new remote job, found on social media, 'processes payments for clients': he deposits checks and sends the money to his manager.")
    b.case(c, d("2026-11-09"), "returned_item", "Check deposited 2026-11-04 for $4,950 returned by the paying bank as altered.", amount=4950.0)
    b.usual_logins(c, "DV-24A24", "2021-05-17", "73.41.240.6", city="Harlow, OH")
    b.alert("A24", d("2026-11-10"), "RAPID_MOVEMENT", c, 9930,
            "90% or more of incoming funds sent out within 48 hours.", [k1, k2],
            "sar", "money mule (fake job) and check fraud", "",
            "Deposits checks from a 'job' found online and forwards the money; one check came back altered. Classic job-scam mule.")

    # extra watchlist entries so screening returns more than one candidate ---------
    b.wl("PEP (fictional)", "Daniela Varga", dob="1979-02-14", nationality="Varonia (fictional)", notes="Deputy minister of Varonia (fictional).")
    b.wl("SANCTIONS (fictional)", "Marat Oskanov", dob="1969-12-01", nationality="Kestovia (fictional)", program="KESTOVIA-RELATED (fictional)", notes="Shipping executive.")
    b.wl("ADVERSE MEDIA (fictional)", "John Pellman", dob=None, age_at_article=45, city="Rivergate, MI (fictional)", article_date="2026-08-14", notes="News: 'Rivergate landlord fined for code violations.'")
    b.wl("SANCTIONS (fictional)", "Nimbus Digital Services FZE", dob=None, nationality="Free Port of Belmora (fictional)", program="none - under review list (fictional)", notes="Entity on internal watch list, not sanctioned.")

    b.transactions.sort(key=lambda t: (t["customer_id"], t["date"], t["transaction_id"]))
    return b


def write(out_dir):
    b = build()
    os.makedirs(out_dir, exist_ok=True)
    bank = {
        "meta": {"bank_name": BANK_NAME, "bank_today": str(BANK_TODAY), "data_start": str(DATA_START),
                 "note": "Synthetic data. All people, companies, countries and list entries are made up."},
        "customers": b.customers, "counterparties": b.counterparties, "transactions": b.transactions,
        "logins": b.logins, "case_history": b.case_history, "watchlist": b.watchlist,
    }
    with open(os.path.join(out_dir, "bank.json"), "w") as f:
        json.dump(bank, f, indent=1)
    with open(os.path.join(out_dir, "alerts.json"), "w") as f:
        json.dump(b.alerts, f, indent=1)
    with open(os.path.join(out_dir, "answer_key.json"), "w") as f:
        json.dump(b.answer_key, f, indent=1)
    return b


if __name__ == "__main__":
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    b = write(os.path.join(here, "data"))
    print("customers %d, counterparties %d, transactions %d, logins %d, case records %d, watchlist %d, alerts %d" % (
        len(b.customers), len(b.counterparties), len(b.transactions), len(b.logins), len(b.case_history),
        len(b.watchlist), len(b.alerts)))
