"""Reset the MRC flow to its demo starting state (MRC only — other flows untouched).

Clears the recorded MRC schema and every MRC document, projection, check and graph row,
regenerates the five contracts (dates roll to today) + the cover note, and re-stages them:
5 awaiting recognition, 1 needs review, no schema recorded.

Run:  PYTHONPATH=. uv run --with databricks-sdk,openpyxl python tools/mrc_reset.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import load_config, sql  # noqa: E402

MRC_TABLES = [("template", "doc_family='mrc'"), ("source_document", "tenant='mrc'"),
              ("mrc_entities", "1=1"), ("mrc_extraction", "1=1"), ("mrc_certainty_check", "1=1"),
              ("graph_nodes", "tenant='mrc'"), ("graph_edges", "tenant='mrc'")]


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
    from jobs import mrc_pipeline
    F = cfg["full_schema"]
    # Return the governance trail to origin too, so the Audit screen starts clean (the reset
    # is the one sanctioned exception to append-only — it rebuilds the demo, not real history).
    _sql_retry(f"""DELETE FROM {F}.audit_event WHERE entity_id IN (SELECT doc_id FROM {F}.source_document WHERE tenant='mrc')
            OR entity_type = 'mrc_entities' OR (entity_type = 'template' AND entity_id LIKE '%/mrc')""", cfg)
    _sql_retry(f"DELETE FROM {F}.decision WHERE tenant='mrc'", cfg)
    for t, w in MRC_TABLES:
        _sql_retry(f"DELETE FROM {F}.{t} WHERE {w}", cfg)
    if regenerate:
        generate_mrc.upload(cfg, generate_mrc.generate())
    mrc_pipeline.process_mrc_inbox(cfg)
    states = sql(f"SELECT inbound_state, count(*) FROM {F}.source_document WHERE tenant='mrc' GROUP BY 1", cfg=cfg)
    print("MRC reset:", {k: int(v) for k, v in states})
    return states


if __name__ == "__main__":
    reset(load_config(), regenerate="--no-regenerate" not in sys.argv)
