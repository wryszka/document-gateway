"""Phase 2/6 — deterministic synthetic bordereaux generator (premium + claims).

Reads the bordereaux tenant config (roster + layouts) and emits realistic coverholder
premium AND claims bordereaux into data/generated/, then uploads them to the landing
inbox. Deterministic conditional on config.seed. Months are DERIVED from as_of (today
by default) so a reset rolls the book forward to now (Principle 11). Every file has a
title block (name / reference / reporting month), a blank row, then the header row
(row 5) using that coverholder's OWN column labels, then data rows.

Exercises all four inbound states + a resubmission:
  - known & unchanged  : established coverholders on their known layout
  - known but changed  : Ridgeway's LATEST premium renames columns (drift layout)
  - unknown            : Saltmarsh (brand-new, no template)
  - unusable           : an image-only PDF cover note with no table
  - resubmission       : Harbourline's MIDDLE-month premium restated (money impact)

Run:  uv run --with databricks-sdk,openpyxl,reportlab python data/generate_docs.py
"""
from __future__ import annotations

import os
import random
import shutil
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import load_config, load_tenant, client  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "generated")
HEADER_ROW = 5

INSUREDS = ["Northwind Logistics", "Blue Harbour Cafes", "Apex Joinery", "Delta Freight",
            "Green Valley Farms", "Coastal Marine Repairs", "Stonebridge Property",
            "Vantage IT Services", "Meadowlark Bakery", "Ironclad Security",
            "Riverside Dental", "Summit Roofing", "Parkside Pharmacy", "Cedar Fabrication"]
LOBS = ["Commercial Property", "General Liability", "Commercial Motor", "Marine Cargo",
        "Professional Indemnity"]
CAUSES = ["Escape of water", "Fire", "Theft", "Storm", "Accidental damage", "Liability", "Impact"]


def _as_of(cfg):
    a = cfg.get("as_of", "auto")
    return date.today() if a in ("auto", "", None) else date.fromisoformat(a)


def _recent_months(as_of, n):
    """The n complete calendar months ending with the month before as_of (oldest first)."""
    y, m = as_of.year, as_of.month
    months = []
    for _ in range(n):
        m -= 1
        if m == 0:
            m = 12; y -= 1
        months.append(f"{y:04d}-{m:02d}")
    return list(reversed(months))


def _rng(cfg, key):
    return random.Random(f"{cfg['seed']}|{key}")


def _month_start(mth):
    y, mo = mth.split("-")
    return date(int(y), int(mo), 1)


def _premium_rows(cfg, ch, month, n, mult=1.0):
    r = _rng(cfg, f"prem|{ch['name']}|{month}")
    ms = _month_start(month)
    ccy = "EUR" if ch["country_code"] == "IE" else "GBP"
    out = []
    for i in range(n):
        inc = ms + timedelta(days=r.randint(0, 27))
        gross = round(r.uniform(1500, 45000) * mult, 2)
        out.append({
            "policy_number": f'{ch["coverholder_reference"]}-{month.replace("-", "")}-{i+1:03d}',
            "insured_name": r.choice(INSUREDS), "line_of_business": r.choice(LOBS),
            "inception_date": inc.isoformat(), "expiry_date": (inc + timedelta(days=365)).isoformat(),
            "currency": ccy, "gross_premium": gross,
            "commission_amount": round(gross * r.uniform(0.10, 0.225), 2),
            "risk_country": ch["country_code"],
            "risk_postcode": f'{r.choice("ABEGLMNS")}{r.randint(1,99)} {r.randint(1,9)}{r.choice("ABDEHJ")}{r.choice("ABDEHJ")}',
        })
    return out


def _claim_rows(cfg, ch, month, n, n_policies):
    r = _rng(cfg, f"clm|{ch['name']}|{month}")
    ms = _month_start(month)
    ccy = "EUR" if ch["country_code"] == "IE" else "GBP"
    out = []
    for i in range(n):
        pol = r.randint(1, n_policies)
        paid = round(r.uniform(500, 28000), 2)
        outstanding = round(r.uniform(0, 20000), 2)
        loss = ms - timedelta(days=r.randint(0, 120))
        out.append({
            "claim_reference": f'CLM-{ch["coverholder_reference"]}-{month.replace("-", "")}-{i+1:03d}',
            "policy_number": f'{ch["coverholder_reference"]}-{month.replace("-", "")}-{pol:03d}',
            "loss_date": loss.isoformat(), "paid_amount": paid, "outstanding_amount": outstanding,
            "cause_of_loss": r.choice(CAUSES), "currency": ccy,
        })
    return out


