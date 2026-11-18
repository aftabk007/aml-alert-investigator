# AML alert investigator (demo for Socratix AI)

An AI agent works a queue of **mock** bank alerts the way an AML or fraud analyst does. For each alert it calls tools over a mock bank (alert queue, KYC file, transactions, counterparties, logins and devices, case history, sanctions / PEP / adverse media screening), then writes a short case where every fact cites the record it came from. It decides **close** (false positive), **escalate** (a person must act now) or **SAR** (with a draft SAR narrative), and gives a confidence. A review rule decides which cases a person must see.

**Synthetic data only.** The bank, people, companies, countries ("Kestovia", "Belmora", "Varonia") and the watchlist are made up. Nothing here touches a real bank, a real sanctions list or Socratix's product.

## Results (18 Nov 2026)

All 24 alerts, run with `gemini-3.5-flash-lite` (thinking `low`) on the free tier. Both investigators use the same tools, the same review rule and the same scoring code (`alertagent/score.py`):

| Investigator | Decisions right | Suspicious alerts it closed | ...of those, closed with no person (must be 0) | Clean alerts closed with no person | Facts not backed by the cited record | Tool calls per alert | Sent to a person |
|---|---|---|---|---|---|---|---|
| Rule-based baseline (no LLM) | 12 / 24 | 1 | 0 | 0 / 11 | 0 / 48 | 4.5 | 24 / 24 (100%) |
| AI agent (Gemini 3.5 Flash-Lite, prompt v1) | **22 / 24** | **0** | **0** | **7 / 11** | 2 / 89 | 5.8 | 17 / 24 (71%) |

13 of the 24 alerts are really suspicious (9 should get a SAR draft, 4 need an escalation) and 11 are clean. Only a "close" can be automatic, so with this review rule the best possible is 8 of 11 clean alerts closed with no person, and 16 of 24 alerts sent to a person (all 13 suspicious ones, plus 3 clean ones over $25,000). The 24 alerts used 297K input and 27K output tokens. The average was 44 seconds per alert, mostly waiting on the free tier's per-minute limit.

What the agent got right that the rules did not:

- **A02:** one $9,600 cash deposit, with a bill of sale on file for a car sale. The agent closed it. The baseline drafted a SAR. (Since October 2025 the US agencies say cash near $10,000 is not enough for a SAR on its own.)
- **A03:** six cash deposits of $4,700-$4,950 in ten days ($29,100), then a $28,000 wire. That is structuring far under $10,000. The agent drafted a SAR. The baseline only looks near $10,000, so it closed this case. Only the review rule's $25,000 check stopped that close from going through.
- **A05:** 12 payments on one day. They are payroll to the same 12 staff every second Friday. Agent: close. Baseline: SAR.
- **A07, A21:** a sanctions name match (born 1991 vs 1967, different nationality) and a news match (age 29 vs 62, different state). Both are other people. Agent: close. Baseline: escalate.
- **A10, A23:** money in and straight out, but it is a home purchase from his own brokerage account and a property tax payment from his own savings. Agent: close. Baseline: SAR.

Mistakes in this run:

- **A06, A09 (wrong decision, but safe):** both are mule cases: money arrives from new sources and goes out within hours, plus a new device. The agent called them "account takeover" and escalated instead of drafting a SAR. Both still went to a person, but with the wrong next step.
- **A07 (right decision, sent to a person):** the agent closed the sanctions match correctly but skipped `get_transactions`, so the review rule did not let it close automatically.
- **A13, A15 (wrong citation):** the amount was true, but the agent cited the wrong record. For example, it took $4,500 of expected monthly income from the alert record instead of the KYC file. The citation check flagged both. Both cases went to a person anyway.
- **What the check cannot see:** in A03 the agent wrote that the $4,700-$4,950 deposits were "just under the $10,000 CTR reporting threshold". The amounts are right, the description is not.
- **Confidence is not a safety signal here:** the agent said 0.9 or more on all 24 alerts, and 1.0 on A06, which was wrong. The 0.85 confidence floor in the review rule never fired. The agent never closed a suspicious alert in this run, so the review rule never had to stop a wrong close. It did stop one for the baseline (A03, with the $25,000 check).

### Fix run (prompt v2)

After run 1 I changed only the prompt (`alertagent/prompt.py`, v2). It now lists the 4 tools every alert needs, explains how an account takeover differs from a mule, and says which record to cite for each number. The review rule did not change. Then I ran all 24 alerts again. **The run stopped after 14 alerts (A01-A14), because the free tier's daily limit for this model (500 requests) ran out.** Same 14 alerts in both runs:

| Prompt | Decisions right | Suspicious alerts closed | Clean alerts closed with no person | Facts not backed by the cited record | Tool calls per alert | Sent to a person |
|---|---|---|---|---|---|---|
| v1 (run 1) | 12 / 14 | 0 | 3 / 7 | 1 / 51 | 5.9 | 11 / 14 |
| v2 (run 2) | 13 / 14 | 0 | 4 / 7 | 0 / 53 | 5.7 | 10 / 14 |

- Fixed: A09 is now a SAR draft. A07 now calls `get_transactions` and closes automatically. No wrong citations.
- Not fixed: A06 is still called "account takeover" and escalated (confidence 0.95).
- I changed the prompt after seeing run 1's mistakes on these same alerts, so v2's numbers are a best case, not a clean test. A clean test needs new alerts the prompt was not tuned on.
- Alerts A15-A24 have not been run with v2 yet. To finish after the daily limit resets: `python3 -m alertagent.run --env-file .env --resume results/runs/202611181705-gemini-3.5-flash-lite-low`

### The review rule

