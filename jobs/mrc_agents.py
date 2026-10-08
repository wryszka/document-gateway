"""MRC review agents — advise only.

Each agent is given facts the deterministic system has already computed (counts, outcomes,
failed checks, diffs, proposed mappings) and writes advice for a person. It never records
a schema, accepts a change or loads a contract, and every review is logged in
mrc_agent_note with the facts it was given, so its advice can always be checked.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import sql  # noqa: E402
from jobs.ingest_pipeline import audit  # noqa: E402

RULES = ("Use ONLY the facts provided — never invent documents, numbers or names. You advise; a person decides. "
         "Write for a Lloyd's market technical audience: precise, plain English, no hype. "
         "Format: a one-paragraph overview, then '### Needs attention' as bullet points (each naming the document "
         "and why), then '### Suggested next steps' as bullet points. Keep it under 250 words.")


def _llm(cfg, prompt):
    out = sql("SELECT ai_query(:ep, :p)", params={"ep": cfg["models"]["narrate"], "p": prompt}, cfg=cfg)
    return (out[0][0] or "").strip()


def _log(cfg, agent, subject, facts, output, actor):
    F = cfg["full_schema"]
    nid = f"AN-{uuid.uuid4().hex[:10]}"
    sql(f"""INSERT INTO {F}.mrc_agent_note VALUES (:i,:a,:s,:f,:o,:m,:r,current_timestamp())""",
        params={"i": nid, "a": agent, "s": subject, "f": json.dumps(facts, default=str)[:20000],
                "o": output, "m": cfg["models"]["narrate"], "r": actor}, cfg=cfg)
    audit(cfg, "agent_review", "mrc_agent_note", nid, detail=f"{agent}: {subject}", actor=actor)
    return nid


def intake_facts(cfg):
    F = cfg["full_schema"]
    docs = sql(f"""SELECT d.file_name, d.inbound_state, d.template_version, d.counterparty,
                          get_json_object(d.reconciliation_detail, '$.schema')
                   FROM {F}.source_document d WHERE d.tenant='mrc' ORDER BY d.file_name""", cfg=cfg)
    entities = sql(f"""SELECT umr, insured_name, class_of_business, broker_name, premium_currency, premium_amount,
                              signed_lines_total, schema_name, schema_version, certainty_status
                       FROM {F}.v_mrc_entities_latest ORDER BY umr""", cfg=cfg)
    fails = sql(f"""SELECT e.umr, e.insured_name, c.label, c.detail FROM {F}.v_mrc_certainty_latest c
                    JOIN {F}.v_mrc_entities_latest e ON c.mrc_id = e.mrc_id WHERE c.status='fail' ORDER BY e.umr""", cfg=cfg)
    gaps = sql(f"""SELECT e.umr, x.label FROM {F}.v_mrc_extraction_latest x JOIN {F}.v_mrc_entities_latest e
                   ON x.mrc_id = e.mrc_id WHERE x.status <> 'identified' ORDER BY e.umr""", cfg=cfg)
    auto = sql(f"""SELECT count(*) FROM {F}.audit_event WHERE event_type='auto_ingested'""", cfg=cfg)[0][0]
    return {
        "documents": [{"file": f, "state": s, "schema": v or flagged, "broker": c} for f, s, v, c, flagged in docs],
        "contracts_landed": [{"umr": r[0], "insured_or_coverholder": r[1], "class": r[2], "broker": r[3],
                              "premium": f"{r[4]} {r[5]}", "signed_lines_pct": r[6], "schema": f"{r[7]} {r[8]}",
                              "certainty": r[9]} for r in entities],
        "loaded_with_no_person_involved": int(auto),
        "failed_certainty_checks": [{"umr": a, "contract": b, "check": c, "detail": d} for a, b, c, d in fails],
        "missing_data_points": [{"umr": a, "data_point": b} for a, b in gaps],
    }


def intake_review(cfg, actor="presenter"):
    facts = intake_facts(cfg)
    prompt = ("You are the intake review agent for a Lloyd's Market Reform Contract gateway. Review today's intake "
              "and tell the operations lead what landed and what needs a person. " + RULES +
              "\n\nFACTS:\n" + json.dumps(facts, indent=1, default=str))
    out = _llm(cfg, prompt)
    nid = _log(cfg, "intake_review", "MRC intake", facts, out, actor)
    return {"note_id": nid, "review": out, "facts": facts}


def schema_review(cfg, kind, payload, actor="presenter"):
    """kind='recognition': payload = proposed schema (name, fields with bindings/confidence).
    kind='changes': payload = the diff and the decisions the person has selected."""
    if kind == "recognition":
        task = ("You are the schema review agent. Review this PROPOSED NEW SCHEMA before a person records it. "
                "Check: fields mapped to the same ACORD term twice; low-confidence model mappings; fields left with no "
                "ACORD term that a Lloyd's Core Data Record would need; whether the core identifiers (UMR, parties, "
                "period, security) are covered; whether the name and description fit the document.")
    else:
        task = ("You are the schema review agent. Review this PROPOSED AMENDMENT to a recorded schema before a person "
                "accepts it. Check: whether each rename keeps the same meaning; whether any mapping points at the wrong "
                "field; which accepted gaps matter for contract certainty or the Core Data Record; what to ask the broker.")
    prompt = task + " " + RULES + "\n\nFACTS:\n" + json.dumps(payload, indent=1, default=str)[:15000]
    out = _llm(cfg, prompt)
    subject = payload.get("file_name") or payload.get("name") or kind
    nid = _log(cfg, "schema_review", f"{kind}: {subject}", payload, out, actor)
    return {"note_id": nid, "review": out}
