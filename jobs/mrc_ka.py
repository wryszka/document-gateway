"""T3 — Knowledge Assistant over the MRC PDFs (the unstructured half of dual retrieval).

Lifted from insurance-mrc-poc: create a Knowledge Assistant, point a FILES knowledge
source at the mrc_inbox volume, sync, wait for ACTIVE, and write the serving endpoint
name into config.json (genie.mrc_ka_endpoint). The app's /api/mrc/ask queries this
endpoint alongside Genie.

Run:  uv run --with databricks-sdk python jobs/mrc_ka.py
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import load_config, client, ROOT  # noqa: E402

KA_NAME = "Document Gateway — MRC Assistant"
KA_DESC = "Knowledge assistant over synthetic Lloyd's Market Reform Contract PDFs — clause text, coverage, exclusions."
KA_INSTR = ("You answer questions about Lloyd's Market Reform Contracts (MRC v3). Cite policy "
            "numbers and UMRs; quote clause references (e.g. LMA5218); state limits with currency, "
            "amount and basis; note which exclusions apply to which class.")


def main():
    cfg = load_config()
    w = client(cfg)
    vol = f'{cfg["volume_path"]}/mrc_inbox'
    try:
        from databricks.sdk.service.knowledgeassistants import (
            KnowledgeAssistant, KnowledgeSource, FilesSpec, KnowledgeAssistantState)
    except Exception as e:
        print(f"KA SDK unavailable ({e}); deferring KA (Genie half of dual retrieval still works).")
        return None

    kas = list(w.knowledge_assistants.list_knowledge_assistants())
    ka = next((k for k in kas if k.display_name == KA_NAME), None)
    if not ka:
        ka = w.knowledge_assistants.create_knowledge_assistant(
            KnowledgeAssistant(display_name=KA_NAME, description=KA_DESC, instructions=KA_INSTR))
        print(f"created KA {ka.name}")
    srcs = list(w.knowledge_assistants.list_knowledge_sources(parent=ka.name))
    if not any(s.display_name == "MRC PDFs" for s in srcs):
        w.knowledge_assistants.create_knowledge_source(
            parent=ka.name, knowledge_source=KnowledgeSource(
                display_name="MRC PDFs", description="MRC v3 PDFs from the mrc_inbox volume",
                source_type="FILES", files=FilesSpec(path=vol)))
        print("added FILES source")
    if not any(s.display_name == "MRC archive PDFs" for s in srcs):  # contracts loaded before today
        w.knowledge_assistants.create_knowledge_source(
            parent=ka.name, knowledge_source=KnowledgeSource(
                display_name="MRC archive PDFs", description="Earlier MRC v3 PDFs from the mrc_archive volume",
                source_type="FILES", files=FilesSpec(path=f'{cfg["volume_path"]}/mrc_archive')))
        print("added archive FILES source")
    w.knowledge_assistants.sync_knowledge_sources(name=ka.name)
    print("sync triggered; waiting for ACTIVE (up to 10 min)...")

    endpoint = None
    start = time.time()
    while time.time() - start < 600:
        st = w.knowledge_assistants.get_knowledge_assistant(ka.name)
        if st.state == KnowledgeAssistantState.ACTIVE:
            endpoint = st.endpoint_name
            break
        if str(st.state) == "FAILED":
            print(f"KA failed: {getattr(st, 'error_info', '')}")
            return None
        time.sleep(15)

    if endpoint:
        c = json.load(open(os.path.join(ROOT, "config.json")))
        c.setdefault("genie", {})["mrc_ka_endpoint"] = endpoint
        json.dump(c, open(os.path.join(ROOT, "config.json"), "w"), indent=2)
        print(f"KA ACTIVE, endpoint={endpoint}; wrote genie.mrc_ka_endpoint -> config.json")
    else:
        print("KA not ACTIVE within timeout; Genie half still works. Re-run to finish.")
    return endpoint


if __name__ == "__main__":
    main()
