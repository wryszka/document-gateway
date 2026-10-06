"""Phase 2 — seed the template registry for established coverholders.

One append-only template per established coverholder (premium_bordereau, v1). The
template's expected_anchors (header labels) are the fingerprint; field_map maps each
logical field to that coverholder's own column label. New coverholders (status=new)
get NO template on purpose — they land as the 'unknown' inbound state and go through
schema recognition.

Run:  uv run --with databricks-sdk python data/seed_templates.py
"""
from __future__ import annotations

import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import load_config, load_tenant, sql, lit  # noqa: E402


def seed(cfg):
    F = cfg["full_schema"]
    tcfg = load_tenant(cfg, "bordereaux")
    layouts = tcfg["layouts"]
    # (family, logical-fields key, roster layout key)
    families = [("premium_bordereau", "premium", "premium_layout"),
                ("claims_bordereau", "claims", "claims_layout")]

    seeded = 0
    for ch in tcfg["coverholders"]["roster"]:
        if ch.get("status") == "new":
            continue  # no template -> unknown inbound state (schema recognition)
        name = ch["name"]
        for family, fkey, layout_key in families:
            fields = tcfg["logical_fields"][fkey]
            exists = sql(
                f"SELECT count(*) FROM {F}.template WHERE counterparty=:c AND doc_family=:f",
                params={"c": name, "f": family}, cfg=cfg)
            if exists and int(exists[0][0]) > 0:
                continue
            layout = layouts[ch[layout_key]]
            field_map = {lf: layout[lf] for lf in fields}
            sql(
                f"""INSERT INTO {F}.template
                    (template_id, tenant, counterparty, doc_family, template_version,
                     expected_anchors, field_map, field_count, status, created_by, created_at)
                    VALUES (:id,'bordereaux',:c,:f,'v1',:anchors,:fmap,:n,'active','seed',current_timestamp())""",
                params={"id": f"TPL-{uuid.uuid4().hex[:8]}", "c": name, "f": family,
                        "anchors": json.dumps(list(field_map.values())),
                        "fmap": json.dumps(field_map), "n": len(fields)}, cfg=cfg)
            seeded += 1
            print(f"  template v1 seeded: {name} ({family}) — {len(fields)} fields, layout {ch[layout_key]}")

    # Health-slip tenant (config-port): seed one renewal_slip template for the carrier.
    if cfg["tenants"].get("health_slip", {}).get("enabled"):
        h = load_tenant(cfg, "health_slip")
        carrier, family = h["carrier"], "renewal_slip"
        fields = h["logical_fields"]["renewal"]
        exists = sql(f"SELECT count(*) FROM {F}.template WHERE counterparty=:c AND doc_family=:f",
                     params={"c": carrier["name"], "f": family}, cfg=cfg)
        if not (exists and int(exists[0][0]) > 0):
            layout = h["layouts"][carrier["layout"]]
            field_map = {lf: layout[lf] for lf in fields}
            sql(f"""INSERT INTO {F}.template
                    (template_id, tenant, counterparty, doc_family, template_version,
                     expected_anchors, field_map, field_count, status, created_by, created_at)
                    VALUES (:id,'health_slip',:c,:f,'v1',:anchors,:fmap,:n,'active','seed',current_timestamp())""",
                params={"id": f"TPL-{uuid.uuid4().hex[:8]}", "c": carrier["name"], "f": family,
                        "anchors": json.dumps(list(field_map.values())),
                        "fmap": json.dumps(field_map), "n": len(fields)}, cfg=cfg)
            seeded += 1
            print(f"  template v1 seeded: {carrier['name']} ({family}) — {len(fields)} fields")
    print(f"== seeded {seeded} templates (new coverholders intentionally have none).")


if __name__ == "__main__":
    seed(load_config())
