"""Text ingestion primitives and application services."""

from knowledge.ingestion.loaders import LoadedText, TextFileLoader, UnsupportedFileTypeError
from knowledge.ingestion.normalization import fingerprint_text, normalize_text
from knowledge.ingestion.pipeline import (
    KnowledgeUnitService,
    SplittingResult,
    TraceableIngestionResult,
    TraceableIngestionService,
)
from knowledge.ingestion.service import (
    FileIngestionService,
    IngestionResult,
    SourceNotFoundError,
    UnsupportedSourceKindError,
)
from knowledge.ingestion.splitting import TraceableTextSplitter

__all__ = [
    "FileIngestionService",
    "IngestionResult",
    "KnowledgeUnitService",
    "LoadedText",
    "SourceNotFoundError",
    "SplittingResult",
    "TextFileLoader",
    "TraceableIngestionResult",
    "TraceableIngestionService",
    "TraceableTextSplitter",
    "UnsupportedFileTypeError",
    "UnsupportedSourceKindError",
    "fingerprint_text",
    "normalize_text",
]
