"""Generates the demo dataset in data/, shaped like SAP S/4HANA procure-to-pay tables.

Fictional Arunika Bank buying for its Payment Security Modernisation programme. Seeded, so
the data (and the dashboard) are identical on every run. A handful of exceptions are planted
on purpose so the analytics have something real to find:
  - maverick buying: invoices dated before their purchase order
  - a duplicate invoice (same vendor, reference and amount)
  - price variances above the 5 % tolerance
  - split purchase orders just under the 250 M IDR approval threshold
  - goods receipts missing for invoiced items (three-way match fails)
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
EXTRACT_DATE = date(2026, 10, 31)  # nothing in the extract is dated after this

VENDORS = [  # LIFNR, NAME1, LAND1, category
    ("100001", "Secure Devices Asia Pte Ltd", "SG", "HSM hardware"),
    ("100002", "Kartu Prima Nusantara", "ID", "Payment cards"),
    ("100003", "Cipta Integrasi Konsultan", "ID", "Consulting"),
    ("100004", "RedLine Security Testing", "ID", "Security testing"),
    ("100005", "Cloudnine Software Licensing", "SG", "Software licences"),
    ("100006", "Datacentre Facilities Jakarta", "ID", "Data centre"),
    ("100007", "Nusantara Training Academy", "ID", "Training"),
    ("100008", "Global Key Ceremony Services", "AU", "Consulting"),
]
MATERIALS = {  # category -> (MATNR prefix, description, unit price range IDR)
    "HSM hardware": [("HSM-APPL", "Payment HSM appliance, dual PSU", (1_350_000_000, 1_500_000_000)), ("HSM-LIC", "HSM performance licence", (180_000_000, 220_000_000))],
    "Payment cards": [("CARD-EMV", "EMV chip card stock (1,000 pcs)", (38_000_000, 42_000_000))],
    "Consulting": [("SVC-ARCH", "Solution architecture (man-day)", (9_500_000, 11_000_000)), ("SVC-KC", "Key ceremony facilitation (day)", (24_000_000, 27_000_000))],
    "Security testing": [("SVC-PEN", "API penetration test (man-day)", (12_000_000, 14_000_000))],
    "Software licences": [("LIC-SIEM", "SIEM connector licence (annual)", (95_000_000, 105_000_000)), ("LIC-APIGW", "API gateway licence (annual)", (310_000_000, 330_000_000))],
    "Data centre": [("DC-RACK", "Secure rack space (month)", (42_000_000, 46_000_000))],
    "Training": [("TRN-HSM", "HSM operator training (seat)", (7_500_000, 8_500_000))],
}
PURCH_GROUPS = ["P10", "P20", "P30"]  # EKGRP: IT infrastructure, IT services, security
REQUESTERS = ["ADIT", "BUDI", "CITRA", "DEWI", "EKO", "FAJAR"]


def write(name: str, header: list[str], rows: list[list]) -> None:
    DATA.mkdir(exist_ok=True)
    with open(DATA / f"{name}.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def main() -> None:
    rng = random.Random(2026)
    start = date(2026, 2, 2)
    lfa1 = [[v[0], v[1], v[2], v[3]] for v in VENDORS]
    eban, ekko, ekpo, mseg, rbkp, rseg, payments = [], [], [], [], [], [], []
    po_no, pr_no, gr_no, inv_no = 4500001200, 10012000, 5000300000, 5100400000

    for n in range(140):
        vendor = rng.choices(VENDORS, weights=[2, 3, 4, 2, 2, 2, 2, 1])[0]
        category = vendor[3]
        matnr, text, (low, high) = rng.choice(MATERIALS[category])
        pr_date = start + timedelta(days=rng.randint(0, 250))
        po_date = pr_date + timedelta(days=max(1, int(rng.gauss(6, 3))))
        qty = 1 if "HSM-APPL" in matnr else rng.randint(1, 12)
        price = rng.randint(low // 1000, high // 1000) * 1000
        pr_no += 1
        po_no += 1
        eban.append([pr_no, 10, pr_date.isoformat(), rng.choice(REQUESTERS), matnr, qty, po_no])
        ekko.append([po_no, vendor[0], po_date.isoformat(), "NB", rng.choice(PURCH_GROUPS), "IDR"])
        ekpo.append([po_no, 10, matnr, text, qty, price, category])

        if po_date > date(2026, 10, 20):
            continue  # recently ordered: not delivered yet
        gr_date = po_date + timedelta(days=rng.randint(5, 30))
        if gr_date > EXTRACT_DATE:
            continue  # not delivered by the extract date
        gr_qty = qty
        missing_gr = n in (17, 58, 101)
        if not missing_gr:
            gr_no += 1
            mseg.append([gr_no, po_no, 10, gr_qty, gr_date.isoformat(), "101"])

        inv_date = gr_date + timedelta(days=rng.randint(1, 10))
        inv_price = price
        if n in (8, 44, 77, 120):
            inv_price = int(price * rng.uniform(1.07, 1.15))  # price variance above tolerance
        if n in (23, 91):
            inv_date = po_date - timedelta(days=rng.randint(3, 15))  # maverick: invoice before PO
        if inv_date > EXTRACT_DATE:
            continue  # not invoiced yet
        inv_no += 1
        reference = f"INV/{vendor[0][-3:]}/{inv_no % 10000:04d}"
        rbkp.append([inv_no, vendor[0], inv_date.isoformat(), reference, qty * inv_price])
        rseg.append([inv_no, po_no, 10, qty, inv_price])
        if n == 66:  # duplicate: same vendor, reference and amount posted again a week later
            inv_no += 1
            rbkp.append([inv_no, vendor[0], (inv_date + timedelta(days=7)).isoformat(), reference, qty * inv_price])
            rseg.append([inv_no, po_no, 10, qty, inv_price])

        due = inv_date + timedelta(days=30)
        paid = due + timedelta(days=rng.choice([-6, -4, -2, -1, 0, 0, 0, 0, 2, 5, 12]))
        if paid <= EXTRACT_DATE:
            payments.append([inv_no, paid.isoformat(), due.isoformat()])

    # split purchasing: four POs on the same day, same vendor, each just under the approval limit
    for i in range(4):
        po_no += 1
        pr_no += 1
        day = date(2026, 6, 15).isoformat()
        eban.append([pr_no, 10, day, "FAJAR", "SVC-ARCH", 24, po_no])
        ekko.append([po_no, "100003", day, "NB", "P20", "IDR"])
        ekpo.append([po_no, 10, "SVC-ARCH", "Solution architecture (man-day)", 24, 10_300_000, "Consulting"])

    write("LFA1", ["LIFNR", "NAME1", "LAND1", "CATEGORY"], lfa1)
    write("EBAN", ["BANFN", "BNFPO", "BADAT", "AFNAM", "MATNR", "MENGE", "EBELN"], eban)
    write("EKKO", ["EBELN", "LIFNR", "BEDAT", "BSART", "EKGRP", "WAERS"], ekko)
    write("EKPO", ["EBELN", "EBELP", "MATNR", "TXZ01", "MENGE", "NETPR", "MATKL"], ekpo)
    write("MSEG", ["MBLNR", "EBELN", "EBELP", "MENGE", "BUDAT", "BWART"], mseg)
    write("RBKP", ["BELNR", "LIFNR", "BLDAT", "XBLNR", "RMWWR"], rbkp)
    write("RSEG", ["BELNR", "EBELN", "EBELP", "MENGE", "WRBTR"], rseg)
    write("PAYMENTS", ["BELNR", "AUGDT", "ZFBDT"], payments)
    print(f"wrote {len(ekko)} POs, {len(rbkp)} invoices, {len(mseg)} goods receipts to {DATA}")


if __name__ == "__main__":
    main()
