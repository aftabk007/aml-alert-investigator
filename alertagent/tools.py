"""The investigator's tools, written the way MCP tools are written:
a name, a description and a JSON Schema for the input (`inputSchema`).

The same list is served by the small MCP server in mcp_server.py and is
turned into Gemini function declarations in agent.py.
"""

from .bank import Bank

TX_TYPES = ["cash_deposit", "cash_withdrawal", "ach_in", "ach_out", "wire_in", "wire_out", "p2p_in", "p2p_out",
            "transfer_in", "transfer_out", "check_deposit", "check_return"]

DATA_TOOLS = [
    {
        "name": "get_alert",
        "description": "Alert queue. Returns the monitoring alert: the rule that fired, the customer, the date, the total amount and the transactions that triggered it.",
        "inputSchema": {"type": "object", "properties": {
            "alert_id": {"type": "string", "description": "Alert id, for example A01."}},
            "required": ["alert_id"]},
    },
    {
        "name": "get_customer_profile",
        "description": "KYC / customer due diligence file: name, date of birth, age, citizenship, city, occupation or business, customer since, risk rating, expected monthly activity, linked own accounts and authorized agents.",
        "inputSchema": {"type": "object", "properties": {
            "customer_id": {"type": "string", "description": "Customer id, for example C01."}},
            "required": ["customer_id"]},
    },
    {
        "name": "get_transactions",
        "description": "Core banking: the customer's cash, ACH, wire, P2P, transfer and check activity in a date range (default: the last 45 days, newest 100 rows). Each row has a transaction id, date, type, amount, channel, location, counterparty id and memo. Data starts 2026-08-01.",
        "inputSchema": {"type": "object", "properties": {
            "customer_id": {"type": "string", "description": "Customer id."},
            "start_date": {"type": "string", "description": "First day, YYYY-MM-DD. Optional."},
            "end_date": {"type": "string", "description": "Last day, YYYY-MM-DD. Optional, default is the bank's today."},
            "types": {"type": "array", "items": {"type": "string", "enum": TX_TYPES}, "description": "Only these transaction types. Optional."},
            "counterparty_id": {"type": "string", "description": "Only transactions with this counterparty. Optional."}},
            "required": ["customer_id"]},
    },
    {
        "name": "get_counterparty",
        "description": "Who is on the other side of a payment: name, type (individual, business, government, own_account, crypto_exchange), country, date registered, how long the customer has paid them, notes, and how many other customers of this bank pay or are paid by them.",
        "inputSchema": {"type": "object", "properties": {
            "counterparty_id": {"type": "string", "description": "Counterparty id, for example CP-012."},
            "customer_id": {"type": "string", "description": "The customer under review, to get payment history with them. Optional."}},
            "required": ["counterparty_id"]},
    },
    {
        "name": "get_login_activity",
        "description": "Digital banking: logins and security events (password reset, phone change, new payee) with device id, when the device was first seen, IP city and country, and other customers who used the same device.",
        "inputSchema": {"type": "object", "properties": {
            "customer_id": {"type": "string", "description": "Customer id."},
            "days": {"type": "integer", "description": "How many days back. Default 30."}},
            "required": ["customer_id"]},
    },
    {
        "name": "get_case_history",
        "description": "Case history and notes: prior alerts and how they were closed, SARs filed, CTRs filed, KYC reviews, teller notes and call notes.",
        "inputSchema": {"type": "object", "properties": {
            "customer_id": {"type": "string", "description": "Customer id."}},
            "required": ["customer_id"]},
    },
    {
        "name": "screen_name",
        "description": "Sanctions, PEP and adverse media screening. Returns list entries whose name is similar, with their date of birth, nationality, location and notes. A similar name alone is not a match.",
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Person or company name to screen."}},
            "required": ["name"]},
    },
]

SUBMIT_TOOL = {
    "name": "submit_decision",
    "description": "Submit the finished investigation. Call this exactly once, at the end.",
    "inputSchema": {"type": "object", "properties": {
        "decision": {"type": "string", "enum": ["close", "escalate", "sar"],
                     "description": "close = false positive, explained by evidence. escalate = a person must act now or more information is needed. sar = draft a SAR for the BSA officer."},
        "confidence": {"type": "number", "description": "0 to 1. How sure you are that the decision is right."},
        "typology": {"type": "string", "description": "The pattern found, for example 'structuring', 'money mule', 'account takeover', or 'none (explained)'."},
        "statements": {"type": "array", "description": "The case narrative: 3 to 8 short facts. Each fact cites the evidence ids it comes from.",
                       "items": {"type": "object", "properties": {
                           "text": {"type": "string", "description": "One fact. Money as $4,321, dates as YYYY-MM-DD."},
                           "evidence_ids": {"type": "array", "items": {"type": "string"},
                                            "description": "Evidence ids from tool results, for example T-0012, KYC-C03, CH-004."}},
                           "required": ["text", "evidence_ids"]}},
        "next_steps": {"type": "string", "description": "What the analyst should do next, in one or two sentences."},
        "sar_draft": {"type": "string", "description": "Only when decision is sar: a short SAR narrative draft (who, what, when, where, why, how)."}},
        "required": ["decision", "confidence", "typology", "statements", "next_steps"]},
}

ALL_TOOLS = DATA_TOOLS + [SUBMIT_TOOL]
_SPECS = {t["name"]: t for t in ALL_TOOLS}


def validate_args(name, args):
    """Small JSON Schema check: required fields, no unknown fields, simple types. Returns an error string or None."""
    spec = _SPECS.get(name)
    if spec is None:
        return "Unknown tool %s." % name
    schema = spec["inputSchema"]
    props = schema.get("properties", {})
    for r in schema.get("required", []):
        if r not in args or args[r] in (None, ""):
            return "Missing required argument: %s." % r
    for k, v in args.items():
        if k not in props:
            return "Unknown argument: %s." % k
        t = props[k].get("type")
        ok = {"string": isinstance(v, str), "integer": isinstance(v, (int, float)) and not isinstance(v, bool),
              "number": isinstance(v, (int, float)) and not isinstance(v, bool), "array": isinstance(v, list),
              "object": isinstance(v, dict)}.get(t, True)
        if not ok:
            return "Argument %s must be of type %s." % (k, t)
        if "enum" in props[k] and v not in props[k]["enum"]:
            return "Argument %s must be one of %s." % (k, props[k]["enum"])
        allowed = props[k].get("items", {}).get("enum")
        if t == "array" and allowed and any(x not in allowed for x in v):
            return "Argument %s may only contain %s." % (k, allowed)
    return None


def call_tool(bank, name, args):
    """Runs one data tool. Returns (result_dict, is_error)."""
    err = validate_args(name, args or {})
    if err:
        return {"error": err}, True
    if name == SUBMIT_TOOL["name"]:
        return {"error": "submit_decision is handled by the agent loop."}, True
    try:
        fn = getattr(bank, name)
        return fn(**(args or {})), False
    except (KeyError, ValueError, TypeError) as e:
        msg = e.args[0] if e.args else str(e)
        return {"error": str(msg)}, True


def evidence_index(result, into=None):
    """Collects every record with an evidence_id inside a tool result: {evidence_id: record}."""
    into = {} if into is None else into
    if isinstance(result, dict):
        if "evidence_id" in result:
            into[result["evidence_id"]] = result
        for v in result.values():
            evidence_index(v, into)
    elif isinstance(result, list):
        for v in result:
            evidence_index(v, into)
    return into


def new_bank():
    return Bank()
