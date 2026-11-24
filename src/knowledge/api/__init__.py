"""Optional FastAPI transport and its explicit public schemas."""

from __future__ import annotations

from knowledge.api.app import create_app
from knowledge.api.models import (
    MODEL_ID,
    APIError,
    APIErrorResponse,
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatContext,
    ChatMessage,
    ChatResponseMessage,
    ContextControls,
    ContextRequest,
    HealthResponse,
    ModelInfo,
    ModelListResponse,
)
from knowledge.context import ContextPacket

__all__ = [
    "MODEL_ID",
    "APIError",
    "APIErrorResponse",
    "ChatCompletionChoice",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "ChatContext",
    "ChatMessage",
    "ChatResponseMessage",
    "ContextControls",
    "ContextPacket",
    "ContextRequest",
    "HealthResponse",
    "ModelInfo",
    "ModelListResponse",
    "create_app",
]
