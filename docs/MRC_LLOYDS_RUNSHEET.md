# MRC run sheet — Lloyd's of London (Corporation, technical audience)

**Slot:** ~30 minutes. **Flow:** Market Reform Contract only (the bordereaux and health-slip flows are not shown).
**Audience:** a Corporation of Lloyd's technical lead — market data and standards, not a syndicate.
**What they should leave with:** *a contract can be read once, checked against market rules, filled into the Core Data Record, and traced back to the wording — on open, governed infrastructure.*

Format per beat: **GO** (where) · **DO** (the one action) · **SAY** (≤20 words) · **IF ASKED / IF SLOW**.

---

## Pre-flight (the morning of, ~10 min)

1. **Reset to the clean start** (from the repo): `uv run --with databricks-sdk,openpyxl,reportlab python tools/orchestrate.py --reset`
   (or MRC only, faster: `PYTHONPATH=. uv run --with databricks-sdk,openpyxl python tools/mrc_reset.py`).
   Expected Inbox: **5 awaiting recognition, 1 needs review, no schema recorded**.
2. **Warm the warehouse** — open the app, click Inbox, then Schema Recognition once (the first query after idle is slow). Do not press Confirm.
3. **Warm Ask** — on Contracts & Ask, ask one throwaway question (both answers should appear).
4. Open the app in its own browser window: https://document-gateway-7474656169654171.aws.databricksapps.com → **1. Market Reform Contract**.

**Ordering guards:** do not press *Confirm & register* until beat 3. Do not resolve the cover note until beat 4.

---

## Beat 0 — The question (2 min)
- **GO:** landing page.
- **DO:** nothing — talk.
- **SAY:** "A contract arrives as a PDF. How do we read it once, check it, and trust the data downstream?"
- **IF ASKED** "why three flows?" — the same engine handles bordereaux and renewal slips; today is MRC only.

## Beat 1 — The inbox (2 min)
- **GO:** 1. Market Reform Contract → **Inbox**.
- **DO:** point at the tiles.
- **SAY:** "**Five** contracts and **one** cover note arrived. Nothing is recorded yet — the system has never seen an MRC."

## Beat 2 — Recognition against the expected data points (4 min)
- **GO:** **Schema Recognition**.
- **DO:** scroll the checklist; point at one row's source line.
- **SAY:** "These are the **22** data points we expect. Each is found, bound to ACORD, mapped to the Core Data Record, and quoted."
- **IF ASKED** "what if a field is missing?" — it shows *not found*; the contract still lands if the **11 core** points are present, and the gap is visible downstream.
- **IF ASKED** "is the AI deciding?" — no; the values are read deterministically by section and label. The AI builds the wider entity graph and is never the source of a number.

## Beat 3 — Record once, then straight through (3 min)
- **GO:** Schema Recognition → **Confirm & register schema**.
- **DO:** confirm; it opens the Inbox and the contracts flip to *recognised* one by one (about a minute).
- **SAY:** "We confirm once. The schema is recorded — every contract that matches now flows through without a person."
- **WHILE IT RUNS:** open **Schema Repository** — "recorded by whom, when, which data points, version 1."
- **IF SLOW:** stay on Schema Repository and talk; return to Inbox when ready.

## Beat 4 — The one that doesn't match (2 min)
- **GO:** **Inbox** → the cover note row.
- **DO:** **Return to broker** → reason "Full MRC required" → Confirm.
- **SAY:** "This isn't a contract. It's held for a person, never loaded — and the decision is recorded."

## Beat 5 — Contract certainty (4 min) — the strongest beat
- **GO:** **Contract Certainty**.
- **DO:** open the two red cards.
- **SAY:** "Seven market rules on every contract. Two fail: the cyber risk is **97.5%** signed, and one has no sanctions clause."
- **IF ASKED** "who wrote the rules?" — they're plain, versioned rules in the repo; adding one is a config change, not a model.
- **IF ASKED** "would it stop binding?" — today it flags; the same rule could gate a downstream step.

## Beat 6 — The Core Data Record (4 min)
- **GO:** **Core Data Record**.
- **DO:** point at the completeness number and one row.
- **SAY:** "Each record field, the MRC section it comes from, and how many contracts supplied it — **100%** here."
- **SAY (honesty):** "The field names are an indicative crosswalk for discussion — not your published specification."
- **IF ASKED** "could you map to the real CDR?" — yes; the mapping is one column per data point in a config file.

## Beat 7 — Lineage to the wording (2 min)
- **GO:** **Lineage** (or *lineage →* on a contract).
- **DO:** choose the cyber contract; point at *Signed lines total*.
- **SAY:** "Every value shows the line it was read from. **97.5%** is the sum of four signed lines — here they are."

## Beat 8 — Metrics, corrected in place (2 min)
- **GO:** **Metrics**.
- **DO:** change one premium, tab out.
- **SAY:** "Totals stay per currency. A person can correct a value — it's saved, and the change is audited."

## Beat 9 — Ask the contracts (3 min)
- **GO:** **Contracts & Ask**.
- **DO:** ask *"Which contracts are not fully signed?"*, then *"What are the exclusions and the deductible on the marine cargo contract?"*
- **SAY:** "Two answers: one from the extracted data with its query shown, one from the contract wording itself."
- **IF SLOW:** the structured answer arrives first; the wording answer follows (allow ~30s).
- **IF ASKED** "what does LMA5218 actually say?" — MRCs reference clauses by number; the wording lives in the LMA clause library. Index that library alongside the contracts and the same assistant quotes it.

## Beat 10 — Audit, and how it's built (2 min)
- **GO:** **Audit**.
- **DO:** scroll the trail.
- **SAY:** "Every act — recognise, record, ingest, flag, correct, return — is a record. Nothing edited, nothing deleted."
- **CLOSE:** "Open code, your workspace, the same loop for any document the market exchanges."

---

## Cut order (if short of time)
Cut 8 (Metrics) → cut 10 (fold the audit line into the close) → shorten 9 to one question. Never cut 2, 3, 5, 6.

## Technical Q&A (likely from this audience)
| Question | Answer |
|---|---|
| What reads the PDF? | `ai_parse_document` in the platform (no external service); values are then read by section headings and field labels. |
| Where is the data? | Governed tables in Unity Catalog — contracts, per-value extraction with source lines, certainty results, audit, decisions. |
| What does the AI do? | Builds the wider entity graph (clauses, limits, insurers) constrained to the ACORD vocabulary; it never supplies a headline number. |
| Two answers in Ask? | Genie writes SQL over the extracted data (query shown); a Knowledge Assistant answers from the PDFs. |
| Could a market participant consume this? | The record is plain tables; Delta Sharing would let a counterparty read them without copying (forward hook, not built). |
| Are these real syndicates? | Real, publicly listed syndicate numbers and managing agents (checked); broker numbers, references and insureds are invented. |
| What if the MRC layout differs? | It doesn't match the recorded schema, so it is held for review rather than loaded. Versioning a changed layout (v2, confirm once) is how the bordereaux flow already works; for MRC it's a next step, not built. |
| Is the CDR mapping official? | No — indicative, paraphrased field names for discussion. |
