# Demo Q&A — Document Gateway

Tab 2 of the run material: every question the demo provokes but can't always show live, answered straight and sourced from the live schema. Persona-labelled **[P]** practitioner (delegated-authority / underwriting) · **[T]** platform/technical · **[E]** executive · **[C]** incumbent champion (the skeptic). Beat refs point at `DEMO_RUNSHEET.md`.

## Trust & the loop

**Q1 [P] — How does it decide a file is "known", "changed", "new" or "unusable"?** *(Beat 1, 3)*
Each file is fingerprinted against the counterparty **template registry** (`v_template_latest`): the header set is compared to the template's expected anchors. All present + both extraction paths agree → **known/unchanged** (lands). Some expected anchors missing or the paths disagree → **known/changed** (quarantine + proposed remap). No template for that counterparty → **unknown** (schema recognition). Not a readable table → **unusable**. All four are live in the pristine inbox (18/1/2/1).

**Q2 [C] — "LLM extraction hallucinates. I'm not trusting a model with my bordereaux."** *(Beat 3; Eval)*
We don't trust one path. Every file is extracted **two ways** — a deterministic pass on the template's column anchors, and a dictionary-constrained AI pass — and reconciled field-by-field by a governed function (`fn_reconcile_status`). Disagreement quarantines, it doesn't land. And the AI mapping is **measured**: the Eval page scores it against synthetic ground truth (we generate the documents, so the true mapping is known). Latest run: **both** `databricks-claude-sonnet-4-5` and `databricks-meta-llama-3-3-70b-instruct` scored **100% (50/50)** across five layouts including decoy columns. Bring your hard cases — the harness runs them.

**Q3 [P/T] — "Who approved this mapping, and when?"** *(Beat 4)*
Templates are **append-only**: accepting a remap writes a new version (v2) with the author and timestamp; the old version is retained. Template history shows the chain, and the Audit feed shows the `template_updated` / `reprocessed` / `signed_off` events. Nothing is edited in place.

**Q5 [C] — "Every coverholder's file is different. This will never keep up."** *(Beat 3–5)*
That's the design. The registry holds one template per counterparty; a drift is a one-time confirm (**confirm once** — then it's automatic); a brand-new counterparty is onboarded by confirming a proposed mapping (**under a minute**, live in beat 5). The variety is absorbed by config, not by code changes.

**Q7 [T] — When the AI proposes a schema, can it invent fields?** *(Beat 5)*
No. Extraction and schema recognition map **into the shared dictionary** (`v_dictionary_entity_latest` — entity types + allowed attributes + relations). It proposes a mapping from the counterparty's columns to canonical fields; it cannot create free-form fields. The graph is typed against the same dictionary.

## Provenance & governance

**Q4 [P] — "Where did this number come from?"** *(Beat 2)*
Lineage walks: analytic → projection row (`premium_bordereau_line`) → the graph assertion (`graph_nodes`, carrying `extraction_path`, `confidence`, `template_version`, `dictionary_version`) → the located **anchor** (the exact cell, e.g. `Bordereau!A6:J6`) → the original file in the volume. Nothing lands without that provenance.

**Q6 [T] — Where does the business logic live? Is it in the app?** 
No. The app is a thin control surface. Reconciliation is a governed UC function (`fn_reconcile_status`); the trust-loop acts (accept-remap, schema-confirm, reject) are governed server-side functions the app and the MCP tools both call; incurred-over-premium is a view (`v_loss_ratio`). No business math in the app container; SQL is parameter-bound throughout.

**Q8 [T] — Is this really governed, or a demo shell?** 
Every screen reads a real Unity Catalog object in `lr_dev_aws_us_catalog.document_gateway` (14 tables, 12 views). Every action leaves an append-only `audit_event` and lands in versioned, superseded-not-deleted rows. Deep links from the Learn panel open the live tables/functions.

