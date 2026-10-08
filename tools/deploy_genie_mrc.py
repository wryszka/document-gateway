"""T3 — create the "Ask the MRCs" Genie space programmatically (never hand-built).

Mirrors the proven bricksurance-data-core builder: POST /api/2.0/genie/spaces with a
serialized_space payload. Space covers the MRC projection + the shared graph. Grants the
app SP CAN_RUN (best-effort) and writes genie.mrc_space_id into config.json.

Run:  uv run --with databricks-sdk python tools/deploy_genie_mrc.py
"""
from __future__ import annotations

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import load_config, client, ROOT  # noqa: E402

APP_SP = "e843ada0-1943-4f9a-8fda-f697b3f412c7"
PARENT_PATH = "/Workspace/Shared/document-gateway"


def uid():
    return uuid.uuid4().hex  # lowercase 32-hex, no hyphens (Genie requirement)


def build(cfg):
    F = cfg["full_schema"]
    E, X, C = f"{F}.v_mrc_entities_latest", f"{F}.v_mrc_extraction_latest", f"{F}.v_mrc_certainty_latest"
    tables = sorted([E, X, C, f"{F}.source_document"])
    examples = [
        ("Which contracts are not fully signed?",
         f"SELECT umr, insured_name, class_of_business, signed_lines_total FROM {E} WHERE abs(signed_lines_total - 100) > 0.05 ORDER BY signed_lines_total",
         "signed_lines_total is the sum of signed lines as a percent of the 100% order; fully signed = 100."),
        ("Which contracts failed a contract-certainty check, and why?",
         f"SELECT e.umr, e.insured_name, c.label, c.detail FROM {C} c JOIN {E} e ON c.mrc_id = e.mrc_id WHERE c.status = 'fail' ORDER BY e.umr",
         "One row per check per contract in v_mrc_certainty_latest; status is pass or fail."),
        ("What are the exclusions and the deductible on the marine cargo contract?",
         f"SELECT e.umr, x.label, x.value, x.source_quote FROM {X} x JOIN {E} e ON x.mrc_id = e.mrc_id WHERE e.class_of_business = 'Marine Cargo' AND x.data_point IN ('exclusions','deductible_text')",
         "v_mrc_extraction_latest has one row per data point per contract with the value and the source line it was read from; list values are in source_quote."),
        ("Total premium by currency",
         f"SELECT premium_currency, count(*) contracts, sum(premium_amount) premium FROM {E} GROUP BY premium_currency ORDER BY premium DESC",
         "Never add premiums across currencies; group by premium_currency."),
        ("Which schema was each contract read with?",
         f"SELECT umr, insured_name, schema_name, schema_version FROM {E} ORDER BY schema_name, umr",
         "schema_name/schema_version come from the schema repository match at intake."),
        ("Which syndicate leads each contract?",
         f"SELECT umr, insured_name, slip_leader FROM {E} ORDER BY umr",
         "slip_leader is the lead syndicate from the Subscription Agreement section."),
    ]
    serialized = {
        "version": 2,
        "data_sources": {"tables": [{"identifier": i} for i in tables]},
        "instructions": {
            "text_instructions": [{"id": uid(), "content": [
                "These are synthetic Lloyd's Market Reform Contracts (MRC v3) read by the Document Gateway. "
                "v_mrc_entities_latest: one row per contract — umr, class_of_business, insured_name, broker_name, "
                "premium_amount + premium_currency, limit_amount, headline_limit, deductible_text, slip_leader, "
                "signed_lines_total (percent of the order), choice_of_law, checks_failed, certainty_status. "
                "v_mrc_extraction_latest: one row per expected data point per contract — data_point, label, value, "
                "section, source_quote (the line in the contract), acord_binding, cdr_field (indicative Core Data "
                "Record field). Use it for clauses, exclusions, deductibles, law, syndicates and any 'where did this "
                "come from' question; list values (clauses, exclusions, security) are in source_quote. "
                "v_mrc_certainty_latest: one row per contract-certainty check — label, status (pass/fail), detail. "
                "schema_name + schema_version say which registered schema a contract was read with: "
                "'Lloyd\'s MRC v3 — Open Market (ACORD)' for open-market contracts, "
                "'Lloyd\'s MRC v3 — Binding Authority Agreement (ACORD)' for binding authorities (its insured_name is the "
                "coverholder and its premium is estimated premium income). "
                "Never sum premiums or limits across currencies. Refer to contracts by UMR and insured name."]}],
            "example_question_sqls": sorted(
                ({"id": uid(), "question": [q], "sql": [s], "usage_guidance": [g]} for q, s, g in examples),
                key=lambda x: x["id"]),
        },
        "benchmarks": {"questions": sorted(
            ({"id": uid(), "question": [q], "answer": [{"format": "SQL", "content": [s]}]}
             for q, s, _ in examples), key=lambda x: x["id"])},
    }
    return {"title": "Ask the MRCs",
            "description": "Synthetic Lloyd's Market Reform Contracts read through the Document Gateway — contracts, every extracted value with its source line, and contract-certainty results. Illustrative; syndicate names are public, insureds invented.",
            "warehouse_id": cfg["warehouse_id"], "serialized_space": json.dumps(serialized, indent=2)}


def update(cfg):
    """Update the existing space in place (keeps the space id the app uses)."""
    w = client(cfg)
    sid = cfg["genie"]["mrc_space_id"]
    w.api_client.do("PATCH", f"/api/2.0/genie/spaces/{sid}", body=build(cfg))
    print(f"updated space {sid}")
    return sid


def main():
    cfg = load_config()
    w = client(cfg)
    payload = build(cfg)
    payload["parent_path"] = PARENT_PATH
    try:
        w.workspace.mkdirs(PARENT_PATH)
    except Exception:
        pass
    resp = w.api_client.do("POST", "/api/2.0/genie/spaces", body=payload)
    space_id = resp["space_id"]
    print(f"created space {space_id}: {w.config.host}/genie/rooms/{space_id}")

    # best-effort CAN_RUN grant for the app SP
    try:
        w.api_client.do("PATCH", f"/api/2.0/permissions/genie/{space_id}",
                        body={"access_control_list": [
                            {"service_principal_name": APP_SP, "permission_level": "CAN_RUN"}]})
        print("  granted app SP CAN_RUN")
    except Exception as e:
        print(f"  (grant note: {e}; app SP typically still queries the space)")

    cfgpath = os.path.join(ROOT, "config.json")
    c = json.load(open(cfgpath))
    c.setdefault("genie", {})["mrc_space_id"] = space_id
    json.dump(c, open(cfgpath, "w"), indent=2)
    print(f"  wrote genie.mrc_space_id -> config.json")
    return space_id


if __name__ == "__main__":
    if "--update" in sys.argv:
        update(load_config())
    else:
        main()
