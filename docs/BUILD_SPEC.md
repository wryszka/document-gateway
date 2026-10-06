# Build Spec — Document Gateway (hero tenant: Bordereaux Ingestion)

Authority document for a new demo asset. Follows the Bricksurance demo standard (the standing
authority — `bricksurance-playbook/demo_build_and_review_standard.md`; read it first; it governs
anything this spec doesn't). The product is a **build track** with a thin app on top, landing in
the actuarial workbench family under the menu entry **"Bordereaux Ingestion"**. The repo/asset
name is **`document-gateway`** — bordereaux is the first tenant of a general pattern, not the
pattern itself.

## 0. Source material — two repos to mine, not merge blindly

- `wryszka/hb-renewal-workbench` — lift the **trust loop**: carrier/counterparty template
  registry, fingerprint check, two-path extraction with field-level reconciliation, quarantine →
  proposed-remap → accept/reject with template versioning ("confirm once"), supersession +
  latest views, append-only decision/audit pattern, version diff with money impact, Learn-panel
  pattern, runsheet format (GO/DO/SAY/IF), persona review pack format.
- `wryszka/insurance-mrc-poc` — lift the **capture layer and vocabulary binding**:
  `graph_nodes`/`graph_edges` in Delta, dictionary-constrained extraction
  (`acord_dictionary.json` pattern), platform-native `ai_parse_document()`/`ai_query()`
  pipeline, Genie-over-graph, `config.json` single-edit + `deploy_all.py` one-command deploy,
  demo-notebook structure (00 index / walkthrough / change management / security audit).
- Known corrections while lifting: HB's client-side extraction moves in-platform; HB's escaped-
  not-parameterised SQL (`sq()`) becomes parameter binding in the new base; HB's credibility-
  lever preview/save divergence is a known bug class — in this app any preview must be
  recomputed server-side at save; MRC POC's supervisor must NOT use the deprecated Supervisor
  API pattern (EOL 2026-09-30) — if the lifted code does, build the agent as a custom agent
  (Responses API on Apps) instead; MRC POC extraction gains the two-path + eval treatment it
  currently lacks.

## 1. Purpose, canonical question, message

**Canonical question (the demo answers this sentence):** *"A counterparty just sent us a file —
how do we trust it, use it, and never map it twice?"*

**Three-beat message:** (1) You already have everything this needs — the files are arriving
today. (2) One governed loop turns any counterparty document into decision-grade data — open
code, your workspace. (3) The results: rows you can defend, a vocabulary that compounds, and a
book you can interrogate.

**Show-don't-say moments:** the second drop of a once-broken layout sailing through (the
template learned); the same pipeline blocks ingesting a *different document family* with only a
config change; field-level lineage from an analytic number back to a cell/clause in the source
file.

## 2. Placement, naming, deploy gating

- Repo: `document-gateway`. Menu entry in the actuarial workbench hub: **Bordereaux Ingestion**
  (subtitle: "bordereaux, MRCs, carrier exhibits — one gateway").
- App boundary per method: this is a **new value chain** (counterparty document → governed
  data) → new app. Tenants are configs inside it, never sibling apps.
