import math
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from adscontrol.api.maintenance import require_action
from adscontrol.auth import (
    COOKIE_NAME,
    SESSION_DAYS,
    is_secure,
    load,
    lockout_seconds,
    make_session_value,
    pin_matches,
    require_pin,
    session_is_valid,
)

router = APIRouter(prefix="/api/auth")


class PinIn(BaseModel):
    pin: str = Field(max_length=64)


@router.get("/status")
async def status(request: Request) -> dict:
    async with request.app.state.sessions() as session:
        row = await load(session)
    return {
        "pin_set": row is not None,
        "unlocked": row is not None
        and session_is_valid(row, request.cookies.get(COOKIE_NAME), request.app.state.clock()),
    }


@router.get("/check", status_code=204, dependencies=[Depends(require_pin)])
async def check() -> None:
    return None


@router.post("/pin", dependencies=[Depends(require_action)])
async def enter_pin(body: PinIn, request: Request, response: Response) -> dict:
    if not is_secure(request):
        raise HTTPException(status_code=400, detail="use the HTTPS address")
    now = request.app.state.clock()
    async with request.app.state.sessions() as session:
        row = await load(session)
        if row is None:
            raise HTTPException(status_code=409, detail="no PIN has been set")
        if row.locked_until is not None and now < row.locked_until:
            wait = math.ceil((row.locked_until - now).total_seconds())
            # The answer is the same whether or not this PIN is right, so nothing leaks.
            raise HTTPException(
                status_code=429, detail="too many tries", headers={"Retry-After": str(wait)}
            )
        if not pin_matches(row, body.pin):
            failures = row.failures + 1
            wait = lockout_seconds(failures)
            await session.execute(
                text("UPDATE auth_settings SET failures = :f, locked_until = :until"),
                {"f": failures, "until": now + timedelta(seconds=wait) if wait else None},
            )
            await session.commit()
            raise HTTPException(status_code=401, detail="wrong PIN")
        await session.execute(text("UPDATE auth_settings SET failures = 0, locked_until = NULL"))
        await session.commit()
    response.set_cookie(
        COOKIE_NAME,
        make_session_value(row, now),
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        secure=not request.app.state.settings.allow_insecure_pin,
        samesite="strict",
        path="/",
    )
    return {"ok": True}


@router.post("/lock", status_code=204, dependencies=[Depends(require_action)])
async def lock(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
