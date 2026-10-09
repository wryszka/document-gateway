"""Create (or update) and publish the 'MRC book' AI/BI dashboard over the governed MRC tables.

The same book the in-app dashboard shows, as a native Databricks dashboard: it reads the
same views, so the two always agree. The id is written to config.json (dashboards.mrc) and
the app embeds it on Analytics → "Databricks dashboard".

Run:  PYTHONPATH=. uv run --with databricks-sdk python tools/create_mrc_dashboard.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import ROOT, client, load_config  # noqa: E402

NAME = "Document Gateway — MRC book"


def spec(F):
    book = f"""SELECT e.umr, e.insured_name, e.class_of_business, e.broker_name,
                      regexp_extract(e.slip_leader, 'Syndicate ([0-9]+)', 0) AS slip_leader,
                      e.premium_currency, e.premium_amount, e.signed_lines_total, e.certainty_status,
                      concat(e.schema_name, ' ', e.schema_version) AS schema_version,
                      date_format(d.ingested_at, 'yyyy-MM') AS month,
                      CASE WHEN a.entity_id IS NOT NULL THEN 'No person involved' ELSE 'After a decision by a person' END AS route
               FROM {F}.v_mrc_entities_latest e JOIN {F}.source_document d ON e.source_document_id = d.doc_id
               LEFT JOIN (SELECT DISTINCT entity_id FROM {F}.audit_event WHERE event_type = 'auto_ingested') a
                 ON a.entity_id = d.doc_id"""
    datasets = [
        {"name": "ds_month", "displayName": "Contracts loaded by month",
         "queryLines": [f"SELECT month, route, count(*) AS contracts FROM ({book}) GROUP BY 1, 2 ORDER BY 1"]},
        {"name": "ds_class", "displayName": "Contracts by class",
         "queryLines": [f"SELECT class_of_business, count(*) AS contracts FROM ({book}) GROUP BY 1 ORDER BY 2 DESC"]},
        {"name": "ds_broker", "displayName": "Contracts by broker",
         "queryLines": [f"SELECT broker_name, count(*) AS contracts FROM ({book}) GROUP BY 1 ORDER BY 2 DESC"]},
        {"name": "ds_leader", "displayName": "Slip leaders",
         "queryLines": [f"SELECT slip_leader, count(*) AS contracts FROM ({book}) GROUP BY 1 ORDER BY 2 DESC LIMIT 10"]},
        {"name": "ds_premium", "displayName": "Premium by class and currency",
         "queryLines": [f"""SELECT class_of_business, premium_currency, round(sum(premium_amount), 0) AS premium
                            FROM ({book}) WHERE premium_currency IS NOT NULL GROUP BY 1, 2 ORDER BY 3 DESC"""]},
        {"name": "ds_rules", "displayName": "Market rules failed",
         "queryLines": [f"""SELECT label AS market_rule, count(*) AS contracts FROM {F}.v_mrc_certainty_latest
                            WHERE status = 'fail' GROUP BY 1 ORDER BY 2 DESC"""]},
        {"name": "ds_attention", "displayName": "Contracts that need attention",
         "queryLines": [f"""SELECT b.umr, b.insured_name, b.class_of_business, b.broker_name, c.label AS failed_rule, c.detail
                            FROM ({book}) b JOIN {F}.v_mrc_entities_latest e ON e.umr = b.umr
                            JOIN {F}.v_mrc_certainty_latest c ON c.mrc_id = e.mrc_id AND c.status = 'fail' ORDER BY b.umr"""]},
        {"name": "ds_book", "displayName": "The book",
         "queryLines": [f"""SELECT umr, insured_name, class_of_business, broker_name, slip_leader, premium_currency,
                                   premium_amount, certainty_status, schema_version, month, route FROM ({book}) ORDER BY month DESC, umr"""]},
    ]

    def chart(name, ds, x, y, title, wtype="bar", color=None, w=3, h=6, x0=0, y0=0):
        fields = [{"name": x, "expression": f"`{x}`"}, {"name": y, "expression": f"`{y}`"}]
        enc = {"x": {"fieldName": x, "scale": {"type": "categorical"}},
               "y": {"fieldName": y, "scale": {"type": "quantitative"}}}
        if color:
            fields.append({"name": color, "expression": f"`{color}`"})
            enc["color"] = {"fieldName": color, "scale": {"type": "categorical"}}
        return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {
                    "datasetName": ds, "fields": fields, "disaggregated": True}}],
                "spec": {"version": 3, "widgetType": wtype, "encodings": enc,
                         "frame": {"title": title, "showTitle": True}}},
                "position": {"x": x0, "y": y0, "width": w, "height": h}}

    def table(name, ds, title, cols, w=6, h=7, x0=0, y0=0):
        # Tables need their columns listed (spec version 2) — an empty list imports as invalid.
        return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {
                    "datasetName": ds, "fields": [{"name": c, "expression": f"`{c}`"} for c, _ in cols],
                    "disaggregated": True}}],
                "spec": {"version": 2, "widgetType": "table",
                         "encodings": {"columns": [{"fieldName": c, "displayName": d} for c, d in cols]},
                         "frame": {"title": title, "showTitle": True}}},
                "position": {"x": x0, "y": y0, "width": w, "height": h}}

    layout = [
        chart("w_month", "ds_month", "month", "contracts", "Contracts loaded by month — no person involved vs after a decision", "bar", "route", 6, 6, 0, 0),
        chart("w_class", "ds_class", "class_of_business", "contracts", "Contracts by class of business", "bar", None, 3, 6, 0, 6),
        chart("w_broker", "ds_broker", "broker_name", "contracts", "Contracts by broker", "bar", None, 3, 6, 3, 6),
        chart("w_premium", "ds_premium", "class_of_business", "premium", "Premium by class — per currency (never added across currencies)", "bar", "premium_currency", 3, 6, 0, 12),
        chart("w_leader", "ds_leader", "slip_leader", "contracts", "Most frequent slip leaders", "bar", None, 3, 6, 3, 12),
        chart("w_rules", "ds_rules", "market_rule", "contracts", "Market rules failed", "bar", None, 2, 6, 0, 18),
        table("t_attention", "ds_attention", "Contracts that need attention",
              [("umr", "UMR"), ("insured_name", "Insured"), ("class_of_business", "Class"), ("broker_name", "Broker"),
               ("failed_rule", "Rule failed"), ("detail", "Detail")], 4, 6, 2, 18),
        table("t_book", "ds_book", "The book — every loaded contract",
              [("umr", "UMR"), ("insured_name", "Insured"), ("class_of_business", "Class"), ("broker_name", "Broker"),
               ("slip_leader", "Slip leader"), ("premium_currency", "Currency"), ("premium_amount", "Premium"),
               ("certainty_status", "Market rules"), ("schema_version", "Read with"), ("month", "Loaded"),
               ("route", "How it loaded")], 6, 9, 0, 24),
    ]
    return {"datasets": datasets,
            "pages": [{"name": "book", "displayName": "MRC book", "layout": layout, "pageType": "PAGE_TYPE_CANVAS"}]}


def main():
    from databricks.sdk.service.dashboards import Dashboard
    cfg = load_config()
    w = client(cfg)
    dash = spec(cfg["full_schema"])
    out = os.path.join(ROOT, "dashboards", "mrc_book.lvdash.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(dash, f, indent=1)
    existing = (cfg.get("dashboards") or {}).get("mrc")
    d = Dashboard(display_name=NAME, serialized_dashboard=json.dumps(dash), warehouse_id=cfg["warehouse_id"])
    if existing:
        d = w.lakeview.update(existing, d)
    else:
        d.parent_path = f"/Workspace/Users/{w.current_user.me().user_name}"
        d = w.lakeview.create(d)
    w.lakeview.publish(d.dashboard_id, embed_credentials=True, warehouse_id=cfg["warehouse_id"])
    c = json.load(open(os.path.join(ROOT, "config.json")))
    c.setdefault("dashboards", {})["mrc"] = d.dashboard_id
    json.dump(c, open(os.path.join(ROOT, "config.json"), "w"), indent=2)
    print("DASHBOARD_ID:", d.dashboard_id)
    return d.dashboard_id


if __name__ == "__main__":
    main()
