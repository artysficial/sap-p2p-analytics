"""Unit tests for the P2P business rules, and checks that every planted exception is detected."""

import pytest

from p2p.analytics import APPROVAL_THRESHOLD, three_way_match

PO_LINE = {"MENGE": "10", "NETPR": "1000000"}


@pytest.mark.category("Business rules")
@pytest.mark.severity("critical")
@pytest.mark.parametrize("received, invoiced, price, expected", [
    (10, 10, 1_000_000, "matched"),
    (10, 10, 1_050_000, "matched"),            # exactly at the 5 % tolerance
    (10, 10, 1_050_001, "price variance"),
    (0, 10, 1_000_000, "no goods receipt"),
    (6, 10, 1_000_000, "quantity mismatch"),   # invoiced more than received
    (10, 12, 1_000_000, "quantity mismatch"),  # invoiced more than ordered
])
def test_three_way_match_rule(received, invoiced, price, expected):
    """Three-way match compares PO, goods receipt and invoice with a 5 % price tolerance"""
    assert three_way_match(PO_LINE, received, invoiced, price) == expected


@pytest.mark.category("Exception detection")
@pytest.mark.severity("high")
def test_price_variances_are_detected(analysis):
    """Invoices priced above tolerance are flagged (4 planted)"""
    assert sum(1 for e in analysis["exceptions"] if e["issue"] == "price variance") == 4


@pytest.mark.category("Exception detection")
@pytest.mark.severity("high")
def test_missing_goods_receipts_are_detected(analysis):
    """Invoices without a goods receipt are flagged (3 planted)"""
    assert sum(1 for e in analysis["exceptions"] if e["issue"] == "no goods receipt") == 3


@pytest.mark.category("Exception detection")
@pytest.mark.severity("high")
def test_maverick_buying_is_detected(analysis):
    """Invoices dated before their PO (retro-POs) are flagged (2 planted)"""
    assert len(analysis["maverick"]) == 2
    assert all(m["invoice_date"] < m["po_date"] for m in analysis["maverick"])


@pytest.mark.category("Exception detection")
@pytest.mark.severity("critical")
def test_duplicate_invoice_is_detected(analysis):
    """The same vendor, reference and amount posted twice is flagged (1 planted)"""
    assert len(analysis["duplicates"]) == 1
    assert analysis["duplicates"][0]["invoice"] != analysis["duplicates"][0]["original"]


@pytest.mark.category("Exception detection")
@pytest.mark.severity("high")
def test_split_purchase_orders_are_detected(analysis):
    """Same-day orders to one vendor that dodge the approval limit are flagged"""
    planted = [s for s in analysis["splits"] if s["date"] == "2026-06-15"]
    # at least the 4 planted orders (a regular order on the same day can join the group)
    assert planted and planted[0]["orders"] >= 4 and planted[0]["total"] >= APPROVAL_THRESHOLD


@pytest.mark.category("KPI sanity")
@pytest.mark.severity("medium")
def test_kpis_are_within_valid_ranges(analysis):
    """Rates are between 0 and 1 and the cycle time is positive"""
    for rate in ("first_time_match_rate", "maverick_spend_share", "on_time_payment_rate"):
        assert 0 <= analysis[rate] <= 1
    assert analysis["cycle_time_avg"] > 0


@pytest.mark.category("KPI sanity")
@pytest.mark.severity("medium")
def test_spend_breakdowns_reconcile_to_total(analysis):
    """Spend by category and by vendor both add up to the committed total"""
    assert sum(analysis["spend_by_category"].values()) == analysis["committed"]
    assert sum(analysis["spend_by_vendor"].values()) == analysis["committed"]
