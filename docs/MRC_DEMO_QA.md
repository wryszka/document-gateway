# MRC demo — Q&A (tab 2 of the run material)

Companion to `docs/MRC_LLOYDS_RUNSHEET.md` (tab 1). These are the questions that **can't be fully shown on screen**, with a straight answer for each. Gathered from the 9-agent review panel on 2026-10-08 (`docs/REVIEW/REVIEW_REPORT_2026-10-08.md`). "Beat" says where in the run the question usually comes up.

## Real-world documents

| # | Question | Straight answer | Beat |
|---|---|---|---|
| 1 | These PDFs are clean and generated. What about a real broker's MRC — scanned, skewed, retyped? | `ai_parse_document` reads scanned and image PDFs as well as text ones, so a scan still produces text. If headings come out damaged, the fingerprint won't match. The document then goes to schema recognition for a person; it is never loaded silently. We haven't measured accuracy on a real inbox. The honest next step is to run a sample of your own MRCs in your workspace and score it. | 2, 5 |
| 2 | Endorsements and addenda change the contract after it's bound. | Not in this demo. The design extends naturally: an endorsement becomes a document type linked to the contract by its Unique Market Reference (UMR), and it adds a new version of the values it changes. The original stays readable, because records are append-only. | 8 |
| 3 | MRCs are increasingly born digital (placing platforms, structured data). Why parse PDFs at all? | Agreed — structured data should be used wherever it exists. A structured feed would land straight into the same tables, skip the reading step, and then get the same checks, Core Data Record view, lineage and governance. PDFs remain the long tail (legacy, bespoke, non-platform placements), and that's where reading them earns its place. | 0, 2 |
| 4 | Older MRC layouts, or a market's own variant? | It's the same mechanism you saw: an unknown layout goes to recognition, a known layout that has changed goes to Changes. Each is recorded once as a schema version, and later documents with that fingerprint go straight through. | 4, 5 |

## The rules and the record

| # | Question | Straight answer | Beat |
|---|---|---|---|
| 5 | Seven certainty checks is thin. A real market has many more. | Yes. These seven are an illustrative set of the contract-certainty basics (fully signed, several liability notice, sanctions clause, valid period, UMR format, leader on the security, governing law). They are plain, versioned rules in the repository, so adding a market rule is a reviewed code change, not model training. | 8 |
| 6 | 97.5% signed may just mean a line is still to be signed. Why "fail"? | The check reports the contract as read: it isn't 100% signed *yet*. A real workflow would add a third state, "pending signing", with a due date. That's a small rule change. | 8 |
| 7 | Several liability: you only look for LSW1001? | Today, yes. Other accepted notice wordings would be added to the same rule's list; it's a one-line change, recorded in the repository. | 8 |
| 8 | Is this the official Core Data Record? | No. The field names are an indicative crosswalk for discussion, and the screen says so. When the published specification is wired in, only the mapping changes; the reading, checks and lineage stay the same. | 8 |
| 9 | Multiple currencies, FX? | Amounts are always kept per currency and never added across currencies. FX conversion isn't modelled; it would be a governed rate table applied in reporting, not during extraction. | 9 |

## When things go wrong

| # | Question | Straight answer | Beat |
|---|---|---|---|
| 10 | What if the model proposes a wrong mapping and a person confirms it? | Each schema is a recorded version with who, when and why, so you can see exactly which contracts were read with it. The fix is to record a corrected version and re-read those contracts. Re-reading is a re-run of intake, not a one-click button in this demo. A one-click "retract and re-read" is roadmap. | 5, 10 |
| 11 | Does the AI decide anything? | No. Values are read by rule from the contract's sections and labels. The model proposes mappings only for an unfamiliar schema, and a person confirms them. The review agents advise only; they cannot record a schema or load a contract, and every review is logged with the facts it was given (see Governance). | 3, 5, 10 |
| 12 | Who approves a schema — is there four-eyes? | Today one named person records each version, and Governance lists who and when. A second-approver step (four-eyes), enforced as a platform permission, is roadmap. | 10 |

## Platform, scale and cost

| # | Question | Straight answer | Beat |
|---|---|---|---|
| 13 | Where does the logic actually run? | The data, checks history, schema versions, decisions and audit are governed tables in Unity Catalog. Reading uses `ai_parse_document` in the platform, and Ask uses Genie plus a Knowledge Assistant. The orchestration (intake, recognise, accept) runs as Python inside the app for this demo. In a production build it moves into scheduled Jobs and Unity Catalog functions, and approvals become platform permissions, so any client — app, notebook or external agent — calls the same governed steps. | 10 |
| 14 | Thousands of documents a day? | The pieces are serverless and scale out: parsing runs per document in the warehouse, and intake already processes documents in parallel. A production build would pick up new files automatically with Auto Loader in a scheduled pipeline, instead of a button. We haven't run a volume test here. | 2 |
| 15 | What does it cost per document? | We haven't measured it in this demo. The cost drivers are `ai_parse_document` (per page) and a few SQL statements per contract; everything scales to zero when idle. Measuring it on a sample of your documents is the right way to get a number. | — |
| 16 | Why your own audit table rather than the platform's audit logs? | They're complementary. The platform audit logs record who accessed what. This table records *business* events: received, matched, flagged, accepted, recognised, returned — each with a reason. | 10 |
| 17 | Could a market participant read this data? | The records are plain governed tables, so Delta Sharing would let a counterparty read their own contracts without copying them. This is a forward hook, not built. | 10 |

## Names and data

| # | Question | Straight answer | Beat |
|---|---|---|---|
| 18 | Are those real syndicates and brokers? | The syndicate numbers, managing agents and broker names are real and publicly known, and we checked them. All insureds, references, figures and wordings are invented. | 1 |
| 19 | Is the UMR format right? | Yes: "B" plus the four-digit Lloyd's broker number, then the broker's own reference. The check also confirms that the broker number in the UMR matches the broker stated on the contract. | 8 |
