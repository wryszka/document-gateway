"""The market standard the gateway reads to — Lloyd's MRC v3 — as a versioned, visible record.

The standard is the structure a Market Reform Contract follows: its title, its sections, the
data points under each (with the label as written in the document, the ACORD term it binds to
and the indicative Core Data Record field), and the market rules checked against it. Until now
it was implied by the open-market schema; here it is its own append-only record in
`mrc_standard`, so anyone can see exactly which version is in force and who recorded it.

When the market publishes the next version (say MRC v4), a person drafts it from the current
one — renaming labels, adding or removing data points and sections — and records it with a
change note. Recording it also records the matching open-market schema in the repository, so
documents laid out to the new version are recognised by their fingerprint from then on. Rules
are code: a new rule is a reviewed change in the repository, not an edit here.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import sql  # noqa: E402
from jobs.ingest_pipeline import audit  # noqa: E402

STANDARD = "Lloyd's Market Reform Contract (MRC)"
REFERENCE = ("The MRC is the London market's standard placing contract, maintained by the London Market Group "
             "with the LMA. Version 3 sections: Risk Details, Information, Security Details, Subscription "
             "Agreement, Fiscal and Regulatory, Broker Remuneration and Deductions. This record holds the "
             "structure the gateway reads; it is not a copy of the published guidance.")
LIST_KEYS = {"clauses", "exclusions", "headline_limit"}


_READY: set = set()


def ensure(cfg):
    """Create the table if it is missing. Built by the schema owner (data/build_schema.py or the
    first CLI run); the app's service principal only needs to read and write it."""
    F = cfg["full_schema"]
    if F in _READY:
        return
    if sql(f"SHOW TABLES IN {F} LIKE 'mrc_standard'", cfg=cfg):
        _READY.add(F)
        return
    sql(f"""CREATE TABLE IF NOT EXISTS {F}.mrc_standard (
              standard STRING, version STRING COMMENT 'v3, v4, ... append-only',
              spec STRING COMMENT 'JSON: title, sections, data points (label, ACORD term, CDR field, required), rules',
              change_note STRING, created_by STRING, created_at TIMESTAMP)
            COMMENT 'The market standard (Lloyd''s MRC) the gateway reads to, one row per recorded version.'""", cfg=cfg)


def _v3_spec(cfg):
    from jobs import mrc_schemas as ms
    from jobs import mrc_pipeline as mp
    fm = ms.open_market_field_map(cfg)
    sections = ["Contract header", "RISK DETAILS", "INFORMATION", "SECURITY DETAILS", "SUBSCRIPTION AGREEMENT",
                "FISCAL AND REGULATORY", "BROKER REMUNERATION AND DEDUCTIONS"]
    pts = [{"key": k, "display": v["display"], "label": v.get("label") or v["display"], "section": v["section"],
            "acord": f"{v['entity']}.{v['attribute']}", "cdr": v.get("cdr"), "required": True,
            "core": bool(v.get("core"))} for k, v in fm.items()]
    rules = [{"id": r["id"], "label": r["label"]} for r in mp._tenant(cfg).get("certainty_checks", [])]
    return {"title": ms.TITLE, "sections": sections, "data_points": pts, "rules": rules, "reference": REFERENCE}


def seed(cfg, actor=None, at=None):
    """Record MRC v3 if no version is on record (dated with the open-market schema v1)."""
    ensure(cfg)
    F = cfg["full_schema"]
    if int(sql(f"SELECT count(*) FROM {F}.mrc_standard", cfg=cfg)[0][0]):
        return False
    from tools.mrc_history import V1_BY, build
    at = at or build()[1]
    sql(f"INSERT INTO {F}.mrc_standard VALUES (:s, 'v3', :j, :n, :a, to_timestamp(:t))",
        params={"s": STANDARD, "j": json.dumps(_v3_spec(cfg)), "n": "MRC v3 recorded as the standard the gateway reads to.",
                "a": actor or V1_BY, "t": at.strftime("%Y-%m-%d %H:%M:%S")}, cfg=cfg)
    return True


def versions(cfg):
    ensure(cfg)
    F = cfg["full_schema"]
    rows = sql(f"SELECT version, spec, change_note, created_by, cast(created_at AS STRING) FROM {F}.mrc_standard ORDER BY created_at",
               cfg=cfg)
    return [{"version": v, "spec": json.loads(j), "change_note": n, "created_by": b, "created_at": t} for v, j, n, b, t in rows]


def _schema_name(version):
    return f"Lloyd's MRC {version} — Open Market (ACORD)"


def _field_map(points):
    fm = {}
    for p in points:
        key = p["key"]
        kind = ("security" if key == "insurers" else "signed_total" if key == "signed_lines_total"
                else "list" if key in LIST_KEYS or p.get("list") else "field")
        ent, _, attr = (p.get("acord") or ".").partition(".")
        spec = {"label": p["label"], "labels": [], "section": p["section"], "kind": kind, "entity": ent or None,
                "attribute": attr or None, "cdr": p.get("cdr"), "core": bool(p.get("core")), "display": p.get("display") or p["label"]}
        if key in ("inception_date", "expiry_date"):
            spec["period_part"] = "start" if key == "inception_date" else "end"
        fm[key] = spec
    return fm


def record(cfg, version, spec, change_note, actor, create_schema=True):
    """Record a new version of the standard (append-only) and, by default, the open-market schema
    for it — so documents laid out to that version are recognised from now on."""
    from jobs import mrc_schemas as ms
    ensure(cfg)
    F = cfg["full_schema"]
    version = version.strip()
    if any(v["version"] == version for v in versions(cfg)):
        raise ValueError(f"{version} is already on record — versions are never edited")
    pts = [p for p in spec.get("data_points", []) if (p.get("label") or "").strip()]
    for i, p in enumerate(pts):
        p["key"] = p.get("key") or f"dp_{i + 1}_" + "".join(ch for ch in p["label"].lower() if ch.isalnum())[:24]
    spec = {**spec, "data_points": pts}
    sql(f"INSERT INTO {F}.mrc_standard VALUES (:s, :v, :j, :n, :a, current_timestamp())",
        params={"s": STANDARD, "v": version, "j": json.dumps(spec), "n": change_note, "a": actor}, cfg=cfg)
    audit(cfg, "standard_recorded", "mrc_standard", f"MRC {version}", detail=f"{STANDARD} {version}: {len(pts)} data points",
          actor=actor)
    schema = None
    if create_schema:
        fp = {"title": spec.get("title") or ms.TITLE,
              "sections": sorted(s for s in spec.get("sections", []) if s != "Contract header")}
        schema = _schema_name(version)
        ms._record_schema(cfg, schema, "v1", fp, _field_map(pts), actor, None, "schema_confirm",
                          f"Recorded from the market standard MRC {version}",
                          description=f"Lloyd's open-market MRC {version}, recorded from the market standard.",
                          change_note=change_note)
    return {"version": version, "data_points": len(pts), "schema": schema}


def clear_drafts(cfg):
    """Reset: keep MRC v3 only (re-seeded if missing)."""
    ensure(cfg)
    sql(f"DELETE FROM {cfg['full_schema']}.mrc_standard WHERE version <> 'v3'", cfg=cfg)
    seed(cfg)
