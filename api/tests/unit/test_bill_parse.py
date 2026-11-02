from datetime import date
from pathlib import Path

import pytest

from adscontrol.bills.parse import parse_bill, parse_bill_text

TEXT = (Path(__file__).parents[1] / "fixtures" / "bill_text.txt").read_text()


def test_parses_october_values():
    d = parse_bill_text(TEXT)
    assert (d.period_start, d.period_end) == (date(2026, 9, 24), date(2026, 10, 23))
    assert (d.on_peak_kwh, d.off_peak_kwh, d.super_off_peak_kwh) == (30, 483, 546)
    assert d.total_kwh == 1058
    assert d.current_service == pytest.approx(126.46)
    assert d.ecc == pytest.approx(11.02)
    assert d.franchise_fee == pytest.approx(1.65)
    assert d.sales_tax == pytest.approx(11.13)
    assert d.actual_charge == pytest.approx(150.26)
    assert d.budget_payment == pytest.approx(248.00)
    assert d.budget_difference == pytest.approx(-97.74)
    assert d.running_difference == pytest.approx(-260.13)


def test_tolerates_rounded_total():
    d = parse_bill_text(TEXT)
    assert d.on_peak_kwh + d.off_peak_kwh + d.super_off_peak_kwh != d.total_kwh


def test_bill_without_budget_billing_leaves_those_empty():
    text = TEXT.split("Current Actual Amount")[0]
    d = parse_bill_text(text)
    assert d.actual_charge == pytest.approx(150.26)
    assert d.budget_payment is None
    assert d.running_difference is None


def test_positive_difference_keeps_its_sign():
    text = TEXT.replace("- $ 97.74", "$ 97.74").replace("- $ 260.13", "$ 260.13")
    d = parse_bill_text(text)
    assert d.budget_difference == pytest.approx(97.74)
    assert d.running_difference == pytest.approx(260.13)


def test_meter_constant_is_applied():
    d = parse_bill_text(TEXT.replace("Tot kWh 6225 5167 1", "Tot kWh 6225 5167 2"))
    assert d.total_kwh == 2116


def test_impossible_date_is_left_empty():
    d = parse_bill_text(TEXT.replace("Sep 24, 2026", "Sep 99, 2026"))
    assert d.period_start is None


def test_unreadable_pdf_returns_empty_draft_not_error():
    d = parse_bill(b"%PDF-1.7 this is not really a pdf")
    assert d.total_kwh is None
    assert d.actual_charge is None


def test_non_pdf_returns_empty_draft():
    assert parse_bill(b"hello").actual_charge is None
