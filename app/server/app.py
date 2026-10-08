"""Document Gateway — thin FastAPI backend (the control surface over the real objects).

Every endpoint reads/writes a real governed UC object or calls a governed function/action.
No business math here (DECISIONS D6) — reconciliation is fn_reconcile_status, the trust-loop
acts are jobs/trust_loop (the same functions the MCP tools call). Serves one self-contained
SPA. Runs in Databricks Apps on the app service principal.
"""
from __future__ import annotations

import json
import os
import sys

from fastapi import FastAPI, Body, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Repo root is synced into the app; make lib/jobs importable.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from databricks.sdk import WorkspaceClient  # noqa: E402
import lib  # noqa: E402
from jobs import ingest_pipeline as pipe  # noqa: E402
from jobs import trust_loop as tl  # noqa: E402
from jobs import mrc_pipeline as mrc  # noqa: E402
from agents import extraction_review as review  # noqa: E402

# In-app: use the app SP (default auth), not a CLI profile.
os.environ.setdefault("DATABRICKS_APP_DEFAULT_AUTH", "1")
_W = WorkspaceClient()
lib.set_client(_W)
CFG = lib.load_config()
F = CFG["full_schema"]
HOST = (_W.config.host or "").rstrip("/")
FRONTEND = os.path.join(ROOT, "app", "frontend")


def q(sql_text, params=None):
    return lib.sql(sql_text, params=params, cfg=CFG)


def rows_as_dicts(sql_text, cols, params=None):
    return [dict(zip(cols, r)) for r in q(sql_text, params)]


app = FastAPI(title="Document Gateway")


class NoStoreHTML(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        if resp.headers.get("content-type", "").startswith("text/html"):
            resp.headers["Cache-Control"] = "no-store"
        return resp


app.add_middleware(NoStoreHTML)


# ------------------------------------------------------------------ static
@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND, "index.html"), media_type="text/html")


@app.get("/tokens.css")
def tokens():
    return FileResponse(os.path.join(FRONTEND, "tokens.css"), media_type="text/css")


@app.get("/api/health")
def health():
    return {"ok": True}


# ------------------------------------------------------------------ config / links
def uc_link(kind, name):
    # kind: table|function|volume
    if kind == "function":
        return f"{HOST}/explore/data/functions/{CFG['catalog']}/{CFG['schema']}/{name}"
    if kind == "volume":
        return f"{HOST}/explore/data/volumes/{CFG['catalog']}/{CFG['schema']}/{name}"
    return f"{HOST}/explore/data/{CFG['catalog']}/{CFG['schema']}/{name}"


@app.get("/api/tenant_config")
def tenant_config(tenant: str = "health_slip"):
    """Return a tenant's config file verbatim — the 'config-port' reveal. Validated against
    the known tenants to prevent path traversal."""
    tv = CFG["tenants"].get(tenant)
    if not tv:
        raise HTTPException(404, "no such tenant")
    path = os.path.join(ROOT, tv["config"])
    with open(path) as f:
        text = f.read()
    return {"tenant": tenant, "path": tv["config"], "lines": text.count(chr(10)) + 1, "config": text}


@app.get("/api/config")
def config():
    g = CFG.get("genie", {})
    return {"catalog": CFG["catalog"], "schema": CFG["schema"], "host": HOST,
            "tenants": {t: v for t, v in CFG["tenants"].items()},
            "genie_space_id": g.get("space_id", ""),
            "mrc_space_id": g.get("mrc_space_id", ""),
            "mrc_ka_endpoint": g.get("mrc_ka_endpoint", ""),
            "models": CFG["models"]}


# ------------------------------------------------------------------ inbox / documents
@app.get("/api/inbox")
def inbox():
    docs = rows_as_dicts(
        f"""SELECT doc_id,tenant,file_name,counterparty,doc_family,reporting_period,status,inbound_state,ingested_at
            FROM {F}.source_document ORDER BY ingested_at DESC""",
        ["doc_id", "tenant", "file_name", "counterparty", "doc_family", "reporting_period",
         "status", "inbound_state", "ingested_at"])
    counts = {}
    for d in docs:
        counts[d["inbound_state"]] = counts.get(d["inbound_state"], 0) + 1
    return {"documents": docs, "state_counts": counts}


