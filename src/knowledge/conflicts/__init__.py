"""Deterministic conflict detection and human-review API."""

from knowledge.conflicts.rules import ConflictCandidate
from knowledge.conflicts.service import (
    ConflictNotFoundError,
    ConflictScan,
    ConflictService,
    ConflictTransitionError,
)

__all__ = [
    "ConflictCandidate",
    "ConflictNotFoundError",
    "ConflictScan",
    "ConflictService",
    "ConflictTransitionError",
]
