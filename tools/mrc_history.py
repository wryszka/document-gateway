"""Contracts loaded before today — so the book, the dashboard and governance aren't empty.

Thirty-six earlier open-market MRCs, generated with the same generator as the demo inbox and
read by the same pipeline (classify -> extract -> certainty checks -> ingest), then dated
back to when they arrived over the past year. They live in the volume's `mrc_archive/` folder,
which is how Reset and the intake screens tell them apart from today's inbox: Reset never
touches them, and the intake agent only reviews today's documents.

Deterministic: the same as-of date gives the same contracts, figures and dates. Values are read
by rule only (no model call), so seeding is quick and needs no Knowledge Assistant re-sync.

Run once per schema (Reset also seeds it when missing):
  PYTHONPATH=. uv run --with databricks-sdk,openpyxl python tools/mrc_history.py
"""
from __future__ import annotations

import os
import random
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import client, load_config, sql  # noqa: E402

ARCHIVE = "mrc_archive"
V1_BY = "Priya Natarajan (Market Data Standards)"
CORRECTOR = "Tom Ellery (Contract Certainty)"

# Real, publicly listed brokers (numbers illustrative) and syndicates (checked 2026-10-06).
BROKERS = [("Aon UK Limited", "0750"), ("Marsh Ltd", "0572"), ("Willis Towers Watson", "0425"),
           ("Gallagher", "1206"), ("Lockton Companies LLP", "0950"), ("Howden Insurance Brokers Ltd", "1180"),
           ("Miller Insurance Services LLP", "0661"), ("McGill and Partners Ltd", "0832")]
SYNDICATES = [("33", "Hiscox Syndicates Ltd"), ("623", "Beazley Furlonge Ltd"), ("2987", "Brit Syndicates Ltd"),
              ("2001", "MS Amlin Underwriting Ltd"), ("510", "Tokio Marine Kiln Syndicates Ltd"),
              ("3000", "Markel Syndicate Management Ltd"), ("1414", "Ascot Underwriting Ltd"),
              ("1084", "Chaucer Syndicates Ltd"), ("2003", "AXA XL Underwriting Agencies Ltd"),
              ("1886", "QBE Underwriting Ltd"), ("4444", "Canopius Managing Agents Ltd"),
              ("457", "Munich Re Syndicate Ltd"), ("1969", "Apollo Syndicate Management Ltd"),
              ("2010", "Lancashire Syndicates Ltd")]
