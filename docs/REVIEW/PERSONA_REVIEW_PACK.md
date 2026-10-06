# Persona review pack — Document Gateway

The demo described for review, verified against a fresh reset (as-of Sep 2026; months Jun/Jul/Aug). Source-of-truth is the live schema `lr_dev_aws_us_catalog.document_gateway` and the deployed app.

## 1. Surface census
Data source tags: **[UC]** governed table · **[VIEW]** governed view · **[FN]** governed function · **[GENIE]** embedded Genie · **[KA]** Knowledge Assistant · **[FILE]** repo file served read-only.

| Screen | Reads | Writes |
|---|---|---|
| Inbox | `source_document` [UC] | Rescan → pipeline; Run-review → `reviewer_finding` [UC] |
| Quarantine & Remap | `source_document`, `reviewer_finding` [UC] | Accept → `template`(v++)+`decision`+`audit_event`, reprocess; Reject → status+`decision` |
| Schema Recognition | AI `propose_schema` over the file | Confirm → `template`(v1)+`decision`+`audit_event`, reprocess |
| Templates | `v_template_latest`, `template` history, `versions()` | — |
| The Book | `v_premium_bordereau_line_latest`, `v_claim_bordereau_line_latest`, `v_loss_ratio`, `v_completeness` [VIEW] | — |
| Lineage | `premium_bordereau_line` + `graph_nodes` [UC] | — |
| Eval | `eval_result` [UC] (+ MLflow) | — |
| MRC | `v_mrc_entities_latest` [VIEW]; Ask = [GENIE] + [KA] | — |
| Config-port | `tenants/health_slip/tenant.json` [FILE] via `/api/tenant_config` | — |
| Ask | [GENIE] over graph + projections | — |
| Audit | `audit_event` [UC] | — |
| Learn | `LEARN_CARDS` + env-driven deep links | — |
Reconciliation is `fn_reconcile_status` [FN]. No business math in the app; SQL parameter-bound.

## 2. Click-flow (from a fresh `--reset`)
Inbox (18/1/2/1) → Lineage (cell anchor) → Quarantine (Ridgeway drift) → **Accept remap** (v2, reprocess) → Schema Recognition (Saltmarsh) → **Confirm** (v1, land) → The Book (completeness + loss ratio) → Ask (Genie) → Templates (Harbourline 2026-07 money impact **+£23,430**) → MRC (5 contracts + Ask) → Config-port. Full click-path in `PRESENTER_RUNBOOK.md`.

## 3. State machine (what live actions mutate + reversibility)
| Action | Mutates | Reversible? | Idempotent? |
|---|---|---|---|
| Accept remap | +`template` version, +`decision`, +`audit`; quarantined doc → superseded; new active doc landed | Yes — old version retained; reset restores | Re-accept is blocked (doc already resolved) |
| Schema confirm | +`template` v1, +`decision`, +`audit`; unknown doc → superseded; new active doc | Yes — reset restores | Same |
| Reject | doc → rejected, +`decision`, +`audit` | Reset restores | Yes |
| Rescan inbox | re-runs pipeline over inbox | n/a | Yes (supersedes prior active per period) |
| Run review | +`reviewer_finding` rows | delete on reset | Re-run appends |
| `--reset` | truncates mutable tables + clears inbox + re-seeds + rolls dates | — | Yes (deterministic on seed + as-of) |
Supersession is a status flip; `_latest` views resolve through it; nothing is deleted in normal operation.

## 4. Persona interrogation
- **Practitioner (delegated authority):** reconciliation catches the real drift (`Gross Premium→GWP`, `Commission→Brokerage`); loss ratio and completeness are the two numbers a DA manager actually watches; incurred = paid + outstanding is the standard convention. Realistic.
- **Platform lead:** everything is a UC object (14 tables/12 views); append-only + supersede-not-delete; parameter-bound SQL; app runs on its own SP with least-privilege grants (USE/SELECT/MODIFY/EXECUTE on the schema, READ/WRITE VOLUME, warehouse CAN_USE, Genie CAN_RUN); MCP surface + advise-only agent (no write autonomy).
- **Executive:** the money reconciles across surfaces — Book GWP £1,983,594.76 = sum of the per-coverholder rows; the resubmission delta on Templates matches v2−v1 on the projection; loss ratio matches incurred/GWP.
- **Incumbent champion:** hunts gaps — see the register below; each has an on-screen answer or a labelled roadmap item.

## 5. Numbers appendix (deterministic; live values)
- Pristine states: known_unchanged 18 (17 active + 1 superseded) · known_changed 1 · unknown 2 · unusable 1 (bordereaux); mrc 5 active; health_slip 1 active.
- Book: 96 premium lines / **£1,983,594.76** GWP / 3 coverholders visible; claims 45 lines / **£1,141,240** incurred.
- Per coverholder: Harbourline 36 / £785,335 (3 mo); Kestrel 36 / £741,270 (3 mo); Ridgeway 24 / £456,990 (**2 mo — Aug quarantined**).
- Loss ratio: Ridgeway **0.8827** · Kestrel **0.5016** · Harbourline **0.4661**.
- Resubmission (Harbourline 2026-07): v1 £292,872.53 (superseded) → v2 £316,302.33 (active) = **+£23,429.80**.
- MRC: 5 contracts, **137** graph assertions. Eval: both models **50/50 (100%)**. Templates: all v1 in pristine state (drift not yet learned).

## 6. Known-weaknesses register (ranked by embarrassment; ≤20 words + fallback)
1. **Knowledge Assistant still indexing at demo time** — MRC dual-retrieval shows only the Genie half. *Fallback:* say "wording search is arming"; run `jobs/mrc_ka.py` + redeploy when ACTIVE.
2. **Eval shows 100% for both models** — reads as "too easy". *Fallback:* frame as "reliable on our truth; bring hard cases — the harness runs them"; decoy columns already included.
3. **Health-slip tenant is intentionally thin** (1 slip, 3 groups, no trust-loop drama). *Fallback:* it's the config-port *proof*, not a workbench — the payoff is "one config file".
4. **gen1, not on the shared spine** — projections conform to the contract but aren't the live spine tables. *Fallback:* `GEN2_MIGRATION_DELTA.md` — migration is a mapping, not a rewrite.
5. **Saltmarsh unknowns are two docs** (premium + claims) — both need confirming. *Fallback:* expected; demo confirms the premium one, mention claims is identical.
6. **Live AI beats can be slow on a cold warehouse.** *Fallback:* the yellow cached toggle; cache pre-warms during the run.
7. **Prose reconciliation is lighter than tabular** (section anchors vs full field-by-field). *Fallback:* honest — tabular is the razor-sharp core; prose capture is credible and graph-backed.
