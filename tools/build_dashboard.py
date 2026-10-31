"""Builds the procure-to-pay dashboard (site/index.html) from the SAP extract and test results."""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import report_kit as rk  # noqa: E402
from p2p.analytics import APPROVAL_THRESHOLD, PRICE_TOLERANCE, Dataset, analyse  # noqa: E402


def idr(amount: float) -> str:
    """IDR in billions/millions, the way finance reads it."""
    return f"Rp {amount / 1e9:,.2f} bn" if amount >= 1e9 else f"Rp {amount / 1e6:,.0f} m"


def main() -> None:
    a = analyse(Dataset.from_dir())
    results = json.loads((ROOT / "reports" / "results.json").read_text(encoding="utf-8"))
    test_counts = Counter(t["status"] for t in results["tests"])
    issues = len(a["exceptions"]) + len(a["maverick"]) + len(a["duplicates"]) + len(a["splits"])
    utilisation = a["committed"] / a["budget"]

    body = rk.kpis([
        ("Committed spend", idr(a["committed"]), f"{utilisation:.0%} of {idr(a['budget'])} budget", "warn" if utilisation > 0.9 else "ok"),
        ("Purchase orders", a["po_count"], f"{a['invoice_count']} invoices"),
        ("PR → PO cycle", f"{a['cycle_time_avg']:.1f} d", f"90th percentile {a['cycle_time_p90']} days"),
        ("First-time match", f"{a['first_time_match_rate']:.0%}", "three-way match, 5 % price tolerance", "ok" if a["first_time_match_rate"] >= 0.95 else "warn"),
        ("On-time payment", f"{a['on_time_payment_rate']:.0%}", f"late payments average {a['avg_days_late']:.1f} days", "ok" if a["on_time_payment_rate"] >= 0.8 else "warn"),
        ("Exceptions", issues, "need buyer or AP follow-up", "bad" if issues else "ok"),
    ])
    body += rk.grid(
        rk.section("Spend by category", rk.bars([(k, round(v / 1e9, 2)) for k, v in a["spend_by_category"].items()], unit=" bn")),
        rk.section("Three-way match results", rk.donut([
            ("Matched", a["three_way"].get("matched", 0), "var(--green)"),
            ("Price variance", a["three_way"].get("price variance", 0), "var(--orange)"),
            ("No goods receipt", a["three_way"].get("no goods receipt", 0), "var(--red)"),
            ("Quantity mismatch", a["three_way"].get("quantity mismatch", 0), "var(--purple)"),
        ], center=f"{a['first_time_match_rate']:.0%}", caption="first-time match")),
    )
    months = list(a["monthly_commitment"])
    cumulative, total = [], 0
    for m in months:
        total += a["monthly_commitment"][m]
        cumulative.append(round(total / 1e9, 2))
    budget_line = [round(a["budget"] / 1e9, 2)] * len(months)
    body += rk.section("Cumulative commitment vs budget (IDR bn)", rk.lines(
        [("Committed", cumulative, "var(--blue)"), ("Budget", budget_line, "var(--red)")], [m[2:] for m in months], unit=""))
    body += rk.section("Top vendors by committed spend", rk.bars([(k, round(v / 1e9, 2)) for k, v in list(a["spend_by_vendor"].items())[:6]], unit=" bn"))

    exception_rows = (
        [[rk.pill("High"), "Duplicate invoice", d["vendor"], f"Invoice {d['invoice']} repeats {d['original']} ({d['reference']})", idr(d["amount"]), "Block payment (MRBR) and reverse (MR8M)"] for d in a["duplicates"]]
        + [[rk.pill("High"), "Maverick buying", m["vendor"], f"Invoice {m['invoice']} dated {m['invoice_date']}, PO {m['po']} created {m['po_date']}", idr(m["amount"]), "Retro-PO: confirm approval, brief requester on PO-first policy"] for m in a["maverick"]]
        + [[rk.pill("High"), "Split purchase order", s["vendor"], f"{s['orders']} POs on {s['date']} under the approval limit", idr(s["total"]), f"Review against the {idr(APPROVAL_THRESHOLD)} approval threshold"] for s in a["splits"]]
        + [[rk.pill("Medium"), e["issue"].capitalize(), e["vendor"], f"Invoice {e['invoice']} on PO {e['po']}", idr(e["amount"]), "Post goods receipt (MIGO)" if e["issue"] == "no goods receipt" else f"Price above {PRICE_TOLERANCE:.0%} tolerance: confirm with buyer before release"] for e in a["exceptions"]]
    )
    body += rk.section("Exceptions for follow-up", rk.table(["Risk", "Type", "Vendor", "Detail", "Amount", "Suggested action (SAP)"], exception_rows, {0}),
                       "Detected automatically from the extract; transaction codes show where the fix happens in S/4HANA.")
    test_rows = [[t["title"], t["category"], rk.pill(t["status"])] for t in results["tests"]]
    body += rk.section(f"Automated checks · {test_counts['passed']}/{len(results['tests'])} passing", rk.table(["Check", "Area", "Result"], test_rows, {2}),
                       "Data-quality and business-rule tests run before the dashboard is built, so the numbers above can be trusted.")
    body += rk.section("Data model", rk.table(["SAP table", "Content", "Key fields used"], [
        ["LFA1", "Vendor master", "LIFNR, NAME1, LAND1"], ["EBAN", "Purchase requisitions", "BANFN, BADAT, EBELN"],
        ["EKKO / EKPO", "Purchase order header / items", "EBELN, EBELP, LIFNR, BEDAT, MENGE, NETPR, MATKL"],
        ["MSEG", "Goods movements (101 = GR)", "EBELN, EBELP, MENGE, BUDAT, BWART"],
        ["RBKP / RSEG", "Supplier invoice header / items", "BELNR, BLDAT, XBLNR, RMWWR, WRBTR"],
        ["BSAK (simplified)", "Cleared vendor items (payments)", "BELNR, AUGDT, ZFBDT"],
    ]))

    verdict = (f"{issues} exceptions to resolve before the next payment run", "warn") if issues else ("No exceptions: ready for payment run", "ok")
    takeaways = [
        f"Committed spend is {idr(a['committed'])}, {utilisation:.0%} of the {idr(a['budget'])} budget.",
        f"{a['first_time_match_rate']:.0%} of invoices matched their purchase order and goods receipt first time, and {a['on_time_payment_rate']:.0%} of suppliers were paid on time.",
    ]
    if a["duplicates"]:
        takeaways.append(f"{len(a['duplicates'])} duplicate invoice{'s' if len(a['duplicates']) != 1 else ''} worth {idr(sum(d['amount'] for d in a['duplicates']))} "
                         "would be paid twice if not blocked before the next payment run.")
    if a["maverick"] or a["splits"]:
        takeaways.append(f"Policy breaches: {len(a['maverick'])} purchase{'s' if len(a['maverick']) != 1 else ''} made before a purchase order existed "
                         f"and {len(a['splits'])} order{'s' if len(a['splits']) != 1 else ''} split to stay under the approval limit.")
    rk.write(str(ROOT / "site" / "index.html"), rk.page(
        title="Procure-to-Pay Analytics",
        eyebrow="SAP Consultant · MM / FI",
        summary="Procure-to-pay KPIs and exception detection on SAP S/4HANA-shaped data for the programme's purchases: HSM appliances, licences, consulting and security testing.",
        body=body, repo="sap-p2p-analytics", verdict=verdict, takeaways=takeaways,
    ))
    print(f"dashboard built: {issues} exceptions")


if __name__ == "__main__":
    main()
