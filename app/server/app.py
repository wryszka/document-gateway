"""Document Gateway — thin FastAPI backend (the control surface over the real objects).

Every endpoint reads/writes a real governed UC object or calls a governed function/action.
No business math here (DECISIONS D6) — reconciliation is fn_reconcile_status, the trust-loop
acts are jobs/trust_loop (the same functions the MCP tools call). Serves one self-contained
SPA. Runs in Databricks Apps on the app service principal.
"""
from __future__ import annotations

import threading
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
from jobs import mrc_schemas as ms  # noqa: E402
from jobs import mrc_agents as ma  # noqa: E402
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
                   slip_leader,signed_lines_total,choice_of_law,checks_failed,certainty_status,schema_name,schema_version
            FROM {F}.v_mrc_entities_latest ORDER BY schema_name, policy_number""",
        ["mrc_id", "umr", "policy_number", "class_of_business", "inception_date", "expiry_date",
         "insured_name", "broker_name", "premium_text", "headline_limit", "deductible_text",
         "n_clauses", "n_exclusions", "n_insurers", "source_document_id",
         "slip_leader", "signed_lines_total", "choice_of_law", "checks_failed", "certainty_status",
         "schema_name", "schema_version"])}


@app.get("/api/mrc/contracts")
def mrc_contracts():
    """Ingested contracts for the searchable list (incl. the syndicates on each)."""
    rows = rows_as_dicts(
        f"""SELECT e.mrc_id, e.umr, e.insured_name, e.class_of_business, e.broker_name, e.slip_leader,
                   e.premium_currency, e.premium_amount, e.signed_lines_total, e.checks_failed, e.certainty_status,
                   e.schema_name, e.schema_version, e.inception_date, e.expiry_date,
                   (SELECT max(x.source_quote) FROM {F}.v_mrc_extraction_latest x
                     WHERE x.mrc_id = e.mrc_id AND x.data_point = 'insurers') AS syndicates
            FROM {F}.v_mrc_entities_latest e ORDER BY e.umr""",
        ["mrc_id", "umr", "insured_name", "class_of_business", "broker_name", "slip_leader", "premium_currency",
         "premium_amount", "signed_lines_total", "checks_failed", "certainty_status", "schema_name", "schema_version",
         "inception_date", "expiry_date", "syndicates"])
    return {"contracts": rows}


@app.get("/api/mrc/contract")
def mrc_contract(mrc_id: str):
    """Everything about one ingested contract: headline facts, certainty checks, every
    value with its source line and CDR field, the source document, and its history."""
    head = rows_as_dicts(
        f"""SELECT e.mrc_id, e.umr, e.policy_number, e.class_of_business, e.inception_date, e.expiry_date, e.insured_name, e.broker_name, e.premium_text, e.headline_limit, e.deductible_text, e.premium_amount, e.premium_currency, e.limit_amount, e.n_clauses, e.n_exclusions, e.n_insurers, e.choice_of_law, e.situation, e.slip_leader, e.signed_lines_total, e.brokerage_pct, e.checks_failed, e.certainty_status, e.schema_name, e.schema_version, e.source_document_id, d.file_name, d.doc_id, d.ingested_at, d.signed_off_by, d.signed_off_at
            FROM {F}.v_mrc_entities_latest e JOIN {F}.source_document d ON e.source_document_id = d.doc_id
            WHERE e.mrc_id = :m""",
        ["mrc_id", "umr", "policy_number", "class_of_business", "inception_date", "expiry_date", "insured_name",
         "broker_name", "premium_text", "headline_limit", "deductible_text", "premium_amount", "premium_currency",
         "limit_amount", "n_clauses", "n_exclusions", "n_insurers", "choice_of_law", "situation", "slip_leader",
         "signed_lines_total", "brokerage_pct", "checks_failed", "certainty_status", "schema_name", "schema_version",
         "source_document_id", "file_name", "doc_id", "ingested_at", "signed_off_by", "signed_off_at"], {"m": mrc_id})
    if not head:
        raise HTTPException(404, "no such contract")
    h = head[0]
    checks = rows_as_dicts(
        f"SELECT check_id, label, status, detail FROM {F}.v_mrc_certainty_latest WHERE mrc_id=:m ORDER BY status, label",
        ["check_id", "label", "status", "detail"], {"m": mrc_id})
    values = rows_as_dicts(
        f"""SELECT label, acord_binding, cdr_field, section, value, source_quote, status
            FROM {F}.v_mrc_extraction_latest WHERE mrc_id=:m ORDER BY section, label""",
        ["label", "acord_binding", "cdr_field", "section", "value", "source_quote", "status"], {"m": mrc_id})
    history = rows_as_dicts(
        f"""SELECT created_at, event_type, actor, detail FROM {F}.audit_event
            WHERE entity_id IN (:d, :m) ORDER BY created_at""",
        ["created_at", "event_type", "actor", "detail"], {"d": h["doc_id"], "m": mrc_id})
    return {"contract": h, "checks": checks, "values": values, "history": history,
            "pdf": f"/api/mrc/pdf/{h['doc_id']}"}


@app.post("/api/mrc/agent/intake_review")
def mrc_agent_intake(body: dict = Body(default={}), mode: str = "live"):
    """Intake review agent: reads the computed intake facts and advises. Logged; never acts."""
    try:
        return ma.intake_review(CFG, actor=body.get("actor", "presenter"), cache=_AI_CACHE if mode == "cached" else None)
    except Exception as e:
        raise HTTPException(500, f"Agent unavailable: {e}")


@app.post("/api/mrc/agent/schema_review")
def mrc_agent_schema(body: dict = Body(...), mode: str = "live"):
    """Schema review agent: critiques a proposed schema or amendment before a person records it."""
    kind = body.get("kind")
    if kind not in ("recognition", "changes"):
        raise HTTPException(400, "kind must be recognition or changes")
    try:
        return ma.schema_review(CFG, kind, body.get("payload") or {}, actor=body.get("actor", "presenter"),
                                cache=_AI_CACHE if mode == "cached" else None)
    except Exception as e:
        raise HTTPException(500, f"Agent unavailable: {e}")


@app.get("/api/mrc/governance")
def mrc_governance():
    """The questions a market regulator or auditor asks, answered from the data."""
    versions = rows_as_dicts(
        f"""SELECT t.counterparty AS schema_name, t.template_version AS version, t.created_by, t.created_at,
                   t.field_count, n.description, n.change_note
            FROM {F}.template t LEFT JOIN {F}.mrc_schema_note n
              ON n.schema_name = t.counterparty AND n.schema_version = t.template_version
            WHERE t.doc_family = 'mrc' ORDER BY t.created_at""",
        ["schema_name", "version", "created_by", "created_at", "field_count", "description", "change_note"])
    decisions = rows_as_dicts(
        f"""SELECT dc.created_at, dc.decision_type, dc.actor, dc.reason, dc.template_version, d.file_name
            FROM {F}.decision dc LEFT JOIN {F}.source_document d ON dc.source_document_id = d.doc_id
            WHERE dc.tenant = 'mrc' ORDER BY dc.created_at""",
        ["created_at", "decision_type", "actor", "reason", "version", "file_name"])
    agents = rows_as_dicts(
        f"""SELECT created_at, agent, subject, requested_by, model, substr(output, 1, 400) AS excerpt
            FROM {F}.mrc_agent_note ORDER BY created_at DESC""",
        ["created_at", "agent", "subject", "requested_by", "model", "excerpt"])
    auto = rows_as_dicts(
        f"""SELECT d.file_name, a.created_at, a.detail FROM {F}.audit_event a
            JOIN {F}.source_document d ON a.entity_id = d.doc_id
            WHERE a.event_type = 'auto_ingested' ORDER BY d.file_name""", ["file_name", "created_at", "detail"])
    fails = rows_as_dicts(
        f"""SELECT e.umr, e.insured_name, c.label, c.detail FROM {F}.v_mrc_certainty_latest c
            JOIN {F}.v_mrc_entities_latest e ON c.mrc_id = e.mrc_id WHERE c.status = 'fail' ORDER BY e.umr""",
        ["umr", "insured_name", "label", "detail"])
    grants = []
    try:
        grants = [{"principal": r[0], "privilege": r[1]} for r in q(f"SHOW GRANTS ON SCHEMA {F}")]
    except Exception:
        pass
    who = lambda v: f"{v['schema_name']} {v['version']} — recorded by {v['created_by']} on {str(v['created_at'])[:16].replace('T', ' ')}"
    questions = [
        {"q": "Who approved each schema, and when?",
         "a": f"{len(versions)} schema versions are on record, each recorded by a named person with a timestamp and a note.",
         "evidence": [who(v) + (f" — “{v['change_note']}”" if v.get("change_note") else "") for v in versions]},
        {"q": "Which contracts were loaded with no person involved?",
         "a": f"{len(auto)} contracts matched a recorded schema with every expected field and were loaded automatically.",
         "evidence": [f"{a['file_name']} — {a['detail']}" for a in auto]},
        {"q": "What did people decide, and why?",
         "a": f"{len(decisions)} human decisions are recorded (schema confirmations, accepted changes, returns, corrections), each with who, when and the reason.",
         "evidence": [f"{str(d['created_at'])[:16].replace('T', ' ')} · {d['decision_type']} · {d['actor']} · {d['file_name'] or ''} — {d['reason'] or ''}" for d in decisions]},
        {"q": "What did the AI do — and did it decide anything?",
         "a": "No. The model only proposed ACORD mappings for an unfamiliar schema and builds the wider entity graph; a person "
              "confirmed every schema. The review agents advise — they cannot record a schema or load a contract. "
              f"{len(agents)} agent reviews are logged with the facts they were given.",
         "evidence": [f"{str(a['created_at'])[:16].replace('T', ' ')} · {a['agent']} · {a['subject']} · asked by {a['requested_by']}" for a in agents]},
        {"q": "Which contracts fail a market rule?",
         "a": f"{len(fails)} certainty check failure(s) across the book.",
         "evidence": [f"{f['umr']} {f['insured_name']} — {f['label']}: {f['detail']}" for f in fails]},
        {"q": "Where did a number come from?",
         "a": "Every value is stored with the MRC section and the exact source line it was read from, and the original PDF is "
              "kept in a governed volume. Open any contract → Values & lineage.", "evidence": []},
        {"q": "Can a schema be changed without anyone knowing?",
         "a": "No. Schema versions are append-only: a change records a new version with who, when and why; earlier versions stay readable.",
         "evidence": [who(v) for v in versions if v["version"] != "v1"]},
        {"q": "Who can see and change this data?",
         "a": "Access is governed in Unity Catalog. Current grants on the schema:",
         "evidence": [f"{g['principal']} — {g['privilege']}" for g in grants[:20]]},
    ]
    return {"questions": questions, "versions": versions, "decisions": decisions, "agents": agents}


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
            FROM {F}.v_mrc_entities_latest WHERE coalesce(schema_name, :om) = :om ORDER BY policy_number""",
        ["mrc_id", "policy_number", "class_of_business", "insured_name", "broker_name",
         "premium_amount", "premium_currency", "limit_amount"], {"om": ms.OPEN_MARKET})
    t = q(f"""SELECT count(*), round(avg(n_clauses),1), round(avg(n_exclusions),1)
              FROM {F}.v_mrc_entities_latest WHERE coalesce(schema_name, :om) = :om""", {"om": ms.OPEN_MARKET})[0]
    by_ccy = rows_as_dicts(
        f"""SELECT premium_currency AS currency, count(*) AS n,
                   round(coalesce(sum(premium_amount),0),2) AS premium,
                   round(coalesce(sum(limit_amount),0),2) AS limit_amt
            FROM {F}.v_mrc_entities_latest WHERE coalesce(schema_name, :om) = :om
            GROUP BY premium_currency ORDER BY premium DESC""",
        ["currency", "n", "premium", "limit_amt"], {"om": ms.OPEN_MARKET})
    by_class = rows_as_dicts(
        f"""SELECT class_of_business, premium_currency AS currency,
                   round(coalesce(sum(premium_amount),0),2) AS premium,
                   round(coalesce(sum(limit_amount),0),2) AS limit_amt, count(*) AS n
            FROM {F}.v_mrc_entities_latest WHERE coalesce(schema_name, :om) = :om
            GROUP BY class_of_business, premium_currency ORDER BY premium DESC""",
        ["class_of_business", "currency", "premium", "limit_amt", "n"], {"om": ms.OPEN_MARKET})
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
        f"""SELECT doc_id,file_name,counterparty,status,inbound_state,reporting_period,ingested_at,template_version,
                   get_json_object(reconciliation_detail, '$.schema') AS flagged_schema
            FROM {F}.source_document WHERE tenant='mrc' ORDER BY file_name""",
        ["doc_id", "file_name", "counterparty", "status", "inbound_state", "reporting_period", "ingested_at",
         "template_version", "flagged_schema"])
    counts = {}
    for d in docs:
        counts[d["inbound_state"]] = counts.get(d["inbound_state"], 0) + 1
    n_schemas = q(f"SELECT count(DISTINCT counterparty) FROM {F}.template WHERE doc_family='mrc'")[0][0]
    return {"documents": docs, "state_counts": counts, "schema_registered": mrc.schema_registered(CFG),
            "schemas": int(n_schemas),
            "job": {"running": _MRC_JOB["running"], "kind": _MRC_JOB["kind"], "error": _MRC_JOB["error"]}}


