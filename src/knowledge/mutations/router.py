"""FastAPI router for the opt-in mutation demo API."""

from __future__ import annotations

import json
import re
import secrets
from typing import Any, NoReturn
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import ValidationError
from starlette.requests import Request

from knowledge.mutations.models import (
    MAX_REQUEST_BYTES,
    MAX_TEXT_BYTES,
    CommandDTO,
    CommandRequest,
    ContentType,
    DocumentDTO,
    MutationError,
    PreviewDTO,
    PreviewRequest,
    SessionDTO,
)
from knowledge.mutations.service import MutationService

_SAFE_ACTOR = re.compile(r"^[A-Za-z0-9._:@-]{1,80}$")


def validate_actor(value: str | None) -> str:
    if value is None or not value or not _SAFE_ACTOR.fullmatch(value):
        raise ValueError("KNOWLEDGE_MUTATION_ACTOR must be a safe non-empty ASCII principal")
    return value


def validate_origin(value: str | None) -> str:
    if value is None:
        raise ValueError("mutation_origin is required")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.port is None
    ):
        raise ValueError("mutation_origin must be an exact loopback http origin")
    return f"http://{parsed.hostname}:{parsed.port}"


def build_mutation_router(
    service: MutationService,
    *,
    mutation_key: str,
    allowed_origin: str,
    read_key: str | None = None,
) -> Any:
    try:
        from fastapi import APIRouter, Depends, HTTPException
        from fastapi.security import HTTPBearer
    except ImportError:  # pragma: no cover - app factory imports FastAPI first
        raise

    bearer = HTTPBearer(auto_error=False)
    router = APIRouter(prefix="/v1/mutations", tags=["mutations"])

    def raise_error(status_code: int, code: str, message: str) -> NoReturn:
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": {"message": message, "type": "mutation_error", "code": code, "param": None}
            },
        )

    async def require_write_key(
        request: Request,
        credentials: Any = Depends(bearer),  # noqa: B008
    ) -> None:
        if len(request.headers.getlist("authorization")) > 1:
            raise_error(400, "duplicate_header", "request contains duplicate headers")
        supplied = "" if credentials is None else credentials.credentials
        if secrets.compare_digest(supplied, mutation_key):
            return
        if read_key is not None and secrets.compare_digest(supplied, read_key):
            raise_error(403, "read_key_forbidden", "read credential cannot write mutations")
        raise_error(401, "invalid_mutation_key", "mutation credential is invalid")

    def _single_header(request: Request, name: str) -> str | None:
        values = request.headers.getlist(name)
        if len(values) > 1:
            raise_error(400, "duplicate_header", "request contains duplicate headers")
        return values[0] if values else None

    def _validate_browser_guards(request: Request, *, require_intent: bool) -> None:
        origin = _single_header(request, "origin")
        if origin != allowed_origin:
            raise_error(403, "origin_not_allowed", "request origin is not allowed")
        fetch_site = _single_header(request, "sec-fetch-site")
        if fetch_site not in {None, "same-origin", "same-site"}:
            raise_error(403, "cross_site_blocked", "cross-site request is not allowed")
        if require_intent and _single_header(request, "x-knowledge-intent") != "document-update":
            raise_error(400, "intent_required", "mutation intent is required")

    async def _strict_body(
        request: Request, model_type: type[PreviewRequest] | type[CommandRequest]
    ) -> Any:
        content_type = request.headers.get("content-type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise_error(415, "json_required", "JSON content type is required")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                raise_error(413, "request_too_large", "request body is too large")
            body.extend(chunk)

        def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in values:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result

        def constant(value: str) -> None:
            raise ValueError(value)

        try:
            decoded = body.decode("utf-8")
            if any(0xD800 <= ord(char) <= 0xDFFF for char in decoded):
                raise UnicodeError
            parsed = json.loads(decoded, object_pairs_hook=pairs, parse_constant=constant)
            if model_type is PreviewRequest and isinstance(parsed, dict):
                input_text = parsed.get("text")
                if isinstance(input_text, str) and len(input_text.encode("utf-8")) > MAX_TEXT_BYTES:
                    raise_error(413, "text_too_large", "text is too large")
            return model_type.model_validate(parsed)
        except UnicodeError:
            raise_error(400, "invalid_utf8", "request body must be valid UTF-8")
        except ValidationError:
            raise_error(400, "validation_error", "request body is invalid")
        except (json.JSONDecodeError, ValueError):
            raise_error(400, "invalid_json", "request body must be strict JSON")

    @router.get("/session", response_model=SessionDTO, dependencies=[Depends(require_write_key)])
    async def session(request: Request) -> SessionDTO:
        _validate_browser_guards(request, require_intent=False)
        try:
            sources = service.list_sources()
        except MutationError as exc:
            raise_error(exc.status_code, exc.code, exc.message)
        return SessionDTO(
            scope_id=service.scope.scope_id,
            actor_id=service.actor_id,
            capabilities=("document.update",),
            sources=sources,
        )

    @router.get(
        "/documents/{document_id}",
        response_model=DocumentDTO,
        dependencies=[Depends(require_write_key)],
    )
    async def document(request: Request, document_id: UUID) -> DocumentDTO:
        _validate_browser_guards(request, require_intent=False)
        try:
            source_id, stored, text_value = service.get_document_text(document_id)
        except MutationError as exc:
            raise_error(exc.status_code, exc.code, exc.message)
        return DocumentDTO(
            scope_id=service.scope.scope_id,
            source_id=source_id,
            document_id=stored.id,
            checksum=stored.checksum,
            content_type=ContentType(stored.content_type.value),
            text=text_value,
        )

    @router.post("/previews", response_model=PreviewDTO, dependencies=[Depends(require_write_key)])
    async def previews(request: Request) -> PreviewDTO:
        _validate_browser_guards(request, require_intent=True)
        payload = await _strict_body(request, PreviewRequest)
        try:
            return service.create_preview(payload)
        except MutationError as exc:
            raise_error(exc.status_code, exc.code, exc.message)

    @router.post("/commands", response_model=CommandDTO, dependencies=[Depends(require_write_key)])
    async def commands(request: Request) -> CommandDTO:
        _validate_browser_guards(request, require_intent=True)
        payload = await _strict_body(request, CommandRequest)
        try:
            return service.apply_command(payload)
        except MutationError as exc:
            raise_error(exc.status_code, exc.code, exc.message)

    @router.get(
        "/commands/{command_id}",
        response_model=CommandDTO,
        dependencies=[Depends(require_write_key)],
    )
    async def command(request: Request, command_id: UUID) -> CommandDTO:
        _validate_browser_guards(request, require_intent=False)
        try:
            return service.get_command(command_id)
        except MutationError as exc:
            raise_error(exc.status_code, exc.code, exc.message)

    return router


__all__ = ["build_mutation_router", "validate_actor", "validate_origin"]
