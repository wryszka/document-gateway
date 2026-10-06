"""Phase 4 — the Document Gateway MCP tool surface.

MCP-first (standard §8): every stage and read surface is a callable tool, and the app,
a notebook and an orchestrating agent are all clients of the SAME tools — nothing built
twice. These tools wrap the exact functions the app calls (jobs/ingest_pipeline,
jobs/trust_loop, agents/extraction_review), so behaviour can never diverge.

Write authority is bounded server-side: confirm_mapping / reject require an explicit
document id and human-supplied mapping; the review tool only ever advises. No tool lets
an agent invent data or bypass the HITL.

Run as a stdio MCP server:
  uv run --with "mcp[cli]",databricks-sdk,openpyxl python mcp_server/server.py

Note: NOT named `mcp/` on purpose — that would shadow the `mcp` SDK package on sys.path.
"""
from __future__ import annotations

import os
import sys

# Append (not insert-0) repo root so the installed `mcp` SDK resolves before local dirs.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server import MCPServer  # the MCP SDK high-level server (FastMCP-equivalent)

from lib import load_config, load_tenant, sql  # noqa: E402
from jobs import ingest_pipeline as pipe  # noqa: E402
from jobs import trust_loop as tl  # noqa: E402
from agents import extraction_review as review  # noqa: E402

CFG = load_config()
F = CFG["full_schema"]
mcp = MCPServer("document-gateway")


def _fields():
    return load_tenant(CFG, "bordereaux")["logical_fields"]["premium"]


@mcp.tool()
def scan_inbox() -> dict:
    """Process every file in the landing inbox through the trust loop; return state counts."""
    return pipe.process_inbox(CFG)


@mcp.tool()
def ingest_file(path: str) -> dict:
    """Ingest one document at a UC volume path; return its resulting inbound state + lines."""
    return pipe.process_file(CFG, path)


@mcp.tool()
def get_document_status(doc_id: str) -> dict:
    """Return a document's trust state, reconciliation summary and template version."""
    r = sql(f"""SELECT doc_id,counterparty,doc_family,status,inbound_state,template_version,
                       reporting_period,file_name FROM {F}.source_document WHERE doc_id=:d""",
            params={"d": doc_id}, cfg=CFG)
    if not r:
        return {"error": "no such document"}
    k = ["doc_id", "counterparty", "doc_family", "status", "inbound_state",
         "template_version", "reporting_period", "file_name"]
    return dict(zip(k, r[0]))


@mcp.tool()
def propose_schema(doc_id: str) -> dict:
    """For an UNKNOWN-counterparty document, AI-propose a template as mappings INTO the
    dictionary (per-field label + confidence). Read-only — proposes, does not land."""
    return tl.propose_schema(CFG, doc_id)


@mcp.tool()
def confirm_mapping(doc_id: str, field_map: dict | None = None, actor: str = "mcp") -> dict:
    """Confirm the mapping for a quarantined document (HITL act). With field_map -> schema
    recognition for an unknown counterparty (creates template v1); without -> accept the
    proposed remap for a drifted layout (bumps the template version). Then reprocesses."""
    if field_map:
        return tl.confirm_schema(CFG, doc_id, field_map, actor=actor)
    return tl.accept_remap(CFG, doc_id, actor=actor)


@mcp.tool()
def reject_document(doc_id: str, reason: str, actor: str = "mcp") -> dict:
    """Reject a quarantined document with a reason (append-only decision + audit)."""
    return tl.reject_doc(CFG, doc_id, reason, actor=actor)


@mcp.tool()
def review_document(doc_id: str) -> dict:
    """Run the advise-only extraction-review agent on a document; writes findings, lands nothing."""
    return review.review_document(CFG, doc_id)


@mcp.tool()
def query_graph(label: str | None = None, limit: int = 50) -> dict:
    """Read latest assertions from the graph (optionally by entity label, e.g. PremiumBordereauLine)."""
    n = max(1, min(int(limit), 500))
    where = "WHERE label=:l" if label else ""
    params = {"l": label} if label else None
    rows = sql(f"""SELECT node_id,label,extraction_path,confidence,anchor,source_document_id
                   FROM {F}.v_graph_nodes_latest {where} LIMIT {n}""", params=params, cfg=CFG)
    cols = ["node_id", "label", "extraction_path", "confidence", "anchor", "source_document_id"]
    return {"nodes": [dict(zip(cols, r)) for r in rows]}


@mcp.tool()
def get_projection(coverholder: str | None = None) -> dict:
    """Read the typed premium projection (latest/active). Optionally filter by coverholder."""
    where = "WHERE coverholder_name=:c" if coverholder else ""
    params = {"c": coverholder} if coverholder else None
    rows = sql(f"""SELECT coverholder_name, count(*) lines, round(sum(gross_premium),2) gwp
                   FROM {F}.v_premium_bordereau_line_latest {where}
                   GROUP BY coverholder_name ORDER BY gwp DESC""", params=params, cfg=CFG)
    return {"by_coverholder": [{"coverholder_name": r[0], "lines": int(r[1]),
                                "gross_premium": float(r[2])} for r in rows]}


if __name__ == "__main__":
    mcp.run()
