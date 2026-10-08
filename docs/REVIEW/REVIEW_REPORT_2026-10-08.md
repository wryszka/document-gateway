# Review report — Document Gateway · MRC flow (Lloyd's of London, Fri 9 Oct 2026)

> Standardized output of the 9-agent review panel (BUILD_AND_REVIEW.md §7), run fan-out (all nine personas in parallel, none seeing another's verdict) and collated here. Scope: the **MRC flow only** (Intake · Schemas · Contracts · Analytics · Governance), for a Corporation of Lloyd's technical lead, ~30 minutes. Questions that can't be answered live are in `docs/MRC_DEMO_QA.md` (tab 2).

- **Demo:** document-gateway — MRC flow · repo wryszka/document-gateway · app `document-gateway` on DEV
- **Reviewed:** 2026-10-08 · against a fresh reset of the isolated test schema `document_gateway_test`. The full flow was run headless: reset → intake 66 s → intake agent 20 s → change agent 14 s → accept 46 s → schema agent 14 s → recognise 46 s → contracts / contract tabs → Ask 30 s → governance. No JavaScript errors. The live demo schema was not written to.
- **Verdict:** **NOT YET against the standard — room-ready for Friday with labelled gaps.** Every room-facing P0 passes. The open P0s are architectural (platform-native thin app, agents on Agent Framework, MCP-first native): the orchestration runs as Python inside the app. That can't be ported honestly in two days, so it is labelled and answered (run sheet close + Q&A #13) and roadmapped.
- **Scorecard (§6):** P0 **31 / 38** pass · P1 **19 / 25** pass · open items below.

**Severity:** `blocker` · `major` · `minor` · `nit`. **Status:** `fixed` · `roadmapped` · `wontfix (reason)` · `open`.

---

## Scorecard summary (gaps only)

| Theme | Item | Result | Note |
|---|---|---|---|
| B | P0 single schema, numbered table prefixes | ⚠️ gap | One schema ✓, but MRC tables are not numbered (`mrc_entities`, `mrc_extraction`…). Roadmapped (rename = migration; not before Friday). |
| C | P0 agents on Agent Bricks / Agent Framework via AI Gateway | ⚠️ gap | Review agents are `ai_query` calls from the app. Roadmapped. |
| C | P0 platform-native, thin app | ❌ fail | Fingerprint, classify, diff, accept, confirm, ingest and the job runner live in `jobs/*` and are imported into the app process (`app/server/app.py` `_start_job`). Data, decisions and audit are governed UC tables ✓. Labelled + roadmapped. |
| D | P0 deployment authority enforced server-side as UC privilege | ⚠️ gap | Accept / confirm / return are app endpoints protected only by app access; no UC `EXECUTE` gate. Roadmapped together with C. |
| D | P0 MCP-first and Databricks-native | ❌ fail | The repo's `mcp_server/` wraps Python modules, and the MRC steps aren't exposed through it. Roadmapped. |
| E | P0 reset rolls data forward to today | ⚠️ gap | Reset is deterministic and in-app ✓, but contract dates are fixed (2026 periods). Acceptable for this room; roadmapped. |
| J | P0 platform-native verified | ❌ fail | Same as C. |
| D | P1 externally callable MCP surface | ⚠️ gap | Not for MRC. |
| E | P1 compatibility tier declared / advance_period | ⚠️ gap | Not declared for the MRC flow; no advance_period beat. |
| F | P1 yellow live/cached toggle | ✅ **fixed in this pass** | The switch read "LIVE" while the app was actually in cached mode, and MRC AI calls ignored it. Both fixed (see Applied fixes). |
| H | P1 manuals surfaced in-app via the hub | ⚠️ gap | Run sheet and Q&A are markdown in the repo + Google Doc; the hub tile links the app only. |
| G | P1 red-team questions answered unprompted on screen | ⚠️ partial | Answered in the close and the Q&A tab rather than on screen. |

All other P0 items pass: story opens on the pain; no vendor names; value is "wrap"; disclaimer present; explainers on every screen; the deterministic engine decides and AI advises; illustrative items (Core Data Record crosswalk) are labelled; every value traces to section + source line + schema version; decisions and schema versions are append-only; Genie is embedded and created via the API; run sheet is in GO · DO · SAY · IF ASKED format; security is clean.

---

## 1 · Practitioner (London-market placement / contract-certainty)
*Verdict from the reviewer: "Credible, real and right for Lloyd's market operations." Beat 8 (one contract: certainty + every value's source line) was judged the strongest moment.*

| # | Finding | Severity | Status |
|---|---|---|---|
| 1.1 | Governing-law check is presence-only (`jobs/mrc_pipeline.py:227`) | minor | wontfix for Friday — Q&A #5 (illustrative rule set) |
| 1.2 | Several-liability check looks for LSW1001 only (`mrc_pipeline.py:210`) | minor | roadmapped — Q&A #7 |
| 1.3 | "UMR must start with B" flagged as too strict | — | **wontfix (reviewer error)**: a Lloyd's UMR is "B" + the four-digit broker number by definition. Q&A #19. |
| 1.4 | Endorsements / binders / facultative scope should be explicit | minor | fixed — Q&A #2, #4 |
| 1.5 | No FX basis for multi-currency | nit | Q&A #9 (per-currency by design) |
| 1.6 | Syndicate verified as real but not as actively writing the class | nit | roadmapped |
| 1.7 | Delta Sharing not built | minor | already labelled "forward hook" — Q&A #17 |

**Deal-breakers:** none, provided the open-market scope and the indicative Core Data Record are said out loud (both are in the run sheet).
**Value story:** **wrap** — a governed, lineaged reading layer around today's placement and document tools. It replaces manual re-keying and checking; it doesn't replace placing platforms.

## 2 · Decision-maker (Corporation director of market data / COO)

| # | Finding | Severity | Status |
|---|---|---|---|
| 2.1 | "These are the results" beat was missing — the run ended on governance, not outcome | major | **fixed** — new CLOSE line (5 of 8 straight through; 3 exceptions, one recorded decision each; every value traced) |
| 2.2 | Beat 0 framed technically, not around today's rework | major | **fixed** — Beat 0 SAY now names the hand-keying and re-checking |
| 2.3 | No quantified risk of inaction / cost | major | **wontfix (reason):** inventing a £ figure for the Lloyd's market would break the "show, don't assert" principle in front of the people who know the numbers. The close states the observable result; Q&A #15 offers to measure on their sample. |
| 2.4 | Agent wording can read prescriptive | minor | mitigated — the panel shows "advises only · logged" on every answer |
| 2.5 | Beat 8 SAY should stress the governance shift | minor | open — presenter's discretion |

## 3 · Databricks SA (demoability)
*Verdict from the reviewer: "You can deliver this live on Friday. No blocker found."*

| # | Finding | Severity | Status |
|---|---|---|---|
| 3.1 | Run is ~33–34 min with talk; slot is 30 | major | existing cut order covers it (cut 7 → optional 9 → 3 → 6; never 2, 4, 5, 8) |
| 3.2 | Pre-flight should wait for reset to finish before anything else | minor | **fixed** — run sheet pre-flight step 1 |
| 3.3 | First AI call is cold (~20 s) and nothing is cached | major | **fixed** — cached mode now works for Ask and all three agents; pre-flight says rehearse once after the last deploy, then reset |
| 3.4 | Job state is in memory; an app restart mid-step loses it | minor | roadmapped (moves with the Jobs migration) |
| 3.5 | Knowledge Assistant may lag Genie | minor | covered — "IF SLOW" line in beat 9 |

## 4 · Senior developer

| # | Finding | Severity | Status |
|---|---|---|---|
| 4.1 | Job runner check-then-set was not atomic (`app.py` `_start_job`) | major | **fixed** — `threading.Lock` |
| 4.2 | `first()` without ordering for syndicates (`/api/mrc/contracts`) | minor | **fixed** — `max()` (one row per contract; deterministic) |
| 4.3 | `window.__mrcProposal / __mrcChanges / __mrcChangesDoc` survive navigation | minor | **fixed** — cleared on every full render |
| 4.4 | Error text truncated to 300 chars | minor | **fixed** — 1,000 |
| 4.5 | Inbox poller race between renders | major | wontfix (reason): render already clears the poller first; re-checked with a 400 s sampled run — no blink, no lost poll |
| 4.6 | DELETE-then-INSERT without a transaction (`mrc_pipeline.py` ingest) | minor | roadmapped (MERGE) — idempotent re-run recovers |
| 4.7 | Broad excepts in the AI-graph path hide failures | minor | roadmapped (log + surface) |
| 4.8 | Documents stuck in "processing" if a job dies | minor | roadmapped; Reset recovers |
| 4.9 | Legacy `/api/mrc` list + hidden "Contracts & Ask" view duplicate newer screens | nit | roadmapped — remove after Friday (still reachable from Analytics links; harmless) |

## 5 · Security
*Verdict from the reviewer: clean; approved.*

| # | Finding | Severity | Status |
|---|---|---|---|
| 5.1 | Secrets in code/history | — | **clean** (history scanned for token/key patterns; `.env` ignored) |
| 5.2 | SQL | — | parameter-bound throughout; the editable field is allow-listed |
| 5.3 | HTML / XSS | — | `escapeHtml` / `escapeAttr` used; the agent markdown renderer escapes first, then formats (checked) |
| 5.4 | PDF endpoint path traversal | — | path read from the database by doc id, never from the URL |
| 5.5 | Contract text flows into agent prompts (prompt injection) | minor | accepted: agents are advise-only and cannot act; every prompt's facts are logged |
| 5.6 | Write endpoints rely on app access, not per-action UC privilege | minor | roadmapped with platform-native (D) |

## 6 · Current-Databricks expert
*Docs swept as of 2026-10-08: Foundation Model APIs supported models, Agent Bricks / Agent Framework, system tables, Auto Loader / Lakeflow, Genie, Databricks Apps, databricks-sdk.*

| # | Finding | Severity | Status |
|---|---|---|---|
| 6.1 | `databricks-claude-sonnet-4-5` is not the newest; `databricks-claude-sonnet-5`, `-sonnet-5-5` and `-opus-5-5` are served on DEV (confirmed via the endpoint list) | minor | roadmapped — not swapping the model the day before the room without a full re-run; one-line config change |
| 6.2 | Agents should be Agent Framework / Agent Bricks, served behind AI Gateway (tracing, evaluation) | major | roadmapped (same as C) |
| 6.3 | Inbox pick-up should be Auto Loader in a scheduled pipeline, not a button | minor | roadmapped — the button is the demo's "run intake now"; Q&A #14 |
| 6.4 | Platform audit (`system.access.audit`, lineage system tables) | minor | wontfix (reason): complementary — the app's audit table records business events with reasons; Q&A #16 |
| 6.5 | `databricks-sdk>=0.133` unpinned | nit | roadmapped |
| 6.6 | `ai_parse_document`, Genie Conversation API, Knowledge Assistant (Responses format), Statement Execution API | — | current |

## 7 · Incumbent champion (hostile veteran)

| # | Objection | Severity | Answered live? | Status |
|---|---|---|---|---|
| 7.1 | All eight PDFs are clean generated documents — what about real scanned MRCs? | major | Q&A #1 | answered honestly: falls to a person, never silently loaded; accuracy on a real inbox unmeasured — offer a sample run |
| 7.2 | Endorsements / addenda not handled | major | Q&A #2 | roadmapped |
| 7.3 | Born-digital MRCs (placing platforms) — why parse PDFs? | major | Q&A #3 | answered: structured feeds land in the same tables; PDFs are the long tail |
| 7.4 | Seven certainty rules vs a real ruleset | major | beat 8 + Q&A #5 | labelled illustrative; rules are versioned code |
| 7.5 | 97.5% signed is often "pending", not "fail" | minor | Q&A #6 | roadmapped (tri-state) |
| 7.6 | Core Data Record is a paraphrase | major | beat 8 (on-screen label) + Q&A #8 | labelled |
| 7.7 | Scale and cost unproven | major | Q&A #14, #15 | answered honestly; no invented numbers |
| 7.8 | No approval workflow / four-eyes / rollback on schemas | major | beat 10 + Q&A #10, #12 | who/when shown live; four-eyes + one-click retract roadmapped |
| 7.9 | No counterparty access (Delta Sharing) | minor | Q&A #17 | forward hook |
| 7.10 | "Real broker/syndicate names are a confidentiality risk" | — | Q&A #18 | **wontfix (reason):** deliberate presenter decision — well-known public market names, no names from customer conversations; insureds are invented |
| 7.11 | "Hiscox insists on deductible ≤10% of limit"; "30+ checks" | — | — | **discarded:** unsourced claims by the reviewer |

**Objections that can't be shown live:** 7.1, 7.2, 7.3, 7.7, 7.8 (four-eyes / retract), 7.9 — all in `docs/MRC_DEMO_QA.md`, cross-referenced by beat.

## 8 · UI/UX expert

| # | Finding | Severity | Status |
|---|---|---|---|
| 8.1 | Schema recognition table is dense (8 columns, small inputs) | major | roadmapped — readable at presenter zoom; restructuring the screen the day before is the bigger risk |
| 8.2 | Long state chips wrap to two lines on Intake | minor | open (polish) |
| 8.3 | "Analytics has no visible text input" | — | **wontfix (reviewer error):** the input box and Ask button are above the example chips (`mrc_analytics` view) |
| 8.4 | Contract list shows pass / n failed, detail shows the reason | nit | intentional list → detail hierarchy |
| 8.5 | "Values & lineage" tab vs hidden "Lineage" page | nit | the Analytics link is already named "Lineage explorer →" |
| 8.6 | Contract hero strip, house palette, tabs, explainers | — | pass |

## 9 · Platform-native architect
*Verdict from the reviewer: **FAIL** on the platform-native P0.*

| Component | Lives today | Native target | Severity | When |
|---|---|---|---|---|
| Intake / recognise / accept orchestration | Python thread in the app (`_start_job`) | Databricks Job triggered by the app | P0 | roadmap |
| Fingerprint, classify, diff | `jobs/mrc_schemas.py` imported into the app | UC functions | P0 | roadmap |
| Parse + certainty checks + ingest | `jobs/mrc_pipeline.py` in the app | Job / Lakeflow pipeline + UC functions | P0 | roadmap |
| Accept / confirm / return gates | App endpoints | UC functions with `EXECUTE` grants | P0 | roadmap |
| Review agents | `ai_query` from `jobs/mrc_agents.py` | Agent Framework agent behind AI Gateway, UC-function tools | P0 | roadmap |
| Data, schema versions, decisions, audit | UC tables / views | ✓ | — | — |
| Reconciliation math (`fn_reconcile_status`) | UC function | ✓ | — | — |

**Honest one-liner for the room** (now in the run sheet close and Q&A #13): *"The data, schema versions, decisions and audit are governed tables. Reading and Ask are platform services. For this demo the orchestration runs inside the app; in production it moves into scheduled Jobs and Unity Catalog functions, with approvals as platform permissions."*

---

## Applied fixes (this pass)
- `app/server/app.py` — job runner check-and-set under a lock; longer error text; deterministic syndicates subquery; **CACHED mode for `/api/mrc/ask` and both agent endpoints** (in-memory replay; survives Reset, not redeploy).
- `jobs/mrc_agents.py` — agents accept the cache; responses say when they were replayed. (Earlier in the day: precomputed counts + per-currency premium so the intake agent can't miscount or convert currencies.)
- `app/frontend/index.html` — MODE switch now starts as yellow **CACHED** (it showed "LIVE" while the app was actually in cached mode); "replayed from cache" labels on Ask and agent answers; stale proposal/changes state cleared on navigation.
- `docs/MRC_LLOYDS_RUNSHEET.md` — pre-flight (wait for reset; cached mode + rehearse once after the last deploy); Beat 0 names today's rework; new results CLOSE; honest "where does the logic run" line; pointer to the Q&A tab.
- `docs/MRC_DEMO_QA.md` — **new** tab 2: 19 questions with straight answers, cross-referenced by beat.

## Open / roadmapped (after Friday)
1. **Platform-native port** — the MRC steps become UC functions and a Job, approvals become UC `EXECUTE` grants, and the agents move to Agent Framework behind AI Gateway, exposed via managed MCP. (Closes C, D and J P0s.)
2. Numbered table prefixes for the MRC tables (B P0).
3. Endorsements as a linked document type; tri-state "pending signing"; more several-liability wordings; one-click "retract schema and re-read".
4. Four-eyes schema approval as a platform permission.
5. Model upgrade to `databricks-claude-sonnet-5-5` with a full flow re-run.
6. Auto Loader pick-up for the inbox; Delta Sharing to counterparties.
7. Remove the legacy `/api/mrc` list and hidden "Contracts & Ask" view; MERGE instead of DELETE + INSERT; surface AI-graph errors.
8. Schema recognition table density (progressive disclosure).
9. Surface the run sheet and Q&A in-app via the hub tile.