@app.get("/api/mrc/pdf/{doc_id}")
def mrc_pdf(doc_id: str):
    """Serve the original PDF for a tracked MRC document, inline, so the browser's own
    viewer shows it. The path comes from source_document (never from the request), so
    only documents the gateway has registered can be opened."""
    r = q(f"SELECT stored_path, file_name FROM {F}.source_document WHERE doc_id=:d AND tenant='mrc'",
          {"d": doc_id})
    if not r:
        raise HTTPException(404, "no such document")
    path, fname = r[0]
    data = _W.files.download(path).contents.read()
    safe = "".join(ch for ch in fname if ch.isalnum() or ch in "._-") or "document.pdf"
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{safe}"',
                             "Cache-Control": "no-store"})


_MRC_JOB = {"running": False, "result": None, "kind": None, "error": None}
_MRC_JOB_LOCK = threading.Lock()


def _start_job(kind, fn):
    """Run one MRC action in the background. Only one runs at a time (intake, recognise,
    accept-changes and reset can never overlap)."""
    with _MRC_JOB_LOCK:  # check-and-set atomically so two clicks can't start two jobs
        if _MRC_JOB["running"]:
            raise HTTPException(409, "Another step is still running — try again when it finishes")
        _MRC_JOB.update(running=True, result=None, kind=kind, error=None)

    def run():
        try:
            _MRC_JOB["result"] = fn()
        except Exception as e:  # surfaced on the progress endpoint
            _MRC_JOB["error"] = str(e)[:1000]
        finally:
            _MRC_JOB["running"] = False
    threading.Thread(target=run, daemon=True).start()
    return {"started": kind}


