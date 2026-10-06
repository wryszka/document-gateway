# Document Gateway

**Canonical question:** *"A counterparty just sent us a file — how do we trust it, use it, and never map it twice?"*

One governed loop that turns any counterparty document — a delegated-authority **bordereau**, a
health **renewal slip**, a **Market Reform Contract** — into decision-grade, fully-lineaged data.
Bordereaux is the hero tenant; the others are **config, not code**. Part of the Bricksurance
actuarial-workbench family, under the menu entry **Bordereaux Ingestion**.

> Bricksurance SE is a fictional insurance group; all coverholders, carriers and figures are
> synthetic. The method is illustrative. Every screen reads a real governed Unity Catalog object.

## What it does — the trust loop

1. **Trust the data.** A file arrives → fingerprint against the counterparty template registry →
   one of four inbound states:
   - **Known & unchanged** → straight through.
   - **Known but changed** → field-level delta + AI-proposed remap → HITL accept (template
     version++) or reject. *Confirm once* — the next drop of that layout sails through.
   - **Unknown** → schema recognition proposes a full template as mappings **into** the shared
     dictionary → HITL confirm → counterparty learned → file re-processes.
   - **Unusable** → quarantine with reason.
2. **Extract, two ways.** A deterministic path (cell/section anchors) and an AI path
   (`ai_parse_document` → dictionary-constrained `ai_query`) run in the pipeline and are
   **reconciled field by field** — agree → land, differ → quarantine with both values shown.
3. **Capture with provenance.** Every assertion lands in an assertion-level graph
   (`graph_nodes`/`graph_edges`) carrying source document, extraction path, confidence, template
   & dictionary version, and the located anchor (cell ref / page+span). Nothing lands without it.
4. **Project & use.** Typed silver projections (premium rows, claims rows, completeness) are
   materialised from the graph, shaped to the canonical exchange contract. Genie answers over the
   book; a dashboard shows the completeness tile. Field-level lineage runs analytic → projection
   → graph row → anchor in the file → download the original.

## Surfaces (app)

The app opens on a **landing with three document flows** — **1. Market Reform Contract (MRC)**, **2. Bordereaux**, **3. Health renewal slip** — and scopes the nav to whichever you enter (a "⌂ All flows" link returns), so each audience sees only its own screens.

**MRC flow** (the recognise → register → straight-through → HITL loop):

| Surface | What it shows |
|---|---|
| **Inbox** | MRC documents by state: *awaiting recognition* / *recognised → ingested* / *needs review (HITL)* |
| **Schema Recognition** | The expected ACORD data points as a checklist — identified all/some, value + confidence + section; **Confirm & register** records the schema |
| **Schema Repository** | The recorded "Lloyd's MRC (ACORD)" schema — its data points, version, who/when. New matching contracts flow straight through |
| **ACORD Semantics** | Every expected data point, its ACORD entity.attribute binding, and whether it's recognised (coverage %) |
| **Contracts & Ask** | The ingested MRCs + dual-retrieval Ask (Genie over the graph + a Knowledge Assistant over the PDFs) |

**Bordereaux flow:**

| Surface | What it shows |
|---|---|
| **Inbox / Ingestion** | Drop or scan files; the four inbound states; per-file status |
| **Quarantine & Remap** | Expected-vs-found, AI-proposed remap, accept (learn) / reject |
| **Schema Recognition** | New-counterparty onboarding: proposed template, per-field confidence + anchor, confirm/correct/mark-not-present |
| **Template Registry** | Versioned templates per counterparty, author + when, history |
| **The Book** | Typed projections; per-coverholder completeness ("who hasn't reported") |
| **Lineage** | Any number → projection → graph assertion → source anchor → original file |
| **Eval** | MLflow per-field precision/recall for the AI path; model-swap comparison |
| **MRC** | Market Reform Contracts (prose tenant): the extracted contracts + dual-retrieval Ask (Genie over the graph + a Knowledge Assistant over the PDFs) |
| **Config-port** | The health renewal-slip family, onboarded as *one config file* — the `tenant.json` shown verbatim with the "no new pipeline code" proof |
| **Ask** | Genie over graph + projections |
| **Learn** | How-it-works: activity → mechanism → deep links to the live UC assets |

## Structure

```
config.json              Single-edit config: catalog, schema, models, tenants (bordereaux/health_slip/mrc)
databricks.yml           DAB — one ${var.catalog}, dev target (default), prod stub
tools/orchestrate.py     One-command end-to-end build (reads config.json)
notebooks/               Build track, walked in dependency order (00 index / walkthrough / change-mgmt / security-audit)
resources/               DAB resources — ingestion job, reset job, pipeline
data/                    Synthetic document generator (deterministic, seeded)
app/                     Thin FastAPI backend (app/server) + self-contained SPA (app/frontend)
mcp/                     MCP tool surface (ingest_file, get_document_status, propose_schema, confirm_mapping, query_graph, get_projection)
agents/                  Extraction-review agent (advise-only) + Ask-the-gateway
eval/                    MLflow evaluation harness (synthetic ground truth)
tenants/<t>/tenant.json  Per-tenant dictionary extensions, families, template seeds, projections, anchors
docs/                    BUILD_SPEC (authority), RUNSHEET, QA, data dictionary, talk track, runbook, GEN2_MIGRATION_DELTA, REVIEW/
```

## Deploy — three steps

```bash
# 1. Point config.json + the DAB dev target at your workspace catalog (defaults: lr_dev_aws_us_catalog / DEV).
# 2. Deploy the bundle (schema, jobs, pipeline, app shell).
databricks bundle deploy -t dev
# 3. Run the orchestrator — synthetic docs, dictionary, extraction, projections, agents, Genie, app.
python tools/orchestrate.py
```

Reset (in-app button + `python tools/orchestrate.py --reset`) returns to pristine state and rolls
the data forward to today, deterministic conditional on the as-of date.

## Compatibility tier

**Tier 2 — Serverless-only.** Core (UC tables/functions, `ai_parse_document`/`ai_query`
extraction, Genie, DLT/jobs) runs on serverless primitives. Agent serving endpoints
(extraction-review, Ask-the-gateway) are serverless model-serving, defined-but-armable. No Free
Edition (Tier 1) because the load-bearing capability needs the AI document functions and Genie;
labelled per the standard §3.5. See `docs/DEPLOYMENT_NOTES.md` for flags and per-module tiers.

## Standards & gen2

Built and reviewed against the Bricksurance demo standard (`STANDARDS.md`). This is a **gen1,
self-contained** demo; it conforms to the `bricksurance-data-core` exchange/reference contract so
migration onto the gen2 shared spine is a delta — see `docs/GEN2_MIGRATION_DELTA.md`.
