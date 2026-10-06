"""Phase 4 — extraction-review agent (advise-only).

Triages the ingest queue: flags low-confidence / disagreeing / drifted / unknown
assertions into the reviewer_finding table for the HITL. It **advises, never lands
data** — by construction it only ever writes reviewer_finding rows and audit events;
it never touches source_document status, templates, the graph, or projections. That is
the server-side policy: graduated autonomy with a hard deterministic ceiling, no prompt
can make it accept a mapping or land a row. Deterministic rules decide; an optional AI
narration only explains.

Importable (app + MCP call it). Reuses the pipeline's audit writer.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import load_config, sql  # noqa: E402
from jobs.ingest_pipeline import audit  # noqa: E402

LOW_CONF = 0.6


def _finding(cfg, doc_id, severity, field, message, path=None, conf=None):
    F = cfg["full_schema"]
    sql(f"""INSERT INTO {F}.reviewer_finding VALUES
            (:id,:doc,:sev,:field,:msg,:path,:conf,'open','review-agent',current_timestamp())""",
        params={"id": f"RF-{uuid.uuid4().hex[:10]}", "doc": doc_id, "sev": severity,
                "field": field, "msg": message, "path": path, "conf": conf}, cfg=cfg)


def review_document(cfg, doc_id):
    """Produce findings for one document. Returns the list; writes reviewer_finding rows."""
    F = cfg["full_schema"]
    r = sql(f"""SELECT inbound_state,status,reconciliation_detail,counterparty
                FROM {F}.source_document WHERE doc_id=:d""",
            params={"d": doc_id}, cfg=cfg)
    if not r:
        raise ValueError(f"no such document {doc_id}")
    state, status, rd_json, counterparty = r[0]
    rd = json.loads(rd_json) if rd_json else {}
    findings = []

    def add(sev, field, msg, path=None, conf=None):
        findings.append({"severity": sev, "field": field, "message": msg})
        _finding(cfg, doc_id, sev, field, msg, path, conf)

    if state == "unusable":
        add("high", None, f"Unreadable document — {rd.get('reason', 'no extractable table')}. "
                          "Cannot extract; request a machine-readable bordereau.")
    elif state == "unknown":
        add("high", None, f"New counterparty '{counterparty}' — no template. Schema recognition "
                          "required before any row can land. Advise HITL confirmation.")
    elif state == "known_changed":
        for m in rd.get("proposed_remap", []):
            add("medium", m["field"], f"Layout drift: expected '{m['expected_label']}', found "
                f"'{m['found_label']}'. Advise confirm-once remap (do not auto-accept).",
                path="det-vs-ai")
        for logical, info in (rd.get("fields") or {}).items():
            if info.get("status") == "differs":
                add("high", logical, f"Extraction paths disagree on '{logical}' "
                    f"(deterministic '{info.get('det_label')}' vs AI '{info.get('ai_header')}').",
                    path="reconciled", conf=info.get("ai_confidence"))

    # Low-confidence landed assertions (applies to active docs).
    low = sql(f"""SELECT node_id, confidence FROM {F}.graph_nodes
                  WHERE source_document_id=:d AND confidence < {LOW_CONF}""",
              params={"d": doc_id}, cfg=cfg)
    for node_id, conf in low:
        add("medium", node_id, f"Low-confidence assertion ({conf:.2f}) — advise spot-check "
            "against the source cell.", path="ai", conf=float(conf))

    audit(cfg, "review_run", "source_document", doc_id,
          detail=f"{len(findings)} finding(s)", actor="review-agent")
    return {"doc_id": doc_id, "findings": findings, "count": len(findings)}


def review_queue(cfg=None):
    """Review every document not yet resolved (quarantined + active without findings)."""
    cfg = cfg or load_config()
    F = cfg["full_schema"]
    docs = sql(f"""SELECT doc_id FROM {F}.source_document
                   WHERE status IN ('quarantined','active','differs')""", cfg=cfg)
    total = 0
    for (doc_id,) in docs:
        total += review_document(cfg, doc_id)["count"]
    print(f"== reviewed {len(docs)} documents, {total} findings written.")
    return {"documents": len(docs), "findings": total}


if __name__ == "__main__":
    review_queue()
