# Data dictionary — Document Gateway

Schema `lr_dev_aws_us_catalog.document_gateway` (gen1, self-contained): **14 tables + 12 views**. Column comments are carried on the live objects (`INFORMATION_SCHEMA`). Projections are shaped to the `bricksurance-data-core` contracts noted below so gen2 migration is a mapping delta (`GEN2_MIGRATION_DELTA.md`).

## The vocabulary

### `dictionary_entity`  ·  `dictionary_relationship`  (append-only, versioned)
The shared vocabulary. Extraction is constrained **by** it; the graph is typed **against** it; schema recognition maps **into** it.
- `dictionary_entity` — grain: one row per (dictionary_version, tenant, entity_type). Cols: `dictionary_version`, `tenant` (`_base` or the extending tenant), `entity_type`, `description`, `attributes ARRAY<STRING>`, `status`, `created_by`, `created_at`. Seeded v1: 13 base entities + 4 bordereaux extensions.
- `dictionary_relationship` — grain: one row per allowed relation. Cols: `dictionary_version`, `tenant`, `relationship_name`, `source_entity`, `target_entity`, `description`, `status`, `created_by`, `created_at`.
- Views: `v_dictionary_entity_latest`, `v_dictionary_relationship_latest` (latest version per tenant+name).

## The assertion graph (capture layer)

### `graph_nodes`  ·  `graph_edges`  (assertion-level provenance)
Every node/edge is an assertion that carries where it came from. Nothing lands without provenance.
- `graph_nodes` — grain: one entity assertion. Cols: `node_id`, `label` (dictionary entity type), `properties` (JSON attributes), **`source_document_id`**, **`extraction_path`** (`det｜ai｜reconciled`), **`confidence`**, `template_version`, `dictionary_version`, **`anchor`** (located anchor JSON — cell ref for tabular, page/span for prose), `tenant`, `created_at`.
- `graph_edges` — grain: one relationship assertion. Cols: `edge_id`, `source_id`, `target_id`, `relationship_type`, + the same provenance columns.
- Views: `v_graph_nodes_latest`, `v_graph_edges_latest` (assertions whose source document is `active`). MRC holds 137 assertions across 12 labels (Exclusion 27, Clause 23, Limit 16, Insurer 13, Insured/Policy/Broker 10 each, …).

## The trust loop

### `template`  (counterparty registry, append-only versions)
Grain: one row per (counterparty, doc_family, template_version). Cols: `template_id`, `tenant`, `counterparty`, `doc_family` (`premium_bordereau｜claims_bordereau｜renewal_slip｜mrc`), `template_version` (v1, v2…; accept-remap bumps it), `expected_anchors` (JSON fingerprint anchors), `field_map` (JSON logical→anchor, pipe-alternatives for learned labels), `field_count`, `status`, `created_by`, `created_at`. View: `v_template_latest`.

### `source_document`  (intake provenance + trust state)
Grain: one row per inbound document. Cols: `doc_id`, `tenant`, `counterparty`, `doc_family`, `file_name`, `stored_path`, `status` (`active｜differs｜quarantined｜superseded｜rejected｜recognized_pending`), `inbound_state` (`known_unchanged｜known_changed｜unknown｜unusable`), `template_version`, `dictionary_version`, `reconciliation_detail` (JSON per-field status + proposed remap), `reporting_period`, `ingested_at`, `signed_off_by`, `signed_off_at`. View: `v_source_document_current` (excludes superseded/rejected). Supersession is a status flip; `_latest` views resolve through it.

### `audit_event`  (append-only)
Grain: one event. Cols: `event_id`, `event_type` (ingested / quarantined / superseded / template_updated / schema_recognized / reprocessed / signed_off / rejected / review_run / reset), `entity_type`, `entity_id`, `detail`, `actor`, `created_at`. Pure inserts.