# Invented insureds.
INSUREDS = [("Kestrel Bay Freight Ltd", "Felixstowe IP11 3QF, United Kingdom", "United Kingdom"),
            ("Orchard Vale Foods PLC", "Evesham WR11 4TS, United Kingdom", "United Kingdom"),
            ("Larkspur Data Centres Ltd", "Slough SL1 4QZ, United Kingdom", "United Kingdom"),
            ("Brightwater Offshore AS", "Stavanger 4006, Norway", "Norway"),
            ("Corvane Shipping Ltd", "Limassol 3036, Cyprus", "Cyprus"),
            ("Halden Ridge Mining Corp", "Toronto ON M5H 2Y4, Canada", "Canada"),
            ("Tessaline Retail Group PLC", "Leeds LS1 4DY, United Kingdom", "United Kingdom"),
            ("Quillon Advisory LLP", "London EC4M 7AN, United Kingdom", "United Kingdom"),
            ("Marrowfield Hotels Ltd", "Edinburgh EH2 2BY, United Kingdom", "United Kingdom"),
            ("Solenne Biotech SA", "Lyon 69002, France", "France"),
            ("Ferrovane Logistics GmbH", "Hamburg 20457, Germany", "Germany"),
            ("Aldermoor Construction Ltd", "Bristol BS1 6QA, United Kingdom", "United Kingdom"),
            ("Pellucid Payments Inc", "Austin TX 78701, USA", "United States of America"),
            ("Glenrock Energy Partners LP", "Houston TX 77002, USA", "United States of America"),
            ("Westmarch Estates PLC", "London W1K 3JY, United Kingdom", "United Kingdom"),
            ("Varenne Wines SAS", "Bordeaux 33000, France", "France"),
            ("Northlake Aviation Services Ltd", "Dublin D02 X285, Ireland", "Ireland"),
            ("Ironmere Steel Ltd", "Sheffield S1 2BJ, United Kingdom", "United Kingdom"),
            ("Calderbrook Healthcare Ltd", "Manchester M2 3AW, United Kingdom", "United Kingdom"),
            ("Saltmarsh Aquaculture Ltd", "Oban PA34 4LW, United Kingdom", "United Kingdom"),
            ("Brennock Software BV", "Amsterdam 1017 CE, Netherlands", "Netherlands"),
            ("Tarrant Mills Holdings PLC", "Glasgow G2 1DU, United Kingdom", "United Kingdom"),
            ("Oakhurst Grain Traders SA", "Geneva 1204, Switzerland", "Switzerland"),
            ("Pemberley Media Group Ltd", "London W1T 1JY, United Kingdom", "United Kingdom"),
            ("Cindermoor Chemicals Ltd", "Runcorn WA7 4QX, United Kingdom", "United Kingdom"),
            ("Ashbourne Marine Services Ltd", "Southampton SO14 3TL, United Kingdom", "United Kingdom"),
            ("Lindqvist Forestry AB", "Gothenburg 411 06, Sweden", "Sweden"),
            ("Harrowgate Rail Systems Ltd", "Derby DE1 2SB, United Kingdom", "United Kingdom"),
            ("Moravia Auto Components SRO", "Brno 602 00, Czech Republic", "Czech Republic"),
            ("Silverbirch Pensions Trustees Ltd", "London EC2V 7HN, United Kingdom", "United Kingdom"),
            ("Duncairn Distilleries Ltd", "Elgin IV30 1BX, United Kingdom", "United Kingdom"),
            ("Ravello Fashion SpA", "Milan 20121, Italy", "Italy"),
            ("Elmstead Waste Solutions Ltd", "Colchester CO1 1BX, United Kingdom", "United Kingdom"),
            ("Kingfisher Ports Authority", "Valletta VLT 1110, Malta", "Malta"),
            ("Thistledown Insurance Services Ltd", "Norwich NR1 3QL, United Kingdom", "United Kingdom"),
            ("Corran Wind Farms Ltd", "Inverness IV1 1QJ, United Kingdom", "United Kingdom")]