- Bricksurance small-project conventions: DAB, serverless-only, single catalog variable,
  scale-to-zero, no client names anywhere, `config.json` + one-command orchestrated deploy
  (lift from MRC POC — this repo must meet the method's "bundle deploy + one orchestrator run"
  bar from day one; HB's five-step deploy is not the precedent).
- Tenancy gating: `tenants` list in config; bordereaux ON, health-slip ON (cheap port), MRC
  behind a flag until Phase 2 completes.

## 3. Architecture — the base (tenant-agnostic)

### 3a. Schema acquisition — four inbound states
1. **Known & unchanged** → fingerprint matches template → straight through.
2. **Known but changed** → field-level delta + AI-proposed remap → HITL accept (template
   version++, append-only) or reject with reason. (Lift HB WP2 wholesale.)
3. **Unknown** → **schema recognition** (new build): AI proposes a full template — document
   family guess, field map as *mappings into the shared dictionary* (never free-form field
   invention), per-field confidence and located anchor. HITL confirmation screen: confirm /
   correct / mark-not-present per field → template saved → counterparty learned → file
   re-processes. This is the promoted new-carrier onboarding.
4. **Unusable** → quarantine with reason (unreadable, wrong doctype, failed reconciliation).

All four states audited; all templates and dictionary entries append-only versioned.

### 3b. Extraction — two paths, in platform
Deterministic path (per-family: cell anchors for tabular, heading/section anchors for prose) +
AI path (`ai_parse_document` → `ai_query`, dictionary-constrained). Field-level reconciliation:
AGREE → land; DIFFER → quarantine with both values shown. Extraction runs in the pipeline
(jobs/DLT), not in the app container.

### 3c. Capture layer — assertion graph in Delta
`graph_nodes` + `graph_edges` (lift MRC POC) upgraded to **assertion-level provenance**: every
node/edge row carries source_document_id, extraction_path (det/ai/reconciled), confidence,
template_version, dictionary_version, located anchor (cell ref / page+span). Nothing lands
without provenance. Supersession at document level as in HB; graph rows resolve through
latest-document views.

### 3d. Dictionary — the shared vocabulary
One `dictionary` (seeded from the ACORD-based `acord_dictionary.json`, extended per tenant)
defining entity types, attributes, and allowed relations. Schema recognition maps INTO it;
extraction is constrained BY it; the graph is typed AGAINST it; Genie metric/semantic
definitions derive FROM it. Versioned, append-only, with a change-management surface (lift the
MRC POC notebook-02 story into the app's Learn/admin surface). This is the Bricksurance
ontology binding — name it as such in docs.

### 3e. Typed projections — the working surface
Per document family, conformant silver views/tables materialised from the graph (bordereau
premium rows, claims rows; slip submission entities; renewal exhibit inputs). Methods, Genie,
dashboards, and downstream demos consume projections, never raw graph. Projections are defined
in the tenant config.

### 3f. Method & decisions — thin, tenant-optional
The gateway's own decision surface is the HITL acts themselves (schema confirms, quarantine
resolutions, sign-offs) — all append-only with audit, per HB's decision-layer pattern. Tenant
configs may attach downstream methods (bordereaux: aggregation checks + expected-vs-received
completeness; the full negotiate/decide loop stays in tenant-specific workbenches like HB —
do NOT rebuild HB inside the gateway).

### 3g. Agents & MCP (method §9)
MCP-first: every stage and read surface is a callable tool (ingest_file, get_document_status,
propose_schema, confirm_mapping, query_graph, get_projection). The app, a notebook, and an
orchestrating agent are all clients of the same tools. Agents: an extraction-review agent
(flags low-confidence/disagreeing assertions for the HITL queue — advises, never lands data)
and Ask-the-gateway (Genie over graph + projections). Deterministic core, graduated autonomy,
server-side policy.

### 3h. Eval harness (non-optional)
MLflow evaluation for the AI extraction path per tenant: synthetic ground truth (we generate
the documents, so truth is free), per-field / per-entity-type precision-recall, model-swap
comparison. Results surfaced in the Learn/how-it-works layer. This is a first-class demo beat,
not plumbing.

## 4. Tenants

### T1 — Bordereaux (hero, build fully)
- Synthetic delegated-authority world: 3 coverholders (invented names), monthly premium +
  claims bordereaux, one coverholder's layout drifting mid-year, one brand-new coverholder
  (exercises schema recognition end-to-end), one resubmission (version diff + money impact on
  aggregates).
- Projections: premium rows, claims rows, per-coverholder completeness (expected vs received
  periods — the "who hasn't reported" tile).
- Demo payoffs: confirm-once; second-broken-drop-sails-through; new-coverholder onboarding in
  under a minute; book-level Genie ("which coverholder's loss ratio moved most this quarter").

### T2 — Health renewal slip (config-port, prove the pattern)
- Port the HB exhibit family as a *tenant config only*: template, field maps, projection to
  the renewal-inputs shape. No renewal workbench UI here — the payoff line is "the entire HB
  ingestion front-end is now this one config file." Target: the tenant config diff is small
  enough to show on one screen.

### T3 — MRC (Phase 2, flag-gated)
- The MRC POC's five synthetic MRCs through the gateway: prose deterministic path = section
  anchors on standard MRC headings; graph capture is the natural home; add the Knowledge
  Assistant + Genie dual-retrieval as the tenant's ask-surface. Ship only when T1/T2 are done;
  do not let it delay the hero.

## 5. Red-team → visible on-screen answers (build these, don't rehearse them)
| Kill-shot | On-screen artifact |
|---|---|
| "LLM extraction hallucinates" | two-path reconciliation table + the eval-harness scores page |
| "Every coverholder file is different" | template registry + the new-coverholder recognition flow, timed |
| "Who approved this mapping?" | template history with author/when + audit events |
| "Where did this number come from?" | assertion lineage: analytic → projection → graph row → anchor in file → download original |
| "What happens at month-end volume?" | completeness tile + batch scan of an inbox with N files, wall-clock on screen |
| "We already have a bordereaux tool" | (show, don't say) the config-not-code tenant diff + open repo |

## 6. Demo walkthrough (headline + reactive act)
Headline (canonical question end-to-end): inbox with mixed files → known one lands (lineage to
cell) → drifted one quarantines → remap accepted → learned → new coverholder recognised and
confirmed → projections + completeness → Genie over the book. Reactive second act (method §7):
a resubmitted bordereau arrives → system detects supersession → diff + aggregate impact →
review agent flags → human accepts → book updates. Close with T2's one-screen config as the
"same gateway, next document family" reveal. Full runsheet in HB's GO/DO/SAY/IF format with
minute budgets, cut order, and ordering-constraint guards from day one.

## 7. Documentation deliverables (method list, same PR as features)
Talk track (exec + technical) · presenter runbook (click-path, fallbacks, known-good inputs) ·
data dictionary for every table/view incl. graph + projections · README (surfaces, structure,
3-step deploy) · deployment notes (flags, tenants, orchestrator) · Learn/how-it-works copy
written once · PERSONA_REVIEW_PACK on the HB format as the final gate · DECISIONS.md from
day one · anticipated-challenges table (seeded from §5) · forward hooks: Delta-Sharing "the
counterparty joins the future" beat, DataCore policy-event-spine feed, cedant statements as
T4 — named, not built.

## 8. Definition of done (method DoD applies; specifics)
- Canonical question answered live end-to-end including the reactive act, on a fresh workspace
  from `config.json` + one orchestrator run.
- All four inbound states demonstrable with seeded twins for every live drop.
- T2 config diff shown on one screen; T1 eval scores on screen; every §5 artifact reachable in
  ≤2 clicks.
- Zero real names (scan against a fresh clone); zero math in the app container; parameterised
  SQL throughout; persona pack complete with a weaknesses register.

## 9. Out of scope / no-build list
Rebuilding any renewal-negotiation UI (lives in HB) · carrier/counterparty portals · email
integration · production hardening beyond the stated items · T4 cedant statements · real ACORD
licensing questions (dictionary is "ACORD-inspired, illustrative") · any write autonomy for
agents.

---

## Build-time addendum — decisions taken at kickoff (see DECISIONS.md for detail)

- **gen1, self-contained, on DEV.** Every object lives in `${catalog}.document_gateway` on the
  dev workspace (`lr_dev_aws_us_catalog`, profile `DEV`). All synthetic data self-contained;
  one-command DAB deploy; portable to a fresh workspace (fresh-workspace DoD). The shared
  `bricksurance-data-core` spine is **not** deployed or touched — serverless is left alone.
- **Conform-to-contract for gen2.** Typed projections are shaped to the data-core exchange
  contract (`bricksurance_exchange.premium_bordereau_line`, etc.) and the dictionary aligns to
  the ACORD/reference contract, so migrating this demo onto the gen2 shared spine later is a
  delta, not a rewrite. That delta is documented in `docs/GEN2_MIGRATION_DELTA.md` — built, not
  deployed.
- **App stack:** thin FastAPI backend + one self-contained SPA (`index.html`, vanilla JS,
  render-fn map, strict CSP) — the HB stack and the standard's §3 house style.
