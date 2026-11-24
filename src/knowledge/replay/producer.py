"""Create a fresh private synthetic scope and project real management reads."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import Engine, select

from knowledge.api.management_models import JobsQuery, PageQuery
from knowledge.api.management_service import ManagementService
from knowledge.application import KnowledgeLibrary
from knowledge.domain import EvaluationItem, EvaluationSet
from knowledge.quality import QualityPolicy
from knowledge.replay.bundle import (
    ReplayBundle,
    ReplayResources,
    ReplayStory,
    encode_bundle,
    require,
)
from knowledge.replay.corpus import MARKERS, TEXTS
from knowledge.replay.files import (
    check_regular,
    ensure_absent,
    exclusive_write,
    parent_fd,
    read_static,
)
from knowledge.storage import create_schema, create_session_factory, create_sqlite_engine
from knowledge.storage.tables import DocumentRow, KnowledgeUnitRow, RevisionRow, SourceRow


@dataclass
class _Seed:
    scope: Path
    library: KnowledgeLibrary
    source_id: UUID
    documents: set[UUID] = field(default_factory=set)
    units: set[UUID] = field(default_factory=set)
    jobs: list[UUID] = field(default_factory=list)


def _collect(seed: _Seed) -> ReplayBundle:
    """Internal only: exact IDs from this producer, never an arbitrary business library."""
    require(
        seed.scope.parent == Path.cwd() / ".knowledge" / "replay",
        "REPLAY_SCOPE_INVALID",
    )
    bind = seed.library._session_factory.kw.get("bind")
    require(
        isinstance(bind, Engine) and bind.url.database == str(seed.scope / "knowledge.db"),
        "REPLAY_SCOPE_INVALID",
    )
    check_regular(seed.scope / "knowledge.db")
    service = ManagementService(seed.library)
    source_path = seed.scope / "synthetic.md"
    require(read_static(source_path).decode() == TEXTS[-1], "REPLAY_CORPUS_INVALID")
    with service.read_session() as session:
        sources = session.scalars(select(SourceRow)).all()
        require(len(sources) == 1 and sources[0].id == seed.source_id, "REPLAY_SCOPE_INVALID")
        require(sources[0].uri == str(source_path), "REPLAY_SCOPE_INVALID")
        docs = session.scalars(select(DocumentRow)).all()
        require({d.id for d in docs} == seed.documents, "REPLAY_SCOPE_INVALID")
        require(
            all(d.source_id == seed.source_id and d.locator == str(source_path) for d in docs),
            "REPLAY_SCOPE_INVALID",
        )
        rows = session.scalars(select(KnowledgeUnitRow)).all()
        require({u.id for u in rows} == seed.units, "REPLAY_SCOPE_INVALID")
        revision_ids = tuple(
            session.scalars(select(RevisionRow.id).order_by(RevisionRow.created_at, RevisionRow.id))
        )
        require(len(revision_ids) <= 100, "REPLAY_SIZE_INVALID")
    page = PageQuery(limit=100, offset=0)
    job_page = service.jobs(JobsQuery(limit=100, offset=0))
    require(job_page.total == 3 and {j.id for j in job_page.items} == set(seed.jobs))
    documents = tuple(service.document(identifier, page) for identifier in sorted(seed.documents))
    units = tuple(service.unit(identifier) for identifier in sorted(seed.units))
    return ReplayBundle(
        schema_version=1,
        mode="replay",
        # Real UTC captured after all publications and evaluation finishes, never a frozen clock.
        generated_at=datetime.now(UTC),
        story=ReplayStory(
            reference_job_id=seed.jobs[0],
            candidate_job_id=seed.jobs[1],
            recovery_job_id=seed.jobs[2],
        ),
        resources=ReplayResources(
            jobs=job_page.items,
            revisions=tuple(service.revision(identifier) for identifier in revision_ids),
            documents=documents,
            units=units,
            lineages=tuple(
                service.lineage(identifier, page)
                for identifier in sorted({u.lineage_id for u in units})
            ),
            evidence=tuple(service.evidence(identifier) for identifier in sorted(seed.units)),
            # All ordered pairs (including identity) support getDocumentDiff(anynew, old).
            diffs=tuple(
                service.diff(new.id, old.id, page) for new in documents for old in documents
            ),
        ),
    )


def _replace_synthetic(path: Path, text: str) -> None:
    require(text in TEXTS, "REPLAY_CORPUS_INVALID")
    require(read_static(path).decode() in TEXTS, "REPLAY_CORPUS_INVALID")
    with parent_fd(path) as (parent, name):
        descriptor = os.open(name, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)


def export_replay(output: Path | str = Path("web/public/replay.json")) -> ReplayBundle:
    """Exclusive output; fresh .knowledge/replay/UUID scope under the current repo.

    There is deliberately no database, manifest, URL, report, input-corpus or scope argument.
    Existing output must be removed explicitly by its owner before rerunning.
    """
    output = Path(output)
    ensure_absent(output)
    scope = Path.cwd() / ".knowledge" / "replay" / str(uuid4())
    with parent_fd(scope, create=True) as (parent, name):
        os.mkdir(name, mode=0o700, dir_fd=parent)
    source_path = scope / "synthetic.md"
    exclusive_write(source_path, TEXTS[0].encode(), private=True)
    database = scope / "knowledge.db"
    ensure_absent(database)
    engine = create_sqlite_engine(f"sqlite+pysqlite:///{database.as_posix()}")
    try:
        create_schema(engine)
        os.chmod(database, 0o600)
        library = KnowledgeLibrary(create_session_factory(engine))
        result = library.import_path(source_path).imported[0].result
        seed = _Seed(scope, library, result.ingestion.document.source_id)
        seed.documents.add(result.ingestion.document.id)
        seed.units.update(unit.id for unit in result.units)
        require(len(result.units) == 3, "REPLAY_SEED_FAILED")
        dataset = EvaluationSet(
            id=uuid4(),
            name="Public synthetic lexical replay",
            version=1,
            created_at=datetime.now(UTC),
            items=(
                *(
                    EvaluationItem(
                        id=f"synthetic-{index + 1}",
                        query=marker,
                        expected_lineage_ids=frozenset({result.units[index].lineage_id}),
                    )
                    for index, marker in enumerate(MARKERS)
                ),
                EvaluationItem(
                    id="synthetic-no-answer", query="quartzmissing", expect_no_answer=True
                ),
            ),
        )
        library.evaluation.import_set(dataset)
        quality = library.quality.run(dataset.id, version=1)
        require(quality.passed, "REPLAY_SEED_FAILED")
        config = library.automatic_evaluation.enable(dataset.id, version=1)
        require(config.quality_policy == QualityPolicy(), "REPLAY_SEED_FAILED")
        require(not library.automatic_evaluation.history(), "REPLAY_SEED_FAILED")
        for text, expected in zip(TEXTS[1:], ("passed", "failed", "passed"), strict=True):
            _replace_synthetic(source_path, text)
            with library.automatic_evaluation.observe_changes() as observation:
                result = library.import_path(source_path).imported[0].result
            require(len(observation.jobs) == 1, "REPLAY_SEED_FAILED")
            job = observation.jobs[0]
            require(job.status.value == expected, "REPLAY_SEED_FAILED")
            seed.jobs.append(job.id)
            seed.documents.add(result.ingestion.document.id)
            seed.units.update(unit.id for unit in result.units)
            require(library.evaluation.get(dataset.id, version=1) == dataset, "REPLAY_SEED_FAILED")
            require(library.automatic_evaluation.status() == config, "REPLAY_SEED_FAILED")
        # Independent static validation runs before any public output write.
        bundle = _collect(seed)
        data = encode_bundle(bundle)
        exclusive_write(output, data)
        report = {
            "schema_version": 1,
            "status": "passed",
            "scope_id": scope.name,
            "story": bundle.story.model_dump(mode="json"),
            "counts": {name: len(items) for name, items in bundle.resources.model_dump().items()},
            "bundle_bytes": len(data),
            "bundle_sha256": hashlib.sha256(data).hexdigest(),
            "jobs": [
                {
                    "id": str(identifier),
                    "status": job.status.value,
                    "error_code": job.error_code,
                    "recall": job.report.metrics.mean_recall if job.report else None,
                }
                for identifier in seed.jobs
                for job in bundle.resources.jobs
                if job.id == identifier
            ],
        }
        exclusive_write(
            scope / "report.json",
            (json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode(),
            private=True,
        )
        return bundle
    finally:
        engine.dispose()
