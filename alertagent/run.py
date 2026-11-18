"""Run the investigator on the alert queue and score it.

  python3 -m alertagent.run --agent baseline                          all 24 alerts, rule-based, no key
  python3 -m alertagent.run --env-file ../payer-call-agent/.env       all 24 alerts with Gemini
  python3 -m alertagent.run --env-file PATH A07                       one alert, printed step by step
  python3 -m alertagent.run --rescore results/runs/<run>              re-score saved traces, no model calls
  python3 -m alertagent.run --env-file PATH --resume results/runs/<run>   finish a run that stopped

Key: GEMINI_API_KEY in the environment, or the GEMINI_API_KEY line of the file given by
--env-file / GEMINI_ENV_FILE. The key is never printed or saved.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

from .agent import run_alert
from .baseline import run_baseline
from .bank import Bank
from .gemini import DEFAULT_MODEL, GeminiClient, GeminiError, load_api_key
from .score import TABLE_HEADER, score_case, summarize, table_row

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_key_file():
    with open(os.path.join(ROOT, "data", "answer_key.json")) as f:
        return json.load(f)


def print_trace(trace, row):
    for s in trace["steps"]:
        args = ", ".join("%s=%s" % (k, json.dumps(v)) for k, v in s["args"].items())
        res = s["result"]
        size = len(json.dumps(res))
        print("  turn %-2d %s(%s) -> %s" % (s["turn"], s["tool"], args, ("ERROR " + res["error"]) if s["is_error"] else "%d chars" % size))
    d = trace.get("decision")
    if d:
        print("\n  decision: %s (confidence %s), typology: %s" % (d["decision"], d.get("confidence"), d.get("typology")))
        for st in d.get("statements", []):
            print("   - %s  [%s]" % (st.get("text"), ", ".join(st.get("evidence_ids") or [])))
        if d.get("sar_draft"):
            print("  SAR draft: %s" % d["sar_draft"])
        print("  next steps: %s" % d.get("next_steps"))
    print("\n  expected: %s -> %s; route: %s (%s); unsupported facts: %d / %d" % (
        row["expected"], "RIGHT" if row["correct"] else "WRONG", row["route"], row["reason"], row["unsupported"], row["statements"]))
    for u in row["unsupported_details"]:
        print("   unsupported: %s -> %s" % (u["text"], "; ".join(u["problems"])))
    for p in row["sar_draft_problems"]:
        print("   SAR draft: %s" % p)


def line(row):
    mark = "RIGHT" if row["correct"] else "WRONG"
    flags = []
    if row["dangerous"]:
        flags.append("DANGEROUS AUTO-CLOSE")
    if row["unsupported"]:
        flags.append("%d unsupported" % row["unsupported"])
    if row["error"]:
        flags.append(row["error"])
    return "%s %-19s expected %-8s got %-8s %s  %-10s %2d tools  %s%s" % (
        row["alert_id"], row["rule"], row["expected"], row["got"], mark, row["route"], row["tool_calls"],
        row["reason"], ("  [" + "; ".join(flags) + "]") if flags else "")


def rescore(run_dir, bank, alerts, key, quiet=False, show_lines=True):
    rows, agent = [], None
    for aid in sorted(alerts):
        path = os.path.join(run_dir, "%s.json" % aid)
        if not os.path.exists(path):
            continue
        with open(path) as f:
            trace = json.load(f)
        agent = agent or trace.get("agent")
        rows.append(score_case(trace, alerts[aid], key[aid], bank))
    if not rows:
        print("No saved alerts in %s" % run_dir)
        return None
    s = summarize(agent, rows)
    with open(os.path.join(run_dir, "summary.json"), "w") as f:
        json.dump({"summary": s, "alerts": rows}, f, indent=1)
    if not quiet:
        if show_lines:
            for r in rows:
                print(line(r))
        print("\n" + TABLE_HEADER + "\n" + table_row(s))
        print("\nFalse positives closed with no human work: %d / %d. False alarms (escalate/SAR on a clean alert): %d. "
              "SAR draft problems: %d. Not decided: %d. Tokens: %d in, %d out. Avg %.1f s per alert." % (
                  s["false_positives_auto_closed"], s["false_positives"], s["false_alarms"], s["sar_draft_problems"],
                  s["not_decided"], s["tokens_input"], s["tokens_output"], s["avg_seconds"]))
        if len(rows) < len(alerts):
            print("%d / %d alerts saved in this run." % (len(rows), len(alerts)))
    return s


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("alerts", nargs="*", help="alert ids (default: all)")
    p.add_argument("--agent", choices=["gemini", "baseline"], default="gemini")
    p.add_argument("--env-file", default=None, help="file with a GEMINI_API_KEY= line")
    p.add_argument("--model", default=os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL)
    p.add_argument("--effort", choices=["low", "medium", "high"], default=os.environ.get("AGENT_EFFORT") or "low")
    p.add_argument("--max-turns", type=int, default=16)
    p.add_argument("--pause", type=float, default=0.0, help="seconds to wait between alerts")
    p.add_argument("--rescore", default=None, help="re-score a saved run folder")
    p.add_argument("--resume", default=None, help="finish a saved run folder")
    a = p.parse_args(argv)

    bank = Bank()
    alerts = bank.alerts
    key = load_key_file()
    if a.rescore:
        return 0 if rescore(a.rescore, bank, alerts, key) else 1

    ids = a.alerts or sorted(alerts)
    for i in ids:
        if i not in alerts:
            print("Unknown alert %s" % i)
            return 1
    send = None
    if a.agent == "gemini":
        try:
            client = GeminiClient(load_api_key(a.env_file), log=lambda m: print("   (%s)" % m))
        except GeminiError as e:
            print(e)
            return 1
        send = client.generate

    tag = "baseline" if a.agent == "baseline" else "%s-%s" % (a.model, a.effort)
    run_dir = a.resume or os.path.join(ROOT, "results", "runs", "%s-%s" % (datetime.now().strftime("%Y%m%d%H%M"), tag))
    os.makedirs(run_dir, exist_ok=True)
    single = len(ids) == 1
    for n, aid in enumerate(ids):
        path = os.path.join(run_dir, "%s.json" % aid)
        if a.resume and os.path.exists(path):
            with open(path) as f:
                if json.load(f).get("outcome") == "decided":
                    continue
        if a.agent == "baseline":
            trace = run_baseline(aid, bank)
        else:
            trace = run_alert(aid, bank, send, a.model, a.effort, a.max_turns)
            if trace["outcome"] == "daily_limit":
                print("%s stopped: %s\nTo finish later: python3 -m alertagent.run --env-file PATH --resume %s" % (aid, trace["error"], run_dir))
                break
        with open(path, "w") as f:
            json.dump(trace, f, indent=1)
        row = score_case(trace, alerts[aid], key[aid], bank)
        if single:
            print("%s %s: %s\n" % (aid, alerts[aid]["rule"], alerts[aid]["summary"]))
            print_trace(trace, row)
        else:
            print(line(row))
            sys.stdout.flush()
        if a.pause and n < len(ids) - 1 and a.agent != "baseline":
            time.sleep(a.pause)
    print("\nSaved: %s\n" % os.path.relpath(run_dir, ROOT))
    if not single:
        rescore(run_dir, bank, alerts, key, show_lines=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