@app.get("/api/document/{doc_id}")
def document(doc_id: str):
    d = rows_as_dicts(
        f"""SELECT doc_id,counterparty,doc_family,file_name,stored_path,status,inbound_state,
                   template_version,reconciliation_detail,reporting_period,ingested_at,signed_off_by
            FROM {F}.source_document WHERE doc_id=:d""",
        ["doc_id", "counterparty", "doc_family", "file_name", "stored_path", "status",
         "inbound_state", "template_version", "reconciliation_detail", "reporting_period",
         "ingested_at", "signed_off_by"], {"d": doc_id})
    if not d:
        raise HTTPException(404, "no such document")
    doc = d[0]
    doc["reconciliation_detail"] = json.loads(doc["reconciliation_detail"]) if doc["reconciliation_detail"] else {}
    lines = rows_as_dicts(
        f"""SELECT bordereau_line_id,policy_number,insured_name,line_of_business_code,
                   currency_code,gross_premium,commission_amount
            FROM {F}.premium_bordereau_line WHERE source_document_id=:d LIMIT 50""",
        ["bordereau_line_id", "policy_number", "insured_name", "line_of_business_code",
         "currency_code", "gross_premium", "commission_amount"], {"d": doc_id})
    finds = rows_as_dicts(
        f"""SELECT severity,field,message FROM {F}.reviewer_finding
            WHERE source_document_id=:d ORDER BY
            CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END""",
        ["severity", "field", "message"], {"d": doc_id})
    return {"document": doc, "lines": lines, "findings": finds}


@app.get("/api/quarantine/{doc_id}")
def quarantine(doc_id: str):
    return document(doc_id)


# ------------------------------------------------------------------ book / projection
@app.get("/api/book")
def book():
    per_ch = rows_as_dicts(
        f"""SELECT coverholder_name, count(*) AS lines, round(sum(gross_premium),2) AS gwp,
                   count(DISTINCT reporting_month) AS months
            FROM {F}.v_premium_bordereau_line_latest
            GROUP BY coverholder_name ORDER BY gwp DESC""",
        ["coverholder_name", "lines", "gwp", "months"])
    totals = q(f"SELECT count(*), round(coalesce(sum(gross_premium),0),2), count(DISTINCT coverholder_name) "
               f"FROM {F}.v_premium_bordereau_line_latest")[0]
    claims = q(f"SELECT count(*), round(coalesce(sum(incurred_amount),0),2) FROM {F}.v_claim_bordereau_line_latest")[0]
    loss = rows_as_dicts(
        f"SELECT coverholder_name,gwp,incurred,loss_ratio FROM {F}.v_loss_ratio ORDER BY loss_ratio DESC",
        ["coverholder_name", "gwp", "incurred", "loss_ratio"])
    return {"per_coverholder": per_ch, "loss_ratio": loss,
            "totals": {"lines": int(totals[0]), "gwp": float(totals[1]),
                       "coverholders": int(totals[2]),
                       "claim_lines": int(claims[0]), "incurred": float(claims[1])}}


@app.get("/api/completeness")
def completeness():
    # The "who hasn't reported" tile — a coverholder is behind if its latest reported
    # month trails the book's latest (e.g. a drifted drop stuck in quarantine).
    return {"coverholders": rows_as_dicts(
        f"""SELECT coverholder_name, months_received, last_month, latest_expected, behind
            FROM {F}.v_completeness ORDER BY behind DESC, coverholder_name""",
        ["coverholder_name", "months_received", "last_month", "latest_expected", "behind"])}