ENGLISH = "English law; courts of England and Wales (exclusive)"
# (type, interest, situation, limits(m), deductible(k), premium range(k), conditions, exclusions)
CLASSES = [
    ("Property Damage & Business Interruption", "Buildings, plant, stock and business interruption at insured sites",
     "United Kingdom", [("any one occurrence (Property Damage)", 30, 120), ("any one occurrence (Business Interruption)", 10, 50)],
     (100, 500), (600, 2600), ["NMA2914 - Communicable Disease Exclusion", "LMA5401 - Property Cyber and Data Exclusion"],
     ["War and terrorism (NMA2918)", "Gradual pollution", "Wear and tear"]),
    ("Marine Cargo", "Goods in transit worldwide by sea, air and land, including storage", "Worldwide",
     [("any one conveyance", 10, 40), ("any one event", 20, 80)], (25, 100), (250, 1100),
     ["Institute Cargo Clauses (A) CL382", "Institute War Clauses (Cargo) CL385"],
     ["Delay and loss of market", "Inherent vice", "Insufficiency of packing"]),
    ("Marine Hull & Machinery", "Hull and machinery of the scheduled fleet, including collision liability", "Worldwide",
     [("any one vessel", 20, 90), ("any one accident", 40, 150)], (100, 400), (500, 1900),
     ["Institute Time Clauses Hulls CL280", "Institute War and Strikes Clauses Hulls CL281"],
     ["Wear and tear", "Unseaworthiness with the privity of the insured", "Sanctioned voyages"]),
    ("Cyber Liability", "Data breach response, network interruption, cyber extortion and liability", "Worldwide",
     [("any one claim and in the aggregate", 5, 30)], (100, 750), (300, 1500),
     ["LMA5567 - Cyber War and Cyber Operation Exclusion"],
     ["Infrastructure failure", "Prior known circumstances", "Bodily injury"]),
    ("Professional Indemnity", "Civil liability arising from the insured's professional services",
     "Worldwide excluding USA and Canada", [("any one claim", 5, 25), ("in the aggregate", 10, 40)], (50, 250),
     (150, 700), ["LMA5401 - Claims Made Notification Clause"],
     ["Bodily injury and property damage", "Prior and pending litigation", "Fraud or dishonesty"]),
    ("Directors & Officers Liability", "Management liability of directors and officers and entity securities claims",
     "Worldwide", [("any one claim and in the aggregate", 10, 60)], (250, 1000), (400, 2200),
     ["Insured vs Insured Exclusion (with carve-backs)"],
     ["Bodily injury and property damage", "Pollution", "Prior and pending litigation"]),
    ("Energy Onshore Property", "Physical damage to onshore energy facilities, plant and equipment", "Worldwide",
     [("any one occurrence", 50, 250)], (500, 2500), (900, 3800), ["LMA5401 - Property Cyber and Data Exclusion"],
     ["Gradual deterioration", "Machinery breakdown", "War and terrorism (NMA2918)"]),
    ("Construction All Risks", "Contract works, plant and equipment for the scheduled project", "United Kingdom",
     [("any one occurrence (Contract Works)", 20, 90)], (25, 250), (250, 1200),
     ["LMA5401 - Property Cyber and Data Exclusion"],
     ["Defective design (LEG 2/96 applies)", "Wear and tear", "Contractual penalties"]),
    ("Aviation Liability", "Third-party and passenger legal liability for the scheduled operations", "Worldwide",
     [("any one occurrence", 100, 500)], (0, 0), (300, 1600), ["AVN 1C War, Hi-jacking and Other Perils Exclusion"],
     ["Noise and pollution", "Radioactive contamination", "Wear and tear"]),
    ("Terrorism", "Physical loss from acts of terrorism and sabotage at the scheduled locations", "Worldwide",
     [("any one occurrence and in the aggregate", 10, 75)], (50, 250), (80, 450),
     ["LMA3030 - Terrorism Exclusion Endorsement (buy-back)"], ["Nuclear, chemical and biological attack", "Cyber attack"]),
]


def _round(x, step):
    return int(round(x / step) * step)