**Q12 [P/E] — A resubmission arrived — did we lose the original figures?** *(Beat 8)*
No. The prior document is **superseded**, not deleted (`source_document.status`); its rows drop out of the `_latest` views but remain for time-travel. Version history shows both, and the impact banner shows the delta — for Harbourline's July restatement, **+£23,430** of premium (v1 £292,872.53 → v2 £316,302.33).

## The book & the money

**Q9 [P] — How is loss ratio computed, and can I trust the 88%?** *(Beat 6)*
`v_loss_ratio` = incurred claims (paid + outstanding, from the claims bordereaux) over gross written premium, per coverholder. Current book: Ridgeway **88.3%**, Kestrel **50.2%**, Harbourline **46.6%**. Ridgeway's premium is understated this instant because their latest month is still in quarantine — resolving it (beat 4) refreshes the ratio; that's the point of completeness.

**Q11 [C] — "What happens at real month-end volume, not a demo of a dozen files?"** *(Beat 6)*
The pipeline runs in the platform (jobs), not the app; it's the same code over N files. The completeness view ("who hasn't reported") is the month-end control that scales — it flags any coverholder whose latest reported month trails the book, exactly how Ridgeway shows **behind** now. Batch scan wall-clock is shown on the Inbox rescan.

**Q10 [P/E] — Can a non-technical user really just ask the book?** *(Beat 7)*
Yes — an embedded Genie space over the projections + graph answers in plain English and shows the SQL it ran. Answers are cached behind the yellow toggle so a live room never stalls.

## Value & positioning

**Q13 [E] — What's the business case / risk of inaction?** 
Delegated-authority data arrives as messy, per-coverholder files today; mapping them is manual, slow, and undocumented, so the book is late and hard to defend. This turns any counterparty document into decision-grade, fully-lineaged data with a confirm-once loop — you already have the files; this is the governed loop over them, on your own platform, open and cheap.

**Q15 [C] — "We already have a bordereaux tool. Why this?"** *(Beat 10)*
Two answers. One: it's open and it's yours — no black box, every number traceable. Two (shown, not asserted): to take on an entirely different document family — health renewal exhibits — we changed **one config file** (`tenants/health_slip/tenant.json`) and added **zero** family-specific pipeline code (one generic lander serves all tabular tenants). A point tool can't re-point itself like that.

**Q14 [P] — Does it read contract wording, or just tables?** *(Beat 9)*
Both. The MRC tenant reads **prose** contracts: `ai_parse_document` + section-heading anchors + a dictionary-constrained AI pass land the entities (137 assertions across the 5 contracts — every limit, clause, exclusion, insurer). The ask-surface is **dual retrieval**: Genie over the structured graph plus a Knowledge Assistant over the PDF wording. (KA endpoint is arming; the Genie half is live.)

**Q16 [T] — How does this relate to your shared data model?** 
gen1 self-contained today; the projections are shaped to the `bricksurance-data-core` exchange / delegated-authority contracts (e.g. `premium_bordereau_line`, `bordereau_claim_row`), so migrating onto the shared spine later is a mapping delta, not a rewrite (`docs/GEN2_MIGRATION_DELTA.md`).

**Q17 [T] — Can an agent or another system drive it, or only this UI?** 
Every stage and read surface is an MCP tool (`ingest_file`, `get_document_status`, `propose_schema`, `confirm_mapping`, `query_graph`, `get_projection`, `review_document`) — the app, a notebook and an agent all call the same functions. An extraction-review agent triages the queue but **only advises** (writes findings, never lands data); the human decides.

**Q18 [E] — Deployable in our environment?** 
Yes — one bundle + one orchestrator run against your catalog. Tier 2 (serverless-only). Reset restores a pristine state and rolls dates to today.

**Q19 [C] — The MRC contracts name real brokers and syndicates.** 
Deliberate: these are publicly-known market participants used for realism; the insureds are invented and nothing here is sourced from any client engagement (DECISIONS D9). The bordereaux world is fully synthetic.
