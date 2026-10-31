"""Procure-to-pay analytics over SAP-shaped tables (plain Python, no pandas needed).

The same checks an SAP MM/FI consultant or auditor runs in S/4HANA (ME2N, MB51, MIR6,
FBL1N) or in an analytics tool on top of it: cycle times, three-way match, price variance,
maverick buying, duplicate invoices, split purchase orders and payment performance.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
PRICE_TOLERANCE = 0.05          # invoice price may exceed PO price by at most 5 %
APPROVAL_THRESHOLD = 250_000_000  # POs above this need a second approval (IDR)
PROGRAMME_BUDGET = 70_000_000_000  # procurement budget of the programme (IDR)


def load(name: str, data_dir: Path = DATA) -> list[dict]:
    with open(data_dir / f"{name}.csv", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def d(value: str) -> date:
    return date.fromisoformat(value)


@dataclass
class Dataset:
    vendors: list[dict]
    requisitions: list[dict]
    po_headers: list[dict]
    po_items: list[dict]
    goods_receipts: list[dict]
    invoice_headers: list[dict]
    invoice_items: list[dict]
    payments: list[dict]

    @classmethod
    def from_dir(cls, data_dir: Path = DATA) -> "Dataset":
        return cls(*(load(n, data_dir) for n in ("LFA1", "EBAN", "EKKO", "EKPO", "MSEG", "RBKP", "RSEG", "PAYMENTS")))


def po_value(item: dict) -> int:
    return int(item["MENGE"]) * int(item["NETPR"])


def three_way_match(po_item: dict, received_qty: int, invoiced_qty: int, invoiced_price: int) -> str:
    """'matched', 'no goods receipt', 'quantity mismatch' or 'price variance'."""
    if received_qty == 0:
        return "no goods receipt"
    if invoiced_qty > received_qty or invoiced_qty > int(po_item["MENGE"]):
        return "quantity mismatch"
    if invoiced_price > int(po_item["NETPR"]) * (1 + PRICE_TOLERANCE):
        return "price variance"
    return "matched"


def analyse(ds: Dataset) -> dict:
    vendors = {v["LIFNR"]: v for v in ds.vendors}
    headers = {h["EBELN"]: h for h in ds.po_headers}
    items = {(i["EBELN"], i["EBELP"]): i for i in ds.po_items}
    received = defaultdict(int)
    for gr in ds.goods_receipts:
        received[(gr["EBELN"], gr["EBELP"])] += int(gr["MENGE"])
    invoice_header = {h["BELNR"]: h for h in ds.invoice_headers}

    # spend
    spend_by_category, spend_by_vendor = defaultdict(int), defaultdict(int)
    for item in ds.po_items:
        spend_by_category[item["MATKL"]] += po_value(item)
        spend_by_vendor[vendors[headers[item["EBELN"]]["LIFNR"]]["NAME1"]] += po_value(item)
    committed = sum(spend_by_category.values())

    # cycle time requisition -> PO
    cycle = [(d(headers[r["EBELN"]]["BEDAT"]) - d(r["BADAT"])).days for r in ds.requisitions if r["EBELN"] in headers]

    # three-way match per invoice line
    match_results, exceptions = defaultdict(int), []
    for line in ds.invoice_items:
        key = (line["EBELN"], line["EBELP"])
        result = three_way_match(items[key], received[key], int(line["MENGE"]), int(line["WRBTR"]))
        match_results[result] += 1
        if result != "matched":
            exceptions.append({"invoice": line["BELNR"], "po": line["EBELN"], "issue": result,
                               "vendor": vendors[invoice_header[line["BELNR"]]["LIFNR"]]["NAME1"],
                               "amount": int(line["MENGE"]) * int(line["WRBTR"])})

    # maverick buying: invoice dated before the PO that it is booked against
    maverick = []
    for line in ds.invoice_items:
        inv, po = invoice_header[line["BELNR"]], headers[line["EBELN"]]
        if d(inv["BLDAT"]) < d(po["BEDAT"]):
            maverick.append({"invoice": inv["BELNR"], "po": po["EBELN"], "invoice_date": inv["BLDAT"], "po_date": po["BEDAT"],
                             "amount": int(inv["RMWWR"]), "vendor": vendors[inv["LIFNR"]]["NAME1"]})

    # duplicate invoices: same vendor, reference and amount
    seen, duplicates = {}, []
    for inv in sorted(ds.invoice_headers, key=lambda h: h["BLDAT"]):
        key = (inv["LIFNR"], inv["XBLNR"], inv["RMWWR"])
        if key in seen:
            duplicates.append({"invoice": inv["BELNR"], "original": seen[key], "reference": inv["XBLNR"], "amount": int(inv["RMWWR"]), "vendor": vendors[inv["LIFNR"]]["NAME1"]})
        else:
            seen[key] = inv["BELNR"]

    # split purchase orders: same vendor and day, each below the threshold, together above it
    groups = defaultdict(list)
    for item in ds.po_items:
        header = headers[item["EBELN"]]
        groups[(header["LIFNR"], header["BEDAT"])].append(po_value(item))
    splits = [
        {"vendor": vendors[vendor]["NAME1"], "date": day, "orders": len(values), "total": sum(values)}
        for (vendor, day), values in groups.items()
        if len(values) > 1 and all(v < APPROVAL_THRESHOLD for v in values) and sum(values) >= APPROVAL_THRESHOLD
    ]

    # payment performance
    on_time = sum(1 for p in ds.payments if d(p["AUGDT"]) <= d(p["ZFBDT"]))
    late_days = [(d(p["AUGDT"]) - d(p["ZFBDT"])).days for p in ds.payments if d(p["AUGDT"]) > d(p["ZFBDT"])]

    monthly = defaultdict(int)
    for item in ds.po_items:
        monthly[headers[item["EBELN"]]["BEDAT"][:7]] += po_value(item)

    lines = len(ds.invoice_items)
    return {
        "committed": committed,
        "budget": PROGRAMME_BUDGET,
        "po_count": len(ds.po_headers),
        "invoice_count": len(ds.invoice_headers),
        "spend_by_category": dict(sorted(spend_by_category.items(), key=lambda kv: -kv[1])),
        "spend_by_vendor": dict(sorted(spend_by_vendor.items(), key=lambda kv: -kv[1])),
        "monthly_commitment": dict(sorted(monthly.items())),
        "cycle_time_avg": sum(cycle) / len(cycle),
        "cycle_time_p90": sorted(cycle)[int(0.9 * (len(cycle) - 1))],
        "three_way": dict(match_results),
        "first_time_match_rate": match_results["matched"] / lines,
        "exceptions": exceptions,
        "maverick": maverick,
        "maverick_spend_share": sum(m["amount"] for m in maverick) / max(1, sum(int(h["RMWWR"]) for h in ds.invoice_headers)),
        "duplicates": duplicates,
        "splits": splits,
        "on_time_payment_rate": on_time / max(1, len(ds.payments)),
        "avg_days_late": sum(late_days) / max(1, len(late_days)),
        "payments": len(ds.payments),
    }
