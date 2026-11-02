"""Power bills: read a PDF into a draft, save what a person confirmed, compare with the meter."""

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from adscontrol.api.maintenance import require_action
from adscontrol.bills.parse import parse_bill
from adscontrol.energy import energy_by_zone
from adscontrol.rates import LOCAL

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
COMPARE_MIN_COVERAGE = 0.9

router = APIRouter(prefix="/api/bills")
write = [Depends(require_action)]

_COLUMNS = (
    "period_start, period_end, on_peak_kwh, off_peak_kwh, super_off_peak_kwh, total_kwh, "
    "current_service, ecc, franchise_fee, sales_tax, actual_charge, budget_payment, "
    "budget_difference, running_difference"
)
_INSERT = f"""
    INSERT INTO bills ({_COLUMNS}) VALUES (
        :period_start, :period_end, :on_peak_kwh, :off_peak_kwh, :super_off_peak_kwh, :total_kwh,
        :current_service, :ecc, :franchise_fee, :sales_tax, :actual_charge, :budget_payment,
        :budget_difference, :running_difference
    )
"""


class BillIn(BaseModel):
    period_start: date
    period_end: date
    on_peak_kwh: float | None = Field(default=None, ge=0)
    off_peak_kwh: float | None = Field(default=None, ge=0)
    super_off_peak_kwh: float | None = Field(default=None, ge=0)
    total_kwh: float = Field(ge=0)
    current_service: float | None = None
    ecc: float | None = None
    franchise_fee: float | None = None
    sales_tax: float | None = None
    actual_charge: float = Field(ge=0)
    budget_payment: float | None = Field(default=None, ge=0)
    budget_difference: float | None = None
    running_difference: float | None = None

    @model_validator(mode="after")
    def period_runs_forward(self) -> "BillIn":
        if self.period_end < self.period_start:
            raise ValueError("the billing period ends before it starts")
        return self


class BillsIn(BaseModel):
    bills: list[BillIn]


def local_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=LOCAL)


async def _all(session) -> list[dict]:
    rows = await session.execute(text(f"SELECT id, {_COLUMNS} FROM bills ORDER BY period_end DESC"))
    return [dict(row._mapping) for row in rows]


@router.get("")
async def list_bills(request: Request) -> dict:
    async with request.app.state.sessions() as session:
        return {"bills": await _all(session)}


@router.get("/latest")
async def latest(request: Request) -> dict | None:
    async with request.app.state.sessions() as session:
        bills = await _all(session)
    return bills[0] if bills else None


@router.get("/export")
async def export(request: Request) -> dict:
    async with request.app.state.sessions() as session:
        bills = await _all(session)
    return {"bills": [{k: v for k, v in b.items() if k != "id"} for b in bills]}


@router.post("/import", dependencies=write)
async def import_(body: BillsIn, request: Request) -> dict:
    added = 0
    async with request.app.state.sessions() as session:
        for bill in body.bills:
            result = await session.execute(
                text(_INSERT + " ON CONFLICT (period_start, period_end) DO NOTHING"),
                bill.model_dump(),
            )
            added += result.rowcount
        await session.commit()
    return {"bills": added}


@router.post("/parse", dependencies=write)
async def parse(request: Request) -> dict:
    """Reads the PDF and returns a draft. Saving is a separate step, after a person checks it."""
    body = await request.body()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="that file is too large")
    return parse_bill(body).model_dump()


@router.post("", status_code=201, dependencies=write)
async def save(body: BillIn, request: Request) -> dict:
    async with request.app.state.sessions() as session:
        try:
            bill_id = await session.scalar(text(_INSERT + " RETURNING id"), body.model_dump())
            await session.commit()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="that period is already saved") from exc
    return {"id": bill_id}


@router.delete("/{bill_id}", status_code=204, dependencies=write)
async def delete(bill_id: int, request: Request) -> None:
    async with request.app.state.sessions() as session:
        result = await session.execute(text("DELETE FROM bills WHERE id = :b"), {"b": bill_id})
        await session.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="no such bill")


@router.get("/{bill_id}/compare")
async def compare(bill_id: int, request: Request) -> dict:
    async with request.app.state.sessions() as session:
        bill = (
            await session.execute(
                text("SELECT period_start, period_end, total_kwh FROM bills WHERE id = :b"),
                {"b": bill_id},
            )
        ).first()
        if bill is None:
            raise HTTPException(status_code=404, detail="no such bill")
        start = local_midnight(bill.period_start)
        end = local_midnight(bill.period_end + timedelta(days=1))
        energy = await energy_by_zone(session, start, end)
    whole = next(e for e in energy if e.name == "Whole House")
    trusted = whole.coverage >= COMPARE_MIN_COVERAGE and bill.total_kwh > 0
    return {
        "billed_kwh": bill.total_kwh,
        "measured_kwh": whole.kwh,
        "coverage": whole.coverage,
        # With gaps the meter reads low for a dull reason, so no percentage is offered.
        "difference_pct": (
            (whole.kwh - bill.total_kwh) / bill.total_kwh * 100 if trusted else None
        ),
    }
