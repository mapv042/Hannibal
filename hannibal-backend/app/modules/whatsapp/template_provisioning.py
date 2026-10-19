"""Create our message templates on each office's WABA and track their approval.

Embedded Signup connects the doctor's own WhatsApp Business Account, and a WABA
starts with none of our templates. Without them every business-initiated
message outside the 24h window fails: reminders, the day-before confirmation,
every doctor alert. So each spec in `wa_templates.TEMPLATE_SPECS` is created on
the office's WABA right after signup (`tasks.provision_office_templates`) and
re-checked daily (`tasks.maintain_whatsapp_accounts`) — which also creates any
template added to the catalogue since the office connected.

The result is stored on `Office.whatsapp_templates` as {name: Meta status}, so
the dashboard and the ops view can tell an office whose reminders cannot go out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import WhatsAppError
from app.db.models import Office
from app.modules.reminders.wa_templates import (
    TEMPLATE_LANGUAGE,
    TEMPLATE_SPECS,
    TemplateSpec,
)
from app.modules.whatsapp.provisioning import GRAPH_BASE_URL
from app.utils.dates import real_now
from app.utils.logger import get_logger

logger = get_logger(__name__)

APPROVED = "APPROVED"
# Meta is still deciding; worth re-checking soon.
PENDING_STATUSES = {"PENDING", "IN_APPEAL"}
# Not on the WABA at all (never created, or creation failed).
MISSING = "MISSING"


@dataclass
class TemplateSyncResult:
    statuses: Dict[str, str]
    created: List[str] = field(default_factory=list)
    failed: Dict[str, str] = field(default_factory=dict)

    @property
    def pending(self) -> bool:
        return any(s in PENDING_STATUSES for s in self.statuses.values())


def build_create_payload(spec: TemplateSpec) -> Dict[str, Any]:
    """The POST /{waba_id}/message_templates body for one spec (named params)."""
    body: Dict[str, Any] = {"type": "BODY", "text": spec.body}
    if spec.examples:
        body["example"] = {
            "body_text_named_params": [
                {"param_name": name, "example": value}
                for name, value in spec.examples.items()
            ]
        }
    components: List[Dict[str, Any]] = [body]
    if spec.quick_replies:
        components.append(
            {
                "type": "BUTTONS",
                "buttons": [{"type": "QUICK_REPLY", "text": t} for t in spec.quick_replies],
            }
        )
    return {
        "name": spec.name,
        "language": TEMPLATE_LANGUAGE,
        "category": spec.category,
        "parameter_format": "named",
        "components": components,
    }


async def list_templates(waba_id: str, token: str) -> Dict[str, str]:
    """{name: status} of the WABA's templates in our language, following paging.

    Raises:
        WhatsAppError: If Meta can't be reached or refuses the listing.
    """
    url: str | None = f"{GRAPH_BASE_URL}/{waba_id}/message_templates"
    params: Dict[str, Any] | None = {"fields": "name,status,language", "limit": 200}
    headers = {"Authorization": f"Bearer {token}"}
    statuses: Dict[str, str] = {}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            while url:
                response = await client.get(url, params=params, headers=headers)
                if response.status_code >= 400:
                    logger.error(
                        "wa_templates_list_failed",
                        waba_id=waba_id,
                        status_code=response.status_code,
                        response_body=response.text,
                    )
                    raise WhatsAppError("Could not list the WABA's message templates")
                data = response.json()
                for template in data.get("data", []):
                    if template.get("language") == TEMPLATE_LANGUAGE:
                        statuses[template["name"]] = template.get("status", "UNKNOWN")
                url = data.get("paging", {}).get("next")
                params = None  # the `next` URL already carries the query
    except httpx.HTTPError as e:
        logger.error("wa_templates_list_transport_error", waba_id=waba_id, error=str(e))
        raise WhatsAppError("Could not reach Meta to list message templates") from e
    return statuses


async def create_template(waba_id: str, token: str, spec: TemplateSpec) -> str:
    """Create one template; returns the status Meta assigned (usually PENDING).

    Raises:
        WhatsAppError: If Meta rejects the creation outright.
    """
    url = f"{GRAPH_BASE_URL}/{waba_id}/message_templates"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=build_create_payload(spec), headers=headers)
    except httpx.HTTPError as e:
        logger.error(
            "wa_template_create_transport_error", waba_id=waba_id, template=spec.name, error=str(e)
        )
        raise WhatsAppError("Could not reach Meta to create a message template") from e

    if response.status_code >= 400:
        logger.error(
            "wa_template_create_failed",
            waba_id=waba_id,
            template=spec.name,
            status_code=response.status_code,
            response_body=response.text,
        )
        raise WhatsAppError(f"Meta refused template {spec.name}")

    status = response.json().get("status", "PENDING")
    logger.info("wa_template_created", waba_id=waba_id, template=spec.name, status=status)
    return status


async def sync_office_templates(office: Office, db: AsyncSession) -> TemplateSyncResult:
    """Create every missing catalogue template on the office's WABA and store statuses.

    A template that exists keeps its name even when Meta rejected it (a name
    can't be reused for new content), so a REJECTED one is reported, not
    recreated: the fix is a new `_vN` spec.

    Raises:
        WhatsAppError: If the WABA's templates can't be listed (nothing stored).
    """
    if not office.whatsapp_waba_id or not office.whatsapp_token:
        raise WhatsAppError("Office has no WABA connected")

    existing = await list_templates(office.whatsapp_waba_id, office.whatsapp_token)
    result = TemplateSyncResult(statuses={})

    for spec in TEMPLATE_SPECS:
        if spec.name in existing:
            result.statuses[spec.name] = existing[spec.name]
            continue
        try:
            result.statuses[spec.name] = await create_template(
                office.whatsapp_waba_id, office.whatsapp_token, spec
            )
            result.created.append(spec.name)
        except WhatsAppError as e:
            result.statuses[spec.name] = MISSING
            result.failed[spec.name] = str(e)

    office.whatsapp_templates = result.statuses
    office.whatsapp_templates_synced_at = real_now()
    await db.commit()

    # Pending is the normal state right after creation; anything else that isn't
    # approved (missing, rejected, paused, disabled) means messages will fail.
    problems = {
        n: s for n, s in result.statuses.items() if s != APPROVED and s not in PENDING_STATUSES
    }
    (logger.error if problems else logger.info)(
        "wa_templates_synced",
        office_id=str(office.id),
        created=result.created,
        problems=problems,
    )
    return result


def template_health(office: Office) -> Dict[str, Any]:
    """Summary of the office's template statuses for the dashboard / ops view."""
    statuses = office.whatsapp_templates or {}
    names = [spec.name for spec in TEMPLATE_SPECS]
    approved = [n for n in names if statuses.get(n) == APPROVED]
    pending = [n for n in names if statuses.get(n) in PENDING_STATUSES]
    problems = {
        n: statuses.get(n, MISSING)
        for n in names
        if n not in approved and n not in pending
    }
    return {
        "total": len(names),
        "approved": len(approved),
        "pending": pending,
        "problems": problems,
        "synced_at": office.whatsapp_templates_synced_at,
    }
