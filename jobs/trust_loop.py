"""Phase 3 — trust-loop server actions (the HITL acts; server-side, governed).

The confirm-once mechanic and schema recognition live here so the app, a notebook and
the MCP tools all call the same logic — nothing built twice, and any preview is the
server-side result (DECISIONS D6). Every act is append-only: a new template version, a
decision row, audit events; the resolved document is superseded, never edited.

Importable. Reuses the pipeline for reprocessing.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import load_config, load_tenant, sql  # noqa: E402
from jobs.ingest_pipeline import (audit, parse_file, ai_extract, lookup_template,  # noqa: E402
                                  process_file)


FAMILY_KEY = {"premium_bordereau": "premium", "claims_bordereau": "claims"}


def _fields_for(cfg, family, tenant="bordereaux"):
    return load_tenant(cfg, tenant)["logical_fields"].get(FAMILY_KEY.get(family, ""), [])


def _bump(version):
    try:
        return f"v{int(str(version).lstrip('v')) + 1}"
    except Exception:
        return "v2"


def _doc(cfg, doc_id):
    F = cfg["full_schema"]
    r = sql(f"""SELECT doc_id,tenant,counterparty,doc_family,file_name,stored_path,status,
                       inbound_state,template_version,reconciliation_detail,reporting_period
                FROM {F}.source_document WHERE doc_id=:d""",
            params={"d": doc_id}, cfg=cfg)
    if not r:
        raise ValueError(f"no such document {doc_id}")
    k = ["doc_id", "tenant", "counterparty", "doc_family", "file_name", "stored_path", "status",
         "inbound_state", "template_version", "reconciliation_detail", "reporting_period"]
    d = dict(zip(k, r[0]))
    d["reconciliation_detail"] = json.loads(d["reconciliation_detail"]) if d["reconciliation_detail"] else {}
    return d


def decision(cfg, decision_type, doc_id, template_version, detail, reason, actor,
             status="saved", parent=None):
    F = cfg["full_schema"]
    did = f"DEC-{uuid.uuid4().hex[:10]}"
    sql(f"""INSERT INTO {F}.decision VALUES
            (:id,:dt,'bordereaux',:doc,:tv,:detail,:reason,:actor,:status,:parent,current_timestamp())""",
        params={"id": did, "dt": decision_type, "doc": doc_id, "tv": template_version,
                "detail": json.dumps(detail), "reason": reason, "actor": actor,
                "status": status, "parent": parent}, cfg=cfg)
    return did


def _resolve(cfg, doc_id, actor):
    """Mark a quarantined/unknown document resolved: superseded + signed off."""
    F = cfg["full_schema"]
    sql(f"""UPDATE {F}.source_document
            SET status='superseded', signed_off_by=:a, signed_off_at=current_timestamp()
            WHERE doc_id=:d""", params={"a": actor, "d": doc_id}, cfg=cfg)
    audit(cfg, "signed_off", "source_document", doc_id, detail="resolved by HITL", actor=actor)


def _reprocess(cfg, stored_path, actor):
    res = process_file(cfg, stored_path)
    audit(cfg, "reprocessed", "source_document", stored_path,
          detail=f"reprocessed -> {res['state']}", actor=actor)
    return res


# ---------------------------------------------------- known-but-changed: confirm once
def accept_remap(cfg, doc_id, actor="reviewer"):
    """Learn the new labels (template version++), reprocess, resolve. Confirm once."""
    F = cfg["full_schema"]
    d = _doc(cfg, doc_id)
    remap = d["reconciliation_detail"].get("proposed_remap", [])
    tmpl = lookup_template(cfg, d["counterparty"], d["doc_family"])
    if tmpl is None:
        raise ValueError("no base template to remap; use confirm_schema for unknown documents")

    field_map = dict(tmpl["field_map"])
    for m in remap:
        f, found = m["field"], m["found_label"]
        alts = [a.strip() for a in str(field_map.get(f, "")).split("|") if a.strip()]
        if found and found not in alts:
            alts.append(found)
        field_map[f] = "|".join(alts) if alts else found

    new_version = _bump(tmpl["version"])
    sql(f"""INSERT INTO {F}.template VALUES
            (:id,'bordereaux',:c,:f,:v,:anchors,:fmap,:n,'active',:actor,current_timestamp())""",
        params={"id": f"TPL-{uuid.uuid4().hex[:8]}", "c": d["counterparty"], "f": d["doc_family"],
                "v": new_version, "anchors": json.dumps(list(field_map.values())),
                "fmap": json.dumps(field_map), "n": len(field_map), "actor": actor}, cfg=cfg)
    audit(cfg, "template_updated", "template", f'{d["counterparty"]}/{d["doc_family"]}',
          detail=f"learned {len(remap)} label(s) -> {new_version}", actor=actor)
    decision(cfg, "remap_accept", doc_id, new_version,
             {"remap": remap, "new_version": new_version}, reason="accepted proposed remap", actor=actor)

    res = _reprocess(cfg, d["stored_path"], actor)
    _resolve(cfg, doc_id, actor)
    return {"new_version": new_version, "learned": remap, "reprocessed_state": res["state"],
            "lines": res.get("lines", 0)}


def reject_doc(cfg, doc_id, reason, actor="reviewer"):
    F = cfg["full_schema"]
    sql(f"UPDATE {F}.source_document SET status='rejected' WHERE doc_id=:d",
        params={"d": doc_id}, cfg=cfg)
    audit(cfg, "rejected", "source_document", doc_id, detail=reason, actor=actor)
    decision(cfg, "remap_reject", doc_id, None, {"reason": reason}, reason=reason, actor=actor)
    return {"status": "rejected"}


# ---------------------------------------------------- unknown: schema recognition
def propose_schema(cfg, doc_id):
    """AI proposes a full template for an unknown counterparty: mappings INTO the dictionary."""
    d = _doc(cfg, doc_id)
    parsed = parse_file(cfg, d["stored_path"])
    fields = _fields_for(cfg, d["doc_family"])
    ai = ai_extract(cfg, parsed["headers"], parsed["rows"], fields)
    proposal = []
    field_map = {}
    for lf in fields:
        info = ai.get(lf) or {}
        hdr = info.get("matched_header")
        proposal.append({"field": lf, "proposed_label": hdr,
                         "confidence": info.get("confidence"),
                         "present": hdr in parsed["headers"] if hdr else False})
        if hdr:
            field_map[lf] = hdr
    return {"counterparty": d["counterparty"], "doc_family": d["doc_family"],
            "headers": parsed["headers"], "proposal": proposal, "field_map": field_map}


def confirm_schema(cfg, doc_id, field_map, actor="reviewer"):
    """HITL confirms the proposed mapping -> create template v1, reprocess, resolve."""
    F = cfg["full_schema"]
    d = _doc(cfg, doc_id)
    sql(f"""INSERT INTO {F}.template VALUES
            (:id,'bordereaux',:c,:f,'v1',:anchors,:fmap,:n,'active',:actor,current_timestamp())""",
        params={"id": f"TPL-{uuid.uuid4().hex[:8]}", "c": d["counterparty"], "f": d["doc_family"],
                "anchors": json.dumps(list(field_map.values())),
                "fmap": json.dumps(field_map), "n": len(field_map), "actor": actor}, cfg=cfg)
    audit(cfg, "schema_recognized", "template", f'{d["counterparty"]}/{d["doc_family"]}',
          detail=f"new counterparty learned, {len(field_map)} fields", actor=actor)
    audit(cfg, "template_updated", "template", f'{d["counterparty"]}/{d["doc_family"]}',
          detail="v1 created from schema recognition", actor=actor)
    decision(cfg, "schema_confirm", doc_id, "v1", {"field_map": field_map},
             reason="confirmed recognised schema", actor=actor)
    res = _reprocess(cfg, d["stored_path"], actor)
    _resolve(cfg, doc_id, actor)
    return {"created_version": "v1", "reprocessed_state": res["state"], "lines": res.get("lines", 0)}


# ---------------------------------------------------- version diff + money impact
def versions(cfg, counterparty, doc_family, period):
    F = cfg["full_schema"]
    chain = sql(f"""SELECT doc_id,file_name,status,ingested_at
                    FROM {F}.source_document
                    WHERE counterparty=:c AND doc_family=:f AND reporting_period=:p
                    ORDER BY ingested_at""",
                params={"c": counterparty, "f": doc_family, "p": period}, cfg=cfg)
    out = []
    for doc_id, fn, status, ts in chain:
        tot = sql(f"""SELECT count(*), coalesce(sum(gross_premium),0)
                      FROM {F}.premium_bordereau_line WHERE source_document_id=:d""",
                  params={"d": doc_id}, cfg=cfg)[0]
        out.append({"doc_id": doc_id, "file_name": fn, "status": status,
                    "ingested_at": str(ts), "lines": int(tot[0]), "gross_premium": float(tot[1])})
    impact = None
    if len(out) >= 2:
        prev, curr = out[-2], out[-1]
        impact = {"old_doc": prev["file_name"], "new_doc": curr["file_name"],
                  "old_gross_premium": prev["gross_premium"], "new_gross_premium": curr["gross_premium"],
                  "premium_delta": round(curr["gross_premium"] - prev["gross_premium"], 2)}
    return {"counterparty": counterparty, "doc_family": doc_family, "period": period,
            "chain": out, "impact": impact}


if __name__ == "__main__":
    # Smoke: resolve the two quarantined states end to end.
    cfg = load_config(); F = cfg["full_schema"]
    changed = sql(f"SELECT doc_id FROM {F}.source_document WHERE inbound_state='known_changed' AND status='quarantined' LIMIT 1", cfg=cfg)
    unknown = sql(f"SELECT doc_id FROM {F}.source_document WHERE inbound_state='unknown' AND status='quarantined' LIMIT 1", cfg=cfg)
    if changed:
        print("accept_remap:", accept_remap(cfg, changed[0][0]))
    if unknown:
        prop = propose_schema(cfg, unknown[0][0])
        print("propose_schema fields:", len(prop["field_map"]))
        print("confirm_schema:", confirm_schema(cfg, unknown[0][0], prop["field_map"]))
