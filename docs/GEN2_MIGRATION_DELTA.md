# gen2 migration delta — Document Gateway onto the shared spine

**Status:** documented, not deployed. Document Gateway is a **gen1** demo — self-contained in
`${catalog}.document_gateway` on the dev workspace. gen2 is the shared `bricksurance-data-core`
data + semantic layer (currently in the serverless catalog). This file is the **delta**: exactly
what changes to migrate this demo onto gen2, so the migration is a mapping exercise, not a
rewrite. Nothing here is built against serverless now.

Why it's cheap: the gateway was built **conform-to-contract** (DECISIONS D4). Its projections
already have the canonical exchange shape and its dictionary already aligns to the ACORD/reference
vocabulary. Migration re-points writers and readers; it does not re-model.

## What the gateway owns (gen1, stays)

The *loop* is the gateway's product and remains its own — these stay in `document_gateway`:
`graph_nodes`, `graph_edges` (assertion capture), the counterparty template registry, the
`dictionary` (gateway working copy), the HITL decision/audit tables, and the extraction pipeline.

## What migrates to the spine (gen2)

| gen1 (document_gateway) | gen2 target (bricksurance-data-core) | Migration action |
|---|---|---|
| Projection: premium rows (exchange-shaped) | `bricksurance_exchange.premium_bordereau_line` | Repoint the projection writer at the spine table; drop the local copy. Columns already match the v0.12.0 contract (see DECISIONS D4). |
| Projection: claims/cession rows | `bricksurance_exchange.cession_bordereau_line` (or the claims exchange table) | Same: repoint writer; confirm column crosswalk against the then-current spec version. |
| `dictionary` (entity types, attributes, allowed relations) | `bricksurance_reference.data_dictionary` + code sets | Map gateway dictionary entries to spine reference rows; adopt spine `line_of_business_code` and other code sets as the authority; keep gateway-only extensions as a documented superset. |
| Coverholder / insured parties captured in the graph | `bricksurance_party.party` + `party_role` | Resolve captured parties to canonical party ids (party–role pattern); store the resolved id as an assertion attribute. |
| Policy references reported on lines | `bricksurance_policy.policy` | Match `policy_number` to canonical policy downstream (already noted as "matched to the core model downstream" in the exchange contract comment). |

## Contract anchors to re-verify at migration time

- The spine is versioned (`bxc_model_version` tag). Re-generate the crosswalk against the
  **then-current** data-core model version — the v0.12.0 shape captured at kickoff may have moved.
- Governance tags: the spine applies `bxc_classification` per column (pii/confidential/internal).
  The gateway's exchange-shaped projections should carry the same classifications so the migrated
  tables inherit the spine's tag policy.
- `source_system_code = COVERHOLDER_BDX` is the spine's provenance value for coverholder
  bordereaux — the gateway already stamps it, so lineage back to the gateway survives migration.

## Deploy delta

- `databricks.yml` already carries a `prod` (serverless) target stub. gen2 migration flips reads
  and writes of the two projections from `${catalog}.document_gateway.*` to
  `bricksurance_exchange.*` behind a config switch (`config.json` → a `spine.mode: gen1|gen2`
  flag, to be added at migration), leaving the loop untouched.
- Genie: the gen1 space is created over `document_gateway` graph + projections. gen2 adds the
  spine's domain Genie spaces (P&C Book, Reinsurance & Exchange) as additional retrieval targets;
  the gateway's space narrows to the loop's own tables.