Only a "close" can be applied automatically (`alertagent/review.py`). An escalation or a SAR draft always goes to a person, because a person has to act on it, and the BSA officer edits and files every SAR. A close goes through only if all of these pass. The first one that fails is the reason the analyst sees:

1. Every fact in the case passes the citation check.
2. The agent called the tools the alert type needs: alert, KYC, transactions and case history for every alert, plus screening for watchlist hits and logins for money-movement and new-device alerts.
3. The alert is under $25,000.
4. The customer has no prior SAR.
5. No device used by the customer in the last 30 days is shared with other customers.
6. No watchlist entry with a similar name has the same date of birth.
7. The agent's confidence is 0.85 or more.

Checks 4-6 do their own lookups in the bank data. They do not trust what the agent says it found.

### The citation check

Every fact in the case has to cite evidence ids from the tool results (`T-0017` for a transaction, `KYC-C01` for the KYC file, `CH-001` for a note, and so on). `alertagent/grounding.py` is plain code, no LLM. It fails a fact if it cites nothing, cites an id that no tool returned in this case, or has an amount or a date (`2026-11-03` or `November 3, 2026`) that is not in the cited records. A total is fine if it is the sum of the cited amounts. The $10,000 CTR line and the $5,000 SAR line are always allowed. SAR drafts get the same money and date check against everything the agent saw.

While checking run 1 by hand, I found a bug in this check: it did not read dates inside timestamps (`2026-11-12T08:05:00`), so it flagged one true fact in A06. I fixed it (commit 2d630f9) and re-scored the saved run. All numbers above use the fixed check.

## What is inside

| Part | File | What it does |
|---|---|---|
| Mock bank | `alertagent/build_data.py` → `data/*.json` | 24 customers with 3 months of activity, 24 alerts, notes, logins, a fictional watchlist, and the answer key |
| Tools | `alertagent/tools.py`, `alertagent/bank.py` | 7 data tools written like MCP tools (name, description, `inputSchema`), one per system an analyst opens, plus `submit_decision` |
| MCP server | `alertagent/mcp_server.py` | The same 7 tools over stdio JSON-RPC (`initialize`, `tools/list`, `tools/call`). Standard library only. The agent in this demo calls the same functions directly, not through this server |
| Agent | `alertagent/agent.py`, `alertagent/prompt.py` | Gemini function calling. The prompt is the bank's operating procedure for alerts |
| Gemini client | `alertagent/gemini.py` | REST `generateContent` with `urllib`. Retries per-minute limits and server errors, stops cleanly on the daily limit |
| Citation check | `alertagent/grounding.py` | Plain code, no LLM. Fails a fact if it cites nothing, cites a record no tool returned, or has an amount or date that is not in the cited records |
| Review rule | `alertagent/review.py` | Decides "close automatically" or "send to a person" |
| Baseline | `alertagent/baseline.py` | No LLM: one fixed if-then rule per alert type. The "before" number |
| Scoring | `alertagent/score.py` | Compares saved traces with the answer key. Runs offline |
| Saved runs | `results/runs/` | Every tool call, result, model turn and decision, so anyone can re-score without new model calls |

## Run it

Python 3.9 or newer, standard library only. No `pip install`.

```bash
python3 -m unittest
```

Without a key (rule-based baseline):

```bash
python3 -m alertagent.run --agent baseline
```

With Gemini: put `GEMINI_API_KEY=...` in `.env` (see `.env.example`), or point at any file that has that line:

```bash
python3 -m alertagent.run --env-file .env A07
```

```bash
python3 -m alertagent.run --env-file .env
```

Re-score a saved run with the current review rule and citation check (no model calls):

```bash
python3 -m alertagent.run --rescore results/runs/<run folder>
```

The MCP server, for any MCP client:

```bash
python3 -m alertagent.mcp_server
```

## Model settings

- `gemini-3.5-flash-lite` unless you set `GEMINI_MODEL` or `--model`. Thinking level `low` (`AGENT_EFFORT` or `--effort`).
- Every turn must be a tool call (function calling mode `ANY`). The model may call several tools in one turn.
- The model's turns are sent back unchanged, so Gemini's thought signatures are kept.
- The key is read at run time from `GEMINI_API_KEY` or from the file given by `--env-file` / `GEMINI_ENV_FILE`. It goes in a request header, never in the URL, and is never printed or saved.

## Limits

- 24 alerts is a small set, and I wrote both the cases and the answer key. The numbers show how the parts work together; they are not a benchmark.
- One run per setting. An LLM can answer differently on the next run.
- The citation check only checks citations, money and dates. It cannot tell if a sentence's words are true ("she seemed rushed").
- The mock data is clean. Real bank data comes from many systems with different ids, gaps and duplicates.
- Not built: learning from past analyst decisions, retrieval of similar past cases, a case screen for analysts, a real audit log store, deployment.

## What I would build next at Socratix

1. **Grow the eval set from real closed cases** (with the customer's permission): each alert with the analyst's final decision. Run it on every prompt or model change. Track two numbers per customer: suspicious alerts closed with no person (must stay 0) and the share of clean alerts closed automatically.
2. **The review rule as a per-customer file**, so a bank's team can read and tune its own "operating procedure": required checks per alert type, money limits, always-a-person rules. Every automatic close keeps the reason it passed, for the examiner.
3. **A stricter citation check for SAR drafts**: check each of the five Ws and the how, names and counts, not only money and dates. Send any failure back to the agent once, then to a person.
4. **Account memory**: give the agent past cases and analyst notes for the same customer and similar cases, and measure if it helps on the eval set before shipping it.

Built by [Aftab Ahmad Khan](https://github.com/aftabk007).
