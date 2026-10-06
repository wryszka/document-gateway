"""MRC (prose) flow — recognise -> register -> straight-through -> HITL.

The rules this flow embodies:
  1. Expected ACORD data points are declared in tenants/mrc/tenant.json.
  2. `recognise()` reports, per expected data point, whether it was identified (value +
     confidence + located section), against the parsed document (ai_parse_document + the
     deterministic MRC section anchors).
  3. On HITL confirmation, `register_schema()` records ONE reusable schema
     "Lloyd's MRC (ACORD)" in the template registry (doc_family='mrc') — the schema repository.
  4. Once registered, subsequent MRCs are recognised as that schema and flow straight through.
  5. Recognised (conforming) -> ingest -> analytics. Not recognised -> HITL (quarantine).
Everything lands in the SHARED graph_nodes/graph_edges + the mrc_entities projection.

Run:  uv run --with databricks-sdk python jobs/mrc_pipeline.py            # stage inbox
      uv run --with databricks-sdk python jobs/mrc_pipeline.py --rescan  # recognise + ingest
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import load_config, load_tenant, sql, insert_rows, client  # noqa: E402
from jobs.ingest_pipeline import audit, NODE_COLS, EDGE_COLS  # noqa: E402


def _parse_money(text):
    """Deterministically parse (amount, currency) from a prose money string, e.g.
    'GBP 1,875,000 annual, payable quarterly' -> (1875000.0, 'GBP'). Returns
    (None, None) if nothing parseable — never guesses. The prose stays as provenance."""
    if not text:
        return (None, None)
    m = re.search(r"\b([A-Z]{3})\s*([\d][\d,]*(?:\.\d+)?)", str(text))
    if not m:
        return (None, None)
    try:
        return (round(float(m.group(2).replace(",", "")), 2), m.group(1))
    except ValueError:
        return (None, None)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_NAME = "Lloyd's MRC (ACORD)"


def _tenant(cfg):
    return load_tenant(cfg, "mrc")


def _node(nid, label, props, doc_id, path, anchor, conf=1.0):
    return {"node_id": nid, "label": label, "properties": json.dumps(props, default=str),
            "source_document_id": doc_id, "extraction_path": path, "confidence": conf,
            "template_version": "mrc-v1", "dictionary_version": "v1",
            "anchor": json.dumps(anchor), "tenant": "mrc"}


def _edge(src, tgt, rel, doc_id, path, conf=1.0):
    return {"edge_id": f"E-{uuid.uuid4().hex[:10]}", "source_id": src, "target_id": tgt,
            "relationship_type": rel, "source_document_id": doc_id, "extraction_path": path,
            "confidence": conf, "template_version": "mrc-v1", "dictionary_version": "v1",
            "anchor": None, "tenant": "mrc"}


# ---------------------------------------------------------------- parse
def parse_document(cfg, path):
    """ai_parse_document -> flat text (platform-native). Path is a trusted volume path."""
    q = (f"SELECT cast(ai_parse_document(content) AS STRING) AS parsed "
         f"FROM read_files('{path}', format => 'binaryFile')")
    r = sql(q, cfg=cfg)
    if not r or not r[0][0]:
        return ""
    try:
        pj = json.loads(r[0][0])
        doc = pj.get("document", pj)
        elements = doc.get("elements") or doc.get("pages") or []
        text = "\n".join(e.get("content", "") for e in elements if isinstance(e, dict) and e.get("content"))
        return text or r[0][0]
    except Exception:
        return r[0][0]


HEADINGS = ["MARKET REFORM CONTRACT", "RISK DETAILS", "INFORMATION", "SECURITY DETAILS",
            "SUBSCRIPTION AGREEMENT", "FISCAL AND REGULATORY", "BROKER REMUNERATION AND DEDUCTIONS"]
SECTION_OF = {"MARKET REFORM CONTRACT": "Contract header"}


def _sections(text):
    """Split the parsed text on the MRC v3 section headings (case-sensitive, in order)."""
    pos = []
    for h in HEADINGS:
        m = re.search(rf"(?m)^\s*{re.escape(h)}\s*$", text) or re.search(re.escape(h), text)
        if m:
            pos.append((m.start(), h))
    pos.sort()
    out = {}
    for i, (start, h) in enumerate(pos):
        end = pos[i + 1][0] if i + 1 < len(pos) else len(text)
        out[SECTION_OF.get(h, h)] = text[start:end]
    return out


def _field(sec, label):
    """Value + the full source line for 'Label: value' inside a section."""
    # The PDF parser may render an apostrophe as a typographic one; accept either.
    pat = re.escape(label).replace("'", "['\u2019`]?")
    m = re.search(rf"{pat}\s*(.+)", sec or "")
    if not m:
        return None, None
    line = m.group(0).strip()
    return m.group(1).strip(), line


def _list_after(sec, label, stops):
    """'- item' lines after `label` up to the next stop label."""
    if not sec or label not in sec:
        return [], None
    tail = sec.split(label, 1)[1]
    for st in stops:
        if st in tail:
            tail = tail.split(st, 1)[0]
    items = [ln.strip()[1:].strip() for ln in tail.splitlines() if ln.strip().startswith("-")]
    return items, (label + " " + "; ".join(items))[:240] if items else None


def det_parse(text):
    """Deterministic extraction against the MRC v3 sections. Returns (values, quotes) where
    quotes[key] = (section, source line) — the lineage for every extracted value."""
    secs = _sections(text or "")
    H, R, S = secs.get("Contract header", ""), secs.get("RISK DETAILS", ""), secs.get("SECURITY DETAILS", "")
    SA, FR, BR = (secs.get("SUBSCRIPTION AGREEMENT", ""), secs.get("FISCAL AND REGULATORY", ""),
                  secs.get("BROKER REMUNERATION AND DEDUCTIONS", ""))
    d, q = {}, {}

    def take(key, sec_name, sec, label):
        v, line = _field(sec, label)
        d[key] = v
        if line:
            q[key] = (sec_name, line[:240])

    take("broker_name", "Contract header", H, "Broker:")
    take("broker_number", "Contract header", H, "Lloyd's Broker Number:")
    take("policy_number", "Contract header", H, "Broker Reference:")
    take("umr", "RISK DETAILS", R, "Unique Market Reference:")
    take("class_of_business", "RISK DETAILS", R, "Type:")
    take("insured_name", "RISK DETAILS", R, "Insured:")
    take("period", "RISK DETAILS", R, "Period:")
    take("situation", "RISK DETAILS", R, "Situation:")
    take("deductible_text", "RISK DETAILS", R, "Deductible:")
    take("premium_text", "RISK DETAILS", R, "Premium:")
    take("choice_of_law", "RISK DETAILS", R, "Choice of Law and Jurisdiction:")
    take("several_liability", "SECURITY DETAILS", S, "Insurer's Liability:")
    take("slip_leader", "SUBSCRIPTION AGREEMENT", SA, "Slip Leader:")
    take("settlement_due_date", "SUBSCRIPTION AGREEMENT", SA, "Settlement Due Date:")
    take("country_of_origin", "FISCAL AND REGULATORY", FR, "Country of Origin:")
    take("regulatory_class", "FISCAL AND REGULATORY", FR, "Regulatory Client Classification:")
    take("brokerage", "BROKER REMUNERATION AND DEDUCTIONS", BR, "Total Brokerage:")

    lims, lq = _list_after(R, "Limit of Liability:", ["Deductible:"])
    d["limits"] = lims
    d["headline_limit"] = lims[0] if lims else None
    if lq:
        q["headline_limit"] = ("RISK DETAILS", lq)
    d["clauses"], cq = _list_after(R, "Conditions:", ["Exclusions:", "Choice of Law"])
    d["exclusions"], eq = _list_after(R, "Exclusions:", ["Choice of Law", "Subjectivities:"])
    if cq:
        q["clauses"] = ("RISK DETAILS", cq)
    if eq:
        q["exclusions"] = ("RISK DETAILS", eq)

    ins = re.findall(r"Syndicate\s+(\d+)\s+\(([^)]+)\)\s*\|\s*Written Line:\s*([\d.]+)%\s*\|\s*Signed Line:\s*([\d.]+)%", S)
    d["insurers"] = [{"syndicate": n, "managing_agent": a, "written": float(w), "signed": float(sg)}
                     for n, a, w, sg in ins]
    if ins:
        q["insurers"] = ("SECURITY DETAILS", "; ".join(f"Syndicate {n} signed {sg}%" for n, _, _, sg in ins)[:240])
    d["signed_lines_total"] = round(sum(i["signed"] for i in d["insurers"]), 2) if ins else None
    if ins:
        q["signed_lines_total"] = ("SECURITY DETAILS", f"Sum of {len(ins)} signed lines = {d['signed_lines_total']:.2f}%")

    m = re.search(r"From\s+(.+?)\s+to\s+(.+?)(?:,|$)", d.get("period") or "")
    d["inception_date"], d["expiry_date"] = (m.group(1).strip(), m.group(2).strip()) if m else (None, None)
    if m:
        q["inception_date"] = q["expiry_date"] = q.get("period")
    return d, q


def certainty_checks(cfg, d, text):
    """Deterministic contract-certainty checks — the rules a market body expects a bound
    contract to satisfy. Pure rules on the extracted values; no AI."""
    from datetime import datetime
    labels = {c["id"]: c["label"] for c in _tenant(cfg).get("certainty_checks", [])}
    out = []

    def add(cid, ok, detail):
        out.append({"check_id": cid, "label": labels.get(cid, cid),
                    "status": "pass" if ok else "fail", "detail": detail})

    tot = d.get("signed_lines_total")
    add("signed_100", tot is not None and abs(tot - 100.0) <= 0.05,
        f"Signed lines total {tot:.2f}% of a 100% order" + ("" if tot is not None and abs(tot - 100) <= 0.05
                                                         else " — not fully placed") if tot is not None
        else "No signed lines found")
    add("several_liability", "LSW1001" in (d.get("several_liability") or "") or "LSW1001" in (text or ""),
        d.get("several_liability") or "Several liability notice not found")
    sanc = [c for c in d.get("clauses", []) if "LMA5218" in c or "LMA3100" in c]
    add("sanctions", bool(sanc), sanc[0] if sanc else "No sanctions clause in the conditions")
    try:
        inc = datetime.strptime(d.get("inception_date") or "", "%d %B %Y")
        exp = datetime.strptime(d.get("expiry_date") or "", "%d %B %Y")
        days = (exp - inc).days
        add("period_valid", exp > inc and 360 <= days <= 370, f"{d['inception_date']} to {d['expiry_date']} ({days + 1} days)")
    except ValueError:
        add("period_valid", False, "Period dates could not be read")
    umr, bno = d.get("umr") or "", d.get("broker_number") or ""
    ok = bool(re.fullmatch(r"B\d{4}[A-Z0-9]{1,12}", umr)) and umr[1:5] == bno
    add("umr_format", ok, f"UMR {umr or '—'} / broker number {bno or '—'}")
    lead = re.search(r"Syndicate\s+(\d+)", d.get("slip_leader") or "")
    on = bool(lead) and lead.group(1) in {i["syndicate"] for i in d.get("insurers", [])}
    add("leader_on_security", on, d.get("slip_leader") or "No slip leader stated")
    add("law_stated", bool(d.get("choice_of_law")), (d.get("choice_of_law") or "Not stated")[:160])
    return out


# ---------------------------------------------------------------- recognise (rule 1 & 2)
def recognise(cfg, path, text=None):
    """Against the expected ACORD data points, report which are identified. No writes."""
    text = parse_document(cfg, path) if text is None else text
    d, quotes = det_parse(text) if text else ({}, {})
    points, core_found, core_total = [], 0, 0
    for dp in _tenant(cfg)["expected_data_points"]:
        val = d.get(dp["key"])
        if dp.get("list"):
            n = len(val or [])
            identified = n > 0
            shown = f"{n} found" if identified else None
        else:
            identified = val not in (None, "")
            shown = (f"{val:.2f}%" if isinstance(val, float) else str(val)[:80]) if identified else None
        status = "identified" if identified else "not_found"
        conf = 0.95 if identified else 0.0
        if dp.get("core"):
            core_total += 1
            core_found += 1 if identified else 0
        sec_q = quotes.get(dp["key"])
        points.append({"key": dp["key"], "label": dp["label"],
                       "acord": f'{dp["entity"]}.{dp["attribute"]}', "cdr": dp.get("cdr"),
                       "section": dp["section"], "core": bool(dp.get("core")), "status": status,
                       "value": shown, "confidence": conf,
                       "source_quote": sec_q[1] if sec_q else None})
    conforming = bool(text) and core_found >= 5
    return {"conforming": conforming, "core_found": core_found, "core_total": core_total,
            "points": points, "text": text, "det": d, "quotes": quotes}


def _yyyymm(d):
    from datetime import datetime
    try:
        return datetime.strptime(d or "", "%d %B %Y").strftime("%Y-%m")
    except ValueError:
        return None


def schema_registered(cfg):
    F = cfg["full_schema"]
    r = sql(f"SELECT count(*) FROM {F}.template WHERE doc_family='mrc'", cfg=cfg)
    return bool(r and int(r[0][0]) > 0)


# ---------------------------------------------------------------- stage (pristine inbox)
def stage(cfg, path):
    """Place a document in the MRC inbox as awaiting_recognition, or HITL if non-conforming.
    No schema needed to stage — this classifies by structure only."""
    F = cfg["full_schema"]
    fname = os.path.basename(path)
    if sql(f"SELECT 1 FROM {F}.source_document WHERE tenant='mrc' AND stored_path=:sp LIMIT 1",
           params={"sp": path}, cfg=cfg):
        return {"doc_id": None, "file": fname, "state": "already tracked"}
    doc_id = f"DOC-{uuid.uuid4().hex[:12]}"
    rec = recognise(cfg, path)
    if rec["conforming"]:
        status, state, reason = "awaiting_recognition", "awaiting_recognition", "conforming MRC — awaiting schema recognition"
    else:
        status, state, reason = "quarantined", "unrecognised", \
            "does not match the MRC structure — needs review (HITL)"
    # Idempotent: a document already tracked (same stored path) is never staged twice, even
    # if two staging passes overlap.
    sql(f"""INSERT INTO {F}.source_document
            SELECT :d,'mrc',:c,'mrc',:fn,:sp,:st,:ins,NULL,'v1',:rd,:rp,current_timestamp(),NULL,NULL
            WHERE NOT EXISTS (SELECT 1 FROM {F}.source_document WHERE tenant='mrc' AND stored_path=:sp)""",
        params={"d": doc_id, "c": rec["det"].get("broker_name") or "MRC counterparty",
                "fn": fname, "sp": path, "st": status, "ins": state,
                "rd": json.dumps({"reason": reason, "core_found": rec["core_found"],
                                  "core_total": rec["core_total"]}),
                "rp": _yyyymm(rec["det"].get("inception_date"))}, cfg=cfg)
    audit(cfg, "staged" if rec["conforming"] else "quarantined", "source_document", doc_id,
          detail=f"{fname}: {state}", actor="mrc-pipeline")
    return {"doc_id": doc_id, "file": fname, "state": state}


# ---------------------------------------------------------------- register schema (rule 3)
def register_schema(cfg, actor="reviewer", from_doc=None):
    """Record the recognised schema in the repository (append-only template row)."""
    F = cfg["full_schema"]
    if schema_registered(cfg):
        r = sql(f"SELECT template_version FROM {F}.v_template_latest WHERE doc_family='mrc'", cfg=cfg)
        return {"already": True, "version": r[0][0] if r else "v1"}
    dps = _tenant(cfg)["expected_data_points"]
    field_map = {dp["key"]: dp["section"] for dp in dps}
    anchors = sorted({dp["section"] for dp in dps})
    sql(f"""INSERT INTO {F}.template VALUES
            (:id,'mrc',:c,'mrc','v1',:anchors,:fmap,:n,'active',:actor,current_timestamp())""",
        params={"id": f"TPL-{uuid.uuid4().hex[:8]}", "c": SCHEMA_NAME,
                "anchors": json.dumps(anchors), "fmap": json.dumps(field_map),
                "n": len(dps), "actor": actor}, cfg=cfg)
    audit(cfg, "schema_recognized", "template", f"{SCHEMA_NAME}/mrc",
          detail=f"registered {len(dps)} expected ACORD data points", actor=actor)
    audit(cfg, "template_updated", "template", f"{SCHEMA_NAME}/mrc",
          detail="v1 recorded in schema repository", actor=actor)
    sql(f"""INSERT INTO {F}.decision VALUES
            (:id,'schema_confirm','mrc',:doc,'v1',:detail,'confirmed recognised MRC schema',:actor,'saved',NULL,current_timestamp())""",
        params={"id": f"DEC-{uuid.uuid4().hex[:10]}", "doc": from_doc or "",
                "detail": json.dumps({"schema": SCHEMA_NAME, "data_points": [dp["key"] for dp in dps]}),
                "actor": actor}, cfg=cfg)
    return {"already": False, "version": "v1", "schema": SCHEMA_NAME, "data_points": len(dps)}


# ---------------------------------------------------------------- ingest (rule 5: recognised -> analytics)
def ingest(cfg, doc_id, actor="mrc-pipeline", rec=None):
    """Extract a recognised MRC into the graph + projections; mark it recognised/active.
    `rec` (from recognise()) is reused so the PDF is parsed once."""
    F = cfg["full_schema"]
    r = sql(f"SELECT stored_path, file_name FROM {F}.source_document WHERE doc_id=:d",
            params={"d": doc_id}, cfg=cfg)
    if not r:
        return {"error": "no such doc"}
    path, fname = r[0]
    ds = doc_id.split("-")[-1][:8]
    rec = rec or recognise(cfg, path)
    text, d = rec["text"], rec["det"]
    ai = ai_graph(cfg, text)

    pol, ins, brk, plc = f"policy_{ds}", f"insured_{ds}", f"broker_{ds}", f"placement_{ds}"
    nodes = [
        _node(pol, "Policy", {"umr": d.get("umr"), "policy_number": d.get("policy_number"),
                              "class_of_business": d.get("class_of_business"),
                              "inception_date": d.get("inception_date"), "expiry_date": d.get("expiry_date")},
              doc_id, "det", {"section": "RISK DETAILS"}),
        _node(ins, "Insured", {"name": d.get("insured_name")}, doc_id, "det", {"section": "RISK DETAILS"}),
        _node(brk, "Broker", {"name": d.get("broker_name"), "broker_code": d.get("broker_number")},
              doc_id, "det", {"section": "Contract header"}),
        _node(plc, "Placement", {"choice_of_law": d.get("choice_of_law"),
                                 "signed_lines_total": d.get("signed_lines_total"),
                                 "slip_leader": d.get("slip_leader"),
                                 "settlement_due_date": d.get("settlement_due_date"),
                                 "country_of_origin": d.get("country_of_origin"),
                                 "regulatory_classification": d.get("regulatory_class"),
                                 "total_brokerage_pct": d.get("brokerage")},
              doc_id, "det", {"section": "SECURITY DETAILS"}),
    ]
    edges = [_edge(pol, ins, "ISSUED_TO", doc_id, "det"), _edge(pol, brk, "PLACED_BY", doc_id, "det"),
             _edge(pol, plc, "HAS_PLACEMENT", doc_id, "det")]
    for i in d.get("insurers", []):
        sid = f"syndicate_{i['syndicate']}_{ds}"
        nodes.append(_node(sid, "Insurer", {"name": i["managing_agent"], "syndicate_number": i["syndicate"],
                                            "written_line_pct": i["written"], "signed_line_pct": i["signed"]},
                           doc_id, "det", {"section": "SECURITY DETAILS"}))
        edges.append(_edge(plc, sid, "SUBSCRIBED_BY", doc_id, "det"))
    idmap = {}
    for n in ai.get("nodes", []):
        raw = n.get("node_id") or f"n_{uuid.uuid4().hex[:6]}"
        nid = f"{ds}_{raw}"; idmap[raw] = nid
        nodes.append(_node(nid, n.get("label", "Unknown"), n.get("properties", {}), doc_id, "ai",
                           {"source": "ai_query"}, conf=0.9))
    for e in ai.get("edges", []):
        s_ = idmap.get(e.get("source_id"), f"{ds}_{e.get('source_id')}")
        t_ = idmap.get(e.get("target_id"), f"{ds}_{e.get('target_id')}")
        edges.append(_edge(s_, t_, e.get("relationship_type", "RELATED"), doc_id, "ai", conf=0.9))
    insert_rows(f"{F}.graph_nodes", NODE_COLS, nodes, cfg)
    insert_rows(f"{F}.graph_edges", EDGE_COLS, edges, cfg)

    # Per-data-point extraction with its source quote — the lineage + Core Data Record view.
    sql(f"DELETE FROM {F}.mrc_extraction WHERE mrc_id=:m", params={"m": pol}, cfg=cfg)
    insert_rows(f"{F}.mrc_extraction", [
        ("mrc_id", "str"), ("source_document_id", "str"), ("data_point", "str"), ("label", "str"),
        ("acord_binding", "str"), ("cdr_field", "str"), ("section", "str"), ("value", "str"),
        ("source_quote", "str"), ("status", "str"), ("confidence", "float"), ("created_at", "ts_now")],
        [{"mrc_id": pol, "source_document_id": doc_id, "data_point": p["key"], "label": p["label"],
          "acord_binding": p["acord"], "cdr_field": p.get("cdr"), "section": p["section"],
          "value": p["value"], "source_quote": p.get("source_quote"), "status": p["status"],
          "confidence": p["confidence"]} for p in rec["points"]], cfg)

    checks = certainty_checks(cfg, d, text)
    sql(f"DELETE FROM {F}.mrc_certainty_check WHERE mrc_id=:m", params={"m": pol}, cfg=cfg)
    insert_rows(f"{F}.mrc_certainty_check", [
        ("mrc_id", "str"), ("source_document_id", "str"), ("check_id", "str"), ("label", "str"),
        ("status", "str"), ("detail", "str"), ("created_at", "ts_now")],
        [{"mrc_id": pol, "source_document_id": doc_id, **c} for c in checks], cfg)
    failed = sum(1 for c in checks if c["status"] == "fail")

    prem_amt, prem_ccy = _parse_money(d.get("premium_text"))
    lim_amt, _ = _parse_money(d.get("headline_limit"))
    try:
        brokerage = float((d.get("brokerage") or "").rstrip("%"))
    except ValueError:
        brokerage = None
    # Idempotent projection: a re-ingest of the same MRC replaces its row rather than appending.
    sql(f"DELETE FROM {F}.mrc_entities WHERE mrc_id=:m", params={"m": pol}, cfg=cfg)
    insert_rows(f"{F}.mrc_entities", [
        ("mrc_id", "str"), ("umr", "str"), ("policy_number", "str"), ("class_of_business", "str"),
        ("inception_date", "str"), ("expiry_date", "str"), ("insured_name", "str"),
        ("broker_name", "str"), ("premium_text", "str"), ("headline_limit", "str"),
        ("deductible_text", "str"), ("premium_amount", "dec"), ("premium_currency", "str"),
        ("limit_amount", "dec"), ("n_clauses", "int"), ("n_exclusions", "int"),
        ("n_insurers", "int"), ("choice_of_law", "str"), ("situation", "str"), ("slip_leader", "str"),
        ("signed_lines_total", "float"), ("brokerage_pct", "float"), ("checks_failed", "int"),
        ("certainty_status", "str"), ("source_document_id", "str")], [{
            "mrc_id": pol, "umr": d.get("umr"), "policy_number": d.get("policy_number"),
            "class_of_business": d.get("class_of_business"), "inception_date": d.get("inception_date"),
            "expiry_date": d.get("expiry_date"), "insured_name": d.get("insured_name"),
            "broker_name": d.get("broker_name"), "premium_text": d.get("premium_text"),
            "headline_limit": d.get("headline_limit"), "deductible_text": d.get("deductible_text"),
            "premium_amount": prem_amt, "premium_currency": prem_ccy, "limit_amount": lim_amt,
            "n_clauses": len(d.get("clauses", [])), "n_exclusions": len(d.get("exclusions", [])),
            "n_insurers": len(d.get("insurers", [])), "choice_of_law": d.get("choice_of_law"),
            "situation": d.get("situation"), "slip_leader": d.get("slip_leader"),
            "signed_lines_total": d.get("signed_lines_total"), "brokerage_pct": brokerage,
            "checks_failed": failed, "certainty_status": "pass" if failed == 0 else "fail",
            "source_document_id": doc_id}], cfg)

    sql(f"""UPDATE {F}.source_document
            SET status='active', inbound_state='recognised', template_version='mrc-v1',
                counterparty=coalesce(:brk, counterparty), signed_off_by=:actor, signed_off_at=current_timestamp()
            WHERE doc_id=:d""",
        params={"brk": d.get("broker_name"), "actor": actor, "d": doc_id}, cfg=cfg)
    audit(cfg, "ingested", "source_document", doc_id,
          detail=f"MRC {d.get('umr')}: recognised -> {len(nodes)} nodes; {failed} certainty check(s) failed",
          actor=actor)
    if failed:
        audit(cfg, "certainty_flag", "mrc_entities", pol,
              detail="; ".join(c["label"] for c in checks if c["status"] == "fail"), actor=actor)
    return {"state": "recognised", "file": fname, "umr": d.get("umr"),
            "nodes": len(nodes), "edges": len(edges), "checks_failed": failed}


def ai_graph(cfg, text):
    base = json.loads(open(os.path.join(ROOT, "data", "acord_dictionary.json")).read())
    prompt = (
        "You are an insurance document graph extractor. Extract structured entities and "
        "relationships from the following Lloyd's Market Reform Contract.\n\n"
        f"ENTITY DEFINITIONS:\n{json.dumps(base['entities'], indent=2)}\n\n"
        f"RELATIONSHIP DEFINITIONS:\n{json.dumps(base['relationships'], indent=2)}\n\n"
        "RULES:\n1. node_id format <entity_type>_<short>.\n2. label + properties JSON per node.\n"
        "3. edges use source_id/target_id/relationship_type from the definitions.\n"
        "4. Extract ALL you can find.\n5. Return ONLY valid JSON.\n\n"
        f"DOCUMENT TEXT:\n{text}\n\n"
        'Return JSON: {"nodes":[{"node_id":"...","label":"...","properties":{}}],'
        '"edges":[{"source_id":"...","target_id":"...","relationship_type":"..."}]}')
    try:
        out = sql("SELECT ai_query(:ep, :p)", params={"ep": cfg["models"]["extract"], "p": prompt}, cfg=cfg)
        txt = (out[0][0] or "").strip()
        if txt.startswith("```"):
            txt = txt.split("```")[1]
            if txt.startswith("json"):
                txt = txt[4:]
        try:
            return json.loads(txt)
        except json.JSONDecodeError:
            s, e = txt.find("{"), txt.rfind("}") + 1
            return json.loads(txt[s:e]) if s >= 0 and e > s else {"nodes": [], "edges": []}
    except Exception as ex:
        print(f"    (ai_query fallback: {ex})")
        return {"nodes": [], "edges": []}


# ---------------------------------------------------------------- HITL actions (app-facing)
def propose_first(cfg):
    """Recognition checklist for the first awaiting document (drives Schema Recognition)."""
    F = cfg["full_schema"]
    r = sql(f"""SELECT doc_id, file_name, stored_path, counterparty FROM {F}.source_document
                WHERE tenant='mrc' AND status='awaiting_recognition'
                ORDER BY ingested_at LIMIT 1""", cfg=cfg)
    if not r:
        return {"doc_id": None, "message": "no documents awaiting recognition"}
    doc_id, fname, path, cp = r[0]
    rec = recognise(cfg, path)
    return {"doc_id": doc_id, "file_name": fname, "counterparty": cp,
            "conforming": rec["conforming"], "core_found": rec["core_found"],
            "core_total": rec["core_total"], "points": rec["points"],
            "schema_registered": schema_registered(cfg), "schema_name": SCHEMA_NAME}


def confirm_and_register(cfg, actor="reviewer"):
    """HITL confirm: register the schema, then straight-through the whole awaiting inbox."""
    first = sql(f"""SELECT doc_id FROM {cfg['full_schema']}.source_document
                    WHERE tenant='mrc' AND status='awaiting_recognition' ORDER BY ingested_at LIMIT 1""",
                cfg=cfg)
    reg = register_schema(cfg, actor=actor, from_doc=first[0][0] if first else None)
    scan = rescan(cfg, actor=actor)
    return {"schema": reg, "rescan": scan}


def rescan(cfg, actor="mrc-pipeline"):
    """Once a schema is registered, recognise + ingest every awaiting MRC (rule 4 & 5).
    Each document is marked 'processing' first so the Inbox shows progress live."""
    F = cfg["full_schema"]
    if not schema_registered(cfg):
        return {"error": "no MRC schema registered yet"}
    awaiting = sql(f"""SELECT doc_id, stored_path FROM {F}.source_document
                       WHERE tenant='mrc' AND status IN ('awaiting_recognition','processing')
                       ORDER BY file_name""", cfg=cfg)
    for doc_id, _ in awaiting:
        sql(f"UPDATE {F}.source_document SET status='processing', inbound_state='processing' WHERE doc_id=:d",
            params={"d": doc_id}, cfg=cfg)
    # Contracts are independent, so process them in parallel (each is ~50s of parse +
    # AI extraction + writes). A transient write conflict is retried; a document is never
    # left stuck in 'processing'.
    from concurrent.futures import ThreadPoolExecutor
    import time as _time

    def one(item):
        doc_id, path = item
        last = None
        for attempt in range(3):
            try:
                rec = recognise(cfg, path)
                if rec["conforming"]:
                    ingest(cfg, doc_id, actor=actor, rec=rec)
                    return "ingested"
                sql(f"UPDATE {F}.source_document SET status='quarantined', inbound_state='unrecognised' WHERE doc_id=:d",
                    params={"d": doc_id}, cfg=cfg)
                audit(cfg, "quarantined", "source_document", doc_id, detail="not recognised -> HITL", actor=actor)
                return "hitl"
            except Exception as ex:
                last = ex
                _time.sleep(2 + attempt * 3)
        sql(f"UPDATE {F}.source_document SET status='awaiting_recognition', inbound_state='awaiting_recognition' WHERE doc_id=:d",
            params={"d": doc_id}, cfg=cfg)
        audit(cfg, "processing_error", "source_document", doc_id, detail=str(last)[:300], actor=actor)
        return "error"

    with ThreadPoolExecutor(max_workers=max(1, min(5, len(awaiting)))) as pool:
        outcomes = list(pool.map(one, awaiting))
    ingested, hitl = outcomes.count("ingested"), outcomes.count("hitl")
    if outcomes.count("error"):
        print(f"  {outcomes.count('error')} document(s) returned to awaiting after retries")
    return {"ingested": ingested, "hitl": hitl}


def review_unrecognised(cfg, doc_id, action, reason="", actor="reviewer"):
    """HITL decision on a document that did not match the MRC schema.
    action: 'reject' (not an MRC — removed from the flow) or 'return' (sent back to the
    broker for a proper MRC). Both are recorded as an append-only decision + audit."""
    F = cfg["full_schema"]
    if action not in ("reject", "return"):
        raise ValueError("action must be 'reject' or 'return'")
    new_state = "rejected" if action == "reject" else "returned_to_broker"
    sql(f"""UPDATE {F}.source_document SET status=:st, inbound_state=:st, signed_off_by=:a,
            signed_off_at=current_timestamp() WHERE doc_id=:d AND tenant='mrc'""",
        params={"st": new_state, "a": actor, "d": doc_id}, cfg=cfg)
    audit(cfg, f"hitl_{action}", "source_document", doc_id, detail=reason or new_state, actor=actor)
    sql(f"""INSERT INTO {F}.decision VALUES
            (:id,'quarantine_resolve','mrc',:doc,NULL,:detail,:reason,:actor,'saved',NULL,current_timestamp())""",
        params={"id": f"DEC-{uuid.uuid4().hex[:10]}", "doc": doc_id,
                "detail": json.dumps({"action": action, "state": new_state}),
                "reason": reason or new_state, "actor": actor}, cfg=cfg)
    return {"doc_id": doc_id, "state": new_state}


# ---------------------------------------------------------------- staging pass (pristine)
def process_mrc_inbox(cfg=None):
    """Stage every file in mrc_inbox that isn't already tracked (pristine = all awaiting/HITL)."""
    cfg = cfg or load_config()
    F = cfg["full_schema"]
    base = f'{cfg["volume_path"]}/mrc_inbox'
    files = sorted(f.path for f in client(cfg).files.list_directory_contents(base))
    known = {row[0] for row in sql(f"SELECT stored_path FROM {F}.source_document WHERE tenant='mrc'", cfg=cfg)}
    out = []
    for p in files:
        if p in known:
            continue
        out.append(stage(cfg, p))
    print(f"== staged {len(out)} MRC files (awaiting/HITL); schema_registered={schema_registered(cfg)}")
    for r in out:
        print(f"  {r['file']:<28} -> {r['state']}")
    return out


if __name__ == "__main__":
    cfg = load_config()
    if "--rescan" in sys.argv:
        print(confirm_and_register(cfg))
    else:
        process_mrc_inbox(cfg)
