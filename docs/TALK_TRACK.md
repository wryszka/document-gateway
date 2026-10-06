# Talk track — Document Gateway

Two versions of the same story. Understated: the platform is *how*, shown behind the scenes — never the opening line.

---

## Executive (≈3 minutes)

**The problem you already have.** Business reaches you as documents from other people — delegated-authority bordereaux from coverholders, renewal exhibits from health carriers, Market Reform Contracts from brokers. Every counterparty sends its own shape. Today, turning those into a book you can act on and defend is manual, slow, and undocumented — so the book is late, and when the regulator or the reinsurer asks "where did this number come from?", the answer is a spreadsheet and a person's memory.

**The three beats.**
1. **You already have everything this needs** — the files are arriving today.
2. **One governed loop** turns any counterparty document into decision-grade data — open code, your workspace, no black box.
3. **The results:** rows you can defend down to the cell they came from, a vocabulary that compounds so you never map the same file twice, and a book anyone can interrogate in plain English.

**What "good" looks like in the room.** A coverholder quietly renames two columns; the system catches it, proposes the fix, you confirm **once**, and every future file is automatic. A brand-new coverholder is onboarded in under a minute. A restated month shows its exact effect — **+£23,430** — instead of silently changing the book. And a coverholder who hasn't reported the latest month is flagged before month-end, not after.

**Risk of inaction.** Manual mapping doesn't scale with the number of coverholders, and undocumented mapping is a governance liability. This is the loop you'd build anyway — built once, openly, on the platform you already run.

**How we sell it, honestly.** We don't out-feature a point bordereaux tool on its own turf. We win on breadth, openness and cost: one open loop that also reads prose contracts and health exhibits, every number traceable, fully yours to extend. To take on a completely different document family we changed **one config file** — no new code.

---

## Technical (≈5 minutes)

**The trust loop.** A file lands → fingerprinted against the counterparty **template registry** into one of four states: known-and-unchanged (straight through), known-but-changed (quarantine + AI-proposed remap, confirm once → new append-only template version), unknown (schema recognition proposes a full mapping into the shared dictionary, human confirms), unusable (quarantine with reason). All four are live in the demo inbox.

**Two-path extraction, in-platform.** A deterministic pass (the template's column/section anchors) and an AI pass (`ai_parse_document` → dictionary-constrained `ai_query`) run in the pipeline — not the app — and are reconciled field-by-field by a governed function (`fn_reconcile_status`). Agreement lands; disagreement quarantines. The AI mapping is measured on the **Eval** page against synthetic ground truth (both Claude and Llama scored 100%/50 on the latest run, decoys included), logged to MLflow.

**Capture with provenance.** Every assertion lands in an assertion graph (`graph_nodes`/`graph_edges`) carrying source document, extraction path, confidence, template + dictionary version, and the **located anchor** — the exact cell or page span. Typed silver projections are materialised from the graph, shaped to the `bricksurance-data-core` exchange / delegated-authority contracts. Lineage runs analytic → projection → assertion → anchor → original file.

**Governance is the product.** Templates, dictionary and decisions are append-only and versioned; supersession is a status flip, never a delete, so any number time-travels. Every action leaves an audit event. Business math lives in UC functions and views, not the app; SQL is parameter-bound.

**Agents at the edges, deterministic core.** MCP-first: every stage and read surface is a callable tool the app, a notebook and an agent all share. The extraction-review agent triages the queue but **only advises** — it writes findings, never lands data; the human decides. The ask-surface is Genie over the graph + projections (and, for MRC, dual retrieval with a Knowledge Assistant over the wording).

**gen1 → gen2.** Self-contained today in one schema, one bundle + one orchestrator run, serverless, reset rolls dates to today. Because the projections already match the shared-spine contracts, migrating onto gen2 is a mapping delta (`GEN2_MIGRATION_DELTA.md`), not a rewrite.

**The reveal.** Three tenants — bordereaux (premium + claims), MRC (prose), health renewal slips — run through the *same* engine. Onboarding the third added one reusable generic lander and one config file. That's the argument for the foundation, made live.

---

## Appendix — the business case (executive)

*Framing only — plug in the client's own baselines; the demo is illustrative, not a costed proposal.*

**The cost of the status quo, in the client's terms:**
- **Manual mapping effort.** Coverholder files are re-mapped by hand every month. Baseline to establish with the client: person-days/month spent mapping and re-keying bordereaux today. The gateway's *confirm-once* turns a layout change into a one-time human decision the template then remembers — the recurring effort trends to zero for known counterparties.
- **Undetected drift = wrong numbers.** A silently renamed column (our Ridgeway beat) today flows straight into the book. Baseline: how often does a mapping error reach reporting, and what did the worst one cost? The gateway *quarantines* drift before it lands and shows the money impact of a restatement (our resubmission beat: a single file moved premium by **+£23,430**).
- **"Where did this number come from?"** A regulator or auditor asks, and the honest answer today is "someone's spreadsheet." The gateway answers on screen — analytic → projection → assertion → the exact cell in the original file — which is the difference between a finding and a clean audit.
- **Late, fragile month-end.** Manual, post-hoc reconciliation is the long pole in the close. The completeness tile ("who hasn't reported") turns chasing into a glance.

**Risk of inaction:** the book keeps growing faster than the manual process scales; drift goes undetected until it's expensive; and the governance answer stays "trust the analyst." **What you win:** rows you can defend, a vocabulary that compounds across counterparties, and a book you can interrogate — on open, cheap, serverless infrastructure you already have.