def _write_xlsx(path, ch, month, layout, fields, rows):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "Bordereau"
    ws["A1"] = ch["name"]; ws["A2"] = ch["coverholder_reference"]; ws["A3"] = month
    for c, f in enumerate(fields, 1):
        ws.cell(row=HEADER_ROW, column=c, value=layout[f])
    for ri, row in enumerate(rows, HEADER_ROW + 1):
        for c, f in enumerate(fields, 1):
            ws.cell(row=ri, column=c, value=row[f])
    wb.save(path)


def _write_unusable_pdf(path, ch, month):
    try:
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(path)
        c.drawString(80, 760, f"{ch['name']} — cover note")
        c.drawString(80, 740, f"Reporting month: {month}")
        c.drawString(80, 700, "(scanned image — bordereau attached separately)")
        c.save()
    except Exception:
        open(path, "wb").write(b"%PDF-1.4\n%%EOF\n")


def generate(cfg):
    t = load_tenant(cfg, "bordereaux")
    layouts, lf, co = t["layouts"], t["logical_fields"], t["coverholders"]
    months = _recent_months(_as_of(cfg), co["report_months"])
    nprem, nclaim = co["lines_per_drop"], co["claims_per_drop"]
    latest, middle = months[-1], months[len(months) // 2]

    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)
    manifest = []

    def emit(ch, month, family, layout_name, fields_key, rows):
        fname = f'{ch["coverholder_reference"]}_{family}_{month}.xlsx'
        _write_xlsx(os.path.join(OUT, fname), ch, month, layouts[layout_name], lf[fields_key], rows)
        manifest.append(fname)

    for ch in co["roster"]:
        ch_months = [latest] if ch["status"] == "new" else months
        for month in ch_months:
            # premium (with drift on the latest month for the drifting coverholder)
            play = ch["premium_layout"]
            if ch.get("drift") and month == latest:
                play = ch["drift"]["layout"]
            emit(ch, month, "premium", play, "premium", _premium_rows(cfg, ch, month, nprem))
            # resubmission of the middle month's premium (restated) — same layout, bumped
            if ch.get("resubmit") and month == middle:
                mult = 1.0 + ch["resubmit"]["gross_premium_delta_pct"]
                fname = f'{ch["coverholder_reference"]}_premium_{month}_v2.xlsx'
                _write_xlsx(os.path.join(OUT, fname), ch, month, layouts[ch["premium_layout"]],
                            lf["premium"], _premium_rows(cfg, ch, month, nprem, mult=mult))
                manifest.append(fname)
            # claims
            emit(ch, month, "claims", ch["claims_layout"], "claims",
                 _claim_rows(cfg, ch, month, nclaim, nprem))

    # unusable image-only PDF drop
    u = co.get("unusable_drop")
    if u:
        fn = f'{co["roster"][0]["coverholder_reference"]}_scan_{latest}.pdf'
        _write_unusable_pdf(os.path.join(OUT, fn), co["roster"][0], latest)
        manifest.append(fn)

    print(f"generated {len(manifest)} files into {OUT} (months {months}):")
    for m in manifest:
        print("  ", m)
    return manifest


def upload(cfg, manifest):
    w = client(cfg)
    base = f'{cfg["volume_path"]}/inbox'
    for fname in manifest:
        with open(os.path.join(OUT, fname), "rb") as f:
            w.files.upload(f"{base}/{fname}", f, overwrite=True)
    print(f"uploaded {len(manifest)} files to {base}")


SLIP_OUT = os.path.join(ROOT, "data", "generated_slips")


def generate_slips(cfg):
    """Health renewal slips — the T2 config-port. Reuses the same xlsx writer; the shape is
    driven entirely by tenants/health_slip/tenant.json (one file, N employer-group rows)."""
    t = load_tenant(cfg, "health_slip")
    carrier = t["carrier"]
    layout = t["layouts"][carrier["layout"]]
    fields = t["logical_fields"]["renewal"]
    if os.path.exists(SLIP_OUT):
        shutil.rmtree(SLIP_OUT)
    os.makedirs(SLIP_OUT, exist_ok=True)
    ch = {"name": carrier["name"], "coverholder_reference": carrier["reference"]}
    fname = f'{carrier["reference"]}_renewalslip_{carrier["period"]}.xlsx'
    _write_xlsx(os.path.join(SLIP_OUT, fname), ch, carrier["period"], layout, fields, t["groups"])
    print(f"generated 1 renewal slip ({len(t['groups'])} groups) into {SLIP_OUT}: {fname}")
    return [fname]


def upload_slips(cfg, manifest):
    w = client(cfg)
    base = f'{cfg["volume_path"]}/slip_inbox'
    for fname in manifest:
        with open(os.path.join(SLIP_OUT, fname), "rb") as f:
            w.files.upload(f"{base}/{fname}", f, overwrite=True)
    print(f"uploaded {len(manifest)} slip(s) to {base}")


if __name__ == "__main__":
    cfg = load_config()
    upload(cfg, generate(cfg))