### `decision`  (append-only HITL acts)
Grain: one human act. Cols: `decision_id`, `decision_type` (schema_confirm / remap_accept / remap_reject / signoff / quarantine_resolve), `tenant`, `source_document_id`, `template_version`, `detail` (JSON), `reason`, `actor`, `status`, `parent_decision_id`, `created_at`.

### `reviewer_finding`  (advise-only agent output)
Grain: one finding. Cols: `finding_id`, `source_document_id`, `severity` (high/medium/low), `field`, `message`, `extraction_path`, `confidence`, `status` (open/resolved), `created_by`, `created_at`. The extraction-review agent writes these and lands nothing else.

## Typed projections (the working surface)

### `premium_bordereau_line`  → gen2 `bricksurance_exchange.premium_bordereau_line`
Grain: one premium line per policy per reporting month per bordereau. Cols: `bordereau_line_id` (= the PremiumBordereauLine node_id — lineage), `reporting_month DATE`, `coverholder_name`, `policy_number`, `insured_name`, `line_of_business_code`, `inception_date`, `expiry_date`, `currency_code`, `gross_premium DECIMAL(18,2)`, `commission_amount`, `risk_country_code`, `risk_postcode`, `source_system_code` (`COVERHOLDER_BDX`), `source_document_id`. View: `v_premium_bordereau_line_latest` (active docs). Live: 96 rows / £1,983,594.76.

### `claim_bordereau_line`  → gen2 `bricksurance_delegated_authority.bordereau_claim_row`
Grain: one claim line per reporting month per bordereau. Cols: `claim_line_id`, `reporting_month DATE`, `coverholder_name`, `claim_reference`, `policy_number`, `loss_date`, `cause_of_loss_code`, `paid_amount`, `outstanding_amount`, `incurred_amount` (= paid + outstanding, governed derivation), `currency_code`, `source_system_code`, `source_document_id`. View: `v_claim_bordereau_line_latest`. Live: 45 rows / £1,141,240 incurred.

### `mrc_entities`  (prose tenant projection)
Grain: one row per Market Reform Contract. Cols: `mrc_id` (= the Policy node_id), `umr`, `policy_number`, `class_of_business`, `inception_date`, `expiry_date`, `insured_name`, `broker_name`, `premium_text`, `headline_limit`, `deductible_text`, `n_clauses`, `n_exclusions`, `n_insurers`, `source_document_id`. View: `v_mrc_entities_latest` (5 rows). Full entity detail lives in the shared graph.

### `renewal_inputs`  (config-port tenant projection)
Grain: one row per employer group per renewal exhibit. Cols: `renewal_input_id` (= the RenewalExhibit node_id), `group_name`, `member_months`, `total_incurred_claims`, `annual_trend`, `months_of_trend`, `demographic_adjustment`, `target_loss_ratio`, `manual_rating_pool_increase`, `carrier_name`, `reporting_period`, `source_document_id`. View: `v_renewal_inputs_latest` (3 rows). **Every column is declared in `tenants/health_slip/tenant.json`** and written by the generic config-driven lander — no health-specific code.

## Derived views

- `v_completeness` — the "who hasn't reported" tile. Grain: one row per coverholder. Cols: `coverholder_name`, `months_received`, `last_month`, `latest_expected`, `behind` (true if `last_month < latest_expected`). Live: Ridgeway `behind` (latest month quarantined).
- `v_loss_ratio` — grain: one row per coverholder. Cols: `coverholder_name`, `gwp`, `incurred`, `loss_ratio` (incurred/gwp). Live: Ridgeway 0.883, Kestrel 0.502, Harbourline 0.466.

## Eval

### `eval_result`
Grain: one row per (run, model, scope[, field]). Cols: `run_id`, `model`, `scope` (`overall｜field`), `field`, `correct`, `total`, `accuracy`, `mlflow_run_id`, `created_at`. Latest run: both models overall 50/50 (1.0). Also logged to the MLflow experiment `/Users/…/document_gateway_eval`.