@app.get("/api/lineage/{line_id}")
def lineage(line_id: str):
    proj = rows_as_dicts(
        f"""SELECT bordereau_line_id,coverholder_name,policy_number,gross_premium,
                   reporting_month,source_document_id
            FROM {F}.premium_bordereau_line WHERE bordereau_line_id=:l""",
        ["bordereau_line_id", "coverholder_name", "policy_number", "gross_premium",
         "reporting_month", "source_document_id"], {"l": line_id})
    if not proj:
        raise HTTPException(404, "no such line")
    node = rows_as_dicts(
        f"""SELECT node_id,label,extraction_path,confidence,anchor,template_version,dictionary_version,properties
            FROM {F}.graph_nodes WHERE node_id=:l""",
        ["node_id", "label", "extraction_path", "confidence", "anchor", "template_version",
         "dictionary_version", "properties"], {"l": line_id})
    doc = document(proj[0]["source_document_id"])["document"]
    return {"projection": proj[0], "assertion": node[0] if node else None,
            "document": {"doc_id": doc["doc_id"], "file_name": doc["file_name"],
                         "stored_path": doc["stored_path"]},
            "download": uc_link("volume", CFG["volume"])}


# ------------------------------------------------------------------ templates / versions
@app.get("/api/templates")
def templates():
    return {"templates": rows_as_dicts(
        f"""SELECT counterparty,doc_family,template_version,field_count,status,created_by,created_at
            FROM {F}.v_template_latest ORDER BY counterparty, doc_family""",
        ["counterparty", "doc_family", "template_version", "field_count", "status",
         "created_by", "created_at"])}


@app.get("/api/template/history")
def template_history(counterparty: str, family: str = "premium_bordereau"):
    return {"history": rows_as_dicts(
        f"""SELECT template_version,field_map,field_count,created_by,created_at
            FROM {F}.template WHERE counterparty=:c AND doc_family=:f ORDER BY created_at""",
        ["template_version", "field_map", "field_count", "created_by", "created_at"],
        {"c": counterparty, "f": family})}


@app.get("/api/versions")
def api_versions(counterparty: str, period: str, family: str = "premium_bordereau"):
    return tl.versions(CFG, counterparty, family, period)


# ------------------------------------------------------------------ dictionary / audit / learn
@app.get("/api/dictionary")
def dictionary():
    ents = rows_as_dicts(
        f"SELECT tenant,entity_type,description,attributes FROM {F}.v_dictionary_entity_latest ORDER BY tenant,entity_type",
        ["tenant", "entity_type", "description", "attributes"])
    rels = rows_as_dicts(
        f"SELECT tenant,relationship_name,source_entity,target_entity FROM {F}.v_dictionary_relationship_latest ORDER BY tenant,relationship_name",
        ["tenant", "relationship_name", "source_entity", "target_entity"])
    return {"entities": ents, "relationships": rels}


@app.get("/api/audit")
def audit_feed(limit: int = 50):
    # LIMIT can't take a bound parameter in Databricks SQL; limit is an int from FastAPI.
    n = max(1, min(int(limit), 500))
    return {"events": rows_as_dicts(
        f"""SELECT event_type,entity_type,entity_id,detail,actor,created_at
            FROM {F}.audit_event ORDER BY created_at DESC LIMIT {n}""",
        ["event_type", "entity_type", "entity_id", "detail", "actor", "created_at"])}


LEARN_CARDS = [
    {"band": "Trust the data", "activity": "A counterparty file arrives and I need to trust it",
     "how": "Fingerprint against the template registry -> one of four states; two-path extraction (deterministic anchors + dictionary-constrained AI) reconciled field by field.",
     "see": ["template", "source_document", "fn_reconcile_status"]},
    {"band": "Trust the data", "activity": "A layout drifts, but I only want to map it once",
     "how": "Quarantine with an AI-proposed remap; accepting it appends the new label to a new, append-only template version, then re-processes the file automatically.",
     "see": ["template", "decision", "audit_event"]},
    {"band": "Trust the data", "activity": "A brand-new counterparty sends its first file",
     "how": "Schema recognition proposes a full template as mappings INTO the shared dictionary; you confirm per field; the counterparty is learned and the file re-processes.",
     "see": ["dictionary_entity", "template"]},
    {"band": "Work the book", "activity": "Turn documents into rows I can defend",
     "how": "Every assertion lands in the graph with provenance (source doc, path, confidence, anchor); typed projections are materialised from it, shaped to the canonical exchange contract.",
     "see": ["graph_nodes", "graph_edges", "premium_bordereau_line"]},
    {"band": "Work the book", "activity": "Where did this number come from?",
     "how": "Lineage walks analytic -> projection row -> graph assertion -> the located anchor (cell) -> the original file.",
     "see": ["premium_bordereau_line", "graph_nodes"]},
    {"band": "Compound the book", "activity": "Interrogate the whole book",
     "how": "Genie answers over the graph + projections; the completeness view shows who has and has not reported.",
     "see": ["v_premium_bordereau_line_latest"]},
]


