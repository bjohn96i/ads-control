"""Google's Smart Device Management API, for the thermostats.

set_setpoint is the only write here, and the app calls it only when a person presses a button.
The API offers no way to read or change a Nest schedule, and neither does this client.
"""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

TOKEN_URL = "https://www.googleapis.com/oauth2/v4/token"
API_URL = "https://smartdevicemanagement.googleapis.com/v1"
REDIRECT_URI = "https://www.google.com"
SCOPE = "https://www.googleapis.com/auth/sdm.service"
THERMOSTAT_TYPE = "sdm.devices.types.THERMOSTAT"
TRAIT = "sdm.devices.traits."
SETPOINT = "sdm.devices.commands.ThermostatTemperatureSetpoint."
LOGIN_HINT = "run: adscontrol nest login"


class NestError(Exception):
    """Google could not be reached or refused. Messages never contain credentials."""


class RateLimited(NestError):
    """Google asked us to slow down."""


@dataclass(frozen=True)
class Thermostat:
    device_id: str
    name: str
    ambient_c: float | None
    humidity: float | None
    mode: str | None
    hvac_status: str | None
    cool_c: float | None
    heat_c: float | None
    eco: bool
    online: bool


def authorization_url(project_id: str, client_id: str) -> str:
    query = urlencode(
        {
            "redirect_uri": REDIRECT_URI,
            "access_type": "offline",
            "prompt": "consent",
            "client_id": client_id,
            "response_type": "code",
            "scope": SCOPE,
        }
    )
    return f"https://nestservices.google.com/partnerconnections/{project_id}/auth?{query}"


def code_from_pasted(pasted: str) -> str:
    """Google lands on google.com with the code in the address; accept either form."""
    text = pasted.strip()
    if text.startswith("http"):
        return parse_qs(urlparse(text).query).get("code", [""])[0]
    return text


def _save_private(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value)


async def exchange_code(client_id: str, secret: str, code: str, token_path: Path) -> None:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": REDIRECT_URI,
                },
            )
    except httpx.HTTPError as exc:
        raise NestError(f"could not reach Google: {type(exc).__name__}") from exc
    refresh = response.json().get("refresh_token") if response.is_success else None
    if not refresh:
        raise NestError(f"Google did not grant access (status {response.status_code}); try again")
    _save_private(token_path, refresh)


def _parse(device: dict) -> Thermostat:
    traits = device.get("traits", {})

    def trait(name: str) -> dict:
        return traits.get(TRAIT + name, {})

    relations = device.get("parentRelations") or [{}]
    setpoint = trait("ThermostatTemperatureSetpoint")
    return Thermostat(
        device_id=device["name"].rsplit("/", 1)[-1],
        name=trait("Info").get("customName") or relations[0].get("displayName") or "Thermostat",
        ambient_c=trait("Temperature").get("ambientTemperatureCelsius"),
        humidity=trait("Humidity").get("ambientHumidityPercent"),
        mode=trait("ThermostatMode").get("mode"),
        hvac_status=trait("ThermostatHvac").get("status"),
        cool_c=setpoint.get("coolCelsius"),
        heat_c=setpoint.get("heatCelsius"),
        eco=trait("ThermostatEco").get("mode") == "MANUAL_ECO",
        online=trait("Connectivity").get("status") == "ONLINE",
    )


def _setpoint_command(mode: str, cool_c: float | None, heat_c: float | None) -> dict:
    if mode == "COOL" and cool_c is not None and heat_c is None:
        return {"command": SETPOINT + "SetCool", "params": {"coolCelsius": cool_c}}
    if mode == "HEAT" and heat_c is not None and cool_c is None:
        return {"command": SETPOINT + "SetHeat", "params": {"heatCelsius": heat_c}}
    if mode == "HEATCOOL" and heat_c is not None and cool_c is not None:
        return {
            "command": SETPOINT + "SetRange",
            "params": {"heatCelsius": heat_c, "coolCelsius": cool_c},
        }
    raise NestError(f"a temperature can't be set that way while the mode is {mode}")


class SdmClient:
    def __init__(
        self,
        client_id: str,
        secret: str,
        project_id: str,
        token_path: Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client_id = client_id
        self._secret = secret
        self._project_url = f"{API_URL}/enterprises/{project_id}"
        self._token_path = token_path
        self._clock = clock
        self._access: str | None = None
        self._access_expires = 0.0

    async def _refresh(self, client: httpx.AsyncClient) -> None:
        if not self._token_path.exists():
            raise NestError(f"not logged in to Google; {LOGIN_HINT}")
        response = await client.post(
            TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._secret,
                "refresh_token": self._token_path.read_text().strip(),
                "grant_type": "refresh_token",
            },
        )
        if not response.is_success:
            raise NestError(
                f"Google refused the saved login ({response.status_code}); {LOGIN_HINT}"
            )
        body = response.json()
        self._access = body["access_token"]
        self._access_expires = self._clock() + body.get("expires_in", 3600) - 60

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                if self._access is None or self._clock() >= self._access_expires:
                    await self._refresh(client)
                response = await self._send(client, method, url, **kwargs)
                if response.status_code == 401:
                    await self._refresh(client)
                    response = await self._send(client, method, url, **kwargs)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise NestError(f"could not reach Google: {type(exc).__name__}") from exc
        if response.status_code == 429:
            raise RateLimited("Google asked us to slow down")
        if not response.is_success:
            raise NestError(f"Google answered {response.status_code}: {_message(response)}")
        return response.json()

    async def _send(self, client: httpx.AsyncClient, method: str, url: str, **kwargs):
        headers = {"Authorization": f"Bearer {self._access}"}
        return await client.request(method, url, headers=headers, **kwargs)

    async def list_thermostats(self) -> list[Thermostat]:
        body = await self._request("GET", f"{self._project_url}/devices")
        return [_parse(d) for d in body.get("devices", []) if d.get("type") == THERMOSTAT_TYPE]

    async def set_setpoint(
        self, device_id: str, mode: str, *, cool_c: float | None = None, heat_c: float | None = None
    ) -> None:
        await self._request(
            "POST",
            f"{self._project_url}/devices/{device_id}:executeCommand",
            json=_setpoint_command(mode, cool_c, heat_c),
        )


def _message(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"]["message"])[:200]
    except (ValueError, KeyError, TypeError):
        return "no details"
