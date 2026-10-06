# Document Gateway — Demo Review (8-agent panel)

**Date:** 2026-09-10 · **Standard:** Bricksurance demo standard v2.2 (§6 scorecard, §7 panel) · **Reviewed:** live on DEV (`document-gateway`, `lr_dev_aws_us_catalog.document_gateway`) + repo + docs.

## Verdict: **SHIP WITH ROADMAPPED GAPS**

The demo answers its canonical question end-to-end across three tenants, the load-bearing capability is razor-sharp under drill-down, and governance/lineage are first-class. **One true P0 (a SQL-injection via an unbound `actor` parameter) was found and fixed.** Everything else is either a quick fix (applied) or a labelled, roadmapped Phase-2 item. The incumbent-champion's summary captures it: *"not a toy — the core is production-solid; ship Phase 1 with an explicit edge-case roadmap, don't overpromise."*

### Scorecard tally
- **P0:** all pass **after** the SQL-injection fix (theme C/J security). No other P0 open.
- **P1:** pass or labelled+roadmapped (business-case quantification, least-privilege grant note, accessibility labels, Genie attachment-API currency — all addressed or roadmapped below).
- **P2:** polish (favicon 404, minor styling).

### Panel verdicts
| Agent | Verdict |
|---|---|
| Practitioner | **Ship** — real & right; completeness/loss-ratio/reconciliation match how DA & MRC actually work; no deal-breakers. |
| Decision-maker | **Ship with roadmapped gaps** — story lands; add a quantified business-case appendix (FTE/error/cycle-time). |
| Databricks SA | **Demo-safe if pre-flighted** — warm the warehouse (beats 7/9 Genie latency); ordering guards + KA-arming documented. |
| Senior developer | Sound; **1 blocker (SQL injection ×2)** + 1 XSS + a grant-style nit. |
| Security | **Blocker: SQL injection** (`actor` unbound); else clean — no secrets, params bound, path-validated, no egress. |
| Current-Databricks | **Mostly current**; one medium (prefer `execute_message_attachment_query`), two minor (ai_query `responseFormat`, ai_parse `version`). |
| Incumbent champion | **Survives scrutiny** — core solid; edge-cases/hard-eval/scale are Phase 2 and honestly labelled. |
| UI/UX | **Coherent, §3 passes**; P1 accessibility (unlabeled inputs) + cosmetic favicon 404. |

---

## Findings & disposition

### Fixed 2026-09-10
| # | Sev | Theme | Finding | Fix |
|---|---|---|---|---|
| 1 | **P0 blocker** | C/J security | **SQL injection** — user/agent-supplied `actor` interpolated as `'{actor}'` in two template INSERTs (`jobs/trust_loop.py:100,150`), reachable from `/api/quarantine/accept|reject`, `/api/schema/confirm`, and MCP tools. | Bound as `:actor` at both sites. |
| 2 | major | J | **XSS** — `e.message` concatenated unescaped into `innerHTML` (`app/frontend/index.html`). | `escapeHtml(e.message)` at the error sink(s). |
| 3 | P1 | F | **Accessibility** — 5 text inputs (Inbox/Lineage/Templates/MRC/Ask) + the confirm-modal textarea lack labels ("No label associated with a form field"). | `aria-label` on each input; `for="confirmReason"` on the modal label. |
| 4 | medium | C | **Genie attachment API** — used `get_message_attachment_query_result` only. | Prefer `execute_message_attachment_query`, fall back to the getter. |
| 5 | minor | F | Disclaimer didn't state insureds are invented while MRC uses real market names. | Footer wording tightened. |

### False positive (verified, not a defect)
- Decision-maker flagged "**DECISIONS.md is a template, not filled**" (claimed blocker). **Verified false** — `DECISIONS.md` is complete: D1–D9 kickoff decisions + build passes P1→T3/T2 + shared gotchas, zero template placeholders. The reviewer likely read the playbook `template/DECISIONS.md`.

### Roadmapped / labelled (ship as-is; in the persona pack weaknesses register)
| Theme | Item | Disposition |
|---|---|---|
| A/decision-maker | **Business-case quantification** (FTE/error/cycle-time baseline vs. impact) | Added a Business Case appendix to `docs/TALK_TRACK.md`. |
| C/security | **Schema-wide `MODIFY` grant** to the app SP is broader than strictly needed | Documented as accepted for a gen1 demo (DECISIONS); tighten to per-table on gen2. |
| Incumbent/practitioner | **Edge cases** — merged cells, multi-sheet, `.xls`/`.csv`, variable header rows, subtotal rows | Phase 2; today's "unusable" state is the safe fallback (labelled). |
| Incumbent | **Eval is synthetic (both models 100%)** — no messy real-data / value-level / null / scale test | Harness runs hard cases on request (DEMO_QA #2); frame as "reliable on our truth, bring hard cases." |
| Incumbent/SA | **Scale not demonstrated** (22 files, no wall-clock on Inbox) | Reframe as Phase-1 volume; pipeline is serverless jobs; enterprise topology in GEN2_MIGRATION_DELTA. |
| Incumbent/practitioner | **Prose reconciliation lighter than tabular** (MRC has no field-level AGREE/DIFFER) | By design; graph-backed + labelled. |
| all | **MRC Knowledge Assistant still arming** | Genie half live; KA arms via `jobs/mrc_ka.py` + redeploy; honest fallback in Q&A #14. |
| B/decision-maker | **gen1, not on the shared spine** | Conform-to-contract; migration is a mapping (`GEN2_MIGRATION_DELTA.md`, D4). |
| D | **Agent graduated-autonomy corridor** not shown | Advise-only ceiling is enforced; corridor is a forward hook. |
| SA | **Pre-flight warm-warehouse mandatory** (cold Genie stalls beats 7/9) | Added a non-negotiable line to the runsheet pre-flight. |

### Deal-breakers
None. The incumbent-champion, practitioner and decision-maker each concluded there is **no moment the room leaves thinking "not possible here"** — the gaps are Phase-2 scope, honestly labelled, with on-screen or Q&A answers.

### Can't-show-live (must live in DEMO_QA — all present)
LLM-hallucination rigor (eval + "bring hard cases"), messy-file edge cases, month-end scale/timing, KA dual-retrieval while arming, gen1→gen2 migration cost. All have Q&A entries cross-linked to the beat that provokes them.

---

*Source of record. Produced by the §7 8-agent fan-out panel; findings collated and P0/major fixes applied the same day. Re-run the panel before the next promotion.*
