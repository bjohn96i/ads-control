"""Reads a Georgia Power bill. Anything it cannot find stays None, for a person to fill in."""

import io
import re
from datetime import date, datetime

from pydantic import BaseModel
from pypdf import PdfReader
from pypdf.errors import PyPdfError

_NUMBER = r"([\d,]+\.\d\d)"
_LABELLED = {
    "current_service": rf"Current Service\s+\$?\s*{_NUMBER}",
    "ecc": rf"Environmental Compliance Cost\s+\$?\s*{_NUMBER}",
    "franchise_fee": rf"Municipal Franchise Fee\s+\$?\s*{_NUMBER}",
    "sales_tax": rf"Sales Tax\s+\$?\s*{_NUMBER}",
    "actual_charge": rf"Total Current Electric Service\s+\$?\s*{_NUMBER}",
}
_METERS = {
    "off_peak_kwh": r"Offpk kWh\s+(\d+)\s+(\d+)\s+(\d+)",
    "on_peak_kwh": r"Onpk kWh\s+(\d+)\s+(\d+)\s+(\d+)",
    "total_kwh": r"Tot kWh\s+(\d+)\s+(\d+)\s+(\d+)",
    "super_off_peak_kwh": r"SuperOffPkKWH?\s+(\d+)\s+(\d+)\s+(\d+)",
}
_PERIOD = r"Billing Period:\s+(\w{3} \d{1,2}, \d{4})\s*-\s*(\w{3} \d{1,2}, \d{4})"
# The Budget Billing box prints its five figures together, without labels beside them:
# actual, budget, current difference, previous difference, total difference.
_BUDGET = r"\$\s*([\d,.]+)\s+\$\s*([\d,.]+)\s+(-?)\s*\$\s*([\d,.]+)\s+(-?)\s*\$\s*([\d,.]+)\s+(-?)\s*\$\s*([\d,.]+)"


class BillDraft(BaseModel):
    period_start: date | None = None
    period_end: date | None = None
    on_peak_kwh: float | None = None
    off_peak_kwh: float | None = None
    super_off_peak_kwh: float | None = None
    total_kwh: float | None = None
    current_service: float | None = None
    ecc: float | None = None
    franchise_fee: float | None = None
    sales_tax: float | None = None
    actual_charge: float | None = None
    budget_payment: float | None = None
    budget_difference: float | None = None
    running_difference: float | None = None


def _money(text: str) -> float:
    return float(text.replace(",", ""))


def _date(text: str) -> date | None:
    try:
        return datetime.strptime(text, "%b %d, %Y").date()
    except ValueError:
        return None


def parse_bill_text(text: str) -> BillDraft:
    fields: dict = {}
    if period := re.search(_PERIOD, text):
        fields["period_start"], fields["period_end"] = _date(period[1]), _date(period[2])
    for name, pattern in _METERS.items():
        if meter := re.search(pattern, text):
            fields[name] = (int(meter[1]) - int(meter[2])) * int(meter[3])
    for name, pattern in _LABELLED.items():
        if found := re.search(pattern, text):
            fields[name] = _money(found[1])
    if budget := re.search(_BUDGET, text):
        fields["budget_payment"] = _money(budget[2])
        fields["budget_difference"] = _money(budget[4]) * (-1 if budget[3] else 1)
        fields["running_difference"] = _money(budget[8]) * (-1 if budget[7] else 1)
    return BillDraft(**fields)


def parse_bill(pdf_bytes: bytes) -> BillDraft:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except (PyPdfError, ValueError, OSError, KeyError, TypeError, IndexError):
        return BillDraft()
    return parse_bill_text(text)