@app.get("/api/eval")
def eval_results():
    latest = q(f"SELECT run_id FROM {F}.eval_result ORDER BY created_at DESC LIMIT 1")
    if not latest:
        return {"run_id": None, "overall": [], "fields": []}
    rid = latest[0][0]
    overall = rows_as_dicts(
        f"""SELECT model,correct,total,accuracy,mlflow_run_id FROM {F}.eval_result
            WHERE run_id=:r AND scope='overall' ORDER BY accuracy DESC""",
        ["model", "correct", "total", "accuracy", "mlflow_run_id"], {"r": rid})
    fields = rows_as_dicts(
        f"""SELECT field,model,accuracy FROM {F}.eval_result
            WHERE run_id=:r AND scope='field' ORDER BY field, model""",
        ["field", "model", "accuracy"], {"r": rid})
    return {"run_id": rid, "overall": overall, "fields": fields}


@app.get("/api/learn")
def learn():
    cards = []
    for c in LEARN_CARDS:
        links = []
        for name in c["see"]:
            kind = "function" if name.startswith("fn_") else "table"
            links.append({"name": name, "url": uc_link(kind, name)})
        cards.append({**c, "links": links})
    return {"cards": cards}


# ------------------------------------------------------------------ write / HITL actions
@app.post("/api/quarantine/accept")
def accept(body: dict = Body(...)):
    return tl.accept_remap(CFG, body["doc_id"], actor=body.get("actor", "reviewer"))


@app.post("/api/quarantine/reject")
def reject(body: dict = Body(...)):
    return tl.reject_doc(CFG, body["doc_id"], body.get("reason", ""), actor=body.get("actor", "reviewer"))


@app.post("/api/schema/propose")
def schema_propose(body: dict = Body(...)):
    return tl.propose_schema(CFG, body["doc_id"])


@app.post("/api/schema/confirm")
def schema_confirm(body: dict = Body(...)):
    return tl.confirm_schema(CFG, body["doc_id"], body["field_map"], actor=body.get("actor", "reviewer"))


@app.post("/api/ingest/scan")
def scan():
    return pipe.process_inbox(CFG)


# ------------------------------------------------------------------ findings / review agent
@app.get("/api/findings")
def findings(doc_id: str = ""):
    where = "WHERE source_document_id=:d" if doc_id else "WHERE status='open'"
    params = {"d": doc_id} if doc_id else None
    return {"findings": rows_as_dicts(
        f"""SELECT finding_id,source_document_id,severity,field,message,created_by,created_at
            FROM {F}.reviewer_finding {where} ORDER BY
            CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, created_at DESC""",
        ["finding_id", "source_document_id", "severity", "field", "message", "created_by", "created_at"],
        params)}


@app.post("/api/review")
def run_review(body: dict = Body(...)):
    """Advise-only extraction-review agent. Writes findings, lands nothing."""
    if body.get("doc_id"):
        return review.review_document(CFG, body["doc_id"])
    return review.review_queue(CFG)


# ------------------------------------------------------------------ Ask the gateway (Genie)
def _genie_query(space, question):
    conv = _W.genie.start_conversation_and_wait(space_id=space, content=question)
    sql_text, answer, data = None, None, None
    for att in (conv.attachments or []):
        if getattr(att, "query", None):
            sql_text = att.query.query
            answer = att.query.description
            # Prefer execute_message_attachment_query (current primitive); fall back to
            # get_message_attachment_query_result if it errors OR returns no rows.
            for fetch in (_W.genie.execute_message_attachment_query,
                          _W.genie.get_message_attachment_query_result):
                try:
                    res = fetch(space, conv.conversation_id, conv.id, att.attachment_id)
                    d = (res.statement_response.result.data_array
                         if getattr(res, "statement_response", None) and res.statement_response.result
                         else None)
                    if d:
                        data = d
                        break
                except Exception:
                    continue
        elif getattr(att, "text", None):
            answer = att.text.content
    return {"sql": sql_text, "answer": answer, "rows": data}


