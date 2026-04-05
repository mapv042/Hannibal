from __future__ import annotations

from fastapi import HTTPException, status


class NotFoundError(HTTPException):
    """Resource not found."""

    def __init__(self, detail: str = "Resource not found"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ForbiddenError(HTTPException):
    """Access forbidden."""

    def __init__(self, detail: str = "Access forbidden"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class ConflictError(HTTPException):
    """Conflict with existing resource."""

    def __init__(self, detail: str = "Resource conflict"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


class SlotNotAvailableError(HTTPException):
    """Appointment slot not available."""

    def __init__(self, detail: str = "Appointment slot not available"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


class WhatsAppError(HTTPException):
    """WhatsApp API error."""

    def __init__(self, detail: str = "WhatsApp error"):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        )


class GoogleCalendarError(HTTPException):
    """Google Calendar API error."""

    def __init__(self, detail: str = "Google Calendar error"):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        )


class AIServiceError(HTTPException):
    """AI service (Claude) error."""

    def __init__(self, detail: str = "AI service error"):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        )


class UnauthorizedError(HTTPException):
    """Authentication error."""

    def __init__(self, detail: str = "Unauthorized"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class IntentDetectionError(Exception):
    """Intent detection failure."""

    pass


class SessionStoreError(Exception):
    """Session store operation failure."""

    pass


class ConversationError(Exception):
    """Conversation processing failure."""

    pass
