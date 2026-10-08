"""MRC schema registry + intake: known / changed / new / not an MRC.

The rules this module implements (the Lloyd's demo story):
  * A schema is identified by its **fingerprint** — the document title plus its section
    headings. One schema is pre-registered: "Lloyd's MRC v3 — Open Market (ACORD)".
  * **Known** — the fingerprint matches a registered schema and every expected data point is
    found -> ingested automatically, no person involved.
  * **Changed** — the fingerprint matches but some expected data points are missing or sit
    under a different label -> flagged, with a side-by-side diff and proposed renames
    (by text similarity). Accepting records a new schema version that has learned the labels.
  * **New** — an MRC whose fingerprint matches no registered schema -> schema recognition:
    fields the vocabulary already knows are reused; unfamiliar fields are mapped to ACORD
    terms by the model (dictionary-constrained, with its stated confidence). A person
    confirms, the schema is recorded, and the document is ingested.
  * **Not an MRC** -> held for review.
Everything is append-only (schema versions, decisions, audit). Values are read by rule; the
model only proposes mappings for a new schema and builds the wider entity graph.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import load_config, sql, client  # noqa: E402
from jobs.ingest_pipeline import audit  # noqa: E402
from jobs import mrc_pipeline as mp  # noqa: E402

OPEN_MARKET = "Lloyd's MRC v3 — Open Market (ACORD)"
TITLE = "MARKET REFORM CONTRACT"

# The label each open-market data point is read from (and the section it sits in).
OM_LABELS = {
    "broker_name": "Broker", "broker_number": "Lloyd's Broker Number", "policy_number": "Broker Reference",
    "umr": "Unique Market Reference", "class_of_business": "Type", "insured_name": "Insured",
    "inception_date": "Period", "expiry_date": "Period", "situation": "Situation",
    "headline_limit": "Limit of Liability", "deductible_text": "Deductible", "premium_text": "Premium",
    "clauses": "Conditions", "exclusions": "Exclusions", "choice_of_law": "Choice of Law and Jurisdiction",
    "slip_leader": "Slip Leader", "settlement_due_date": "Settlement Due Date",
    "country_of_origin": "Country of Origin", "regulatory_class": "Regulatory Client Classification",
    "brokerage": "Total Brokerage",
}
# Lines the open-market schema reads but deliberately does not treat as data points.
NOT_DATA_POINTS = {"Insured Address", "Interest", "Insurer's Liability", "Insurer’s Liability",
                   "Order Hereon", "Basis of Written Lines", "Basis of Signed Lines",
                   "Basis of Agreement to Contract Changes", "Basis of Claims Agreement",
                   "Subjectivities", "Tax Payable by Insurer(s)", "Other Deductions from Premium"}
# ACORD binding -> mrc_entities column (works for any schema).
BINDING_TO_COLUMN = {"Policy.umr": "umr", "Policy.policy_number": "policy_number",
                     "Policy.class_of_business": "class_of_business", "Insured.name": "insured_name",
                     "Coverholder.name": "insured_name", "Broker.name": "broker_name",
                     "Limit.amount": "headline_limit", "Premium.amount": "premium_text",
                     "Deductible.amount": "deductible_text", "Placement.choice_of_law": "choice_of_law",
                     "RiskLocation.country_code": "situation", "Placement.slip_leader": "slip_leader"}


def _norm(label):
    return label.replace("’", "'").strip().rstrip(":").strip()


# ------------------------------------------------------------------ fingerprint + generic read
def _is_heading(line):
    l = line.strip()
    return (len(l) >= 6 and ":" not in l and not l.startswith("-") and any(c.isalpha() for c in l)
            and l == l.upper())


def fingerprint(text):
    heads = [l.strip() for l in (text or "").splitlines() if _is_heading(l)]
    title = heads[0] if heads else ""
    return {"title": title, "sections": sorted(set(heads[1:]))}


def generic_fields(text):
    """Every 'Label: value' line and every 'Label:' + '- item' list, with its section."""
    out, section, pending = [], "Contract header", None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if _is_heading(line):
            section, pending = (line if out or section != "Contract header" else "Contract header"), None
            if line.startswith(TITLE):
                section = "Contract header"
            continue
        if line.startswith("-") and pending is not None:
            pending["items"].append(line[1:].strip())
            continue
        m = re.match(r"^([A-Z][^:]{1,60}):\s*(.*)$", line)
        if m:
            label, value = _norm(m.group(1)), m.group(2).strip()
            if re.match(r"^Syndicate\s+\d+", line):
                continue
            entry = {"section": section, "label": label, "value": value, "line": line[:240], "items": []}
            out.append(entry)
            pending = entry if not value else None
    return out


# ------------------------------------------------------------------ registry
def schemas(cfg):
    """Latest version of every registered MRC schema."""
    F = cfg["full_schema"]
    rows = sql(f"""SELECT counterparty, template_version, expected_anchors, field_map, created_by, created_at
                   FROM {F}.v_template_latest WHERE doc_family='mrc'""", cfg=cfg)
    out = []
    for name, ver, fp, fmap, by, at in rows:
        out.append({"name": name, "version": ver, "fingerprint": json.loads(fp or "{}"),
                    "field_map": json.loads(fmap or "{}"), "created_by": by, "created_at": str(at)})
    return out


def _record_schema(cfg, name, version, fp, field_map, actor, from_doc, decision_type, reason):
    F = cfg["full_schema"]
    sql(f"""INSERT INTO {F}.template VALUES
            (:id,'mrc',:c,'mrc',:v,:fp,:fmap,:n,'active',:actor,current_timestamp())""",
        params={"id": f"TPL-{uuid.uuid4().hex[:8]}", "c": name, "v": version, "fp": json.dumps(fp),
                "fmap": json.dumps(field_map), "n": len(field_map), "actor": actor}, cfg=cfg)
    audit(cfg, "schema_recorded", "template", f"{name}/mrc", detail=f"{name} {version}: {len(field_map)} data points",
          actor=actor)
    sql(f"""INSERT INTO {F}.decision VALUES
            (:id,:dt,'mrc',:doc,:v,:detail,:reason,:actor,'saved',NULL,current_timestamp())""",
        params={"id": f"DEC-{uuid.uuid4().hex[:10]}", "dt": decision_type, "doc": from_doc or "", "v": version,
                "detail": json.dumps({"schema": name, "version": version, "data_points": list(field_map)}),
                "reason": reason, "actor": actor}, cfg=cfg)


def open_market_field_map(cfg):
    pts = mp._tenant(cfg)["expected_data_points"]
    fm = {}
    for p in pts:
        kind = "list" if p.get("list") else "field"
        if p["key"] in ("insurers",):
            kind = "security"
        if p["key"] == "signed_lines_total":
            kind = "signed_total"
        fm[p["key"]] = {"label": OM_LABELS.get(p["key"]), "labels": [], "section": p["section"], "kind": kind,
                        "entity": p["entity"], "attribute": p["attribute"], "cdr": p.get("cdr"),
                        "core": bool(p.get("core")), "display": p["label"]}
    return fm


def preregister_open_market(cfg, actor="Market data team"):
    """The schema the demo starts with — recorded before the documents arrive."""
    fp = {"title": TITLE, "sections": sorted(["RISK DETAILS", "INFORMATION", "SECURITY DETAILS",
                                              "SUBSCRIPTION AGREEMENT", "FISCAL AND REGULATORY",
                                              "BROKER REMUNERATION AND DEDUCTIONS"])}
    _record_schema(cfg, OPEN_MARKET, "v1", fp, open_market_field_map(cfg), actor, None,
                   "schema_confirm", "Open-market MRC v3 schema recorded in the repository")


# ------------------------------------------------------------------ extraction against a schema
def _alt_labels(field_map):
    return {k: [l + ":" for l in v.get("labels", [])] for k, v in field_map.items() if v.get("labels")}


def extract(text, schema):
    """Read a document with a schema -> (values, quotes, points). Open-market uses the tested
    deterministic reader (+ learned labels); a learned schema reads its own labels."""
    fm = schema["field_map"]
    if schema["name"] == OPEN_MARKET:
        d, quotes = mp.det_parse(text, alt=_alt_labels(fm))
    else:
        d, quotes = _extract_learned(text, fm)
    points = []
    for key, spec in fm.items():
        val = d.get(key)
        if spec["kind"] in ("list", "security"):
            ok = bool(val)
            shown = f"{len(val)} found" if ok else None
        else:
            ok = val not in (None, "")
            shown = (f"{val:.2f}%" if isinstance(val, float) else str(val)[:80]) if ok else None
        q = quotes.get(key)
        points.append({"key": key, "label": spec.get("display") or spec.get("label"),
                       "acord": f"{spec['entity']}.{spec['attribute']}" if spec.get("entity") else None,
                       "cdr": spec.get("cdr"), "section": spec["section"], "core": bool(spec.get("core")),
                       "status": "identified" if ok else "not_found", "value": shown,
                       "confidence": 1.0 if ok else 0.0, "source_quote": q[1] if q else None})
    return d, quotes, points


def _extract_learned(text, fm):
    secs = mp._sections(text)
    secs.update({k: v for k, v in _sections_any(text).items() if k not in secs})
    d, q = {}, {}
    for key, spec in fm.items():
        sec = secs.get(spec["section"], text)
        if spec["kind"] == "field":
            v, line = mp._field(sec, spec["label"] + ":")
            for a in spec.get("labels", []):
                if v is None:
                    v, line = mp._field(sec, a + ":")
            if spec.get("period_part"):
                m = re.search(r"From\s+(.+?)\s+to\s+(.+?)(?:,|$)", v or "")
                v = (m.group(1) if spec["period_part"] == "start" else m.group(2)).strip() if m else None
            d[key] = v
            if line:
                q[key] = (spec["section"], line[:240])
        elif spec["kind"] == "list":
            items, quote = mp._list_after(sec, spec["label"] + ":", spec.get("stops", []))
            d[key] = items
            if quote:
                q[key] = (spec["section"], quote)
    ins = re.findall(r"Syndicate\s+(\d+)\s+\(([^)]+)\)\s*\|\s*Written Line:\s*([\d.]+)%\s*\|\s*Signed Line:\s*([\d.]+)%",
                     text or "")
    if "insurers" in fm or "signed_lines_total" in fm:
        d["insurers"] = [{"syndicate": n, "managing_agent": a, "written": float(w), "signed": float(sg)}
                         for n, a, w, sg in ins]
        d["signed_lines_total"] = round(sum(i["signed"] for i in d["insurers"]), 2) if ins else None
        if ins:
            q["insurers"] = ("SECURITY DETAILS", "; ".join(f"Syndicate {n} signed {sg}%" for n, _, _, sg in ins)[:240])
            q["signed_lines_total"] = ("SECURITY DETAILS", f"Sum of {len(ins)} signed lines = {d['signed_lines_total']:.2f}%")
    sl = mp._field(secs.get("Insurer's Liability", text), "Insurer's Liability:")[0]
    d["several_liability"] = sl or ("LSW1001" if "LSW1001" in (text or "") else None)
    return d, q


def _sections_any(text):
    """Section split on any heading line (for learned schemas with unfamiliar headings)."""
    out, cur, buf = {}, "Contract header", []
    for line in (text or "").splitlines():
        if _is_heading(line) and not line.strip().startswith(TITLE):
            out[cur] = "\n".join(buf); cur, buf = line.strip(), []
        else:
            buf.append(line)
    out[cur] = "\n".join(buf)
    return out


# ------------------------------------------------------------------ classify
def _match(fp, schema):
    sfp = schema["fingerprint"]
    if fp["title"] != sfp.get("title"):
        return 0.0
    a, b = set(fp["sections"]), set(sfp.get("sections", []))
    return len(a & b) / max(1, len(a | b))


def diff(text, schema, points):
    """What changed against the schema: missing data points and likely renames."""
    expected = {}
    for key, spec in schema["field_map"].items():
        if spec["kind"] in ("field", "list") and spec.get("label"):
            expected[key] = [spec["label"]] + spec.get("labels", [])
    known_labels = {l for ls in expected.values() for l in ls} | NOT_DATA_POINTS
    doc = generic_fields(text)
    unmatched = [f for f in doc if f["label"] not in known_labels]
    missing = [p for p in points if p["status"] != "identified"]
    rows, used = [], set()
    for p in missing:
        spec = schema["field_map"][p["key"]]
        best, score = None, 0.0
        for f in unmatched:
            if id(f) in used or f["section"] != spec["section"]:
                continue
            r = difflib.SequenceMatcher(None, spec.get("label") or "", f["label"]).ratio()
            if r > score:
                best, score = f, r
        if best is not None and score >= 0.55:
            used.add(id(best))
            rows.append({"key": p["key"], "data_point": p["label"], "section": spec["section"],
                         "change": "renamed", "expected_label": spec["label"], "found_label": best["label"],
                         "similarity": round(score, 2), "value": best["value"] or "; ".join(best["items"]),
                         "source_quote": best["line"]})
        else:
            rows.append({"key": p["key"], "data_point": p["label"], "section": spec["section"],
                         "change": "missing", "expected_label": spec.get("label"), "found_label": None,
                         "similarity": None, "value": None, "source_quote": None})
    return rows


def classify(cfg, path, text=None):
    text = mp.parse_document(cfg, path) if text is None else text
    fp = fingerprint(text)
    if not fp["title"].startswith(TITLE):
        return {"outcome": "not_mrc", "fingerprint": fp, "text": text}
    best, score = None, 0.0
    for sc in schemas(cfg):
        m = _match(fp, sc)
        if m > score:
            best, score = sc, m
    if best is None or score < 0.8:
        return {"outcome": "new", "fingerprint": fp, "text": text}
    d, quotes, points = extract(text, best)
    missing = [p for p in points if p["status"] != "identified"]
    if not missing:
        return {"outcome": "known", "schema": best, "d": d, "quotes": quotes, "points": points,
                "fingerprint": fp, "text": text}
    return {"outcome": "changed", "schema": best, "d": d, "quotes": quotes, "points": points,
            "diff": diff(text, best, points), "fingerprint": fp, "text": text}


# ------------------------------------------------------------------ intake (the automatic step)
def _set_state(cfg, doc_id, status, state, detail=None, version=None):
    F = cfg["full_schema"]
    sql(f"""UPDATE {F}.source_document SET status=:st, inbound_state=:ins,
            reconciliation_detail=coalesce(:rd, reconciliation_detail),
            template_version=coalesce(:v, template_version) WHERE doc_id=:d""",
        params={"st": status, "ins": state, "rd": json.dumps(detail) if detail is not None else None,
                "v": version, "d": doc_id}, cfg=cfg)


def _ingest(cfg, doc_id, cls, actor):
    rec = {"text": cls["text"], "det": cls["d"], "points": cls["points"]}
    return mp.ingest(cfg, doc_id, actor=actor, rec=rec, schema=cls["schema"])


def process_one(cfg, doc_id, path, actor="intake"):
    cls = classify(cfg, path)
    o = cls["outcome"]
    if o == "known":
        _ingest(cfg, doc_id, cls, actor)
        audit(cfg, "auto_ingested", "source_document", doc_id,
              detail=f"matched {cls['schema']['name']} {cls['schema']['version']} — no person involved", actor=actor)
    elif o == "changed":
        _set_state(cfg, doc_id, "quarantined", "schema_changed",
                   {"schema": cls["schema"]["name"], "version": cls["schema"]["version"], "diff": cls["diff"]},
                   cls["schema"]["version"])
        audit(cfg, "flagged_schema_change", "source_document", doc_id,
              detail=f"{cls['schema']['name']}: " + ", ".join(f"{r['data_point']} {r['change']}" for r in cls["diff"]),
              actor=actor)
    elif o == "new":
        _set_state(cfg, doc_id, "awaiting_recognition", "new_schema",
                   {"fingerprint": cls["fingerprint"]})
        audit(cfg, "new_schema_detected", "source_document", doc_id,
              detail=f"no registered schema matches '{cls['fingerprint']['title']}'", actor=actor)
    else:
        _set_state(cfg, doc_id, "quarantined", "unrecognised", {"reason": "not a Market Reform Contract"})
        audit(cfg, "quarantined", "source_document", doc_id, detail="not a Market Reform Contract", actor=actor)
    return o


def intake(cfg, actor="intake"):
    """Process every received document. In production a file-arrival trigger runs this."""
    from concurrent.futures import ThreadPoolExecutor
    import time
    F = cfg["full_schema"]
    rows = sql(f"""SELECT doc_id, stored_path FROM {F}.source_document
                   WHERE tenant='mrc' AND status IN ('received','processing') ORDER BY file_name""", cfg=cfg)
    for doc_id, _ in rows:
        _set_state(cfg, doc_id, "processing", "processing")

    def one(item):
        doc_id, path = item
        last = None
        for attempt in range(3):
            try:
                return process_one(cfg, doc_id, path, actor)
            except Exception as ex:
                last = ex
                time.sleep(2 + attempt * 3)
        _set_state(cfg, doc_id, "received", "received")
        audit(cfg, "processing_error", "source_document", doc_id, detail=str(last)[:300], actor=actor)
        return "error"

    with ThreadPoolExecutor(max_workers=max(1, min(8, len(rows)))) as pool:
        out = list(pool.map(one, rows))
    return {k: out.count(k) for k in set(out)}


# ------------------------------------------------------------------ changed -> accept (schema v2)
def doc_row(cfg, doc_id):
    F = cfg["full_schema"]
    r = sql(f"""SELECT doc_id, file_name, stored_path, counterparty, status, inbound_state, reconciliation_detail
                FROM {F}.source_document WHERE tenant='mrc' AND doc_id=:d""", params={"d": doc_id}, cfg=cfg)
    if not r:
        raise ValueError("no such document")
    k = ["doc_id", "file_name", "stored_path", "counterparty", "status", "inbound_state", "detail"]
    row = dict(zip(k, r[0]))
    row["detail"] = json.loads(row["detail"]) if row["detail"] else {}
    return row


def changes(cfg, doc_id):
    row = doc_row(cfg, doc_id)
    cls = classify(cfg, row["stored_path"])
    return {"doc_id": doc_id, "file_name": row["file_name"], "state": row["inbound_state"],
            "outcome": cls["outcome"], "schema": (cls.get("schema") or {}).get("name"),
            "version": (cls.get("schema") or {}).get("version"), "diff": cls.get("diff", []),
            "points": cls.get("points", [])}


def _bump(v):
    try:
        return f"v{int(str(v).lstrip('v')) + 1}"
    except ValueError:
        return "v2"


def accept_changes(cfg, doc_id, actor="reviewer"):
    """Record a new version of the schema that has learned the renamed labels, then ingest.
    Missing data points stay missing — they remain visible as gaps downstream."""
    row = doc_row(cfg, doc_id)
    cls = classify(cfg, row["stored_path"])
    if cls["outcome"] != "changed":
        raise ValueError("this document is not flagged as a changed layout")
    sc = cls["schema"]
    fm = json.loads(json.dumps(sc["field_map"]))
    learned = []
    for r in cls["diff"]:
        if r["change"] == "renamed" and r["found_label"] not in fm[r["key"]].setdefault("labels", []):
            fm[r["key"]]["labels"].append(r["found_label"])
            learned.append(f"{r['expected_label']} → {r['found_label']}")
    new_v = _bump(sc["version"])
    _record_schema(cfg, sc["name"], new_v, sc["fingerprint"], fm, actor, doc_id, "schema_change_accept",
                   "Accepted layout change: " + (", ".join(learned) or "no renames"))
    sc2 = dict(sc, version=new_v, field_map=fm)
    d, quotes, points = extract(cls["text"], sc2)
    _ingest(cfg, doc_id, {"text": cls["text"], "d": d, "points": points, "schema": sc2}, actor)
    gaps = [p["label"] for p in points if p["status"] != "identified"]
    return {"schema": sc["name"], "version": new_v, "learned": learned, "gaps": gaps}


# ------------------------------------------------------------------ new -> recognise (schema proposal)
def _dictionary_bindings(cfg):
    F = cfg["full_schema"]
    rows = sql(f"SELECT entity_type, attributes FROM {F}.v_dictionary_entity_latest", cfg=cfg)
    out = []
    for ent, attrs in rows:
        try:
            attrs = json.loads(attrs) if isinstance(attrs, str) else attrs
        except json.JSONDecodeError:
            attrs = [a.strip(' "') for a in str(attrs).strip("[]").split(",")]
        out += [f"{ent}.{a}" for a in (attrs or [])]
    return sorted(set(out))


def propose(cfg, doc_id):
    """Propose a schema for a document no registered schema matches."""
    row = doc_row(cfg, doc_id)
    text = mp.parse_document(cfg, row["stored_path"])
    fp = fingerprint(text)
    fields = [f for f in generic_fields(text) if f["label"] not in NOT_DATA_POINTS]
    om = open_market_field_map(cfg)
    by_label = {v["label"]: (k, v) for k, v in om.items() if v.get("label")}
    allowed = _dictionary_bindings(cfg)
    rows, unknown = [], []
    for f in fields:
        if f["label"] in by_label:  # the vocabulary already knows this field
            k, v = by_label[f["label"]]
            if f["label"] == "Period":
                for part, key in (("start", "inception_date"), ("end", "expiry_date")):
                    s = om[key]
                    rows.append({"key": key, "label": s["display"], "source_label": "Period", "section": f["section"],
                                 "kind": "field", "period_part": part, "value": f["value"], "source_quote": f["line"],
                                 "binding": f"{s['entity']}.{s['attribute']}", "cdr": s["cdr"],
                                 "origin": "known field", "confidence": None, "core": True, "include": True})
                continue
            rows.append({"key": k, "label": v["display"], "source_label": f["label"], "section": f["section"],
                         "kind": v["kind"] if v["kind"] in ("field", "list") else "field", "value": f["value"] or "; ".join(f["items"]),
                         "source_quote": f["line"], "binding": f"{v['entity']}.{v['attribute']}", "cdr": v["cdr"],
                         "origin": "known field", "confidence": None, "core": v["core"], "include": True})
        else:
            unknown.append(f)
    ai = _ai_map(cfg, unknown, allowed) if unknown else {}
    for f in unknown:
        m = ai.get(f["label"], {})
        b = m.get("binding") if m.get("binding") in allowed else None
        key = re.sub(r"[^a-z0-9]+", "_", f["label"].lower()).strip("_")
        rows.append({"key": key, "label": f["label"], "source_label": f["label"], "section": f["section"],
                     "kind": "list" if f["items"] else "field", "value": f["value"] or "; ".join(f["items"]),
                     "source_quote": f["line"] if f["value"] else (f["label"] + ": " + "; ".join(f["items"]))[:240],
                     "binding": b, "cdr": m.get("cdr"), "origin": "proposed by the model",
                     "confidence": m.get("confidence"), "why": m.get("why"),
                     "core": b in ("Coverholder.name",), "include": b is not None})
    if re.search(r"Syndicate\s+\d+\s+\(", text):
        for key in ("insurers", "signed_lines_total"):
            s = om[key]
            rows.append({"key": key, "label": s["display"], "source_label": "Security lines", "section": "SECURITY DETAILS",
                         "kind": s["kind"], "value": "syndicate lines found", "source_quote": None,
                         "binding": f"{s['entity']}.{s['attribute']}", "cdr": s["cdr"], "origin": "known field",
                         "confidence": None, "core": True, "include": True})
    return {"doc_id": doc_id, "file_name": row["file_name"], "fingerprint": fp,
            "suggested_name": _suggest_name(fp), "fields": rows, "bindings": allowed}


def _suggest_name(fp):
    t = fp["title"].replace(TITLE, "").strip(" -—")
    return f"Lloyd's MRC v3 — {t.title()} (ACORD)" if t else "Lloyd's MRC v3 — New layout (ACORD)"


def _ai_map(cfg, fields, allowed):
    """Dictionary-constrained mapping of unfamiliar labels to ACORD terms (one model call)."""
    items = [{"label": f["label"], "section": f["section"], "example": (f["value"] or "; ".join(f["items"]))[:120]}
             for f in fields]
    prompt = ("You map fields from a Lloyd's Market Reform Contract to an insurance data dictionary (ACORD-based). "
              "For each field choose ONE binding from the allowed list, or null if none fits. Never invent a binding. "
              "Also give an indicative Lloyd's Core Data Record field name (plain words) or null, a confidence 0..1, "
              "and a short reason. Return STRICT JSON: an object keyed by the field label, each value "
              '{"binding": <allowed binding or null>, "cdr": <text or null>, "confidence": <0..1>, "why": <text>}. '
              "JSON only.\n\nALLOWED BINDINGS: " + json.dumps(allowed) + "\n\nFIELDS: " + json.dumps(items))
    try:
        out = sql("SELECT ai_query(:ep, :p)", params={"ep": cfg["models"]["extract"], "p": prompt}, cfg=cfg)
        txt = (out[0][0] or "").strip()
        if txt.startswith("```"):
            txt = txt.split("```")[1].lstrip("json").strip()
        s, e = txt.find("{"), txt.rfind("}") + 1
        return json.loads(txt[s:e]) if s >= 0 else {}
    except Exception as ex:
        print(f"    (ai mapping unavailable: {ex})")
        return {}


def confirm_new_schema(cfg, doc_id, name, fields, actor="reviewer"):
    """A person confirmed the proposal -> record the schema (v1) and ingest the document."""
    row = doc_row(cfg, doc_id)
    if row["inbound_state"] != "new_schema":
        raise ValueError("this document is not waiting for schema recognition")
    text = mp.parse_document(cfg, row["stored_path"])
    fp = fingerprint(text)
    fm = {}
    for f in fields:
        if not f.get("include") or not f.get("binding"):
            continue
        ent, attr = f["binding"].split(".", 1)
        spec = {"label": f["source_label"], "labels": [], "section": f["section"], "kind": f["kind"],
                "entity": ent, "attribute": attr, "cdr": f.get("cdr"), "core": bool(f.get("core")),
                "display": f["label"]}
        if f.get("period_part"):
            spec["period_part"] = f["period_part"]
        fm[f["key"]] = spec
    if not fm:
        raise ValueError("no fields selected")
    names = {s["name"] for s in schemas(cfg)}
    if name in names:
        raise ValueError("a schema with that name already exists")
    _record_schema(cfg, name, "v1", fp, fm, actor, doc_id, "schema_confirm", "Confirmed a newly recognised schema")
    sc = {"name": name, "version": "v1", "fingerprint": fp, "field_map": fm}
    d, quotes, points = extract(text, sc)
    _ingest(cfg, doc_id, {"text": text, "d": d, "points": points, "schema": sc}, actor)
    return {"schema": name, "version": "v1", "data_points": len(fm),
            "identified": sum(1 for p in points if p["status"] == "identified")}


# ------------------------------------------------------------------ arrival (reset / new files)
def receive_inbox(cfg):
    """Register every file in the MRC inbox as 'received' (not yet read). Idempotent."""
    F = cfg["full_schema"]
    base = f'{cfg["volume_path"]}/mrc_inbox'
    files = sorted(f.path for f in client(cfg).files.list_directory_contents(base))
    n = 0
    for path in files:
        fname = os.path.basename(path)
        doc_id = f"DOC-{uuid.uuid4().hex[:12]}"
        sql(f"""INSERT INTO {F}.source_document
                SELECT :d,'mrc','—','mrc',:fn,:sp,'received','received',NULL,'v1',NULL,NULL,current_timestamp(),NULL,NULL
                WHERE NOT EXISTS (SELECT 1 FROM {F}.source_document WHERE tenant='mrc' AND stored_path=:sp)""",
            params={"d": doc_id, "fn": fname, "sp": path}, cfg=cfg)
        n += 1
    audit(cfg, "documents_received", "mrc_inbox", "mrc_inbox", detail=f"{n} documents received", actor="intake")
    return n


if __name__ == "__main__":
    cfg = load_config()
    print(intake(cfg))
