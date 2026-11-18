import io
import json
import os
import tempfile
import unittest
import urllib.error

from alertagent.agent import FUNCTION_DECLARATIONS, check_decision, run_alert
from alertagent.bank import Bank, name_score
from alertagent.baseline import run_baseline
from alertagent.gemini import DailyLimitError, GeminiClient, GeminiError, load_api_key, thinking_config
from alertagent.grounding import check_case, check_statement, money_values
from alertagent.mcp_server import handle, serve
from alertagent.review import review
from alertagent.score import score_case, summarize
from alertagent.tools import ALL_TOOLS, DATA_TOOLS, call_tool, evidence_index

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANK = Bank()
with open(os.path.join(ROOT, "data", "answer_key.json")) as f:
    KEY = json.load(f)


class DataTest(unittest.TestCase):
    def test_answer_key_matches_alerts(self):
        self.assertEqual(sorted(KEY), sorted(BANK.alerts))
        self.assertEqual(len(KEY), 24)
        self.assertEqual(sum(v["suspicious"] for v in KEY.values()), 13)
        for aid, a in BANK.alerts.items():
            self.assertIn(a["customer_id"], BANK.customers)
            for t in a["triggering_transaction_ids"]:
                self.assertTrue(any(x["transaction_id"] == t for x in BANK.transactions), t)

    def test_evidence_ids_are_unique(self):
        ids = [t["evidence_id"] for t in BANK.transactions] + [l["evidence_id"] for l in BANK.logins] \
            + [c["evidence_id"] for c in BANK.case_history] + [w["evidence_id"] for w in BANK.watchlist] \
            + [c["evidence_id"] for c in BANK.customers.values()] + [c["evidence_id"] for c in BANK.counterparties.values()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_tools_never_expose_the_answer_key(self):
        for aid in BANK.alerts:
            a = BANK.get_alert(aid)
            self.assertEqual(set(a), {"alert_id", "evidence_id", "date", "rule", "customer_id", "amount_total", "summary",
                                      "triggering_transaction_ids"})
            self.assertNotIn(KEY[aid]["why"], json.dumps(a))


class ToolsTest(unittest.TestCase):
    def test_specs_look_like_mcp_tools(self):
        for t in ALL_TOOLS:
            self.assertEqual(set(t), {"name", "description", "inputSchema"})
            self.assertEqual(t["inputSchema"]["type"], "object")
        self.assertEqual([d["name"] for d in FUNCTION_DECLARATIONS], [t["name"] for t in ALL_TOOLS])

    def test_transactions_filters(self):
        r, err = call_tool(BANK, "get_transactions", {"customer_id": "C01", "types": ["cash_deposit"]})
        self.assertFalse(err)
        self.assertEqual([x["amount"] for x in r["rows"]], [9400, 9200, 9800, 9500])
        r, _ = call_tool(BANK, "get_transactions", {"customer_id": "C05", "start_date": "2026-08-01"})
        self.assertTrue(r["total_rows"] > r["returned"])
        self.assertIn("note", r)

    def test_bad_arguments_are_errors_not_crashes(self):
        for name, args in [("get_alert", {}), ("get_alert", {"alert_id": "Z99"}), ("get_transactions", {"customer_id": "C01", "foo": 1}),
                           ("get_transactions", {"customer_id": "C01", "types": ["bitcoin"]}), ("nope", {}),
                           ("get_transactions", {"customer_id": "C01", "start_date": "2026-13-01"})]:
            r, err = call_tool(BANK, name, args)
            self.assertTrue(err, (name, args))
            self.assertIn("error", r)

    def test_screening_returns_candidates_not_verdicts(self):
        r, _ = call_tool(BANK, "screen_name", {"name": "Daniel Varga Moreno"})
        self.assertEqual(r["candidates"][0]["dob"], "1967-09-30")
        self.assertNotIn("match", r["candidates"][0])
        self.assertGreater(name_score("Daniel Varga Moreno", "Daniel Vargas Moreno"), 0.9)

    def test_login_activity_shows_shared_device(self):
        r, _ = call_tool(BANK, "get_login_activity", {"customer_id": "C09"})
        shared = [e for e in r["events"] if e["device_id"] == "DV-55K9"]
        self.assertEqual(shared[0]["other_customers_on_this_device"], ["C30", "C31"])


class GroundingTest(unittest.TestCase):
    def setUp(self):
        r, _ = call_tool(BANK, "get_transactions", {"customer_id": "C01"})
        self.seen = evidence_index(r)
        self.ids = [x["evidence_id"] for x in r["rows"] if x["type"] == "cash_deposit"]

    def test_money_parsing(self):
        self.assertEqual(money_values("deposits of $9,400 and $9,200.50, total $37.9K"), [9400, 9200.5, 37900])

    def test_supported_and_total(self):
        ok = {"text": "Cash deposits of $9,400 on 2026-11-03 and more, $37,900 in total.", "evidence_ids": self.ids}
        self.assertEqual(check_statement(ok, self.seen), [])

    def test_unsupported_cases(self):
        self.assertEqual(check_statement({"text": "Big deposits.", "evidence_ids": []}, self.seen), ["no evidence cited"])
        p = check_statement({"text": "Deposit of $9,999 on 2026-11-03.", "evidence_ids": [self.ids[0]]}, self.seen)
        self.assertTrue(any("$9,999" in x for x in p))
        p = check_statement({"text": "Deposit of $9,400 on 2026-11-05.", "evidence_ids": [self.ids[0]]}, self.seen)
        self.assertTrue(any("2026-11-05" in x for x in p))
        p = check_statement({"text": "Teller note.", "evidence_ids": ["CH-001"]}, self.seen)
        self.assertTrue(any("no tool returned" in x for x in p))

    def test_dates_inside_timestamps_count(self):
        r, _ = call_tool(BANK, "get_login_activity", {"customer_id": "C06"})
        seen = evidence_index(r)
        last = r["events"][-1]
        s = {"text": "Login from a new device on %s." % last["timestamp"][:10], "evidence_ids": [last["evidence_id"]]}
        self.assertEqual(check_statement(s, seen), [])

    def test_written_dates_are_checked(self):
        ok = {"text": "On November 3, 2026 the customer deposited $9,400.", "evidence_ids": [self.ids[0]]}
        self.assertEqual(check_statement(ok, self.seen), [])
        bad = {"text": "On Nov 4, 2026 the customer deposited $9,400.", "evidence_ids": [self.ids[0]]}
        self.assertTrue(any("2026-11-04" in x for x in check_statement(bad, self.seen)))

    def test_policy_amounts_allowed(self):
        s = {"text": "All four deposits were just under the $10,000 CTR line.", "evidence_ids": self.ids}
        self.assertEqual(check_statement(s, self.seen), [])

    def test_check_case_counts(self):
        d = {"decision": "sar", "statements": [{"text": "Deposit of $9,400.", "evidence_ids": [self.ids[0]]},
                                               {"text": "Deposit of $1.", "evidence_ids": [self.ids[0]]}],
             "sar_draft": "On 2026-11-03 the customer deposited $9,400 and later $123,456."}
        g = check_case(d, self.seen)
        self.assertEqual((g["statements"], g["unsupported"]), (2, 1))
        self.assertEqual(len(g["sar_draft_problems"]), 1)


class ReviewTest(unittest.TestCase):
    def close(self, conf=0.95):
        return {"decision": "close", "confidence": conf, "statements": [{"text": "x", "evidence_ids": ["a"]}]}

    ok_g = {"unsupported": 0}
    tools = ["get_alert", "get_customer_profile", "get_transactions", "get_case_history", "screen_name", "get_login_activity"]

    def test_only_close_can_be_automatic(self):
        a = BANK.alerts["A02"]
        self.assertEqual(review(a, {"decision": "sar"}, self.ok_g, self.tools, BANK)["route"], "human")
        self.assertEqual(review(a, {"decision": "escalate"}, self.ok_g, self.tools, BANK)["route"], "human")
        self.assertEqual(review(a, None, self.ok_g, self.tools, BANK)["route"], "human")
        self.assertEqual(review(a, self.close(), self.ok_g, self.tools, BANK)["route"], "auto_close")

    def test_each_check(self):
        a = BANK.alerts["A02"]
        self.assertIn("not backed", review(a, self.close(), {"unsupported": 1}, self.tools, BANK)["reason"])
        self.assertIn("get_case_history", review(a, self.close(), self.ok_g, self.tools[:3], BANK)["reason"])
        self.assertIn("confidence", review(a, self.close(0.7), self.ok_g, self.tools, BANK)["reason"])
        self.assertIn("high impact", review(BANK.alerts["A10"], self.close(), self.ok_g, self.tools, BANK)["reason"])
        self.assertIn("prior SAR", review(dict(BANK.alerts["A20"], amount_total=100), self.close(), self.ok_g, self.tools, BANK)["reason"])
        self.assertIn("shared", review(BANK.alerts["A09"], self.close(), self.ok_g, self.tools, BANK)["reason"])
        self.assertIn("date of birth", review(BANK.alerts["A08"], self.close(), self.ok_g, self.tools, BANK)["reason"])
        self.assertIn("screen_name", review(BANK.alerts["A07"], self.close(), self.ok_g, self.tools[:4], BANK)["reason"])


class BaselineTest(unittest.TestCase):
    def test_known_baseline_behaviour(self):
        got = {aid: run_baseline(aid, BANK)["decision"]["decision"] for aid in ["A01", "A02", "A03", "A05", "A07"]}
        self.assertEqual(got, {"A01": "sar", "A02": "sar", "A03": "close", "A05": "sar", "A07": "escalate"})

    def test_baseline_scores(self):
        rows = [score_case(run_baseline(aid, BANK), BANK.alerts[aid], KEY[aid], BANK) for aid in sorted(BANK.alerts)]
        s = summarize("baseline", rows)
        self.assertEqual(s["dangerous_auto_closes"], 0)
        self.assertEqual(s["unsupported_statements"], 0)


def fake_response(*calls):
    return {"candidates": [{"content": {"role": "model", "parts": [{"functionCall": {"name": n, "args": a}} for n, a in calls]},
                            "finishReason": "STOP"}], "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 10}}


class AgentLoopTest(unittest.TestCase):
    def test_runs_tools_and_records_decision(self):
        decision = {"decision": "close", "confidence": 0.9, "typology": "none", "next_steps": "none",
                    "statements": [{"text": "One cash deposit of $9,600 on 2026-11-05.", "evidence_ids": ["T-0000"]}]}
        script = [
            fake_response(("get_alert", {"alert_id": "A02"})),
            fake_response(("get_customer_profile", {"customer_id": "C02"}), ("get_transactions", {"customer_id": "C02"})),
            {"candidates": [{"content": {"role": "model", "parts": [{"text": "thinking out loud"}]}, "finishReason": "STOP"}]},
            fake_response(("submit_decision", dict(decision, decision="sar"))),  # missing sar_draft -> error back to model
            fake_response(("submit_decision", decision)),
        ]
        bodies = []

        def send(model, body):
            bodies.append(json.loads(json.dumps(body)))
            return script[len(bodies) - 1]

        t = run_alert("A02", BANK, send, "gemini-3.5-flash-lite")
        self.assertEqual(t["outcome"], "decided")
        self.assertEqual(t["decision"]["decision"], "close")
        self.assertEqual([s["tool"] for s in t["steps"]], ["get_alert", "get_customer_profile", "get_transactions", "submit_decision"])
        self.assertEqual(bodies[0]["toolConfig"]["functionCallingConfig"]["mode"], "ANY")
        self.assertEqual(bodies[0]["generationConfig"]["thinkingConfig"], {"thinkingLevel": "LOW"})
        last = bodies[-1]["contents"]
        self.assertIn("sar_draft is required", json.dumps(last[-1]))
        self.assertEqual(t["usage"]["input"], 400)

    def test_max_turns_gives_no_decision(self):
        t = run_alert("A02", BANK, lambda m, b: fake_response(("get_alert", {"alert_id": "A02"})), "m", max_turns=3)
        self.assertEqual((t["outcome"], t["decision"]), ("max_turns", None))
        row = score_case(t, BANK.alerts["A02"], KEY["A02"], BANK)
        self.assertEqual(row["route"], "human")

    def test_decision_checks(self):
        self.assertIsNone(check_decision({"decision": "close", "confidence": 0.5, "typology": "x", "next_steps": "y",
                                          "statements": [{"text": "a", "evidence_ids": []}]}))
        self.assertIn("confidence", check_decision({"decision": "close", "confidence": 5, "typology": "x", "next_steps": "y",
                                                    "statements": [{"text": "a", "evidence_ids": []}]}))

    def test_thinking_config(self):
        self.assertEqual(thinking_config("gemini-2.5-flash", "low"), {"thinkingBudget": 512})
        self.assertIsNone(thinking_config("gemma-3-27b-it"))


class FakeHTTP:
    def __init__(self, items):
        self.items = list(items)
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return io.BytesIO(json.dumps(item).encode())


def http_error(code, body):
    return urllib.error.HTTPError("https://example.invalid", code, "err", {}, io.BytesIO(body.encode()))


class GeminiClientTest(unittest.TestCase):
    def test_retries_then_succeeds_and_key_stays_in_header(self):
        waits = []
        http = FakeHTTP([http_error(429, '{"error":{"message":"Quota exceeded per minute. Please retry in 3.2s."}}'),
                         http_error(503, '{"error":{"message":"high demand"}}'), {"ok": True}])
        c = GeminiClient("SECRET-KEY", sleep=waits.append, opener=http)
        self.assertEqual(c.generate("m", {}), {"ok": True})
        self.assertAlmostEqual(waits[0], 3.7)
        self.assertEqual(len(waits), 2)
        self.assertNotIn("SECRET-KEY", http.requests[0].full_url)
        self.assertEqual(http.requests[0].get_header("X-goog-api-key"), "SECRET-KEY")

    def test_daily_limit_stops(self):
        http = FakeHTTP([http_error(429, '{"error":{"message":"Quota exceeded: GenerateRequestsPerDayPerProjectPerModel, limit: 1000"}}')])
        with self.assertRaises(DailyLimitError):
            GeminiClient("k", sleep=lambda s: None, opener=http).generate("m", {})

    def test_errors_never_show_the_key(self):
        http = FakeHTTP([http_error(400, '{"error":{"message":"bad key SECRET-KEY"}}')])
        with self.assertRaises(GeminiError) as ctx:
            GeminiClient("SECRET-KEY", sleep=lambda s: None, opener=http).generate("m", {})
        self.assertNotIn("SECRET-KEY", str(ctx.exception))

    def test_load_key_from_env_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("# comment\nOTHER=1\nGEMINI_API_KEY=abc123\n")
        try:
            self.assertEqual(load_api_key(f.name, environ={}), "abc123")
            self.assertEqual(load_api_key(None, environ={"GEMINI_ENV_FILE": f.name}), "abc123")
            self.assertEqual(load_api_key(f.name, environ={"GEMINI_API_KEY": "fromenv"}), "fromenv")
        finally:
            os.unlink(f.name)
        with self.assertRaises(GeminiError):
            load_api_key(None, environ={})


class McpServerTest(unittest.TestCase):
    def test_initialize_list_and_call(self):
        lines = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_alert", "arguments": {"alert_id": "A01"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_alert", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "nope"},
        ]
        out = io.StringIO()
        serve(io.StringIO("\n".join(json.dumps(l) for l in lines) + "\n"), out, BANK)
        resp = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual([r["id"] for r in resp], [1, 2, 3, 4, 5])
        self.assertEqual(resp[0]["result"]["serverInfo"]["name"], "mock-bank-investigation-tools")
        self.assertEqual(len(resp[1]["result"]["tools"]), len(DATA_TOOLS))
        self.assertEqual(resp[2]["result"]["structuredContent"]["customer_id"], "C01")
        self.assertTrue(resp[3]["result"]["isError"])
        self.assertEqual(resp[4]["error"]["code"], -32601)
        self.assertIsNone(handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, BANK))


if __name__ == "__main__":
    unittest.main()
