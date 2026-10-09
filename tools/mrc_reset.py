"""Reset the MRC flow to its demo starting state (MRC only — other flows untouched).

Clears the MRC schemas and today's inbox with every projection, check, graph row, decision and
audit event it produced (contracts loaded before today, in mrc_archive/, are kept); regenerates the PDFs if asked (dates roll to today); records the open-market
schema (v1) and registers all eight documents as received, ready for Run intake.

Run:  PYTHONPATH=. uv run --with databricks-sdk,openpyxl python tools/mrc_reset.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import load_config, sql  # noqa: E402

# Contracts loaded before today live in the volume's mrc_archive/ folder (tools/mrc_history.py).
# Reset clears today's inbox and everything it produced, and leaves those earlier contracts alone.
def _hist(F):
    docs = f"(SELECT doc_id FROM {F}.source_document WHERE tenant='mrc' AND stored_path LIKE '%/mrc_archive/%')"
    mrcs = f"(SELECT mrc_id FROM {F}.mrc_entities WHERE source_document_id IN {docs})"
    return docs, mrcs


def _mrc_tables(F):
    docs, _ = _hist(F)
    keep = f"source_document_id NOT IN {docs}"
    return [("template", "doc_family='mrc'"), ("mrc_schema_note", "1=1"), ("mrc_agent_note", "1=1"),
            ("mrc_entities", keep), ("mrc_extraction", keep), ("mrc_certainty_check", keep),
            ("graph_nodes", f"tenant='mrc' AND {keep}"), ("graph_edges", f"tenant='mrc' AND {keep}"),
            ("source_document", "tenant='mrc' AND stored_path NOT LIKE '%/mrc_archive/%'")]  # last: the others read it


def _sql_retry(stmt, cfg):
    """A DELETE can report a conflict with its own committed retry; one more try is safe
    because every statement here is idempotent."""
    import time
    for attempt in range(3):
        try:
            return sql(stmt, cfg=cfg)
        except RuntimeError as e:
            if "CONCURRENT" not in str(e) or attempt == 2:
                raise
            time.sleep(3)


def reset(cfg, regenerate=True):
    from data import generate_mrc
    from jobs import mrc_schemas
    F = cfg["full_schema"]
    # Return the governance trail to origin too, so the Audit screen starts clean (the reset
    # is the one sanctioned exception to append-only — it rebuilds the demo, not real history).
    docs, mrcs = _hist(F)
    _sql_retry(f"""DELETE FROM {F}.audit_event WHERE
            (entity_id IN (SELECT doc_id FROM {F}.source_document WHERE tenant='mrc')
             OR entity_type IN ('mrc_entities', 'mrc_inbox', 'mrc_agent_note') OR (entity_type = 'template' AND entity_id LIKE '%/mrc'))
            AND entity_id NOT IN {docs} AND entity_id NOT IN {mrcs}""", cfg)
    _sql_retry(f"""DELETE FROM {F}.decision WHERE tenant='mrc'
            AND coalesce(source_document_id, '') NOT IN {docs}""", cfg)
    for t, w in _mrc_tables(F):
        _sql_retry(f"DELETE FROM {F}.{t} WHERE {w}", cfg)
    if regenerate:
        generate_mrc.upload(cfg, generate_mrc.generate())
    # The demo starts with one schema already in the repository, and every document received
    # but not yet read — pressing Run intake does the reading and routing live.
    mrc_schemas.preregister_open_market(cfg)
    from tools import mrc_history
    if mrc_history.present(cfg) == 0:   # first reset on a fresh schema: load the earlier contracts
        mrc_history.seed(cfg)
    mrc_history.backdate_v1(cfg, mrc_history.build()[1])
    mrc_schemas.receive_inbox(cfg)
    states = sql(f"""SELECT inbound_state, count(*) FROM {F}.source_document WHERE tenant='mrc'
                     AND stored_path LIKE '%/mrc_inbox/%' GROUP BY 1""", cfg=cfg)
    print("MRC reset:", {k: int(v) for k, v in states})
    return states


if __name__ == "__main__":
    reset(load_config(), regenerate="--no-regenerate" not in sys.argv)
