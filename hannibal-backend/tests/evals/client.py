"""Thin async client for the simulator's operator API (/api/sim)."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional

import httpx
from dotenv import dotenv_values

# SIM_URL / SIM_PASSWORD / SIM_USER / OPEN_AI_KEY may live in hannibal-backend/.env;
# real environment variables win over it.
_ENV_FILE = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
for _key, _value in dotenv_values(_ENV_FILE).items():
    if _key in ("SIM_URL", "SIM_PASSWORD", "SIM_USER", "OPEN_AI_KEY", "EVAL_PATIENT_MODEL") and _value:
        os.environ.setdefault(_key, _value)


class SimClient:
    """Drives one simulator deployment. Configure with SIM_URL / SIM_USER / SIM_PASSWORD."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        base = (base_url or os.environ["SIM_URL"]).rstrip("/")
        self.http = httpx.AsyncClient(
            base_url=f"{base}/api/sim",
            auth=(user or os.environ.get("SIM_USER", "argos"), password or os.environ["SIM_PASSWORD"]),
            # A turn with reasoning + a corrective pass can take a while.
            timeout=httpx.Timeout(180.0),
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def _call(self, method: str, path: str, **kw) -> dict:
        r = await self.http.request(method, path, **kw)
        r.raise_for_status()
        return r.json()

    # --- scenario lifecycle -------------------------------------------------

    async def reset(self) -> dict:
        return await self._call("POST", "/reset")

    async def state(self) -> dict:
        return await self._call("GET", "/state")

    async def now(self) -> datetime:
        return datetime.fromisoformat((await self.state())["clock"]["now"])

    async def advance(self, seconds: int) -> dict:
        return await self._call("POST", "/clock", json={"seconds": int(seconds)})

    async def advance_to(self, target: datetime) -> datetime:
        """Move the clock forward to `target` (aware datetime)."""
        now = await self.now()
        delta = (target - now).total_seconds()
        if delta > 0:
            await self.advance(int(delta))
        return await self.now()

    async def start_on_monday(self, hour: int = 8) -> datetime:
        """Reset, then put the clock on the next Monday at `hour`:00.

        Scenarios are written against a known weekday so "mañana" and "el
        jueves" mean the same thing on every run.
        """
        await self.reset()
        now = await self.now()
        days = (7 - now.weekday()) % 7 or 7
        target = (now + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
        return await self.advance_to(target)

    # --- conversation -------------------------------------------------------

    async def send(
        self,
        text: str,
        *,
        whatsapp_id: Optional[str] = None,
        sender: str = "patient",
        provider: Optional[str] = None,
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ) -> list[dict]:
        body = {"sender": sender, "text": text}
        if whatsapp_id:
            body["whatsapp_id"] = whatsapp_id
        if model:
            body.update(provider=provider or "openai", model=model)
            if reasoning_effort:
                body["reasoning_effort"] = reasoning_effort
        return (await self._call("POST", "/inbound", json=body))["produced"]

    async def send_burst(self, texts: list[str], **kw) -> None:
        """Send several messages at once, as a patient typing fast would."""
        await asyncio.gather(*[self.send(t, **kw) for t in texts])

    async def outbox(self) -> list[dict]:
        return (await self.state())["outbox"]

    # --- inspection & fixtures ----------------------------------------------

    async def appointments(self) -> list[dict]:
        return (await self._call("GET", "/appointments"))["appointments"]

    async def traces(self, limit: int = 100) -> list[dict]:
        return (await self._call("GET", "/traces", params={"limit": limit}))["traces"]

    async def fixture_appointment(self, start: str, **kw) -> str:
        return (await self._call("POST", "/fixtures/appointment", json={"start": start, **kw}))["id"]

    async def gcal_connected(self) -> bool:
        return bool((await self._call("GET", "/gcal/status")).get("connected"))

    async def gcal_events(self, start: str, end: str) -> list[dict]:
        """Events in the simulator's Google Calendar between two YYYY-MM-DD dates."""
        return (await self._call("GET", "/gcal/events", params={"start": start, "end": end}))["events"]

    async def fixture_gcal_event(self, start: str, end: str, title: str = "Junta (evento personal de prueba)") -> str:
        return (await self._call(
            "POST", "/fixtures/gcal_event", json={"start": start, "end": end, "title": title}
        ))["id"]

    async def fixture_block(self, start: str, end: str, reason: str = "Bloqueo de prueba") -> str:
        return (await self._call(
            "POST", "/fixtures/block", json={"start": start, "end": end, "reason": reason}
        ))["id"]
