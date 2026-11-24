"""Traceable citations and bounded context assembly."""

from knowledge.context.assembly import assemble_context, validate_budget
from knowledge.context.citations import (
    CitationEvidenceError,
    citation_from_hit,
    validate_hit_evidence,
    verify_citation,
)
from knowledge.context.models import (
    ContextPacket,
    ContextSkipReason,
    EvidenceBlock,
    SkippedEvidence,
    TokenContextPacket,
    render_context,
)
from knowledge.context.service import ContextService
from knowledge.context.tokens import TiktokenTokenCounter, TokenCounter

__all__ = [
    "CitationEvidenceError",
    "ContextPacket",
    "ContextService",
    "ContextSkipReason",
    "EvidenceBlock",
    "SkippedEvidence",
    "TiktokenTokenCounter",
    "TokenContextPacket",
    "TokenCounter",
    "assemble_context",
    "citation_from_hit",
    "render_context",
    "validate_budget",
    "validate_hit_evidence",
    "verify_citation",
]
