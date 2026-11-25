"""SQLite metadata storage and transaction boundaries."""

from knowledge.storage.conflicts import ConflictRepository
from knowledge.storage.conversations import (
    ConversationCandidateRepository,
    ConversationRepository,
    ConversationReviewRepository,
)
from knowledge.storage.database import (
    SessionFactory,
    create_schema,
    create_session_factory,
    create_sqlite_engine,
)
from knowledge.storage.database_schema import DatabaseSchemaSnapshotRepository
from knowledge.storage.evaluation import EvaluationSetRepository
from knowledge.storage.repository import (
    CitationRepository,
    DocumentRepository,
    EntityNotFoundError,
    ImmutableEntityError,
    KnowledgeUnitRepository,
    Repository,
    RevisionRepository,
    SourceRepository,
)
from knowledge.storage.unit_of_work import UnitOfWork

__all__ = [
    "CitationRepository",
    "ConflictRepository",
    "ConversationCandidateRepository",
    "ConversationRepository",
    "ConversationReviewRepository",
    "DatabaseSchemaSnapshotRepository",
    "DocumentRepository",
    "EntityNotFoundError",
    "EvaluationSetRepository",
    "ImmutableEntityError",
    "KnowledgeUnitRepository",
    "Repository",
    "RevisionRepository",
    "SessionFactory",
    "SourceRepository",
    "UnitOfWork",
    "create_schema",
    "create_session_factory",
    "create_sqlite_engine",
]
