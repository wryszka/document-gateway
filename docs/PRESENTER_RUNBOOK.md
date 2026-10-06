# Presenter runbook — Document Gateway

Literal click-path for someone who is **not** the author. App: `https://document-gateway-7474656169654171.aws.databricksapps.com` (Databricks login required; you need access to the `document-gateway` app). Pairs with `DEMO_RUNSHEET.md` (the beats) and `DEMO_QA.md` (tab 2).

## Before the room
1. **Reset to pristine + roll dates to today:** `python tools/orchestrate.py --reset` (a few minutes — it re-runs the AI pipeline). Restores the four inbound states with the drift + new coverholder **quarantined** for the live acts, months rolled to the last three complete months.
2. **Warm up:** open the app, click **The Book** once (starts the SQL warehouse).
3. **Mode pill (top-left, under MODE):** leave on **cached** for a smooth run; the cache pre-warms as you go. Flip to **live** only to prove a beat is real.
4. **Sanity check the Inbox tiles:** Unchanged 18 · Known-changed 1 · Unknown 2 · Unusable 1; Tenant column shows bordereaux / mrc / health_slip.

## Known-good inputs
- **Drifted coverholder (beats 3–4):** Ridgeway Binder Co — the *latest* month premium file (status `quarantined`, state `known_changed`). Proposed remap: `Gross Premium → GWP`, `Commission → Brokerage`.
- **New coverholder (beat 5):** Saltmarsh Underwriting (state `unknown`).
- **Resubmission / money impact (beat 8):** Templates → Version history → counterparty **Harbourline Underwriting**, period **2026-07** → impact **+£23,430** (v1 £292,872.53 → v2 £316,302.33).
- **Genie (beat 7):** "Which coverholder has the highest loss ratio?" · "How many premium lines did each coverholder report by month?"
- **MRC Ask (beat 9):** "How many contracts by class of business?" · "Which contracts have a cyber exclusion?" (5 contracts: MRC-2025-LL-001…005).
- **Config-port (beat 10):** Config-port nav → health_slip config.

## Click-path per surface
| Beat | Nav | Action | What changes on screen | Fallback if slow/live |
|---|---|---|---|---|
| 1 | **Inbox** | read the 4 tiles | counts 18/1/2/1 | — (static) |
| 2 | Inbox → active row → **Lineage** | enter/keep the line id → Trace | chain analytic→projection→assertion→**cell**→file | screenshot in `docs/REVIEW/` |
| 3 | **Quarantine & Remap** | pick Ridgeway (latest month) | reconciliation table + proposed remap rows | — |
| 4 | same | **Accept remap** | toast "template v2; reprocessed, 12 lines"; doc leaves quarantine | if the AI reprocess is slow, set **cached** |
| 5 | **Schema Recognition** | pick Saltmarsh → confirm mapping | proposed fields + confidences → "learned, lines landed" | **cached** returns the pre-warmed proposal |
| 6 | **The Book** | read strip + tables | GWP ~£2.0m; **Ridgeway behind** (until beat 4 done); loss ratio Ridgeway **88.3%** | — |
| 7 | **Ask** | type a Genie question | answer + generated SQL + rows | flip **cached** for the instant pre-warmed answer |
| 8 | **Templates** → Version history | Harbourline / 2026-07 | two versions + **+£23,430** banner | — (SQL only, fast) |
| 9 | **MRC** | open a contract; **Ask the MRCs** | 5 contracts; Genie answer + SQL | KA half may be arming → Genie half still answers |
| 10 | **Config-port** | read | the `tenant.json` + "no new pipeline code" caption | — (static) |
| — | **Audit** | scroll | ingested / quarantined / superseded / template_updated / signed_off trail | — |
| — | **Eval** | read | Claude & Llama **100% (50/50)**; per-field chips | — |

## If something breaks
- **A view is blank / errors:** flip the **cached** toggle (avoids a live AI call), and re-click the nav item. Every read is a real query — a cold warehouse just needs a few seconds.
- **A live AI beat stalls (accept-remap, schema-confirm, Ask, MRC Ask):** the cached mode returns the pre-warmed result; narrate from the run-sheet SAY line and move on.
- **MRC Ask KA half returns nothing:** the Knowledge Assistant is still indexing — the Genie half answers structurally; say "the wording search is arming" and continue (Q&A #14).
- **State looks wrong (drift already accepted, Saltmarsh already landed):** re-run `python tools/orchestrate.py --reset` to restore pristine.
- **Full recovery:** `databricks bundle deploy -t dev` then `python tools/orchestrate.py` rebuilds everything on a fresh workspace.