def build(as_of: date | None = None, n: int = 36):
    """The earlier contracts as generator specs, each with the date it arrived. Deterministic."""
    as_of = as_of or date.today()
    rnd = random.Random(20251001)
    v1_at = datetime.combine(as_of - timedelta(days=392), datetime.min.time()).replace(hour=10, minute=12)
    specs = []
    order = [c for _ in range(n // len(CLASSES) + 1) for c in CLASSES]
    rnd.shuffle(order)                                            # an even spread of classes
    brokers = [b for _ in range(n // len(BROKERS) + 1) for b in BROKERS]
    rnd.shuffle(brokers)
    for i in range(n):
        ins_name, addr, country = INSUREDS[i % len(INSUREDS)]
        typ, interest, situation, lims, ded, prem, conds, excls = order[i]
        bname, bno = brokers[i]
        ccy = "USD" if typ.startswith(("Marine", "Energy", "Aviation")) or country == "United States of America" \
            else ("EUR" if country in ("France", "Germany", "Netherlands", "Italy", "Ireland", "Malta", "Cyprus", "Czech Republic")
                  else "GBP")
        months_ago = (i * 12) // n                               # inception spread over the last year
        limits = [f"{ccy} {_round(rnd.uniform(a, b), 5):,},000,000 {lab}" for lab, a, b in lims]
        d_lo, d_hi = ded
        deductible = (f"{ccy} {_round(rnd.uniform(d_lo, d_hi), 25):,},000 each and every loss" if d_hi
                      else "Nil")
        premium = f"{ccy} {_round(rnd.uniform(*prem), 5):,},000 annual"
        panel = rnd.sample(SYNDICATES, rnd.choice([3, 3, 4]))
        written = [rnd.choice([30, 35, 40, 45, 50]) for _ in panel]
        if sum(written) < 105:
            written[0] += 105 - sum(written)
        sanctions = True
        if i in (9, 27):                                          # two placements left short: not fully signed
            written = [round(w * 95.0 / sum(written), 1) for w in written]
        if i == 18:                                               # one with no sanctions clause
            sanctions = False
        law = f"{'New York' if country.startswith('United States') else 'English'} law; " \
              f"{'courts of the State of New York' if country.startswith('United States') else 'courts of England and Wales (exclusive)'}"
        spec = {"filename": f"mrc_hist_{i + 1:03d}.pdf", "ref": f"H{i + 1:02d}", "months_ago": months_ago,
                "broker": {"name": bname, "number": bno}, "type": typ, "ccy": ccy,
                "insured": {"name": ins_name, "address": addr}, "interest": interest, "situation": situation,
                "limits": limits, "deductible": deductible, "premium": premium,
                "conditions": (["LMA5218 - Sanction Limitation and Exclusion Clause"] if sanctions else []) + conds,
                "exclusions": excls, "law": law,
                "security": [(s, a, float(w)) for (s, a), w in zip(panel, written)],
                "country": country, "brokerage": f"{rnd.choice([10, 12.5, 15, 17.5, 20]):.2f}%"}
        # Arrived 5–25 days before inception, never before v1 was recorded, never in the last 2 days.
        from data.generate_mrc import _period
        inc_d = _period(months_ago, as_of)[3]
        arrived = datetime.combine(inc_d - timedelta(days=rnd.randrange(5, 25)), datetime.min.time())
        arrived = arrived.replace(hour=rnd.randrange(8, 18), minute=rnd.randrange(60))
        arrived = min(max(arrived, v1_at + timedelta(days=3)), datetime.combine(as_of - timedelta(days=2), datetime.min.time()))
        spec["arrived"] = arrived
        specs.append(spec)
    return specs, v1_at


def present(cfg) -> int:
    F = cfg["full_schema"]
    return int(sql(f"""SELECT count(*) FROM {F}.mrc_entities e JOIN {F}.source_document d ON e.source_document_id = d.doc_id
                       WHERE d.stored_path LIKE '%/{ARCHIVE}/%'""", cfg=cfg)[0][0])


def backdate_v1(cfg, v1_at):
    """The open-market schema was recorded long before today's documents — date it so."""
    from jobs.mrc_schemas import OPEN_MARKET
    F, ts = cfg["full_schema"], v1_at.strftime("%Y-%m-%d %H:%M:%S")
    p = {"n": OPEN_MARKET, "ts": ts}
    p["by"] = V1_BY
    sql(f"""UPDATE {F}.template SET created_at=to_timestamp(:ts), created_by=:by
            WHERE doc_family='mrc' AND counterparty=:n AND template_version='v1'""", params=p, cfg=cfg)
    sql(f"""UPDATE {F}.mrc_schema_note SET created_at=to_timestamp(:ts), created_by=:by
            WHERE schema_name=:n AND schema_version='v1'""", params=p, cfg=cfg)
    sql(f"""UPDATE {F}.decision SET created_at=to_timestamp(:ts), actor=:by WHERE tenant='mrc' AND template_version='v1'
            AND decision_type='schema_confirm' AND get_json_object(detail, '$.schema')=:n""", params=p, cfg=cfg)
    sql(f"""UPDATE {F}.audit_event SET created_at=to_timestamp(:ts), actor=:by WHERE event_type='schema_recorded'
            AND entity_id=concat(:n, '/mrc') AND detail LIKE '% v1:%'""", params=p, cfg=cfg)


def seed(cfg, as_of: date | None = None):
    """Generate, upload and load the earlier contracts (skips any already loaded)."""
    import uuid
    from concurrent.futures import ThreadPoolExecutor
    from data import generate_mrc as g
    from jobs import mrc_schemas as ms
    from jobs.ingest_pipeline import audit
    F = cfg["full_schema"]
    specs, v1_at = build(as_of)
    out = os.path.join(g.OUT, ARCHIVE)
    os.makedirs(out, exist_ok=True)
    w, base = client(cfg), f'{cfg["volume_path"]}/{ARCHIVE}'
    for s in specs:
        too_long = [l for l in g._field_lines(s) if len(l) > 96]
        if too_long:
            raise ValueError(f"{s['filename']}: line would wrap: {too_long[0]!r}")
        g.generate_pdf(s, out)
        with open(os.path.join(out, s["filename"]), "rb") as f:
            w.files.upload(f"{base}/{s['filename']}", f, overwrite=True)
    loaded = {r[0] for r in sql(f"""SELECT d.file_name FROM {F}.source_document d JOIN {F}.mrc_entities e
                                    ON e.source_document_id = d.doc_id WHERE d.stored_path LIKE '%/{ARCHIVE}/%'""", cfg=cfg)}
    sql(f"""DELETE FROM {F}.source_document WHERE tenant='mrc' AND stored_path LIKE '%/{ARCHIVE}/%'
            AND doc_id NOT IN (SELECT source_document_id FROM {F}.mrc_entities)""", cfg=cfg)  # half-loaded leftovers
    todo = [s for s in specs if s["filename"] not in loaded]

    def one(s):
        doc_id, path = f"DOC-{uuid.uuid4().hex[:12]}", f"{base}/{s['filename']}"
        sql(f"""INSERT INTO {F}.source_document VALUES
                (:d,'mrc','—','mrc',:fn,:sp,'processing','processing',NULL,'v1',NULL,NULL,current_timestamp(),NULL,NULL)""",
            params={"d": doc_id, "fn": s["filename"], "sp": path}, cfg=cfg)
        for attempt in range(3):
            try:
                o = ms.process_one(cfg, doc_id, path, actor="intake", ai=False)
                break
            except Exception:
                if attempt == 2:
                    raise
        return doc_id, s, o

    with ThreadPoolExecutor(max_workers=8) as pool:
        done = list(pool.map(one, todo))
    bad = [(s["filename"], o) for _, s, o in done if o != "known"]
    if bad:
        raise RuntimeError(f"earlier contracts did not load straight through: {bad}")

    # Date every record of each contract to when it arrived.
    if done:
        vals = ",".join(f"('{d}','policy_{d.split('-')[-1][:8]}',to_timestamp('{s['arrived']:%Y-%m-%d %H:%M:%S}'))"
                        for d, s, _ in done)  # ids and dates are generated here, not user input
        m = f"(SELECT * FROM VALUES {vals} AS m(doc, mrc, ts))"
        sql(f"MERGE INTO {F}.source_document t USING {m} m ON t.doc_id = m.doc WHEN MATCHED THEN UPDATE SET ingested_at = m.ts", cfg=cfg)
        for t in ("mrc_extraction", "mrc_certainty_check", "graph_nodes", "graph_edges"):
            sql(f"MERGE INTO {F}.{t} t USING {m} m ON t.source_document_id = m.doc WHEN MATCHED THEN UPDATE SET created_at = m.ts", cfg=cfg)
        sql(f"""MERGE INTO {F}.audit_event t USING {m} m ON t.entity_id = m.doc OR t.entity_id = m.mrc
                WHEN MATCHED THEN UPDATE SET created_at = m.ts + INTERVAL 2 MINUTES""", cfg=cfg)
        # Two later corrections by a named person, so the record shows people at work.
        for d, s, _ in done[3:5]:
            mrc_id = f"policy_{d.split('-')[-1][:8]}"
            when = s["arrived"] + timedelta(days=6, hours=2)
            audit(cfg, "metric_corrected", "mrc_entities", mrc_id,
                  detail="broker_name: confirmed against the broker's placing record", actor=CORRECTOR)
            sql(f"""INSERT INTO {F}.decision VALUES (:id,'metric_correction','mrc',:doc,'v1',:det,
                    'Broker confirmed the placing record; no change to the value',:a,'saved',NULL,to_timestamp(:ts))""",
                params={"id": f"DEC-{uuid.uuid4().hex[:10]}", "doc": d, "det": '{"field": "broker_name"}',
                        "a": CORRECTOR, "ts": f"{when:%Y-%m-%d %H:%M:%S}"}, cfg=cfg)
            sql(f"""UPDATE {F}.audit_event SET created_at=to_timestamp(:ts) WHERE entity_id=:m AND event_type='metric_corrected'""",
                params={"ts": f"{when:%Y-%m-%d %H:%M:%S}", "m": mrc_id}, cfg=cfg)
    backdate_v1(cfg, v1_at)
    print(f"earlier contracts: {len(done)} loaded now, {len(loaded)} already present")
    return len(done) + len(loaded)


if __name__ == "__main__":
    seed(load_config())
