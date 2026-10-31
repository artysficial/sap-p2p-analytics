"""Data-quality checks on the SAP extract, the same ones you run before trusting any P2P report."""

from collections import Counter
from datetime import date

import pytest

pytestmark = pytest.mark.category("Data quality")


@pytest.mark.severity("critical")
@pytest.mark.parametrize("table, key", [("vendors", ("LIFNR",)), ("po_headers", ("EBELN",)), ("po_items", ("EBELN", "EBELP")), ("invoice_headers", ("BELNR",)), ("goods_receipts", ("MBLNR",))])
def test_primary_keys_are_unique(ds, table, key):
    """Primary keys are unique in every table"""
    rows = getattr(ds, table)
    duplicates = [k for k, n in Counter(tuple(r[c] for c in key) for r in rows).items() if n > 1]
    assert not duplicates, f"duplicate keys in {table}: {duplicates[:5]}"


@pytest.mark.severity("critical")
def test_purchase_orders_reference_existing_vendors(ds):
    """Every PO header points at a vendor in LFA1"""
    vendors = {v["LIFNR"] for v in ds.vendors}
    assert all(h["LIFNR"] in vendors for h in ds.po_headers)


@pytest.mark.severity("critical")
def test_items_goods_receipts_and_invoices_reference_existing_po_lines(ds):
    """Every PO item, goods receipt and invoice line references an existing PO (line)"""
    headers = {h["EBELN"] for h in ds.po_headers}
    lines = {(i["EBELN"], i["EBELP"]) for i in ds.po_items}
    assert all(i["EBELN"] in headers for i in ds.po_items)
    assert all((g["EBELN"], g["EBELP"]) in lines for g in ds.goods_receipts)
    assert all((r["EBELN"], r["EBELP"]) in lines for r in ds.invoice_items)


@pytest.mark.severity("high")
def test_invoice_header_totals_equal_their_lines(ds):
    """Each invoice header amount (RMWWR) equals the sum of its lines"""
    totals = Counter()
    for line in ds.invoice_items:
        totals[line["BELNR"]] += int(line["MENGE"]) * int(line["WRBTR"])
    assert all(int(h["RMWWR"]) == totals[h["BELNR"]] for h in ds.invoice_headers)


@pytest.mark.severity("high")
def test_quantities_and_prices_are_positive(ds):
    """Quantities and net prices are positive numbers"""
    assert all(int(i["MENGE"]) > 0 and int(i["NETPR"]) > 0 for i in ds.po_items)
    assert all(int(g["MENGE"]) > 0 for g in ds.goods_receipts)


@pytest.mark.severity("medium")
def test_documents_are_in_a_single_currency(ds):
    """All purchase orders are in IDR (no unconverted foreign currency)"""
    assert {h["WAERS"] for h in ds.po_headers} == {"IDR"}


@pytest.mark.severity("medium")
def test_goods_receipts_use_movement_type_101(ds):
    """Goods receipts are movement type 101 (GR for purchase order)"""
    assert {g["BWART"] for g in ds.goods_receipts} == {"101"}


@pytest.mark.severity("medium")
def test_requisitions_precede_their_purchase_orders(ds):
    """No PO is dated before its purchase requisition"""
    po_dates = {h["EBELN"]: date.fromisoformat(h["BEDAT"]) for h in ds.po_headers}
    assert all(po_dates[r["EBELN"]] >= date.fromisoformat(r["BADAT"]) for r in ds.requisitions)


@pytest.mark.severity("medium")
def test_no_documents_dated_in_the_future(ds):
    """No document is dated after the extract date"""
    extract = date(2026, 10, 31)
    for rows, field in ((ds.po_headers, "BEDAT"), (ds.invoice_headers, "BLDAT"), (ds.goods_receipts, "BUDAT")):
        assert all(date.fromisoformat(r[field]) <= extract for r in rows)
