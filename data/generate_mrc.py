"""T3 — synthetic Lloyd's MRC (Market Reform Contract) PDF generator.

Lifted from insurance-mrc-poc: a pure-Python PDF writer (no external libs) + 5 MRCs
across Property/BI, PI, Marine Cargo, Cyber, D&O. Real, publicly-known market names
(brokers/syndicates) are kept deliberately (DECISIONS D9) — they are common market
knowledge and aid comprehension; the insureds are invented. Writes to data/generated_mrc/
and uploads to the landing volume's mrc_inbox.

Run:  uv run --with databricks-sdk python data/generate_mrc.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import load_config, client  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "generated_mrc")


class SimplePDF:
    """Minimal PDF 1.4 writer supporting Helvetica text with headings and body."""

    def __init__(self):
        self.pages = []
        self.current_page_streams = []
        self._y = 750

    def _escape(self, text):
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def add_heading(self, text, size=16):
        if self._y < 60:
            self._new_page()
        self._y -= size + 8
        self.current_page_streams.append(
            f"BT /F1 {size} Tf 50 {self._y:.0f} Td ({self._escape(text)}) Tj ET")
        self._y -= 4

    def add_text(self, text, size=10, width=96):
        import textwrap
        lines = []
        for raw in text.split("\n"):
            wrapped = textwrap.wrap(raw, width=width, subsequent_indent="    ") if raw else [""]
            lines.extend(wrapped or [""])
        for line in lines:
            if self._y < 50:
                self._new_page()
            self._y -= size + 4
            self.current_page_streams.append(
                f"BT /F2 {size} Tf 60 {self._y:.0f} Td ({self._escape(line)}) Tj ET")

    def add_separator(self):
        self._y -= 6
        self.current_page_streams.append(f"0.7 G 50 {self._y:.0f} m 550 {self._y:.0f} l S 0 G")
        self._y -= 6

    def _new_page(self):
        self.pages.append("\n".join(self.current_page_streams))
        self.current_page_streams = []
        self._y = 750

    def save(self, path):
        if self.current_page_streams:
            self._new_page()
        objs = []
        objnum = [0]

        def new_obj(data: str) -> int:
            objnum[0] += 1
            objs.append((objnum[0], data.encode("latin-1")))
            return objnum[0]

        catalog_id = new_obj("")
        pages_id = new_obj("")
        font1_id = new_obj("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
        font2_id = new_obj("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        page_ids = []
        for page_stream in self.pages:
            stream_bytes = page_stream.encode("latin-1")
            stream_id = new_obj(
                f"<< /Length {len(stream_bytes)} >>\nstream\n" + page_stream + "\nendstream")
            page_id = new_obj(
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 792] "
                f"/Contents {stream_id} 0 R /Resources << /Font << /F1 {font1_id} 0 R /F2 {font2_id} 0 R >> >> >>")
            page_ids.append(page_id)
        objs[catalog_id - 1] = (catalog_id, f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("latin-1"))
        kids = " ".join(f"{pid} 0 R" for pid in page_ids)
        objs[pages_id - 1] = (pages_id, f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("latin-1"))
        with open(path, "wb") as f:
            f.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
            offsets = {}
            for oid, data in objs:
                offsets[oid] = f.tell()
                f.write(f"{oid} 0 obj\n".encode())
                f.write(data)
                f.write(b"\nendobj\n")
            xref_offset = f.tell()
            f.write(b"xref\n")
            f.write(f"0 {len(objs) + 1}\n".encode())
            f.write(b"0000000000 65535 f \n")
            for oid in range(1, len(objs) + 1):
                f.write(f"{offsets[oid]:010d} 00000 n \n".encode())
            f.write(b"trailer\n")
            f.write(f"<< /Size {len(objs) + 1} /Root {catalog_id} 0 R >>\n".encode())
            f.write(b"startxref\n")
            f.write(f"{xref_offset}\n".encode())
            f.write(b"%%EOF\n")


# Five synthetic MRCs, laid out to the MRC v3 section structure. Syndicate numbers and
# managing agents are real and were checked against public Lloyd's filings (2026-10-06);
# broker numbers, stamps and references are illustrative. Insureds are invented.
# Two contracts deliberately fail a contract-certainty check (the demo's "catch"):
#   MRC-004 is only 97.5% signed (not fully placed); MRC-002 omits the sanctions clause.
POLICIES = [
    {"filename": "mrc_policy_001.pdf", "ref": "001", "months_ago": 8,
     "broker": {"name": "Aon UK Limited", "number": "0750"},
     "type": "Property Damage & Business Interruption", "ccy": "GBP",
     "insured": {"name": "Meridian Global Industries PLC", "address": "45 Bishopsgate, London EC2N 3DA, United Kingdom"},
     "interest": "Buildings, machinery, stock and business interruption at the insured's UK sites",
     "situation": "United Kingdom",
     "limits": ["GBP 50,000,000 any one occurrence (Property Damage)",
                "GBP 25,000,000 any one occurrence (Business Interruption)"],
     "deductible": "GBP 250,000 each and every loss",
     "premium": "GBP 1,875,000 annual, payable in quarterly instalments",
     "conditions": ["LMA5218 - Sanction Limitation and Exclusion Clause",
                    "NMA2914 - Communicable Disease Exclusion",
                    "LMA5401 - Property Cyber and Data Exclusion"],
     "exclusions": ["War and terrorism (NMA2918)", "Nuclear, chemical, biological and radiological contamination",
                    "Gradual pollution"],
     "law": "English law; courts of England and Wales (exclusive)",
     "security": [("33", "Hiscox Syndicates Ltd", 40.0), ("623", "Beazley Furlonge Ltd", 35.0),
                  ("2987", "Brit Syndicates Ltd", 25.0), ("2001", "MS Amlin Underwriting Ltd", 25.0)],
     "country": "United Kingdom", "brokerage": "15.00%"},
    {"filename": "mrc_policy_002.pdf", "ref": "002", "months_ago": 6,
     "broker": {"name": "Marsh Ltd", "number": "0572"},
     "type": "Professional Indemnity", "ccy": "GBP",
     "insured": {"name": "Thornfield Consulting Group Ltd", "address": "12 Fenchurch Street, London EC3M 3BY, United Kingdom"},
     "interest": "Civil liability arising from professional management consultancy services",
     "situation": "Worldwide excluding USA and Canada",
     "limits": ["GBP 10,000,000 any one claim", "GBP 20,000,000 in the aggregate"],
     "deductible": "GBP 100,000 each and every claim, inclusive of costs",
     "premium": "GBP 425,000 annual, minimum and deposit",
     "conditions": ["LMA5401 - Claims Made Notification Clause", "IUA09-045 - Dishonesty Exclusion"],
     "exclusions": ["Bodily injury and property damage", "Prior and pending litigation",
                    "Fraud or dishonesty of the insured"],
     "law": "English law; courts of England and Wales (exclusive)",
     "security": [("510", "Tokio Marine Kiln Syndicates Ltd", 45.0), ("3000", "Markel Syndicate Management Ltd", 40.0),
                  ("1414", "Ascot Underwriting Ltd", 40.0)],
     "country": "United Kingdom", "brokerage": "17.50%"},
    {"filename": "mrc_policy_003.pdf", "ref": "003", "months_ago": 5,
     "broker": {"name": "Willis Towers Watson", "number": "0425"},
     "type": "Marine Cargo", "ccy": "USD",
     "insured": {"name": "Atlantic Shipping & Logistics SA", "address": "Rue du Rhone 14, 1204 Geneva, Switzerland"},
     "interest": "Goods in transit worldwide by sea, air and land, including storage",
     "situation": "Worldwide",
     "limits": ["USD 30,000,000 any one conveyance", "USD 60,000,000 any one event"],
     "deductible": "USD 50,000 each and every loss",
     "premium": "USD 780,000 adjustable, minimum USD 600,000",
     "conditions": ["Institute Cargo Clauses (A) CL382", "Institute War Clauses (Cargo) CL385",
                    "LMA5218 - Sanction Limitation and Exclusion Clause"],
     "exclusions": ["Delay and loss of market", "Inherent vice", "Insufficiency of packing"],
     "law": "English law; courts of England and Wales (exclusive)",
     "security": [("1084", "Chaucer Syndicates Ltd", 50.0), ("2003", "AXA XL Underwriting Agencies Ltd", 40.0),
                  ("1886", "QBE Underwriting Ltd", 35.0)],
     "country": "Switzerland", "brokerage": "12.50%"},
    {"filename": "mrc_policy_004.pdf", "ref": "004", "months_ago": 3,
     "broker": {"name": "Gallagher", "number": "1206"},
     "type": "Cyber Liability", "ccy": "USD",
     "insured": {"name": "NovaTech Digital Solutions Inc", "address": "100 California Street, San Francisco, CA 94111, USA"},
     "interest": "Data breach response, network interruption, cyber extortion and third-party liability",
     "situation": "Worldwide",
     "limits": ["USD 25,000,000 any one claim and in the aggregate", "USD 5,000,000 sub-limit ransomware"],
     "deductible": "USD 500,000 each and every claim; 12-hour waiting period",
     "premium": "USD 1,250,000 annual, flat",
     "conditions": ["LMA5218 - Sanction Limitation and Exclusion Clause", "LMA5567 - Cyber War and Cyber Operation Exclusion"],
     "exclusions": ["Infrastructure failure", "Prior known circumstances", "Bodily injury"],
     "law": "New York law; courts of the State of New York",
     "security": [("623", "Beazley Furlonge Ltd", 30.0), ("4444", "Canopius Managing Agents Ltd", 25.0),
                  ("457", "Munich Re Syndicate Ltd", 22.5), ("1969", "Apollo Syndicate Management Ltd", 20.0)],
     "country": "United States of America", "brokerage": "15.00%"},
    {"filename": "mrc_policy_005.pdf", "ref": "005", "months_ago": 1,
     "broker": {"name": "Lockton Companies LLP", "number": "0950"},
     "type": "Directors & Officers Liability", "ccy": "GBP",
     "insured": {"name": "Halcyon Pharmaceuticals PLC", "address": "1 Cabot Square, Canary Wharf, London E14 4QJ, United Kingdom"},
     "interest": "Management liability of directors and officers, company reimbursement and securities claims",
     "situation": "Worldwide",
     "limits": ["GBP 50,000,000 any one claim and in the aggregate (Side A)",
                "GBP 25,000,000 sub-limit (Side C entity securities)"],
     "deductible": "GBP 500,000 each and every claim (Sides B and C only)",
     "premium": "GBP 2,100,000 annual, minimum and deposit",
     "conditions": ["LMA5218 - Sanction Limitation and Exclusion Clause", "Insured vs Insured Exclusion (with carve-backs)"],
     "exclusions": ["Bodily injury and property damage", "Pollution", "Prior and pending litigation"],
     "law": "English law; courts of England and Wales (exclusive)",
     "security": [("2003", "AXA XL Underwriting Agencies Ltd", 50.0), ("2010", "Lancashire Syndicates Ltd", 40.0),
                  ("2001", "MS Amlin Underwriting Ltd", 35.0)],
     "country": "United Kingdom", "brokerage": "10.00%"},
    {"filename": "mrc_policy_006.pdf", "ref": "006", "months_ago": 2,
     "broker": {"name": "Marsh Ltd", "number": "0572"},
     "type": "Construction All Risks", "ccy": "GBP",
     "insured": {"name": "Ashgrove Developments Ltd", "address": "8 Canal Street, Manchester M1 3HE, United Kingdom"},
     "interest": "Contract works, plant and equipment for a mixed-use development",
     "situation": "United Kingdom",
     "limits": ["GBP 40,000,000 any one occurrence (Contract Works)", "GBP 2,500,000 any one occurrence (Plant)"],
     "deductible": "GBP 50,000 each and every loss; GBP 250,000 defects",
     "premium": "GBP 640,000 for the period, adjustable",
     "conditions": ["LMA5218 - Sanction Limitation and Exclusion Clause", "LMA5401 - Property Cyber and Data Exclusion"],
     "exclusions": ["Defective design (LEG 2/96 applies)", "Wear and tear", "Contractual penalties"],
     "law": "English law; courts of England and Wales (exclusive)",
     "security": [("1414", "Ascot Underwriting Ltd", 50.0), ("2010", "Lancashire Syndicates Ltd", 40.0),
                  ("1084", "Chaucer Syndicates Ltd", 35.0)],
     "country": "United Kingdom", "brokerage": "15.00%",
     # This broker's layout has drifted from the recorded schema: two labels renamed, two fields left out.
     "drift": {"rename": {"Unique Market Reference": "Unique Market Ref", "Premium": "Gross Premium"},
               "omit": ["Choice of Law and Jurisdiction", "Settlement Due Date"]}},
]


def _period(months_ago, as_of=None):
    """Inception = first of the month `months_ago` before as_of (today); 12-month period.
    Dates roll with the reset so the book is always live (Principle 11)."""
    from datetime import date, timedelta
    t = as_of or date.today()
    y, m = t.year, t.month - months_ago
    while m <= 0:
        m += 12; y -= 1
    inc = date(y, m, 1)
    exp = date(y + 1, m, 1) - timedelta(days=1)
    settle = inc + timedelta(days=60)
    fmt = lambda d: d.strftime("%d %B %Y")
    return fmt(inc), fmt(exp), fmt(settle), inc


def _signed(security, ccy_short_order=None):
    """Written lines may exceed 100% (over-subscribed); signed lines are signed down to the
    100% order. MRC-004 is deliberately under-subscribed (written total < 100%), so it signs
    at its written lines and the placement is not fully placed."""
    written_total = sum(w for _, _, w in security)
    factor = 100.0 / written_total if written_total > 100 else 1.0
    return [(n, a, w, round(w * factor, 2)) for n, a, w in security]


def generate_pdf(policy, out_dir, as_of=None):
    inc, exp, settle, inc_d = _period(policy["months_ago"], as_of)
    umr = f"B{policy['broker']['number']}{inc_d.strftime('%y')}LL{policy['ref']}"
    drift = policy.get("drift", {})
    rename, omit = drift.get("rename", {}), set(drift.get("omit", []))
    pdf = SimplePDF()
    _add = pdf.add_text

    def field(label, value):  # one 'Label: value' line, honouring the policy's drift
        if label in omit:
            return
        _add(f"{rename.get(label, label)}: {value}")
    pdf.field = field
    pdf.add_heading("MARKET REFORM CONTRACT", size=14)
    pdf.add_text(f"Broker: {policy['broker']['name']}")
    pdf.add_text(f"Lloyd's Broker Number: {policy['broker']['number']}")
    pdf.add_text(f"Broker Reference: MRC-{inc_d.year}-LL-{policy['ref']}")
    pdf.add_separator()
    pdf.add_heading("RISK DETAILS", size=13)
    field("Unique Market Reference", umr)
    pdf.add_text(f"Type: {policy['type']}")
    pdf.add_text(f"Insured: {policy['insured']['name']}")
    pdf.add_text(f"Insured Address: {policy['insured']['address']}")
    pdf.add_text(f"Period: From {inc} to {exp}, both days inclusive")
    pdf.add_text(f"Interest: {policy['interest']}")
    pdf.add_text(f"Situation: {policy['situation']}")
    pdf.add_text("Limit of Liability:")
    for lim in policy["limits"]:
        pdf.add_text(f"- {lim}")
    pdf.add_text(f"Deductible: {policy['deductible']}")
    field("Premium", policy["premium"])
    pdf.add_text("Conditions:")
    for cl in policy["conditions"]:
        pdf.add_text(f"- {cl}")
    pdf.add_text("Exclusions:")
    for ex in policy["exclusions"]:
        pdf.add_text(f"- {ex}")
    field("Choice of Law and Jurisdiction", policy["law"])
    pdf.add_text("Subjectivities: None")
    pdf.add_separator()
    pdf.add_heading("INFORMATION", size=13)
    pdf.add_text("Presentation of the risk as provided by the broker, held on file.")
    pdf.add_separator()
    pdf.add_heading("SECURITY DETAILS", size=13)
    pdf.add_text("Insurer's Liability: LSW1001 (Several Liability Notice)")
    pdf.add_text("Order Hereon: 100% of 100%")
    pdf.add_text("Basis of Written Lines: Percentage of Whole")
    pdf.add_text("Basis of Signed Lines: Percentage of Whole")
    for num, agent, w, sgn in _signed(policy["security"]):
        pdf.add_text(f"Syndicate {num} ({agent}) | Written Line: {w:.2f}% | Signed Line: {sgn:.2f}%")
    pdf.add_separator()
    pdf.add_heading("SUBSCRIPTION AGREEMENT", size=13)
    lead_num, lead_agent, _ = policy["security"][0]
    pdf.add_text(f"Slip Leader: Syndicate {lead_num} ({lead_agent})")
    pdf.add_text("Basis of Agreement to Contract Changes: General Underwriters Agreement (GUA)")
    pdf.add_text("Basis of Claims Agreement: Lloyd's Claims Scheme")
    field("Settlement Due Date", settle)
    pdf.add_separator()
    pdf.add_heading("FISCAL AND REGULATORY", size=13)
    pdf.add_text(f"Country of Origin: {policy['country']}")
    pdf.add_text("Regulatory Client Classification: Large Risk")
    pdf.add_text("Tax Payable by Insurer(s): None")
    pdf.add_separator()
    pdf.add_heading("BROKER REMUNERATION AND DEDUCTIONS", size=13)
    pdf.add_text(f"Total Brokerage: {policy['brokerage']}")
    pdf.add_text("Other Deductions from Premium: None")
    path = os.path.join(out_dir, policy["filename"])
    pdf.save(path)
    return path


BINDING_AUTHORITY = {
    "filename": "mrc_binding_authority_007.pdf", "ref": "007", "months_ago": 4,
    "broker": {"name": "Lockton Companies LLP", "number": "0950"},
    "coverholder": "Harbourline Underwriting", "coverholder_pin": "CH-8801",
    "classes": ["Commercial Property", "Commercial Combined (package)", "Public and Products Liability"],
    "territory": "United Kingdom",
    "max_line": "GBP 5,000,000 any one risk",
    "epi": "GBP 4,000,000 estimated premium income for the period",
    "reporting": "Premium and claims bordereaux monthly, within 30 days of month end",
    "claims_authority": "Coverholder may settle claims up to GBP 25,000",
    "conditions": ["LMA5218 - Sanction Limitation and Exclusion Clause",
                   "Lloyd's Coverholder Reporting Standards apply"],
    "law": "English law; courts of England and Wales (exclusive)",
    "security": [("33", "Hiscox Syndicates Ltd", 50.0), ("623", "Beazley Furlonge Ltd", 40.0),
                 ("2987", "Brit Syndicates Ltd", 35.0)],
    "country": "United Kingdom", "brokerage": "7.50%",
}


def generate_binding_authority(out_dir, as_of=None):
    """A Lloyd's MRC for a binding authority: the same market structure, a different
    document type (title + fields), so the gateway has no schema for it yet."""
    b = BINDING_AUTHORITY
    inc, exp, settle, inc_d = _period(b["months_ago"], as_of)
    umr = f"B{b['broker']['number']}{inc_d.strftime('%y')}BA{b['ref']}"
    pdf = SimplePDF()
    pdf.add_heading("MARKET REFORM CONTRACT - BINDING AUTHORITY AGREEMENT", size=14)
    pdf.add_text(f"Broker: {b['broker']['name']}")
    pdf.add_text(f"Lloyd's Broker Number: {b['broker']['number']}")
    pdf.add_text(f"Broker Reference: BA-{inc_d.year}-{b['ref']}")
    pdf.add_separator()
    pdf.add_heading("RISK DETAILS", size=13)
    pdf.add_text(f"Unique Market Reference: {umr}")
    pdf.add_text("Type: Binding Authority Agreement")
    pdf.add_text(f"Coverholder: {b['coverholder']}")
    pdf.add_text(f"Coverholder Reference: {b['coverholder_pin']}")
    pdf.add_text(f"Period: From {inc} to {exp}, both days inclusive")
    pdf.add_text("Classes of Business Authorised:")
    for c in b["classes"]:
        pdf.add_text(f"- {c}")
    pdf.add_text(f"Territorial Limits: {b['territory']}")
    pdf.add_text(f"Maximum Line Size: {b['max_line']}")
    pdf.add_text(f"Estimated Premium Income: {b['epi']}")
    pdf.add_text(f"Bordereaux Reporting: {b['reporting']}")
    pdf.add_text(f"Claims Authority: {b['claims_authority']}")
    pdf.add_text("Conditions:")
    for c in b["conditions"]:
        pdf.add_text(f"- {c}")
    pdf.add_text(f"Choice of Law and Jurisdiction: {b['law']}")
    pdf.add_separator()
    pdf.add_heading("INFORMATION", size=13)
    pdf.add_text("Coverholder approval, business plan and audit reports held on file.")
    pdf.add_separator()
    pdf.add_heading("SECURITY DETAILS", size=13)
    pdf.add_text("Insurer's Liability: LSW1001 (Several Liability Notice)")
    pdf.add_text("Order Hereon: 100% of 100%")
    for num, agent, w, sgn in _signed(b["security"]):
        pdf.add_text(f"Syndicate {num} ({agent}) | Written Line: {w:.2f}% | Signed Line: {sgn:.2f}%")
    pdf.add_separator()
    pdf.add_heading("SUBSCRIPTION AGREEMENT", size=13)
    lead_num, lead_agent, _ = b["security"][0]
    pdf.add_text(f"Slip Leader: Syndicate {lead_num} ({lead_agent})")
    pdf.add_text(f"Settlement Due Date: {settle}")
    pdf.add_separator()
    pdf.add_heading("FISCAL AND REGULATORY", size=13)
    pdf.add_text(f"Country of Origin: {b['country']}")
    pdf.add_text("Regulatory Client Classification: Large Risk")
    pdf.add_separator()
    pdf.add_heading("BROKER REMUNERATION AND DEDUCTIONS", size=13)
    pdf.add_text(f"Total Brokerage: {b['brokerage']}")
    pdf.save(os.path.join(out_dir, b["filename"]))
    return b["filename"]


def generate_nonconforming(out_dir):
    """A plain broker cover note — parses to text but has NO MRC structure, so it is not
    recognised as the schema and lands in HITL (the 'not recognised' branch)."""
    pdf = SimplePDF()
    pdf.add_heading("BROKER COVER NOTE", size=14)
    pdf.add_text("To: New Business Team")
    pdf.add_text("From: Placement Team")
    pdf.add_text("Re: forthcoming placement - documents to follow")
    pdf.add_text("")
    pdf.add_text("Please find attached our client's summary of requirements. A full Market "
                "Reform Contract will be issued separately once terms are agreed. This note is "
                "for information only and does not constitute a slip or evidence of cover.")
    pdf.add_text("Kind regards, Placement Team")
    path = os.path.join(out_dir, "cover_note_unstructured.pdf")
    pdf.save(path)
    return "cover_note_unstructured.pdf"


def _field_lines(policy):
    """Every 'Label: value' line the parser reads as a field. Each must fit on one PDF
    line (no wrap), or the parser would only see the first part of the value."""
    lines = [f"Broker: {policy['broker']['name']}", f"Type: {policy['type']}",
             f"Insured: {policy['insured']['name']}", f"Situation: {policy['situation']}",
             f"Deductible: {policy['deductible']}", f"Premium: {policy['premium']}",
             f"Choice of Law and Jurisdiction: {policy['law']}",
             f"Country of Origin: {policy['country']}"]
    lines += [f"- {x}" for x in policy["limits"] + policy["conditions"] + policy["exclusions"]]
    lines += [f"Syndicate {n} ({a}) | Written Line: {w:.2f}% | Signed Line: {w:.2f}%" for n, a, w in policy["security"]]
    lines += [f"Slip Leader: Syndicate {policy['security'][0][0]} ({policy['security'][0][1]})"]
    return lines


def generate():
    for p in POLICIES:
        too_long = [l for l in _field_lines(p) if len(l) > 96]
        if too_long:
            raise ValueError(f"{p['filename']}: field line would wrap and be cut when parsed: {too_long[0]!r}")
    os.makedirs(OUT, exist_ok=True)
    names = []
    for p in POLICIES:
        generate_pdf(p, OUT)
        names.append(p["filename"])
    names.append(generate_binding_authority(OUT))  # a new document type -> new schema
    names.append(generate_nonconforming(OUT))  # the 'not recognised -> HITL' document
    print(f"generated {len(names)} MRC PDFs in {OUT} (incl. 1 non-conforming)")
    return names


def upload(cfg, names):
    w = client(cfg)
    base = f'{cfg["volume_path"]}/mrc_inbox'
    for fn in names:
        with open(os.path.join(OUT, fn), "rb") as f:
            w.files.upload(f"{base}/{fn}", f, overwrite=True)
    print(f"uploaded {len(names)} MRC PDFs to {base}")


if __name__ == "__main__":
    cfg = load_config()
    upload(cfg, generate())