def _ka_query(endpoint, question):
    """Query a Knowledge Assistant serving endpoint. KA endpoints take the Responses
    format ({"input": [...]}) and reject chat-style "messages"."""
    r = _W.api_client.do("POST", f"/serving-endpoints/{endpoint}/invocations",
                         body={"input": [{"role": "user", "content": question}]})
    texts = []
    for item in (r or {}).get("output", []):
        for c in item.get("content", []) or []:
            if c.get("type") == "output_text" and c.get("text"):
                texts.append(c["text"])
    return "\n\n".join(texts) or None


@app.post("/api/ask")
def ask(body: dict = Body(...)):
    space = CFG.get("genie", {}).get("space_id", "")
    if not space:
        raise HTTPException(400, "Genie space not configured yet")
    try:
        return {"question": body["question"], **_genie_query(space, body["question"])}
    except Exception as e:
        raise HTTPException(500, f"Genie query failed: {e}")


# ------------------------------------------------------------------ MRC tenant
@app.get("/api/mrc")
def mrc_list():
    return {"mrcs": rows_as_dicts(
        f"""SELECT mrc_id,umr,policy_number,class_of_business,inception_date,expiry_date,
                   insured_name,broker_name,premium_text,headline_limit,deductible_text,
                   n_clauses,n_exclusions,n_insurers,source_document_id,
                   slip_leader,signed_lines_total,choice_of_law,checks_failed,certainty_status
            FROM {F}.v_mrc_entities_latest ORDER BY policy_number""",
        ["mrc_id", "umr", "policy_number", "class_of_business", "inception_date", "expiry_date",
         "insured_name", "broker_name", "premium_text", "headline_limit", "deductible_text",
         "n_clauses", "n_exclusions", "n_insurers", "source_document_id",
         "slip_leader", "signed_lines_total", "choice_of_law", "checks_failed", "certainty_status"])}


# Editable metric columns — an allowlist; the field name is validated against this
# fixed set before it ever reaches SQL (never interpolate a raw client field name).
MRC_EDITABLE = {"class_of_business": "str", "insured_name": "str", "broker_name": "str",
                "premium_amount": "dec", "premium_currency": "str", "limit_amount": "dec"}


@app.get("/api/mrc/metrics")
def mrc_metrics():
    """Numeric metrics for the MRC book — totals + per-class + per-contract (for the viz + edit table)."""
    contracts = rows_as_dicts(
        f"""SELECT mrc_id, policy_number, class_of_business, insured_name, broker_name,
                   premium_amount, premium_currency, limit_amount
            FROM {F}.v_mrc_entities_latest ORDER BY policy_number""",
        ["mrc_id", "policy_number", "class_of_business", "insured_name", "broker_name",
         "premium_amount", "premium_currency", "limit_amount"])
    t = q(f"""SELECT count(*), round(avg(n_clauses),1), round(avg(n_exclusions),1)
              FROM {F}.v_mrc_entities_latest""")[0]
    by_ccy = rows_as_dicts(
        f"""SELECT premium_currency AS currency, count(*) AS n,
                   round(coalesce(sum(premium_amount),0),2) AS premium,
                   round(coalesce(sum(limit_amount),0),2) AS limit_amt
            FROM {F}.v_mrc_entities_latest GROUP BY premium_currency ORDER BY premium DESC""",
        ["currency", "n", "premium", "limit_amt"])
    by_class = rows_as_dicts(
        f"""SELECT class_of_business, premium_currency AS currency,
                   round(coalesce(sum(premium_amount),0),2) AS premium,
                   round(coalesce(sum(limit_amount),0),2) AS limit_amt, count(*) AS n
            FROM {F}.v_mrc_entities_latest GROUP BY class_of_business, premium_currency
            ORDER BY premium DESC""",
        ["class_of_business", "currency", "premium", "limit_amt", "n"])
    return {"contracts": contracts, "by_class": by_class, "by_currency": by_ccy,
            "totals": {"contracts": int(t[0]), "avg_clauses": float(t[1] or 0),
                       "avg_exclusions": float(t[2] or 0)},
            "editable": list(MRC_EDITABLE.keys())}


