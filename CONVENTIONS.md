# Conventions — <App Name>

> Skeleton. Copy into the repo (root or `.claude/`). The hard build rules a coding agent must follow. Mirror, don't invent. See BUILD_AND_REVIEW.md §1 and DESIGN_LANGUAGE.md.

## Schema & tables
- **One schema per demo** (e.g. `hb_renewal`, `ifrs17_workbench`). No schema proliferation — medallion is by **table prefix**, not by schema.
- **Numbered / lettered prefixes:** `1_` raw, `2_` silver, … (or `brz_/slv_/gld_`). Governed `gov_`, reference `ref_`, consumption/metric views `mv_`, cache `cache_`.
- **Portable catalog:** a single `${var.catalog}` bundle variable — no hardcoded catalog names anywhere.
- Identifiers: lowercase, underscores only.

## UC functions (the compute path)
- **All business math lives in governed UC functions** (`fn_*`), never in the app. The app renders and recomputes by calling the function.
- Rich `COMMENT` on every function (agents route off them). Deterministic — dependencies resolved at design time.
- See the EXECUTE-grant gotcha in DECISIONS.md before recreating one.

## Real services only (nothing faked) — the platform stack
- **"Real" = credible under drill-down.** The demoed capability runs for real, end to end, and survives a practitioner's "but how does it work?" — shown via the actual asset (model/dataset/pipeline/governance) or its build track. **Accepted cut corners** are peripheral plumbing only (e.g. synthetic ingestion instead of Lakeflow Connect), **labelled**, with a ready "how you'd really do it" answer — never the load-bearing capability.
- **MCP server(s):** every stage/read surface is exposed as MCP tools so the demo is **externally agent-manageable**, not only a UI. (Evolving area — forward hook.)
- **Genie:** embedded in-app **and** created **programmatically via the Databricks API** (a shared builder utility lives in the standards repo under `tools/`) — never hand-built in the UI. Grant the app SP `CAN_RUN`; keep a space ≤ ~30 tables. (This is the recurring pitfall — see gotchas.)
- **Agents:** managed on **Agent Bricks / Mosaic AI Agent Framework**, served through the **Unity Catalog AI Gateway**. MCP-first tool surface. No bespoke orchestration glue.
- **Dashboards:** embedded Lakeview (not linked, not mocked). **Models:** Feature Store + Model Serving.
- **AI response cache + the yellow button:** every LLM/agent call is cached; a visible live/cached toggle switches modes; the cache **pre-warms as the demo runs** so no beat stalls on a model.
- Deterministic engines decide; **AI narrates**. Never hardcode a number that should be computed. Label anything illustrative.

## Compute
- **Serverless everywhere; scale-to-zero.** DLT `serverless: true`; jobs pin the current serverless environment version; no always-on clusters. Expensive tiers defined-but-dormant, armed on demand.

## Reset / reseed
- **One idempotent path** (in-app button → job, and/or `deploy.sh`): regenerate synthetic data (seeded) → land files → medallion `full_refresh` → features/models → governance reseed → cache clear. Result: pristine, heroes **deterministic conditional on the as-of date** (same seed + same as-of date ⇒ identical output).
- **Roll the calendar forward:** reset must refresh dates so the data reads **as of today** (current "latest month," recent event dates) — never a book that is visibly months stale. Determinism holds (seeded) while dates move with the demo (e.g. rolling offsets from `current_date()`).

## Reinstall (client environments)
- **Reinstallable via a bundle (DAB) with minimal config** — point `${var.catalog}` at the client's catalog, `bundle deploy` + one orchestrator run, done. No hardcoded workspace URLs, job IDs, or catalog names.

## App layer
- Thin FastAPI + one self-contained HTML (no external scripts; strict CSP). Vanilla JS, render-fn map. Statement Execution API (INLINE), thread-pool concurrency.
- Every panel reads a real UC function / view / query / Genie / endpoint. Behind-the-scenes is a click (deep links, env-driven hosts).
- Auth: `Config().authenticate()` in-app (app SP). Escape user input (`sq()` quote-doubling) or bind parameters.

## Naming & safety
- **No real customer names or recognizable customer estates** anywhere — code, comments, docs, git history. Synthetic entities only.
- Public repo under the team account; shared workspace location (`/Workspace/Shared/...`); portable config; nothing tied to one person.
- Every build ships a **Learn section** + the doc trio (RUNSHEET, QA, DECISIONS) + data dictionary + README, in the same PR as the feature.
- **All documentation is markdown in the demo repo** (the single source), shipped in the same PR as the feature, covering the demo track as **beats / user stories** (one story per beat — demos can be complex). Reader-facing manuals may be surfaced in-app or rendered for readers, but the repo markdown is always the source — never the other way round. Expected **Q&A** listed and answered (per persona).

## Review before the room
- Reviewed by the **8-agent panel, fan-out (all personas in parallel)** (BUILD_AND_REVIEW.md §7): practitioner · decision-maker · Databricks SA · senior developer · security · current-Databricks expert (sweeps live docs) · **incumbent champion** (veteran skeptic who hunts every gap to keep the old toolset) · **UI/UX expert** (domain-fluent — logical layout, familiar-but-better, nothing out of place). Results collated into one report.
- Any question that **can't be answered live in the demo** is documented + answered in the run's **Q&A tab** (`DEMO_QA.md`, tab 2), cross-referenced from the beat.
- Findings recorded in `docs/REVIEW/REVIEW_REPORT.md` (standardized template) and **fixes applied**; smoke also flags dead / unnecessary / non-best-practice code for removal.
- Not "done" until the panel is clean or every open item is labelled + roadmapped.
