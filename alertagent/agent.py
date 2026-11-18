"""The investigator agent on Gemini function calling.

Every model turn must be a tool call (function calling mode ANY). The loop runs the
data tools against the mock bank, records every call and result (the audit trail),
and stops when the model calls submit_decision.
"""

import time

from .prompt import opening_message, system_prompt
from .tools import ALL_TOOLS, SUBMIT_TOOL, call_tool, validate_args
from .gemini import thinking_config

BLOCKED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}
RETRYABLE = {"MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL"}

FUNCTION_DECLARATIONS = [
    {"name": t["name"], "description": t["description"], "parametersJsonSchema": t["inputSchema"]} for t in ALL_TOOLS
]


def check_decision(args):
    """Extra checks on submit_decision beyond the schema. Returns an error string or None."""
    err = validate_args(SUBMIT_TOOL["name"], args)
    if err:
        return err
    if not args.get("statements"):
        return "statements must have at least one fact."
    for s in args["statements"]:
        if not isinstance(s, dict) or not s.get("text"):
            return "each statement needs text and evidence_ids."
    if args["decision"] == "sar" and not args.get("sar_draft"):
        return "sar_draft is required when decision is sar."
    c = args.get("confidence")
    if not isinstance(c, (int, float)) or c < 0 or c > 1:
        return "confidence must be a number from 0 to 1."
    return None


def run_alert(alert_id, bank, send, model, effort="low", max_turns=16):
    """send(model, body) -> Gemini response dict. Returns a trace dict (saved as JSON)."""
    contents = [{"role": "user", "parts": [{"text": opening_message(alert_id)}]}]
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt(bank.meta)}]},
        "contents": contents,
        "tools": [{"functionDeclarations": FUNCTION_DECLARATIONS}],
        "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
    }
    tc = thinking_config(model, effort)
    if tc:
        body["generationConfig"] = {"thinkingConfig": tc}

    trace = {"alert_id": alert_id, "agent": "%s (%s)" % (model, effort), "model": model, "effort": effort,
             "outcome": "max_turns", "error": None, "turns": 0, "steps": [], "decision": None,
             "usage": {"input": 0, "output": 0, "thinking": 0}, "model_turns": []}
    started = time.time()
    try:
        while trace["turns"] < max_turns:
            trace["turns"] += 1
            res = send(model, body)
            u = res.get("usageMetadata", {})
            trace["usage"]["input"] += u.get("promptTokenCount", 0)
            trace["usage"]["output"] += u.get("candidatesTokenCount", 0)
            trace["usage"]["thinking"] += u.get("thoughtsTokenCount", 0)
            cand = (res.get("candidates") or [{}])[0]
            finish = str(cand.get("finishReason", ""))
            block = (res.get("promptFeedback") or {}).get("blockReason")
            if block or finish in BLOCKED:
                trace["outcome"], trace["error"] = "refusal", str(block or finish)
                break
            content = cand.get("content") or {}
            if content.get("parts"):
                # Keep the model's turn exactly as returned: it carries thought signatures Gemini needs back.
                contents.append(content)
                trace["model_turns"].append(content)
            calls = [p["functionCall"] for p in content.get("parts", []) if "functionCall" in p]
            if not calls:
                if finish == "MAX_TOKENS":
                    trace["outcome"], trace["error"] = "error", "hit max output tokens without a tool call"
                    break
                why = "Your last tool call could not be read. Try again." if finish in RETRYABLE else "Only tool calls do anything here. Call a tool."
                contents.append({"role": "user", "parts": [{"text": "[%s]" % why}]})
                continue

            parts, done = [], False
            for call in calls:
                name, args, cid = call.get("name", ""), call.get("args") or {}, call.get("id")
                if done:
                    response = {"output": "[Skipped: the decision is already submitted.]"}
                elif name == SUBMIT_TOOL["name"]:
                    err = check_decision(args)
                    if err:
                        response = {"error": err}
                        trace["steps"].append({"turn": trace["turns"], "tool": name, "args": args, "is_error": True, "result": {"error": err}})
                    else:
                        trace["decision"] = args
                        trace["outcome"] = "decided"
                        done = True
                        response = {"output": "Decision recorded."}
                else:
                    result, is_err = call_tool(bank, name, args)
                    trace["steps"].append({"turn": trace["turns"], "tool": name, "args": args, "is_error": is_err, "result": result})
                    response = {"error": result["error"]} if is_err else {"output": result}
                fr = {"name": name, "response": response}
                if cid:
                    fr["id"] = cid
                parts.append({"functionResponse": fr})
            contents.append({"role": "user", "parts": parts})
            if done:
                break
    except Exception as e:  # saved in the trace; the run goes on with the next alert
        trace["outcome"], trace["error"] = "error", "%s: %s" % (type(e).__name__, e)
        if type(e).__name__ == "DailyLimitError":
            trace["outcome"] = "daily_limit"
    trace["wall_ms"] = int((time.time() - started) * 1000)
    return trace
