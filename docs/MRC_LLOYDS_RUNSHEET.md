# MRC run sheet — Lloyd's of London (Corporation, technical audience)

**Slot:** ~30 minutes. **Flow:** Market Reform Contract only (the bordereaux and health-slip flows are not shown).
**Audience:** a Corporation of Lloyd's technical lead — market data and standards, not a syndicate.
**What they should leave with:** *a contract can be read once, checked against market rules, filled into the Core Data Record, and traced back to the wording — on open, governed infrastructure.*

Format per beat: **GO** (where) · **DO** (the one action) · **SAY** (≤20 words) · **IF ASKED / IF SLOW**.

---

## Pre-flight (the morning of, ~10 min)

1. **Reset to the clean start** — open the app → **1. Market Reform Contract** → **Inbox** → **↺ Reset demo** (top right of the Documents card) → Confirm. About half a minute.
   Expected afterwards: **8 documents "Received — not yet read"**, a **Run intake** button, and **1 schema in the repository** (Open Market v1, recorded by "Market data team").
   The button is disabled while any step is running; steps never overlap.
   *Fallback (command line, from the repo):* `PYTHONPATH=. uv run --with databricks-sdk,openpyxl python tools/mrc_reset.py --no-regenerate`
2. **Warm the warehouse** — after the reset, open Schema Repository and Contract Certainty once (the first query after idle is slow). Do **not** press Run intake.
3. **Warm Ask** — on Contracts & Ask, ask one throwaway question (both answers should appear).
4. Keep the app in its own browser window: https://document-gateway-7474656169654171.aws.databricksapps.com → **1. Market Reform Contract**.

**Ordering guards:** press *Run intake* only in beat 2. Review the changed contract in beat 3 and recognise the binding authority in beat 4 — not before.
**Between rehearsals:** press **↺ Reset demo** on the Inbox to start again.

---

## Beat 0 — The question (2 min)
- **GO:** landing page.
- **DO:** nothing — talk.
- **SAY:** "A contract arrives as a PDF. How do we read it once, check it, and trust the data downstream?"
- **IF ASKED** "why three flows?" — the same engine handles bordereaux and renewal slips; today is MRC only.

## Beat 1 — What has arrived, and what we already know (1.5 min)
- **GO:** 1. Market Reform Contract → **Inbox**.
- **DO:** point at the eight received documents and the "1 schema in repository" tile; optionally **View** one PDF.
- **SAY:** "**Eight** documents arrived overnight. We already have **one** schema on file — the open-market MRC."

## Beat 2 — Run intake: three outcomes at once (3 min)
- **GO:** Inbox → **Run intake**.
- **DO:** press it; the banner shows and the rows update on their own (about 90 seconds).
- **SAY:** "Each document is matched on its fingerprint — the title and its sections. Known ones land with no person involved."
- **WHILE IT RUNS:** open **Schema Repository** — "this is the schema we start with: recorded by whom, when, and the 22 data points it reads."
- **THEN SAY:** "**Five** contracts landed on their own. One known layout has changed. One is a document type we have never seen. One isn't a contract."
- **IF SLOW:** stay on Schema Repository and talk; return to the Inbox when ready.

## Beat 3 — A known layout that has changed (3 min)
- **GO:** Inbox → mrc_policy_006 → **Review changes →**.
- **DO:** point at the two renames and the two missing fields; press **Accept & record v2**.
- **SAY:** "Same schema, but this broker renamed two fields and left two out. We accept once — version 2 learns the new labels."
- **SAY (honesty):** "The missing fields stay missing. They're still flagged downstream — accepting doesn't hide a gap."

## Beat 4 — A schema we have never seen (4 min)
- **GO:** Inbox → mrc_binding_authority_007 → **Recognise →**.
- **DO:** point at "known field" rows, then a "model" row (Coverholder → Coverholder.name), then the two rows with no ACORD term; press **Confirm & record schema**.
- **SAY:** "A binding authority. Fields we already know are reused; the model proposes the rest — and says when nothing fits."
- **IF ASKED** "what about Bordereaux Reporting?" — the vocabulary has no term for it today; that is a dictionary extension, recorded once, not a code change.
- **IF ASKED** "is the model deciding?" — it only proposes the mapping; a person confirms, and the values themselves are read by rule.