@app.post("/api/mrc/update")
def mrc_update(body: dict = Body(...)):
    """Governed in-place correction of an extracted MRC metric. Allowlisted field,
    parameter-bound; writes an audit event + an append-only decision so it is traceable.
    (Corrects the projection; a full build would also revise the graph assertion + provenance.)"""
    mrc_id, field, value = body.get("mrc_id"), body.get("field"), body.get("value")
    if field not in MRC_EDITABLE:
        raise HTTPException(400, f"field '{field}' is not editable")
    kind = MRC_EDITABLE[field]
    prior = q(f"SELECT {field}, source_document_id FROM {F}.mrc_entities WHERE mrc_id=:m", {"m": mrc_id})
    if not prior:
        raise HTTPException(404, "no such MRC")
    old_val, sdoc = prior[0][0], prior[0][1]
    set_expr = f"{field}=cast(:v as decimal(18,2))" if kind == "dec" else f"{field}=:v"
    q(f"UPDATE {F}.mrc_entities SET {set_expr} WHERE mrc_id=:m", {"v": value, "m": mrc_id})
    actor = body.get("actor", "reviewer")
    pipe.audit(CFG, "metric_corrected", "mrc_entities", mrc_id,
               detail=f"{field}: '{old_val}' -> '{value}'", actor=actor)
    tl.decision(CFG, "metric_correction", sdoc, "mrc-v1",
                {"mrc_id": mrc_id, "field": field, "old": str(old_val), "new": str(value)},
                reason="HITL metric correction", actor=actor)
    return {"ok": True, "mrc_id": mrc_id, "field": field, "old": str(old_val), "new": str(value)}


@app.get("/api/mrc/inbox")
def mrc_inbox():
    """MRC documents with their flow state: awaiting recognition / recognised / HITL."""
    docs = rows_as_dicts(
        f"""SELECT doc_id,file_name,counterparty,status,inbound_state,reporting_period,ingested_at
            FROM {F}.source_document WHERE tenant='mrc' ORDER BY ingested_at""",
        ["doc_id", "file_name", "counterparty", "status", "inbound_state", "reporting_period", "ingested_at"])
    counts = {}
    for d in docs:
        counts[d["inbound_state"]] = counts.get(d["inbound_state"], 0) + 1
    return {"documents": docs, "state_counts": counts, "schema_registered": mrc.schema_registered(CFG),
            "job": {"running": _MRC_JOB["running"], "kind": _MRC_JOB["kind"]}}


@app.get("/api/mrc/propose")
def mrc_propose():
    """Recognition checklist for the first awaiting MRC — expected ACORD data points, all/some."""
    return mrc.propose_first(CFG)


_MRC_JOB = {"running": False, "result": None, "kind": None}


@app.post("/api/mrc/confirm")
def mrc_confirm(body: dict = Body(...)):
    """HITL confirm: record the schema in the repository immediately, then process the
    awaiting contracts in the background. The Inbox shows each one flip to recognised."""
    import threading
    actor = body.get("actor", "reviewer")
    first = q(f"""SELECT doc_id FROM {F}.source_document WHERE tenant='mrc'
                  AND status='awaiting_recognition' ORDER BY ingested_at LIMIT 1""")
    if _MRC_JOB["running"] and _MRC_JOB["kind"] == "reset":
        raise HTTPException(409, "The demo is being reset — try again when it finishes")
    reg = mrc.register_schema(CFG, actor=actor, from_doc=first[0][0] if first else None)
    if not _MRC_JOB["running"]:
        def run():
            _MRC_JOB.update(running=True, result=None, kind="processing")
            try:
                _MRC_JOB["result"] = mrc.rescan(CFG, actor="mrc-pipeline")
            finally:
                _MRC_JOB["running"] = False
        threading.Thread(target=run, daemon=True).start()
    return {"schema": reg, "processing": True}