@app.post("/api/mrc/intake")
def mrc_intake(body: dict = Body(default={})):
    """Read and route every received document (in production a file-arrival trigger does this)."""
    return _start_job("intake", lambda: ms.intake(CFG))


@app.get("/api/mrc/propose")
def mrc_propose(doc_id: str = ""):
    """Schema recognition: a proposed schema for a document no registered schema matches.
    Without doc_id: the documents waiting for recognition."""
    if not doc_id:
        rows = rows_as_dicts(
            f"""SELECT doc_id, file_name FROM {F}.source_document
                WHERE tenant='mrc' AND inbound_state='new_schema' ORDER BY file_name""", ["doc_id", "file_name"])
        return {"doc_id": None, "waiting": rows}
    try:
        return ms.propose(CFG, doc_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/mrc/confirm")
def mrc_confirm(body: dict = Body(...)):
    """A person confirmed a proposed schema: record it (v1) and ingest the document."""
    doc_id, name, fields = body.get("doc_id"), (body.get("name") or "").strip(), body.get("fields") or []
    if not doc_id or not name:
        raise HTTPException(400, "doc_id and a schema name are required")
    st = q(f"SELECT inbound_state FROM {F}.source_document WHERE tenant='mrc' AND doc_id=:d", {"d": doc_id})
    if not st or st[0][0] != "new_schema":
        raise HTTPException(400, "This document is not waiting for schema recognition")
    if not any(f.get("include") and f.get("binding") for f in fields):
        raise HTTPException(400, "Select at least one field")
    actor, description = body.get("actor", "reviewer"), body.get("description")
    return _start_job("recognise", lambda: ms.confirm_new_schema(CFG, doc_id, name, fields, actor=actor,
                                                                   description=description))


@app.get("/api/mrc/changes")
def mrc_changes(doc_id: str):
    """What changed against the registered schema for a flagged document."""
    try:
        return ms.changes(CFG, doc_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/mrc/accept_changes")
def mrc_accept_changes(body: dict = Body(...)):
    """Accept a changed layout: record the next schema version (learned labels) and ingest."""
    doc_id = body.get("doc_id")
    st = q(f"SELECT inbound_state FROM {F}.source_document WHERE tenant='mrc' AND doc_id=:d", {"d": doc_id})
    if not st or st[0][0] != "schema_changed":
        raise HTTPException(400, "This document is not flagged as a changed layout")
    actor, decisions, note = body.get("actor", "reviewer"), body.get("decisions") or {}, body.get("change_note")
    for k, dsc in decisions.items():  # validate the person's choices before starting
        if dsc.get("action") not in ("rename", "map", "gap"):
            raise HTTPException(400, f"unknown decision for {k}")
        if dsc.get("action") == "map" and not (dsc.get("label") or "").strip():
            raise HTTPException(400, f"choose a document field to map {k} to")
    return _start_job("accept", lambda: ms.accept_changes(CFG, doc_id, actor=actor, decisions=decisions,
                                                            change_note=note))


@app.get("/api/mrc/progress")
def mrc_progress():
    states = {r[0]: int(r[1]) for r in q(
        f"SELECT inbound_state, count(*) FROM {F}.source_document WHERE tenant='mrc' GROUP BY inbound_state")}
    return {"running": _MRC_JOB["running"], "kind": _MRC_JOB["kind"], "result": _MRC_JOB["result"],
            "error": _MRC_JOB["error"], "states": states}


@app.post("/api/mrc/reset")
def mrc_reset_demo(body: dict = Body(default={})):
    """Return the MRC flow to its demo starting point: the open-market schema recorded (v1)
    and all eight documents received, not yet read. PDFs are not regenerated here, so the
    Knowledge Assistant index stays valid."""
    from tools.mrc_reset import reset as _reset
    return _start_job("reset", lambda: {k: int(v) for k, v in _reset(CFG, regenerate=False)})


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
    return {"contract": head[0], "points": pts, "download": uc_link("volume", CFG["volume"]),
            "pdf": f"/api/mrc/pdf/{head[0]['doc_id']}"}


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
    """The schema repository: every recorded MRC schema with its full version history."""
    rows = rows_as_dicts(
        f"""SELECT counterparty, template_version, field_count, field_map, expected_anchors, created_by, created_at
            FROM {F}.template WHERE doc_family='mrc' ORDER BY counterparty, created_at DESC""",
        ["name", "version", "field_count", "field_map", "fingerprint", "created_by", "created_at"])
    used = {r[0]: int(r[1]) for r in q(
        f"SELECT schema_name, count(*) FROM {F}.v_mrc_entities_latest GROUP BY schema_name")}
    notes = {(n[0], n[1]): {"description": n[2], "change_note": n[3]} for n in q(
        f"SELECT schema_name, schema_version, description, change_note FROM {F}.mrc_schema_note")}
    out = {}
    for r in rows:
        r.update(notes.get((r["name"], r["version"]), {"description": None, "change_note": None}))
        fm = json.loads(r["field_map"] or "{}")
        r["points"] = [{"key": k, "label": v.get("display") or v.get("label"), "source_label": v.get("label"),
                        "learned_labels": v.get("labels", []), "acord": f"{v.get('entity')}.{v.get('attribute')}",
                        "cdr": v.get("cdr"), "section": v.get("section"), "core": v.get("core"),
                        "note": v.get("description")} for k, v in fm.items()]
        r["fingerprint"] = json.loads(r["fingerprint"] or "{}")
        r.pop("field_map")
        out.setdefault(r["name"], {"name": r["name"], "versions": [], "contracts": used.get(r["name"], 0)})["versions"].append(r)
    return {"schemas": list(out.values())}


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


# CACHED mode (the yellow pill): a model answer already given is replayed instantly so no
# beat stalls on a model; LIVE always calls the model. In-memory, so it survives a demo reset
# but not a redeploy — rehearse once after the last deploy.
_AI_CACHE: dict = {}


@app.post("/api/mrc/ask")
def mrc_ask(body: dict = Body(...), mode: str = "live"):
    """Dual retrieval: Genie over the MRC graph/projection + the Knowledge Assistant over the PDFs."""
    q = body["question"]
    key = ("ask", q.strip().lower())
    if mode == "cached" and key in _AI_CACHE:
        return {**_AI_CACHE[key], "cached": True}
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
    if not (out["genie"] or {}).get("error") and not (out["ka"] or {}).get("error"):
        _AI_CACHE[key] = out
    return out
