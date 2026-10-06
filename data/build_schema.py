"""Phase 1 — Base data plane. Idempotent, tenant-agnostic.

Creates the Document Gateway schema, landing volume, the assertion graph, the
trust-loop tables (template registry, source_document, audit, decision, findings),
the governed UC functions (the math path), the latest/supersession views, and seeds
the shared dictionary from data/acord_dictionary.json + enabled tenants' extensions.

Run:  uv run --with databricks-sdk python data/build_schema.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import load_config, load_tenant, enabled_tenants, sql, run_batch, lit  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build(cfg):
    C, S = cfg["catalog"], cfg["schema"]
    F = cfg["full_schema"]
    V = cfg["volume"]

    print(f"== Phase 1: base data plane -> {F}")

    # --- schema + volume -----------------------------------------------------
    run_batch([
        f"CREATE SCHEMA IF NOT EXISTS {F} "
        f"COMMENT 'Document Gateway (gen1, self-contained): the governed loop that turns any "
        f"counterparty document into decision-grade data. Assertion graph + trust-loop tables + "
        f"typed projections. Conforms to the bricksurance-data-core exchange/reference contract "
        f"for gen2 migration.'",
        f"CREATE VOLUME IF NOT EXISTS {F}.{V} "
        f"COMMENT 'Landing zone for inbound counterparty documents; quarantine/ and processed/ subfolders.'",
    ], cfg, label="schema")

    # --- dictionary (versioned, append-only) --------------------------------
    tables = [
        f"""CREATE TABLE IF NOT EXISTS {F}.dictionary_entity (
              dictionary_version STRING COMMENT 'Version this entry belongs to; append-only, latest wins.',
              tenant STRING COMMENT '_base for the shared vocabulary, or the tenant that extended it.',
              entity_type STRING COMMENT 'Canonical entity type name (e.g. Policy, Coverholder).',
              description STRING,
              attributes ARRAY<STRING> COMMENT 'Allowed attribute names for the entity.',
              status STRING COMMENT 'active | retired.',
              created_by STRING, created_at TIMESTAMP
            ) COMMENT 'The shared vocabulary — entity types and their attributes. Extraction is constrained BY this; the graph is typed AGAINST it. Append-only; schema recognition bumps the version.'""",
        f"""CREATE TABLE IF NOT EXISTS {F}.dictionary_relationship (
              dictionary_version STRING, tenant STRING,
              relationship_name STRING COMMENT 'Allowed relation (e.g. ISSUED_TO, SUBMITTED_BY).',
              source_entity STRING, target_entity STRING, description STRING,
              status STRING, created_by STRING, created_at TIMESTAMP
            ) COMMENT 'Allowed relations between entity types. The graph edges are typed against this. Append-only.'""",

        # --- assertion graph (MRC shape upgraded to assertion-level provenance)
        f"""CREATE TABLE IF NOT EXISTS {F}.graph_nodes (
              node_id STRING COMMENT 'Stable id, <entity_type>_<short>.',
              label STRING COMMENT 'Entity type from the dictionary.',
              properties STRING COMMENT 'JSON of extracted attributes.',
              source_document_id STRING COMMENT 'The document this assertion came from (provenance).',
              extraction_path STRING COMMENT 'det | ai | reconciled — which path produced/confirmed it.',
              confidence DOUBLE COMMENT 'Extraction confidence 0..1.',
              template_version STRING, dictionary_version STRING,
              anchor STRING COMMENT 'Located anchor as JSON, e.g. cell Sheet1!B4 for tabular, or page 2 span start..end for prose.',
              tenant STRING, created_at TIMESTAMP
            ) COMMENT 'Assertion-level node capture. Nothing lands without provenance: every row carries its source document, extraction path, confidence, versions and located anchor.'""",
        f"""CREATE TABLE IF NOT EXISTS {F}.graph_edges (
              edge_id STRING, source_id STRING, target_id STRING,
              relationship_type STRING COMMENT 'From dictionary_relationship.',
              source_document_id STRING, extraction_path STRING, confidence DOUBLE,
              template_version STRING, dictionary_version STRING, anchor STRING,
              tenant STRING, created_at TIMESTAMP
            ) COMMENT 'Assertion-level edge capture, same provenance discipline as graph_nodes.'""",

        # --- template registry (HB 0_carrier_template, generalised, append-only)
        f"""CREATE TABLE IF NOT EXISTS {F}.template (
              template_id STRING, tenant STRING,
              counterparty STRING COMMENT 'The counterparty (coverholder/carrier/broker) this template recognises.',
              doc_family STRING COMMENT 'e.g. premium_bordereau, claims_bordereau, renewal_slip, mrc.',
              template_version STRING COMMENT 'v1, v2, ... append-only; accept-remap bumps it.',
              expected_anchors STRING COMMENT 'JSON list of fingerprint anchors (columns/sheets or headings).',
              field_map STRING COMMENT 'JSON mapping each logical field to its anchor spec; learned labels append on remap.',
              field_count INT, status STRING COMMENT 'active | superseded.',
              created_by STRING, created_at TIMESTAMP
            ) COMMENT 'Counterparty template registry. Append-only versions — the confirm-once mechanism: an accepted remap writes a new version, the old one is retained.'""",

        # --- intake provenance (HB 1_source_document)
        f"""CREATE TABLE IF NOT EXISTS {F}.source_document (
              doc_id STRING, tenant STRING, counterparty STRING, doc_family STRING,
              file_name STRING, stored_path STRING,
              status STRING COMMENT 'active | differs | quarantined | superseded | rejected | recognized_pending.',
              inbound_state STRING COMMENT 'known_unchanged | known_changed | unknown | unusable.',
              template_version STRING, dictionary_version STRING,
              reconciliation_detail STRING COMMENT 'JSON: per-field agree/differs/det-only/ai-only/missing + proposed remap.',
              reporting_period STRING COMMENT 'e.g. 2026-07 for a monthly bordereau.',
              ingested_at TIMESTAMP, signed_off_by STRING, signed_off_at TIMESTAMP
            ) COMMENT 'One row per inbound document with its trust state and reconciliation detail. Supersession is a status flip; downstream reads go through v_*_latest.'""",

        # --- append-only audit (HB 5_gov_audit_event)
        f"""CREATE TABLE IF NOT EXISTS {F}.audit_event (
              event_id STRING, event_type STRING COMMENT 'ingested, quarantined, differs, template_updated, schema_recognized, superseded, reprocessed, signed_off, rejected, reset, ...',
              entity_type STRING, entity_id STRING, detail STRING, actor STRING, created_at TIMESTAMP
            ) COMMENT 'Append-only audit trail. Pure inserts — never updated or deleted.'""",

        # --- append-only HITL decisions (generalised HB 5_scenario)
        f"""CREATE TABLE IF NOT EXISTS {F}.decision (
              decision_id STRING,
              decision_type STRING COMMENT 'schema_confirm | remap_accept | remap_reject | signoff | quarantine_resolve.',
              tenant STRING, source_document_id STRING, template_version STRING,
              detail STRING COMMENT 'JSON of the act (confirmed fields, corrections, remap).',
              reason STRING, actor STRING, status STRING COMMENT 'saved | approved.',
              parent_decision_id STRING, created_at TIMESTAMP
            ) COMMENT 'Append-only record of the human-in-the-loop acts (the gateway''s own decision surface). Versioned by new rows, never edited.'""",

        # --- reviewer findings (HB 4_reviewer_finding) — advise-only agent output
        f"""CREATE TABLE IF NOT EXISTS {F}.reviewer_finding (
              finding_id STRING, source_document_id STRING,
              severity STRING COMMENT 'high | medium | low.',
              field STRING, message STRING, extraction_path STRING, confidence DOUBLE,
              status STRING COMMENT 'open | resolved.', created_by STRING, created_at TIMESTAMP
            ) COMMENT 'Extraction-review agent findings queued for the HITL. Advises, never lands data.'""",

        # --- typed projection: premium rows, shaped to the data-core exchange contract (D4)
        f"""CREATE TABLE IF NOT EXISTS {F}.premium_bordereau_line (
              bordereau_line_id STRING COMMENT 'Identifier for the bordereau line; equals the PremiumBordereauLine graph node_id (lineage).',
              reporting_month DATE COMMENT 'First day of the calendar month the bordereau reports on.',
              coverholder_name STRING COMMENT 'Coverholder/broker submitting the bordereau.',
              policy_number STRING COMMENT 'Policy reference as reported; matched to the core model downstream.',
              insured_name STRING COMMENT 'Insured as reported.',
              line_of_business_code STRING COMMENT 'Mapped from the coverholder''s own class descriptions to the canonical code set.',
              inception_date DATE, expiry_date DATE,
              currency_code STRING, gross_premium DECIMAL(18,2), commission_amount DECIMAL(18,2),
              risk_country_code STRING, risk_postcode STRING,
              source_system_code STRING COMMENT 'Provenance; coverholder bordereaux use COVERHOLDER_BDX.',
              source_document_id STRING COMMENT 'Lineage back to the document that produced this row.'
            ) COMMENT 'Typed silver projection of premium bordereau lines, materialised from the assertion graph. Column shape matches bricksurance_exchange.premium_bordereau_line (v0.12.0) for cheap gen2 migration; source_document_id is a gateway lineage extension.'""",

        # --- typed projection: claims rows, shaped to the delegated-authority claim-row contract
        f"""CREATE TABLE IF NOT EXISTS {F}.claim_bordereau_line (
              claim_line_id STRING COMMENT 'Equals the ClaimBordereauLine graph node_id (lineage).',
              reporting_month DATE, coverholder_name STRING,
              claim_reference STRING, policy_number STRING COMMENT 'Reported risk/policy reference.',
              loss_date DATE, cause_of_loss_code STRING,
              paid_amount DECIMAL(18,2), outstanding_amount DECIMAL(18,2),
              incurred_amount DECIMAL(18,2) COMMENT 'paid + outstanding (governed derivation).',
              currency_code STRING, source_system_code STRING, source_document_id STRING
            ) COMMENT 'Typed silver projection of claim bordereau lines. Column shape follows bricksurance_delegated_authority.bordereau_claim_row for cheap gen2 migration.'""",

        # --- typed projection: one row per MRC (prose tenant)
        f"""CREATE TABLE IF NOT EXISTS {F}.mrc_entities (
              mrc_id STRING COMMENT 'Equals the Policy graph node_id for this MRC (lineage).',
              umr STRING COMMENT 'Unique Market Reference.',
              policy_number STRING, class_of_business STRING,
              inception_date STRING, expiry_date STRING,
              insured_name STRING, broker_name STRING,
              premium_text STRING, headline_limit STRING, deductible_text STRING,
              premium_amount DECIMAL(18,2) COMMENT 'Numeric premium parsed deterministically from premium_text (the prose is retained as provenance).',
              premium_currency STRING COMMENT '3-letter currency parsed from premium_text.',
              limit_amount DECIMAL(18,2) COMMENT 'Numeric headline limit parsed deterministically from headline_limit.',
              n_clauses INT, n_exclusions INT, n_insurers INT,
              choice_of_law STRING, situation STRING, slip_leader STRING,
              signed_lines_total DOUBLE COMMENT 'Sum of signed lines (percent of the order).',
              brokerage_pct DOUBLE,
              checks_failed INT COMMENT 'Number of contract-certainty checks failed.',
              certainty_status STRING COMMENT 'pass | fail.',
              source_document_id STRING
            ) COMMENT 'Headline structured facts extracted from each Market Reform Contract (prose). Numeric premium/limit are parsed deterministically from the prose (which is kept as provenance). Full entity detail lives in the shared assertion graph.'""",

        # --- MRC: per-data-point extraction with source quote (lineage + Core Data Record view)
        f"""CREATE TABLE IF NOT EXISTS {F}.mrc_extraction (
              mrc_id STRING, source_document_id STRING,
              data_point STRING, label STRING,
              acord_binding STRING COMMENT 'ACORD entity.attribute the value binds to.',
              cdr_field STRING COMMENT 'Indicative Lloyd''s Core Data Record field (paraphrased crosswalk, not the published specification).',
              section STRING COMMENT 'MRC v3 section the value was read from.',
              value STRING, source_quote STRING COMMENT 'The source line in the contract the value came from.',
              status STRING COMMENT 'identified | not_found.', confidence DOUBLE, created_at TIMESTAMP
            ) COMMENT 'One row per expected data point per MRC: value, ACORD binding, indicative CDR field and the source quote it was read from.'""",
        # --- MRC: contract-certainty check results
        f"""CREATE TABLE IF NOT EXISTS {F}.mrc_certainty_check (
              mrc_id STRING, source_document_id STRING,
              check_id STRING, label STRING,
              status STRING COMMENT 'pass | fail.', detail STRING, created_at TIMESTAMP
            ) COMMENT 'Deterministic contract-certainty rules run on every recognised MRC (signed lines, several liability, sanctions clause, period, UMR, slip leader, law).'""",

        # --- eval harness results (AI extraction path, per model)
        f"""CREATE TABLE IF NOT EXISTS {F}.eval_result (
              run_id STRING, model STRING,
              scope STRING COMMENT 'overall | field.',
              field STRING, correct INT, total INT, accuracy DOUBLE,
              mlflow_run_id STRING, created_at TIMESTAMP
            ) COMMENT 'Per-field / overall mapping accuracy of the AI extraction path, per model, against synthetic ground truth (we generate the documents, so truth is free). Drives the Eval screen and the model-swap comparison.'""",

        # --- typed projection: health renewal-slip inputs (the T2 config-port target)
        f"""CREATE TABLE IF NOT EXISTS {F}.renewal_inputs (
              renewal_input_id STRING COMMENT 'Equals the RenewalExhibit graph node_id (lineage).',
              group_name STRING, member_months DECIMAL(18,2), total_incurred_claims DECIMAL(18,2),
              annual_trend DOUBLE, months_of_trend DOUBLE, demographic_adjustment DOUBLE,
              target_loss_ratio DOUBLE, manual_rating_pool_increase DOUBLE,
              carrier_name STRING, reporting_period STRING, source_document_id STRING
            ) COMMENT 'Renewal-input assumptions extracted from a health carrier renewal exhibit (the HB exhibit family, ported as a tenant config). One row per employer group per slip; materialised by the config-driven generic lander.'""",
    ]
    run_batch(tables, cfg, label="tables")
    for col, typ in [("choice_of_law", "STRING"), ("situation", "STRING"), ("slip_leader", "STRING"),
                     ("signed_lines_total", "DOUBLE"), ("brokerage_pct", "DOUBLE"),
                     ("checks_failed", "INT"), ("certainty_status", "STRING")]:
        try:
            sql(f"ALTER TABLE {F}.mrc_entities ADD COLUMNS ({col} {typ})", cfg=cfg)
        except Exception:
            pass  # column already present

    # --- governed functions (the math path; no math in the app) --------------
    functions = [
        f"""CREATE OR REPLACE FUNCTION {F}.fn_reconcile_status(det STRING, ai STRING, tol DOUBLE)
            RETURNS STRING
            COMMENT 'Deterministic field-level reconciliation of the two extraction paths. Numeric values agree within tol (relative); strings agree case/space-insensitively. Returns agree | differs | det-only | ai-only | missing.'
            RETURN CASE
              WHEN det IS NULL AND ai IS NULL THEN 'missing'
              WHEN det IS NULL THEN 'ai-only'
              WHEN ai IS NULL THEN 'det-only'
              WHEN try_cast(det AS DOUBLE) IS NOT NULL AND try_cast(ai AS DOUBLE) IS NOT NULL
                THEN CASE WHEN abs(try_cast(det AS DOUBLE) - try_cast(ai AS DOUBLE))
                          <= tol * greatest(abs(try_cast(det AS DOUBLE)), abs(try_cast(ai AS DOUBLE)), 1e-9)
                     THEN 'agree' ELSE 'differs' END
              WHEN lower(trim(det)) = lower(trim(ai)) THEN 'agree'
              ELSE 'differs' END""",
    ]
    run_batch(functions, cfg, label="functions")

    # --- latest / supersession views ----------------------------------------
    views = [
        f"""CREATE OR REPLACE VIEW {F}.v_source_document_current AS
            SELECT * FROM {F}.source_document WHERE status NOT IN ('superseded','rejected')""",
        f"""CREATE OR REPLACE VIEW {F}.v_graph_nodes_latest AS
            SELECT n.* FROM {F}.graph_nodes n
            JOIN {F}.source_document d ON n.source_document_id = d.doc_id
            WHERE d.status = 'active'""",
        f"""CREATE OR REPLACE VIEW {F}.v_graph_edges_latest AS
            SELECT e.* FROM {F}.graph_edges e
            JOIN {F}.source_document d ON e.source_document_id = d.doc_id
            WHERE d.status = 'active'""",
        f"""CREATE OR REPLACE VIEW {F}.v_template_latest AS
            SELECT * EXCEPT(rn) FROM (
              SELECT t.*, row_number() OVER (
                PARTITION BY tenant, counterparty, doc_family ORDER BY created_at DESC) rn
              FROM {F}.template t) WHERE rn = 1""",
        f"""CREATE OR REPLACE VIEW {F}.v_dictionary_entity_latest AS
            SELECT * EXCEPT(rn) FROM (
              SELECT e.*, row_number() OVER (
                PARTITION BY tenant, entity_type ORDER BY created_at DESC) rn
              FROM {F}.dictionary_entity e) WHERE rn = 1""",
        f"""CREATE OR REPLACE VIEW {F}.v_dictionary_relationship_latest AS
            SELECT * EXCEPT(rn) FROM (
              SELECT r.*, row_number() OVER (
                PARTITION BY tenant, relationship_name ORDER BY created_at DESC) rn
              FROM {F}.dictionary_relationship r) WHERE rn = 1""",
        # The book reads latest-only: superseded/rejected documents' projection rows drop out.
        f"""CREATE OR REPLACE VIEW {F}.v_premium_bordereau_line_latest AS
            SELECT p.* FROM {F}.premium_bordereau_line p
            JOIN {F}.source_document d ON p.source_document_id = d.doc_id
            WHERE d.status = 'active'""",
        f"""CREATE OR REPLACE VIEW {F}.v_claim_bordereau_line_latest AS
            SELECT c.* FROM {F}.claim_bordereau_line c
            JOIN {F}.source_document d ON c.source_document_id = d.doc_id
            WHERE d.status = 'active'""",
        f"""CREATE OR REPLACE VIEW {F}.v_renewal_inputs_latest AS
            SELECT r.* FROM {F}.renewal_inputs r
            JOIN {F}.source_document d ON r.source_document_id = d.doc_id
            WHERE d.status = 'active'""",
        # Completeness — the "who hasn't reported" tile: a coverholder is behind if its
        # latest reported month trails the book's latest month.
        f"""CREATE OR REPLACE VIEW {F}.v_completeness AS
            WITH g AS (SELECT max(reporting_month) gmax FROM {F}.v_premium_bordereau_line_latest),
                 c AS (SELECT coverholder_name,
                              count(DISTINCT reporting_month) AS months_received,
                              max(reporting_month) AS last_month
                       FROM {F}.v_premium_bordereau_line_latest GROUP BY coverholder_name)
            SELECT c.coverholder_name, c.months_received, c.last_month,
                   g.gmax AS latest_expected, (c.last_month < g.gmax) AS behind
            FROM c CROSS JOIN g""",
        # Loss ratio by coverholder — incurred (claims) over GWP (premium).
        f"""CREATE OR REPLACE VIEW {F}.v_loss_ratio AS
            WITH p AS (SELECT coverholder_name, sum(gross_premium) gwp
                       FROM {F}.v_premium_bordereau_line_latest GROUP BY coverholder_name),
                 cl AS (SELECT coverholder_name, sum(incurred_amount) incurred
                        FROM {F}.v_claim_bordereau_line_latest GROUP BY coverholder_name)
            SELECT p.coverholder_name, p.gwp, coalesce(cl.incurred, 0) AS incurred,
                   round(coalesce(cl.incurred, 0) / nullif(p.gwp, 0), 4) AS loss_ratio
            FROM p LEFT JOIN cl ON p.coverholder_name = cl.coverholder_name""",
        f"""CREATE OR REPLACE VIEW {F}.v_mrc_extraction_latest AS
            SELECT x.* FROM {F}.mrc_extraction x
            JOIN {F}.source_document d ON x.source_document_id = d.doc_id
            WHERE d.status = 'active'""",
        f"""CREATE OR REPLACE VIEW {F}.v_mrc_certainty_latest AS
            SELECT c.* FROM {F}.mrc_certainty_check c
            JOIN {F}.source_document d ON c.source_document_id = d.doc_id
            WHERE d.status = 'active'""",
        f"""CREATE OR REPLACE VIEW {F}.v_mrc_entities_latest AS
            SELECT m.* FROM {F}.mrc_entities m
            JOIN {F}.source_document d ON m.source_document_id = d.doc_id
            WHERE d.status = 'active'""",
    ]
    run_batch(views, cfg, label="views")

    seed_dictionary(cfg)
    print("== Phase 1 complete.")


def seed_dictionary(cfg):
    """Seed the baseline dictionary (idempotent — skips if already seeded)."""
    F = cfg["full_schema"]
    have = {r[0] for r in sql(f"SELECT DISTINCT tenant FROM {F}.dictionary_entity", cfg=cfg)}
    have |= {r[0] for r in sql(f"SELECT DISTINCT tenant FROM {F}.dictionary_relationship", cfg=cfg)}

    base = json.loads(open(os.path.join(ROOT, "data", "acord_dictionary.json")).read())
    ver = base.get("version", "v1")

    layers = [("_base", base.get("entities", {}), base.get("relationships", {}))]
    for t in enabled_tenants(cfg):
        ext = load_tenant(cfg, t).get("dictionary_extensions", {})
        layers.append((t, ext.get("entities", {}), ext.get("relationships", {})))

    ent_rows, rel_rows = [], []
    layers = [l for l in layers if l[0] not in have and (l[1] or l[2])]
    if not layers:
        print("  dictionary already seeded — nothing new.")
        return
    for tenant, entities, rels in layers:
        for name, e in entities.items():
            attrs = "array(" + ",".join(lit(a) for a in e.get("attributes", [])) + ")" if e.get("attributes") else "array()"
            ent_rows.append(
                f"({lit(ver)},{lit(tenant)},{lit(name)},{lit(e.get('description',''))},{attrs},'active','build',current_timestamp())"
            )
        for rname, r in rels.items():
            rel_rows.append(
                f"({lit(ver)},{lit(tenant)},{lit(rname)},{lit(r.get('source'))},{lit(r.get('target'))},{lit(r.get('description',''))},'active','build',current_timestamp())"
            )

    if ent_rows:
        sql(f"INSERT INTO {F}.dictionary_entity VALUES " + ",".join(ent_rows), cfg=cfg)
    if rel_rows:
        sql(f"INSERT INTO {F}.dictionary_relationship VALUES " + ",".join(rel_rows), cfg=cfg)
    print(f"  seeded dictionary {ver}: {len(ent_rows)} entities, {len(rel_rows)} relationships "
          f"across {len(layers)} layers.")


if __name__ == "__main__":
    build(load_config())
