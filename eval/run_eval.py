"""Phase 5 — MLflow eval of the AI extraction path (first-class demo beat).

The AI path's job is mapping each column to a canonical dictionary field — that is where
hallucination risk lives. Because we generate the documents, the true mapping is free
ground truth (each coverholder layout IS the answer key). This harness runs the AI mapper
over every layout for each candidate model, scores per-field / overall accuracy against
that truth, logs to MLflow, and writes eval_result (which drives the Eval screen).

Run:  uv run --with databricks-sdk,mlflow python eval/run_eval.py
"""
from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import load_config, load_tenant, sql, client  # noqa: E402
from jobs.ingest_pipeline import ai_extract  # noqa: E402

SAMPLE = {"policy_number": "CH-8801-202607-001", "insured_name": "Northwind Logistics",
          "line_of_business": "Commercial Property", "inception_date": "2026-07-03",
          "expiry_date": "2027-07-02", "currency": "GBP", "gross_premium": 12500.00,
          "commission_amount": 1875.00, "risk_country": "GB", "risk_postcode": "E1 4AB"}

# Decoy columns present in the file but NOT in the answer key — the AI must ignore them
# (e.g. it must map gross_premium to the gross column, never to 'Net Premium').
DECOYS = {"Net Premium": 10200.00, "IPT Amount": 1500.00, "Broker Reference": "BRK-77"}

# Eval-only adversarial layouts (terse / abbreviated headers) on top of the real ones.
EVAL_ONLY = {
    "layout_terse": {"policy_number": "Ref", "insured_name": "Client", "line_of_business": "Type",
                     "inception_date": "From", "expiry_date": "To", "currency": "Cur",
                     "gross_premium": "Prem", "commission_amount": "Comm", "risk_country": "Ctry",
                     "risk_postcode": "PCode"},
}


def _rows_for(layout, fields):
    # two ground-truth rows keyed by the layout's own header labels, plus decoy columns
    def row(mult):
        r = {layout[f]: (round(SAMPLE[f] * mult, 2) if isinstance(SAMPLE[f], float) else SAMPLE[f])
             for f in fields}
        r.update(DECOYS)
        return r
    return [row(1.0), row(1.3)]


def run(cfg):
    F = cfg["full_schema"]
    tcfg = load_tenant(cfg, "bordereaux")
    fields = tcfg["logical_fields"]["premium"]
    # each layout is the answer key: field -> true header (skip the _comment key);
    # augment with the eval-only adversarial layouts.
    layouts = {k: v for k, v in tcfg["layouts"].items() if not k.startswith("_")}
    layouts.update(EVAL_ONLY)
    models = [cfg["models"]["extract"], cfg["models"]["eval_challenger"]]

    # MLflow (best-effort; Delta is the source of record for the app).
    ml = None
    try:
        os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", cfg["databricks_profile"])
        import mlflow
        mlflow.set_tracking_uri("databricks")
        me = client(cfg).current_user.me().user_name
        mlflow.set_experiment(f"/Users/{me}/document_gateway_eval")
        ml = mlflow
    except Exception as e:
        print(f"(MLflow unavailable, writing Delta only: {e})")

    run_id = f"EV-{uuid.uuid4().hex[:10]}"
    all_rows = []
    print(f"== eval run {run_id}: {len(models)} models x {len(layouts)} layouts x {len(fields)} fields")
    for model in models:
        per_field = {f: {"c": 0, "t": 0} for f in fields}
        for lname, layout in layouts.items():
            headers = [layout[f] for f in fields] + list(DECOYS.keys())
            ai = ai_extract(cfg, headers, _rows_for(layout, fields), fields, endpoint=model)
            for f in fields:
                pred = (ai.get(f) or {}).get("matched_header")
                per_field[f]["t"] += 1
                if pred == layout[f]:
                    per_field[f]["c"] += 1
        tot_c = sum(v["c"] for v in per_field.values())
        tot_t = sum(v["t"] for v in per_field.values())
        acc = round(tot_c / tot_t, 4) if tot_t else 0.0
        print(f"  {model:<45} mapping accuracy {acc:.1%}  ({tot_c}/{tot_t})")

        mlflow_run_id = ""
        if ml:
            try:
                with ml.start_run(run_name=model) as r:
                    mlflow_run_id = r.info.run_id
                    ml.log_param("model", model)
                    ml.log_param("layouts", len(layouts))
                    ml.log_metric("mapping_accuracy", acc)
                    for f, v in per_field.items():
                        ml.log_metric(f"field_acc__{f}", round(v["c"] / v["t"], 4))
            except Exception as e:
                print(f"    (mlflow log skipped: {e})")

        all_rows.append((run_id, model, "overall", None, tot_c, tot_t, acc, mlflow_run_id))
        for f, v in per_field.items():
            all_rows.append((run_id, model, "field", f, v["c"], v["t"],
                             round(v["c"] / v["t"], 4), mlflow_run_id))

    # persist
    from lib import insert_rows
    cols = [("run_id", "str"), ("model", "str"), ("scope", "str"), ("field", "str"),
            ("correct", "int"), ("total", "int"), ("accuracy", "float"),
            ("mlflow_run_id", "str"), ("created_at", "ts_now")]
    rows = [dict(zip([c for c, _ in cols[:-1]], r)) for r in all_rows]
    insert_rows(f"{F}.eval_result", cols, rows, cfg)
    print(f"== wrote {len(rows)} eval_result rows (run {run_id}).")
    return run_id


if __name__ == "__main__":
    run(load_config())