@app.get("/api/mrc/progress")
def mrc_progress():
    states = {r[0]: int(r[1]) for r in q(
        f"SELECT inbound_state, count(*) FROM {F}.source_document WHERE tenant='mrc' GROUP BY inbound_state")}
    return {"running": _MRC_JOB["running"], "kind": _MRC_JOB["kind"], "result": _MRC_JOB["result"], "states": states}


@app.post("/api/mrc/reset")
def mrc_reset_demo(body: dict = Body(default={})):
    """Return the MRC flow to its demo starting point (the in-app version of
    tools/mrc_reset.py): clears the recorded schema, processed contracts, checks, graph rows,
    decisions and this flow's audit trail, then re-stages the five contracts and the cover
    note. Runs in the background (~1 min); refuses while another MRC job is running.
    The PDFs are not regenerated here, so the Knowledge Assistant index stays valid."""
    import threading
    if _MRC_JOB["running"]:
        raise HTTPException(409, "Contracts are still being processed — try again when it finishes")
    from tools.mrc_reset import reset as _reset

    def run():
        _MRC_JOB.update(running=True, result=None, kind="reset")
        try:
            states = _reset(CFG, regenerate=False)
            _MRC_JOB["result"] = {k: int(v) for k, v in states}
        finally:
            _MRC_JOB["running"] = False
    threading.Thread(target=run, daemon=True).start()
    return {"resetting": True}


