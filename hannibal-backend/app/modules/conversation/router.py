"""Dashboard endpoints for reading WhatsApp conversations (read-only)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_office, get_redis
from app.db.models import Office
from app.modules.conversation.inbox import (
    ConversationSummary,
    InboxMessage,
    get_conversation_messages,
    list_conversations,
)

router = APIRouter(tags=["Conversations"])


@router.get("", response_model=List[ConversationSummary])
async def list_conversations_endpoint(
    search: Optional[str] = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office),
    redis_client: aioredis.Redis = Depends(get_redis),
):
    """The office's WhatsApp threads, most recent activity first."""
    return await list_conversations(
        db, office.id, search=search, limit=limit, redis_client=redis_client
    )


@router.get("/{conversation_id}/messages", response_model=List[InboxMessage])
async def conversation_messages_endpoint(
    conversation_id: UUID,
    before: Optional[datetime] = Query(None, description="Page back from this timestamp"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    office: Office = Depends(get_office),
):
    """One page of a thread, oldest first. 404 for a thread of another office."""
    return await get_conversation_messages(
        db, office.id, conversation_id, before=before, limit=limit
    )
