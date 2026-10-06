"""One-command build orchestrator — the method's "config.json + one orchestrator run" bar.

Reads config.json and runs the end-to-end build against the configured workspace:

  1. schema / data plane   (data/build_schema.py)
  2. seed templates        (data/seed_templates.py)   established coverholders only
  3. synthetic documents   (data/generate_docs.py)    deterministic; upload to landing
  4. initial ingest        (jobs/ingest_pipeline)     lands the four inbound states
  5. app grants + deploy   (--deploy)                 grant the app SP + push the app

The pristine state deliberately leaves the drifted + unknown drops QUARANTINED so the
presenter performs the accept-remap and schema-recognition live in the room.

Usage:
  uv run --with databricks-sdk,openpyxl,reportlab python tools/orchestrate.py            # steps 1-4
  uv run --with databricks-sdk,openpyxl,reportlab python tools/orchestrate.py --deploy   # + app deploy
  uv run --with databricks-sdk,openpyxl,reportlab python tools/orchestrate.py --reset    # rebuild data
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lib import load_config, client, sql, save_state  # noqa: E402


def step(n, title):
    print(f"\n{'='*70}\n== STEP {n}: {title}\n{'='*70}")


# Mutable data cleared on --reset (dictionary + eval history are preserved).
RESET_TABLES = ["source_document", "graph_nodes", "graph_edges", "premium_bordereau_line",
                "claim_bordereau_line", "mrc_entities", "mrc_extraction", "mrc_certainty_check", "renewal_inputs", "audit_event",
                "decision", "reviewer_finding", "template"]


def clear_inbox(cfg):
    w = client(cfg)
    for sub in ("inbox", "mrc_inbox", "slip_inbox"):
        try:
            for f in w.files.list_directory_contents(f'{cfg["volume_path"]}/{sub}'):
                w.files.delete(f.path)
        except Exception:
            pass  # inbox may not exist yet


def reset_data(cfg):
    F = cfg["full_schema"]
    print("  clearing mutable data (dictionary + eval history preserved) + inbox")
    for t in RESET_TABLES:
        try:
            sql(f"TRUNCATE TABLE {F}.{t}", cfg=cfg)
        except Exception as e:
            print(f"    (skip {t}: {e})")
    clear_inbox(cfg)


def build_all(cfg, reset=False):
    from data import build_schema, seed_templates, generate_docs
    from jobs import ingest_pipeline

    step(1, "schema / data plane")
    build_schema.build(cfg)

    if reset:
        step("1b", "reset — restore pristine state, roll dates to today")
        reset_data(cfg)
    else:
        clear_inbox(cfg)  # avoid stale drops from a previous as_of accumulating

    step(2, "seed templates (established coverholders; premium + claims)")
    seed_templates.seed(cfg)

    step(3, "generate + upload synthetic documents (premium + claims, months rolled to today)")
    manifest = generate_docs.generate(cfg)
    generate_docs.upload(cfg, manifest)

    step(4, "initial ingest (four inbound states)")
    summary = ingest_pipeline.process_inbox(cfg)
    save_state("inbox_summary", summary)

    if cfg["tenants"].get("health_slip", {}).get("enabled"):
        step("4b", "Health-slip tenant (config-port) — generate + generic ingest")
        generate_docs.upload_slips(cfg, generate_docs.generate_slips(cfg))
        ingest_pipeline.process_inbox(cfg, tenant_name="health_slip", subdir="slip_inbox")

    if cfg["tenants"].get("mrc", {}).get("enabled"):
        step("4c", "MRC tenant — generate PDFs + prose ingestion")
        from data import generate_mrc
        from jobs import mrc_pipeline
        generate_mrc.upload(cfg, generate_mrc.generate())
        mrc_pipeline.process_mrc_inbox(cfg)

    print("\nPristine state ready. Drift + unknown remain quarantined for the live demo acts.")


def grant_app_sp(cfg):
    """Grant the app service principal least-privilege access."""
    w = client(cfg)
    app = w.apps.get(cfg["app_name"])
    sp = app.service_principal_client_id or app.service_principal_name
    F = cfg["full_schema"]
    print(f"  granting app SP {sp} on {F} + catalog + volume")
    sql(f"GRANT USE CATALOG ON CATALOG {cfg['catalog']} TO `{sp}`", cfg=cfg)
    sql(f"GRANT USE SCHEMA, SELECT, MODIFY, EXECUTE, READ VOLUME, WRITE VOLUME "
        f"ON SCHEMA {F} TO `{sp}`", cfg=cfg)
    # Warehouse CAN_USE via permissions API.
    try:
        from databricks.sdk.service.sql import WarehouseAccessControlRequest, WarehousePermissionLevel
        w.warehouses.set_permissions(
            warehouse_id=cfg["warehouse_id"],
            access_control_list=[WarehouseAccessControlRequest(
                service_principal_name=sp, permission_level=WarehousePermissionLevel.CAN_USE)])
    except Exception as e:
        print(f"    (warehouse grant note: {e})")
    # The MRC ask-surface calls the Knowledge Assistant endpoint as the app SP.
    ka = cfg.get("genie", {}).get("mrc_ka_endpoint")
    if ka:
        try:
            eid = w.serving_endpoints.get(ka).id
            w.api_client.do("PATCH", f"/api/2.0/permissions/serving-endpoints/{eid}", body={
                "access_control_list": [{"service_principal_name": sp, "permission_level": "CAN_QUERY"}]})
            print(f"  granted CAN_QUERY on {ka}")
            ka_id = cfg.get("genie", {}).get("mrc_ka_id")
            if ka_id:  # the endpoint also checks the Knowledge Assistant object itself
                w.api_client.do("PATCH", f"/api/2.0/permissions/knowledge-assistants/{ka_id}", body={
                    "access_control_list": [{"service_principal_name": sp, "permission_level": "CAN_QUERY"}]})
                print(f"  granted CAN_QUERY on knowledge assistant {ka_id}")
        except Exception as e:
            print(f"    (KA endpoint grant note: {e})")
    return sp


def deploy_app(cfg):
    step(5, "app grants + deploy")
    grant_app_sp(cfg)
    profile = cfg["databricks_profile"]
    ws_path = f"/Workspace/Users/{_me(cfg)}/document-gateway-src"
    print(f"  syncing repo -> {ws_path}")
    subprocess.run(["databricks", "--profile", profile, "sync", ".", ws_path], cwd=ROOT, check=True)
    print("  deploying app")
    subprocess.run(["databricks", "--profile", profile, "apps", "deploy", cfg["app_name"],
                    "--source-code-path", ws_path], cwd=ROOT, check=True)
    url = client(cfg).apps.get(cfg["app_name"]).url
    save_state("app_url", url)
    print(f"  app URL: {url}")


def _me(cfg):
    return client(cfg).current_user.me().user_name


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", action="store_true", help="also grant + deploy the app")
    ap.add_argument("--reset", action="store_true", help="rebuild synthetic data")
    args = ap.parse_args()
    cfg = load_config()
    build_all(cfg, reset=args.reset)
    if args.deploy:
        deploy_app(cfg)
    print("\n== orchestrator complete.")
