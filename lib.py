"""Shared helpers for Document Gateway build/deploy scripts.

Single source of: config loading, a parameter-bound SQL runner over the SQL
Statement Execution API, and deploy-state persistence. Every build script and the
orchestrator import from here so there is one connection/SQL path (method: nothing
built twice).

Run scripts with:  uv run --with databricks-sdk python <script>.py
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"


# --------------------------------------------------------------------------- config
def load_config() -> dict[str, Any]:
    """Load config.json and add computed convenience fields."""
    cfg = json.loads(CONFIG_PATH.read_text())
    if os.environ.get("DG_SCHEMA"):  # point a local run at an isolated test copy of the schema
        cfg["schema"] = os.environ["DG_SCHEMA"]
    cfg["full_schema"] = f'{cfg["catalog"]}.{cfg["schema"]}'
    cfg["volume_path"] = f'/Volumes/{cfg["catalog"]}/{cfg["schema"]}/{cfg["volume"]}'
    return cfg


def load_tenant(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    """Load a tenant config file referenced from config.json."""
    rel = cfg["tenants"][name]["config"]
    return json.loads((ROOT / rel).read_text())


def enabled_tenants(cfg: dict[str, Any]) -> list[str]:
    return [t for t, v in cfg["tenants"].items() if v.get("enabled")]


# --------------------------------------------------------------------------- client
_CLIENT = None


def set_client(w) -> None:
    """Inject a WorkspaceClient (e.g. the app's default-auth client in Databricks Apps).
    When set, all sql()/file calls use it instead of the config profile."""
    global _CLIENT
    _CLIENT = w


def client(cfg: dict[str, Any] | None = None):
    """Cached WorkspaceClient. Uses an injected client if set (in-app app SP), else the
    configured CLI profile (build scripts). In Databricks Apps, WorkspaceClient() with no
    profile picks up the app service principal automatically."""
    global _CLIENT
    if _CLIENT is None:
        from databricks.sdk import WorkspaceClient

        cfg = cfg or load_config()
        if os.environ.get("DATABRICKS_APP_DEFAULT_AUTH") or not cfg.get("databricks_profile"):
            _CLIENT = WorkspaceClient()
        else:
            _CLIENT = WorkspaceClient(profile=cfg["databricks_profile"])
    return _CLIENT


# --------------------------------------------------------------------------- SQL
def _param(name: str, value: Any):
    from databricks.sdk.service.sql import StatementParameterListItem

    if value is None:
        return StatementParameterListItem(name=name, value=None)
    if isinstance(value, bool):
        return StatementParameterListItem(name=name, value=str(value).lower(), type="BOOLEAN")
    if isinstance(value, int):
        return StatementParameterListItem(name=name, value=str(value), type="BIGINT")
    if isinstance(value, float):
        return StatementParameterListItem(name=name, value=repr(value), type="DOUBLE")
    return StatementParameterListItem(name=name, value=str(value))


def sql(stmt: str, params: dict[str, Any] | None = None, cfg: dict[str, Any] | None = None,
        warehouse_id: str | None = None) -> list[list[Any]]:
    """Execute a statement and return rows (list of lists). Parameter-bound.

    Use named markers (:name) in `stmt` and pass `params={"name": value}` — never
    string-concatenate untrusted values (DECISIONS D6). Catalog/schema identifiers,
    which can't be parameter markers, come from trusted config and are f-string safe.
    """
    from databricks.sdk.service.sql import StatementState

    cfg = cfg or load_config()
    w = client(cfg)
    wh = warehouse_id or cfg["warehouse_id"]
    plist = [_param(k, v) for k, v in (params or {}).items()] or None

    r = w.statement_execution.execute_statement(
        warehouse_id=wh, statement=stmt, wait_timeout="50s", parameters=plist
    )
    # Poll while pending/running.
    while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)

    if r.status and r.status.state != StatementState.SUCCEEDED:
        msg = r.status.error.message if (r.status and r.status.error) else "unknown error"
        raise RuntimeError(f"SQL failed ({r.status.state}): {msg}\n---\n{stmt[:600]}")

    if r.result and r.result.data_array:
        return r.result.data_array
    return []


def run_batch(statements: Iterable[str], cfg: dict[str, Any] | None = None,
              label: str = "") -> None:
    """Run a sequence of DDL/DML statements, logging progress."""
    cfg = cfg or load_config()
    stmts = [s for s in statements if s and s.strip()]
    for i, s in enumerate(stmts, 1):
        head = " ".join(s.split())[:70]
        print(f"  [{i:>2}/{len(stmts)}] {label} {head}...")
        sql(s, cfg=cfg)


# --------------------------------------------------------------------------- state
def save_state(key: str, value: Any) -> None:
    state = load_state()
    state[key] = value
    STATE_PATH.write_text(json.dumps(state, indent=2))


def load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def insert_rows(table: str, col_exprs: list[tuple[str, str]], rows: list[dict],
                cfg: dict[str, Any] | None = None, chunk: int = 50) -> int:
    """Parameter-bound multi-row INSERT (DoD §8 — bound, not concatenated).

    `col_exprs` is [(column, kind)] where kind is one of:
      'str'|'int'|'float'  -> bound param, plain
      'date'               -> bound param wrapped in to_date(:k)
      'dec'                -> bound param wrapped in cast(:k as decimal(18,2))
      'ts_now'             -> literal current_timestamp() (no value read from row)
    Each row is a dict keyed by column name (ts_now columns are ignored).
    """
    if not rows:
        return 0
    cfg = cfg or load_config()
    cols = [c for c, _ in col_exprs]
    n = 0
    for start in range(0, len(rows), chunk):
        batch = rows[start:start + chunk]
        tuples, params = [], {}
        for i, row in enumerate(batch):
            cells = []
            for c, kind in col_exprs:
                if kind == "ts_now":
                    cells.append("current_timestamp()")
                    continue
                key = f"p{i}_{c}"
                params[key] = row.get(c)
                if kind == "date":
                    cells.append(f"to_date(:{key})")
                elif kind == "dec":
                    cells.append(f"cast(:{key} as decimal(18,2))")
                else:
                    cells.append(f":{key}")
            tuples.append("(" + ",".join(cells) + ")")
        sql(f"INSERT INTO {table} ({','.join(cols)}) VALUES " + ",".join(tuples),
            params=params, cfg=cfg)
        n += len(batch)
    return n


def lit(v: Any) -> str:
    """SQL literal for BUILD-TIME static seed data only (trusted repo content).
    Runtime/user input must use parameter binding via sql(..., params=...)."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"
