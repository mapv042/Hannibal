"""WhatsApp voice-note transcription (OpenAI Whisper).

Voice notes are the dominant message type for many Mexican patients, so
instead of apologizing for audio we transcribe it and feed the text to the
conversation. Best-effort: any failure (no OpenAI key, download error, API
error) returns None and the caller falls back to the "text only" reply.

Transcription uses the OpenAI key directly regardless of AI_PROVIDER —
Anthropic has no audio API.
"""

from __future__ import annotations

from typing import Optional

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

TRANSCRIPTION_MODEL = "whisper-1"
# WhatsApp voice notes longer than this are suspicious as commands/requests;
# Whisper also bills per minute. ~16MB is Meta's own media cap anyway.
MAX_AUDIO_BYTES = 16 * 1024 * 1024


async def transcribe_whatsapp_audio(
    meta_client,
    office,
    media_id: str,
) -> Optional[str]:
    """Download a WhatsApp audio by media_id and return its Spanish transcript.

    Returns None when transcription is unavailable or fails.
    """
    if not settings.open_ai_key:
        return None
    if not (office.whatsapp_phone_id and office.whatsapp_token):
        return None

    try:
        media_url = await meta_client.get_media_url(
            office.whatsapp_phone_id, office.whatsapp_token, media_id
        )
        audio_bytes = await meta_client.download_media(media_url, office.whatsapp_token)
        if not audio_bytes or len(audio_bytes) > MAX_AUDIO_BYTES:
            logger.warning(
                "audio_transcription_skipped_size",
                media_id=media_id,
                size=len(audio_bytes) if audio_bytes else 0,
            )
            return None

        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.open_ai_key)
        # WhatsApp voice notes are OGG/Opus; the filename hint tells the API the format.
        result = await client.audio.transcriptions.create(
            model=TRANSCRIPTION_MODEL,
            file=("voice.ogg", audio_bytes),
            language="es",
        )
        text = (result.text or "").strip()
        if not text:
            return None

        logger.info(
            "audio_transcribed",
            media_id=media_id,
            office_id=str(office.id),
            chars=len(text),
        )
        return text

    except Exception as e:
        logger.warning("audio_transcription_failed", media_id=media_id, error=str(e))
        return None
