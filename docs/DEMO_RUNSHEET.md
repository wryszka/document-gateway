# Demo run-sheet — Document Gateway

**Canonical question:** *"A counterparty just sent us a file — how do we trust it, use it, and never map it twice?"*

**Audiences:** Head of Delegated Authority / Chief Underwriting Officer (does this hold up?), a data/platform lead (is it real and governed?), and any SA/AE (can I run it cold?). **SAY lines carry no platform words** — the mechanism lives in the Q&A (`DEMO_QA.md`) and the Learn panel.

**App:** `https://document-gateway-7474656169654171.aws.databricksapps.com` · **Default demo:** beats 1–8 (~12 min). MRC (beat 9) and the config-port reveal (beat 10) are composable add-ons.

**Timings** are per-beat budgets — validate on one dry run before the room (times move with warehouse warm-up + live AI calls; the yellow **cached** toggle keeps repeated beats instant).

### Pre-flight (before the room)
1. `python tools/orchestrate.py --reset` — restores the pristine four-state book and **rolls the months to today** (currently Jun/Jul/Aug 2026). Deterministic on the seed + as-of.
2. Confirm pristine state on the **Inbox**: Unchanged **18** · Known-changed **1** (Ridgeway, latest month) · Unknown **2** (Saltmarsh premium + claims) · Unusable **1**. MRC shows **5**, health-slip **1**.
3. Warm the warehouse (open The Book once). Set the mode pill to **cached** for a smooth run; flip to **live** when you want to prove a beat is real.
4. Known-good inputs are in `PRESENTER_RUNBOOK.md`.

### Ordering guards
- Do **not** accept the Ridgeway remap (beat 4) before showing completeness (beat 6) — "Ridgeway is behind" (beat 6) is the *consequence* of the quarantine; accepting first spoils it.
- Beat 5 (schema recognition) needs Saltmarsh still **unknown**; beat 8 needs Harbourline's July **v2** present (both true in the pristine state).

---

## Headline walkthrough

### Beat 1 — The inbox (1.5 min)
- **GO:** Inbox.
- **DO:** Read the four tiles aloud; point at the mixed list of files.
- **SAY:** "A month's files just arrived from our coverholders. **Most** are fine. **One** looks off, **one's** from someone new, **one's** unusable."
- **IF ASKED:** how are they sorted? → Q&A #1 (fingerprint against the registry).

### Beat 2 — A known file lands, traceably (1.5 min)
- **GO:** Inbox → click an active Harbourline row → **Lineage**.
- **DO:** Trace one line back to the source cell.
- **SAY:** "This number came from **this cell** in **this file** — I can defend every row back to the page it arrived on."
- **IF ASKED:** did a human check it? → Q&A #4 (two paths agreed; audit event).

### Beat 3 — The drifted file quarantines (2 min)
- **GO:** Quarantine & Remap → select the Ridgeway (latest month) doc.
- **DO:** Show the reconciliation table + the proposed remap rows.
- **SAY:** "Ridgeway renamed two columns — **Gross Premium → GWP**, **Commission → Brokerage**. We didn't guess; we caught it and stopped."
- **IF ASKED:** how did you know they're the same field? → Q&A #1/#5 (two-path reconciliation).

### Beat 4 — Confirm once (1.5 min)
- **GO:** same screen → **Accept remap**.
- **DO:** Accept; watch it re-process and land.
- **SAY:** "I confirm **once**. The template learns the new name, and **every future file** from Ridgeway sails straight through."
- **IF ASKED:** who approved this? → Q&A #3 (template history + audit, with author + time).

### Beat 5 — A brand-new coverholder (2 min)
- **GO:** Schema Recognition → select Saltmarsh.
- **DO:** Show the proposed field map (per-field confidence); confirm.
- **SAY:** "A coverholder we've **never seen**. The system proposes the whole mapping; I confirm it, and they're **onboarded in under a minute**."
- **IF ASKED:** could it invent a field? → Q&A #7 (maps only into the shared dictionary).

### Beat 6 — The book & who hasn't reported (1.5 min)
- **GO:** The Book.
- **DO:** Read GWP + the completeness table + loss ratio.
- **SAY:** "**£2.0m** of premium. One coverholder was flagged **behind** until we cleared their file. And **Ridgeway's loss ratio is 88%** — worth a look."
- **IF ASKED:** where does loss ratio come from? → Q&A #9 (claims incurred over premium, governed).

### Beat 7 — Ask the book (1 min)
- **GO:** Ask.
- **DO:** Ask "Which coverholder has the highest loss ratio?"
- **SAY:** "Anyone can interrogate the whole book in plain English — and see the query behind the answer."
- **IF FAILS:** flip to **cached**; the pre-warmed answer is instant. → Q&A #10.

## Reactive second act

### Beat 8 — A resubmission, and what it costs (2 min)
- **GO:** Templates → Version history & money impact → Harbourline Underwriting, period **2026-07**.
- **DO:** Show the two versions + the impact banner.
- **SAY:** "Harbourline restated July. The book updated itself, and the change is **+£23,430** of premium — shown, not buried."
- **IF ASKED:** did the old numbers vanish? → Q&A #12 (superseded, never deleted; time-travellable).

---

## Composable add-ons

### Beat 9 — MRC: the same loop, a different document (2 min)
- **GO:** MRC → open a contract → **Ask the MRCs** ("How many contracts by class of business?").
- **DO:** Show the 5 extracted contracts + a Genie answer.
- **SAY:** "Same gateway — now reading **prose** contracts, not spreadsheets. Five placements, every limit and clause captured."
- **IF ASKED:** does it also search the wording? → Q&A #14 (dual retrieval; Knowledge Assistant arming).

### Beat 10 — Same gateway, next document family (1.5 min)
- **GO:** Config-port.
- **DO:** Show the health-slip `tenant.json`.
- **SAY:** "To take on a completely different document — health renewal exhibits — we changed **this one file**. No new code."
- **IF ASKED:** really no code? → Q&A #15 (one generic lander; everything else is config).

---

## Cut order (if short on time)
Cut **beat 10**, then **beat 9**, then **beat 7**. **Never cut** beats 3–4 (confirm-once — the heart) or beat 8 (the money). Beats 1–6 are the spine.
