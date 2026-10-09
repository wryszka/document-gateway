# MRC run sheet — Lloyd's of London (Corporation, technical audience)

**Slot:** ~30 minutes. **Flow:** Market Reform Contract only (the bordereaux and health-slip flows are not shown).
**Audience:** a Corporation of Lloyd's technical lead — market data and standards, not a syndicate.
**What they should leave with:** *a contract can be read once, checked against market rules, filled into the Core Data Record, and traced back to the wording — on open, governed infrastructure.*

Format per beat: **GO** (where) · **DO** (the one action) · **SAY** (≤20 words) · **IF ASKED / IF SLOW**.

---

## Pre-flight (the morning of, ~10 min)

1. **Reset to the clean start** — open the app → **1. Market Reform Contract** → **Intake** → **↺ Reset demo** (top right of the Documents card) → Confirm. About half a minute.
   Expected afterwards: **8 documents "Received — not yet read"**, a **Run intake** button, and **1 schema in the repository** (Open Market v1, recorded by Priya Natarajan, Market Data Standards, about a year ago).
   The **36 contracts loaded earlier** (over the past year) are kept by Reset — they fill Contracts, the Analytics dashboard and Governance. Today's intake is only the eight in the inbox.
   The button is disabled while any step is running; steps never overlap. **Wait for the banner to clear** (8 received + 1 schema showing) before anything else.
   *Fallback (command line, from the repo):* `PYTHONPATH=. uv run --with databricks-sdk,openpyxl python tools/mrc_reset.py --no-regenerate`
2. **Warm the warehouse** — after the reset, open **Schemas** and **Governance** once (the first query after idle is slow). Do **not** press Run intake.
3. **Warm Ask** — on **Analytics**, press each example question you plan to use once (both answers should appear).
3a. **Leave the MODE switch (bottom left) on yellow CACHED.** In cached mode, an AI answer already given (Ask and the three review agents) is replayed instantly, so no beat waits on a model. LIVE always asks the model. The cache lives in the app's memory: it survives **↺ Reset demo** but not a redeploy. So **do one full rehearsal after the last deploy**, then reset — the agents and Ask answers are then warm for the room.
4. Keep the app in its own browser window: https://document-gateway-7474656169654171.aws.databricksapps.com → **1. Market Reform Contract**.