## Beat 5 — The one that isn't a contract (1 min)
- **GO:** **Inbox** → the cover note row.
- **DO:** **Return to broker** → reason "Full MRC required" → Confirm.
- **SAY:** "Not a contract. Held for a person, never loaded — and the decision is recorded."

## Beat 6 — The repository has learned (1.5 min)
- **GO:** **Schema Repository**.
- **DO:** show the two schemas; open Open Market's v2 data points ("also 'Unique Market Ref'").
- **SAY:** "Two schemas now, and a version history. Every future document with these fingerprints flows straight through."

## Beat 7 — Contract certainty (3 min) — the strongest beat
- **GO:** **Contract Certainty**.
- **DO:** open the red cards.
- **SAY:** "Seven market rules on every contract. The cyber risk is **97.5%** signed; one has no sanctions clause; one has no governing law."
- **IF ASKED** "who wrote the rules?" — plain, versioned rules in the repo; adding one is a config change, not a model.

## Beat 8 — The Core Data Record (3 min)
- **GO:** **Core Data Record**.
- **DO:** point at the completeness number and a row with gaps.
- **SAY:** "Each record field, the MRC section it comes from, and how many contracts supplied it — the gaps are the ones we just saw."
- **SAY (honesty):** "The field names are an indicative crosswalk for discussion — not your published specification."

## Beat 9 — Lineage to the wording (2 min)
- **GO:** **Lineage** → **Cyber Liability · NovaTech**.
- **DO:** point at *Signed lines total*; optionally *Open the original PDF ↗*.
- **SAY:** "Every value shows the line it was read from. **97.5%** is the sum of four signed lines — here they are."

## Beat 10 — Metrics, corrected in place (1 min, optional)
- **GO:** **Metrics**.
- **DO:** change one premium, tab out.
- **SAY:** "Totals stay per currency. A person can correct a value — it's saved, and audited."

## Beat 11 — Ask the contracts (2.5 min)
- **GO:** **Contracts & Ask**.
- **DO:** ask *"Which contracts are not fully signed?"*, then *"What are the exclusions and the deductible on the marine cargo contract?"*
- **SAY:** "Two answers: one from the extracted data with its query shown, one from the contract wording itself."
- **IF SLOW:** the structured answer arrives first; the wording answer follows (allow ~30s).
- **IF ASKED** "what does LMA5218 actually say?" — MRCs reference clauses by number; the wording lives in the LMA clause library. Index that library alongside the contracts and the same assistant quotes it.

## Beat 12 — Audit, and how it's built (1.5 min)
- **GO:** **Audit**.
- **DO:** scroll the trail.
- **SAY:** "Every act — received, matched, flagged, accepted, recognised, returned — is a record. Nothing edited, nothing deleted."
- **CLOSE:** "Open code, your workspace, the same loop for any document the market exchanges."

---

## Cut order (if short of time)
Cut 10 (Metrics) → cut 12 (fold the audit line into the close) → shorten 11 to one question → cut 5. Never cut 2, 3, 4, 7.

## Technical Q&A (likely from this audience)
| Question | Answer |
|---|---|
| How is a schema recognised? | By fingerprint — the document title plus its section headings. Same fingerprint and every field found → straight through; same fingerprint, fields changed → review; no matching fingerprint → schema recognition. |
| What reads the PDF? | `ai_parse_document` in the platform (no external service); values are then read by section headings and field labels. |
| Where is the data? | Governed tables in Unity Catalog — contracts, per-value extraction with source lines, certainty results, audit, decisions. |
| What does the AI do? | Builds the wider entity graph (clauses, limits, insurers) constrained to the ACORD vocabulary; it never supplies a headline number. |
| Two answers in Ask? | Genie writes SQL over the extracted data (query shown); a Knowledge Assistant answers from the PDFs. |
| Could a market participant consume this? | The record is plain tables; Delta Sharing would let a counterparty read them without copying (forward hook, not built). |
| Are these real syndicates? | Real, publicly listed syndicate numbers and managing agents (checked); broker numbers, references and insureds are invented. |
| What if the MRC layout differs? | Shown live (beat 3): same fingerprint, changed fields → flagged with a diff; accepting records v2 with the learned labels; missing fields stay flagged. |
| Is the CDR mapping official? | No — indicative, paraphrased field names for discussion. |
