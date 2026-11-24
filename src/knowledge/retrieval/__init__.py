"""Lifecycle-aware lexical, vector, and hybrid retrieval."""

from knowledge.retrieval.fusion import FusedUnit, RankedUnit, fuse_rankings
from knowledge.retrieval.models import RetrievalHit, RetrievalMode, RetrievalResult
from knowledge.retrieval.service import RetrievalConfigurationError, RetrievalService

__all__ = [
    "FusedUnit",
    "RankedUnit",
    "RetrievalConfigurationError",
    "RetrievalHit",
    "RetrievalMode",
    "RetrievalResult",
    "RetrievalService",
    "fuse_rankings",
]