**Learn** (how it works) is pinned at the bottom of the menu. **The menu follows the story:** **Intake** (what arrived, what needs attention) → **Schemas** (every schema-reading activity, in tabs: Repository · Recognition · Changes · Vocabulary) → **Contracts** (search any contract; open it for everything about it) → **Analytics** (ask the book) → **Governance** (the questions you'll be asked, answered from the data).
**Ordering guards:** press *Run intake* only in beat 2. Review the changed contract in beat 4 and recognise the binding authority in beat 5 — not before.
**Between rehearsals:** press **↺ Reset demo** on Intake to start again. Agent reviews are logged (they show in Governance); a reset clears them.

---

## Beat 0 — The question (2 min)
- **GO:** landing page.
- **DO:** nothing — talk.
- **SAY:** "A contract arrives as a PDF. Today it is read, keyed and checked by hand — often more than once. How do we read it once, check it against market rules, and trust the data downstream?"
- **IF ASKED** "why three flows?" — the same engine handles bordereaux and renewal slips; today is MRC only.

## Beat 1 — What has arrived, and what we already know (1.5 min)
- **GO:** 1. Market Reform Contract → **Intake**.
- **DO:** point at the eight received documents and the "1 schema in repository" tile; optionally **View** one PDF.
- **SAY:** "**Eight** documents arrived overnight. We already have **one** schema on file — the open-market MRC."

## Beat 2 — Run intake: three outcomes at once (3 min)
- **GO:** Intake → **Run intake**.
- **DO:** press it; a banner shows progress and the page stays still (about 90 seconds).
- **SAY:** "Each document is matched on its fingerprint — the title and its sections. Known ones land with no person involved."
- **WHILE IT RUNS:** open **Schemas** → Repository — "this is the schema we start with: recorded by whom, when, and the 22 data points it reads."
- **THEN SAY:** "**Five** contracts landed on their own. One known layout has changed. One is a document type we have never seen. One isn't a contract."
- **IF SLOW:** stay on the Repository and talk; return to Intake when ready.

## Beat 3 — The intake agent: what needs a person (2 min)
- **GO:** Intake → **🤖 Intake review agent** → **Review this intake**.
- **DO:** let it answer (~15 s); point at *Needs attention*.
- **SAY:** "An agent reads what the system already computed and tells the operations lead what needs a person — the 97.5% cyber risk, the missing sanctions clause, the missing governing law, the cover note."
- **SAY (honesty):** "It advises; it can't load or approve anything. Every review is logged with the facts it was given."

## Beat 4 — A known layout that has changed (3 min)
- **GO:** Intake → mrc_policy_006 → **Review changes →** (opens **Schemas → Changes**).
- **DO:** point at the two renames and the two missing fields; show a decision dropdown (rename / map to another field / accept as gap); type a change note; optionally **🤖 Review these changes**; press **Accept & record v2**.
- **SAY:** "Same schema, but this broker renamed two fields and left two out. A person decides each one and says why — version 2 learns the new labels."
- **SAY (honesty):** "The missing fields stay missing. They're still flagged downstream — accepting doesn't hide a gap."

## Beat 5 — A schema we have never seen (4 min)
- **GO:** Intake → mrc_binding_authority_007 → **Recognise →** (opens **Schemas → Recognition**).
- **DO:** point at "known field" rows, then a "model" row (Coverholder → Coverholder.name), then the rows with no ACORD term; type a one-line description; press **🤖 Review this schema**, read one point; press **Confirm & record schema**.
- **SAY:** "A binding authority. Fields we already know are reused; the model proposes the rest; an agent critiques it — and a person records it, with a description."
- **IF ASKED** "what about Bordereaux Reporting?" — the vocabulary has no term for it today; that is a dictionary extension (Schemas → Vocabulary), recorded once, not a code change.
- **IF ASKED** "is the model deciding?" — it only proposes the mapping; a person confirms, and the values themselves are read by rule.

## Beat 6 — The one that isn't a contract (1 min)
- **GO:** **Intake** → the cover note row.
- **DO:** **Return to broker** → reason "Full MRC required" → Confirm.
- **SAY:** "Not a contract. Held for a person, never loaded — and the decision is recorded."

## Beat 7 — The repository has learned (1 min)
- **GO:** **Schemas** → Repository.
- **DO:** show the two schemas, the v2 change note and the description you typed.
- **SAY:** "Two schemas now, a version history, and who recorded each one. Every future document with these fingerprints flows straight through."

## Beat 8 — Contracts: everything about one contract (5 min) — the strongest beat
- **GO:** **Contracts**.
- **DO:** point out the book is ~43 contracts (a year of earlier loads + today's). Type *cyber* in the search — several cyber risks — then *novatech*, or press **Needs attention**; open **NovaTech**. Walk the tabs:
  - **Certainty** — "seven market rules; this one is **97.5%** signed."
  - **Values & lineage** — *Signed lines*: "every value shows the line it was read from — here are the four signed lines."
  - **Core Data Record** — "the record fields this contract supplies, and the gaps."
  - **Document** — the original PDF. **History** — every event for this contract.
- **SAY:** "One place per contract: the checks, every value with its source, the record fields, the wording and the history."
- **SAY (honesty, on CDR):** "The field names are an indicative crosswalk for discussion — not your published specification."

## Beat 9 — Analytics: what's in the book, then ask it (3 min)
- **GO:** **Analytics**.
- **DO:** point at the dashboard first: contracts in the book (a year of earlier loads plus today's), share loaded with no person, share passing every market rule, contracts by month, by class, by broker, slip leaders, rules failed. Then press the example *"Show me all contracts placed by Willis Towers Watson on marine"*.
- **SAY:** "A year of contracts, read once and checked — most landed with no one touching them. Ask it anything: one answer from the data with its query shown, one from the wording."
- **IF SLOW:** the structured answer arrives first; the wording answer follows (allow ~30 s). In CACHED mode a question already asked returns instantly.
- **OPTIONAL:** *Core Data Record completeness →* for the book-wide view; correct a premium in the metrics table (saved and audited).
- **IF ASKED** "what does LMA5218 actually say?" — MRCs reference clauses by number; the wording lives in the LMA clause library. Index that library alongside the contracts and the same assistant quotes it.

## Beat 10 — Governance: answers, not slides (2.5 min)
- **GO:** **Governance**. It opens on today's changed contract (Ashgrove, read with **Open Market v2**).
- **DO:** read the chain top to bottom: *Received* (date, original PDF kept) → *Read with* v2, **recorded by you, today** (your sign-in identity) → *Schema history*: **original v1 approved by Priya Natarajan (Market Data Standards)** a year ago, v2 by you with your change note → *Values*: every value traced to its line → *Market rules* → *AI involvement* → *Who can see it*. Then switch the picker to an earlier contract ("Loaded earlier") to show the same chain for a contract loaded months ago with no one involved.
- **SAY:** "Any contract, any question: who approved the schema it was read with, when the original was approved, who changed it and why, and what the AI did — which is nothing it could decide."
- **THEN:** scroll to *Across the whole book* — each line is an answer with its records behind it (schema approvals, human decisions, agent reviews).
- **CLOSE (the result):** "Five of eight contracts landed with no one touching them. The three exceptions each took one decision, and that decision is now on record, so the next document like it goes straight through. Every value traces to its line in the wording. Open code, your workspace, the same loop for any document the market exchanges." (Full trail: *Audit →*.)
- **IF ASKED** "where does the logic run?" — "The data, schema versions, decisions and audit are governed tables. Reading and Ask are platform services. For this demo the orchestration runs inside the app; in production it moves into scheduled Jobs and Unity Catalog functions, with approvals as platform permissions." (Q&A #13.)

---

## Cut order (if short of time)
Cut 7 (show it inside beat 10) → cut the optional part of 9 → cut 3 (mention the agent in beat 10) → cut 6. Never cut 2, 4, 5, 8.

## Technical Q&A (likely from this audience)
The questions that can't be shown on screen (real scanned documents, endorsements, born-digital placements, scale, cost, a wrong mapping, four-eyes approval) have straight answers in **`docs/MRC_DEMO_QA.md` (tab 2)**.

| Question | Answer |
|---|---|
| How is a schema recognised? | By fingerprint — the document title plus its section headings. Same fingerprint and every field found → straight through; same fingerprint, fields changed → review; no matching fingerprint → schema recognition. |
| What reads the PDF? | `ai_parse_document` in the platform (no external service); values are then read by section headings and field labels. |
| Where is the data? | Governed tables in Unity Catalog — contracts, per-value extraction with source lines, certainty results, audit, decisions. |
| What does the AI do? | Builds the wider entity graph (clauses, limits, insurers) constrained to the ACORD vocabulary and proposes mappings for a new schema; it never supplies a headline number. Review agents (intake, schema) advise only and are logged. |
| Two answers in Ask? | Genie writes SQL over the extracted data (query shown); a Knowledge Assistant answers from the PDFs. |
| Could a market participant consume this? | The record is plain tables; Delta Sharing would let a counterparty read them without copying (forward hook, not built). |
| Are these real syndicates? | Real, publicly listed syndicate numbers and managing agents (checked); broker numbers, references and insureds are invented. |
| What if the MRC layout differs? | Shown live (beat 3): same fingerprint, changed fields → flagged with a diff; accepting records v2 with the learned labels; missing fields stay flagged. |
| Is the CDR mapping official? | No — indicative, paraphrased field names for discussion. |