@app.post("/api/mrc/review")
def mrc_review(body: dict = Body(...)):
    """HITL decision on a document that did not match the MRC schema (reject / return to broker)."""
    try:
        return mrc.review_unrecognised(CFG, body["doc_id"], body.get("action", "reject"),
                                       reason=body.get("reason", ""), actor=body.get("actor", "reviewer"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/mrc/certainty")
def mrc_certainty():
    """Contract-certainty results — every check, every contract."""
    rows = rows_as_dicts(
        f"""SELECT c.mrc_id, e.umr, e.insured_name, e.class_of_business, c.check_id, c.label,
                   c.status, c.detail
            FROM {F}.v_mrc_certainty_latest c JOIN {F}.v_mrc_entities_latest e ON c.mrc_id = e.mrc_id
            ORDER BY e.umr, c.check_id""",
        ["mrc_id", "umr", "insured_name", "class_of_business", "check_id", "label", "status", "detail"])
    checks = [c["label"] for c in mrc._tenant(CFG).get("certainty_checks", [])]
    return {"rows": rows, "checks": checks,
            "failed": sum(1 for r in rows if r["status"] == "fail"), "total": len(rows)}


@app.get("/api/mrc/cdr")
def mrc_cdr():
    """Indicative Lloyd's Core Data Record view: for each CDR-aligned field, how many of the
    landed contracts supplied it, and from which MRC section + ACORD binding."""
    rows = rows_as_dicts(
        f"""SELECT cdr_field, label, acord_binding, section,
                   count(*) AS contracts,
                   sum(CASE WHEN status='identified' THEN 1 ELSE 0 END) AS supplied
            FROM {F}.v_mrc_extraction_latest WHERE cdr_field IS NOT NULL
            GROUP BY cdr_field, label, acord_binding, section ORDER BY section, label""",
        ["cdr_field", "label", "acord_binding", "section", "contracts", "supplied"])
    n = q(f"SELECT count(*) FROM {F}.v_mrc_entities_latest")[0][0]
    total = sum(int(r["contracts"]) for r in rows)
    supplied = sum(int(r["supplied"]) for r in rows)
    return {"fields": rows, "contracts": int(n), "fields_per_contract": len(rows),
            "completeness_pct": round(100 * supplied / total) if total else 0,
            "note": "Indicative crosswalk to the Lloyd's Core Data Record for discussion — field names are paraphrased, not the published specification."}


@app.get("/api/mrc/lineage")
def mrc_lineage(mrc_id: str):
    """Every extracted value for one contract with the source line it came from."""
    head = rows_as_dicts(
        f"""SELECT e.mrc_id, e.umr, e.insured_name, d.file_name, d.stored_path, d.doc_id
            FROM {F}.v_mrc_entities_latest e JOIN {F}.source_document d ON e.source_document_id = d.doc_id
            WHERE e.mrc_id=:m""", ["mrc_id", "umr", "insured_name", "file_name", "stored_path", "doc_id"],
        {"m": mrc_id})
    if not head:
        raise HTTPException(404, "no such MRC")
    pts = rows_as_dicts(
        f"""SELECT label, acord_binding, cdr_field, section, value, source_quote, status, confidence
            FROM {F}.v_mrc_extraction_latest WHERE mrc_id=:m ORDER BY section, label""",
        ["label", "acord_binding", "cdr_field", "section", "value", "source_quote", "status", "confidence"],
        {"m": mrc_id})
    return {"contract": head[0], "points": pts, "download": uc_link("volume", CFG["volume"])}


@app.get("/api/mrc/audit")
def mrc_audit():
    """The governance trail for the MRC flow: recognition, schema, ingest, checks, corrections, reviews."""
    return {"events": rows_as_dicts(
        f"""SELECT a.created_at, a.event_type, a.actor, a.detail, coalesce(d.file_name, a.entity_id) AS subject
            FROM {F}.audit_event a LEFT JOIN {F}.source_document d ON a.entity_id = d.doc_id
            WHERE d.tenant='mrc' OR a.entity_type IN ('template','mrc_entities')
                  AND (a.entity_id LIKE '%mrc%' OR a.entity_id LIKE 'policy_%')
            ORDER BY a.created_at DESC LIMIT 200""",
        ["created_at", "event_type", "actor", "detail", "subject"])}


@app.get("/api/mrc/schemas")
def mrc_schemas():
    """The registered MRC schema(s) in the repository."""
    rows = rows_as_dicts(
        f"""SELECT counterparty,doc_family,template_version,field_count,field_map,created_by,created_at
            FROM {F}.v_template_latest WHERE doc_family='mrc' ORDER BY created_at DESC""",
        ["counterparty", "doc_family", "template_version", "field_count", "field_map", "created_by", "created_at"])
    return {"schemas": rows}


@app.get("/api/mrc/semantics")
def mrc_semantics():
    """The ACORD semantics space: expected data points, their ACORD binding, and whether
    each entity is recognised (present in the shared graph for MRC)."""
    tcfg = mrc._tenant(CFG)
    dps = tcfg["expected_data_points"]
    hits = {r[0]: int(r[1]) for r in q(
        f"""SELECT data_point, sum(CASE WHEN status='identified' THEN 1 ELSE 0 END)
            FROM {F}.v_mrc_extraction_latest GROUP BY data_point""")}
    rows = []
    for dp in dps:
        n = hits.get(dp["key"], 0)
        rows.append({"data_point": dp["label"], "entity": dp["entity"], "attribute": dp["attribute"],
                     "cdr": dp.get("cdr"), "core": bool(dp.get("core")), "section": dp["section"],
                     "recognised": n > 0, "instances": n})
    covered = sum(1 for r in rows if r["recognised"])
    return {"data_points": rows, "required": len(rows), "recognised": covered,
            "coverage_pct": round(100 * covered / len(rows)) if rows else 0,
            "schema_registered": mrc.schema_registered(CFG)}


@app.post("/api/mrc/ask")
def mrc_ask(body: dict = Body(...)):
    """Dual retrieval: Genie over the MRC graph/projection + the Knowledge Assistant over the PDFs."""
    q = body["question"]
    g = CFG.get("genie", {})
    out = {"question": q, "genie": None, "ka": None}
    space = g.get("mrc_space_id", "")
    if space:
        try:
            out["genie"] = _genie_query(space, q)
        except Exception as e:
            out["genie"] = {"error": str(e)}
    ka = g.get("mrc_ka_endpoint", "")
    if ka:
        try:
            out["ka"] = {"answer": _ka_query(ka, q)}
        except Exception as e:
            out["ka"] = {"error": str(e)}
    if not space and not ka:
        raise HTTPException(400, "MRC ask-surface not configured yet")
    return out
