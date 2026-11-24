"""Exact B1 DTO bundle, with bounded syntax, public-corpus and graph validation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal, TypeVar
from uuid import UUID

from pydantic import AwareDatetime, Field, ValidationError

from knowledge.api.management_models import (
    DocumentDiffDTO,
    DocumentDTO,
    EvidenceDTO,
    JobDTO,
    LineageDTO,
    ManagementModel,
    Page,
    ResourceLink,
    RevisionDTO,
    UnitDTO,
)
from knowledge.replay.corpus import DOCUMENT_TEXTS, SEGMENTS

MAX_BYTES = 5 * 1024 * 1024
T = TypeVar("T")
Bounded = Annotated[tuple[T, ...], Field(max_length=100)]


class ReplayError(ValueError):
    """Only fixed codes; never retain validation input, storage details or paths."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ReplayStory(ManagementModel):
    reference_job_id: UUID
    candidate_job_id: UUID
    recovery_job_id: UUID


class ReplayResources(ManagementModel):
    jobs: Bounded[JobDTO]
    revisions: Bounded[RevisionDTO]
    documents: Bounded[DocumentDTO]
    lineages: Bounded[LineageDTO]
    units: Bounded[UnitDTO]
    evidence: Bounded[EvidenceDTO]
    diffs: Bounded[DocumentDiffDTO]


class ReplayBundle(ManagementModel):
    schema_version: Literal[1]
    mode: Literal["replay"]
    generated_at: AwareDatetime
    story: ReplayStory
    resources: ReplayResources


def require(condition: bool, code: str = "REPLAY_RELATION_INVALID") -> None:
    if not condition:
        raise ReplayError(code)


def _unique(values: tuple[UUID, ...]) -> None:
    require(len(set(values)) == len(values), "REPLAY_DUPLICATE_ID")


def _page(page: Page[T]) -> None:
    require(
        page.limit == 100 and page.offset == 0 and page.total == len(page.items) <= 100,
        "REPLAY_SIZE_INVALID",
    )


def validate_bundle(bundle: ReplayBundle) -> ReplayBundle:
    """Validate closure without SQLite, SDK reads, status materialization or HTTP."""
    r = bundle.resources
    groups = (r.jobs, r.revisions, r.documents, r.lineages, r.units)
    for group in groups:
        _unique(tuple(item.id for item in group))
    # A lineage intentionally shares its first version's UUID, unlike other resources.
    _unique(
        tuple(item.id for group in (r.jobs, r.revisions, r.documents, r.units) for item in group)
    )
    _unique(tuple(item.unit_id for item in r.evidence))
    jobs = {item.id: item for item in r.jobs}
    revisions = {item.id: item for item in r.revisions}
    documents = {item.id: item for item in r.documents}
    units = {item.id: item for item in r.units}
    lineages = {item.id: item for item in r.lineages}
    evidence = {item.unit_id: item for item in r.evidence}
    sources = {item.source_id for item in r.documents}
    require(len(sources) == 1 and len(documents) == 4, "REPLAY_SCOPE_INVALID")
    source = next(iter(sources))

    story_ids = (
        bundle.story.reference_job_id,
        bundle.story.candidate_job_id,
        bundle.story.recovery_job_id,
    )
    _unique(story_ids)
    require(set(story_ids) == set(jobs) and len(jobs) == 3)
    story = tuple(jobs[identifier] for identifier in story_ids)
    require(tuple(job.status.value for job in story) == ("passed", "failed", "passed"))
    require(story[0].created_at < story[1].created_at < story[2].created_at)
    require(len({(j.dataset_id, j.dataset_version, j.dataset_hash) for j in story}) == 1)
    require(len({(j.config_generation, j.config_fingerprint) for j in story}) == 1)
    require(len({j.knowledge_fingerprint for j in story}) == 3)
    for job in story:
        require(job.parent_job_id is None and job.attempt_count == 1)
        require(job.report is not None)
        assert job.report is not None
        report = job.report
        require(report.passed == (job.status.value == "passed"))
        require(report.metrics.case_count == 4)
        require(report.metrics.answerable_count == 3 and report.metrics.no_answer_count == 1)
        require(report.stale_hits == 0 and not report.degraded)
        require(report.citation_coverage == 1 and report.metrics.no_answer_accuracy == 1)
        require(
            report.metrics.mean_recall == (2 / 3 if job.status.value == "failed" else 1)
            and report.metrics.mean_reciprocal_rank
            == (2 / 3 if job.status.value == "failed" else 1)
        )
        require(job.error_code == ("QUALITY_GATE_FAILED" if job.status.value == "failed" else None))
        require(
            bool(job.trigger_revision_ids) and set(job.trigger_revision_ids) <= revisions.keys()
        )
        _unique(job.trigger_revision_ids)
        require(job.started_at is not None and job.finished_at is not None)
        assert job.started_at is not None and job.finished_at is not None
        require(job.created_at <= job.started_at <= job.finished_at <= bundle.generated_at)
        require(job.evaluated_at <= bundle.generated_at)

    def links(
        items: tuple[ResourceLink, ...], expected_links: tuple[tuple[str, UUID], ...]
    ) -> None:
        require(tuple((link.kind, link.id) for link in items) == expected_links)
        collections: dict[str, set[UUID]] = {
            "job": set(jobs),
            "revision": set(revisions),
            "document": set(documents),
            "unit": set(units),
            "lineage": set(lineages),
            "evidence": set(evidence),
        }
        paths = {
            "job": "jobs",
            "revision": "revisions",
            "document": "documents",
            "unit": "units",
            "lineage": "lineages",
            "evidence": "units",
        }
        for link in items:
            suffix = "/evidence" if link.kind == "evidence" else ""
            require(link.id in collections[link.kind])
            require(link.href == f"/v1/management/{paths[link.kind]}/{link.id}{suffix}")

    ordered_documents = sorted(r.documents, key=lambda d: (d.ingested_at, d.id))
    require({doc.checksum for doc in ordered_documents} == set(DOCUMENT_TEXTS))
    require(tuple(doc.checksum for doc in ordered_documents) == tuple(DOCUMENT_TEXTS))
    for index, doc in enumerate(ordered_documents):
        require(doc.content_type.value == "markdown", "REPLAY_CORPUS_INVALID")
        require(doc.ingested_at <= bundle.generated_at)
        require(doc.previous_document_id == (ordered_documents[index - 1].id if index else None))
        require(doc.next_document_id == (ordered_documents[index + 1].id if index < 3 else None))
        _page(doc.units)
        expected = tuple(
            sorted((u for u in r.units if u.document_id == doc.id), key=lambda u: u.ordinal)
        )
        require(doc.units.items == expected and len(expected) == 3)
        require(tuple(u.ordinal for u in expected) == (0, 1, 2))
        links(
            doc.links,
            tuple(
                ("document", identifier)
                for identifier in (doc.previous_document_id, doc.next_document_id)
                if identifier is not None
            ),
        )
    require(set(evidence) == set(units))
    require(set(lineages) == {unit.lineage_id for unit in r.units})
    for lineage in r.lineages:
        _page(lineage.versions)
        expected = tuple(
            sorted(
                (u for u in r.units if u.lineage_id == lineage.id),
                key=lambda u: (documents[u.document_id].ingested_at, u.document_id, u.ordinal),
            )
        )
        require(lineage.versions.items == expected)
    for unit in r.units:
        require(unit.document_id in documents and unit.lineage_id in lineages)
        require(unit.source_id == source, "REPLAY_SCOPE_INVALID")
        links(
            unit.links,
            (("document", unit.document_id), ("lineage", unit.lineage_id), ("evidence", unit.id)),
        )
        ev = evidence[unit.id]
        doc = documents[unit.document_id]
        require(
            (
                ev.source_id,
                ev.document_id,
                ev.lineage_id,
                ev.start_char,
                ev.end_char,
                ev.content_hash,
            )
            == (source, doc.id, unit.lineage_id, unit.start_char, unit.end_char, unit.content_hash)
        )
        require(ev.document_checksum == doc.checksum)
        require(
            (doc.checksum, ev.start_char, ev.end_char, ev.text) in SEGMENTS,
            "REPLAY_CORPUS_INVALID",
        )
        require(hashlib.sha256(ev.text.encode()).hexdigest() == unit.content_hash)
        require(bool(ev.revision_ids) and set(ev.revision_ids) <= revisions.keys())
        _unique(ev.revision_ids)
        anchors: set[str] = set()
        for identifier in ev.revision_ids:
            rev = revisions[identifier]
            nav = rev.navigation
            require(rev.entity_id in {source, unit.lineage_id})
            if nav.unit_id == unit.id:
                require(nav.document_id == doc.id)
                require(nav.content_hash is not None)
                anchors.add(str(nav.content_hash))
            elif nav.previous_unit_id == unit.id:
                require(nav.previous_document_id == doc.id)
                require(nav.previous_content_hash is not None)
                anchors.add(str(nav.previous_content_hash))
            elif rev.entity_type.value == "knowledge_unit":
                # Unchanged unit: B1 uses the last lineage anchor before publication.
                require(rev.created_at <= doc.ingested_at)
                require(nav.content_hash is not None)
                anchors.add(str(nav.content_hash))
            else:
                require(nav.document_id == doc.id and nav.document_checksum == doc.checksum)
        require(anchors == {unit.content_hash})
        links(
            ev.links,
            (
                ("document", ev.document_id),
                ("lineage", ev.lineage_id),
                *(("revision", identifier) for identifier in ev.revision_ids),
            ),
        )

    for rev in r.revisions:
        require(rev.created_at <= bundle.generated_at)
        entity = {"source": {source}, "document": set(documents), "knowledge_unit": set(lineages)}
        require(rev.entity_type.value in entity)
        require(rev.entity_id in entity[rev.entity_type.value])
        require(set(rev.affected_document_ids) <= documents.keys())
        require(set(rev.affected_unit_ids) <= units.keys())
        require(set(rev.affected_lineage_ids) <= lineages.keys())
        nav = rev.navigation
        for doc_id in (nav.document_id, nav.previous_document_id):
            require(doc_id is None or doc_id in documents)
        if nav.document_checksum is not None:
            require(nav.document_id in documents)
            require(documents[nav.document_id].checksum == nav.document_checksum)  # type: ignore[index]
        for unit_id, doc_id, content_hash in (
            (nav.unit_id, nav.document_id, nav.content_hash),
            (nav.previous_unit_id, nav.previous_document_id, nav.previous_content_hash),
        ):
            if unit_id is not None:
                require(unit_id in units)
                unit = units[unit_id]
                require(unit.document_id == doc_id and unit.content_hash == content_hash)
                require(unit.lineage_id == rev.entity_id)
        affected_docs = {
            identifier
            for identifier in (nav.document_id, nav.previous_document_id)
            if identifier is not None
        }
        affected_units = {
            identifier
            for identifier in (nav.unit_id, nav.previous_unit_id)
            if identifier is not None
        }
        affected_lineages = {rev.entity_id} if rev.entity_type.value == "knowledge_unit" else set()
        for identifier in affected_units:
            affected_docs.add(units[identifier].document_id)
            affected_lineages.add(units[identifier].lineage_id)
        if rev.entity_type.value == "document":
            affected_docs.add(rev.entity_id)
        if rev.entity_type.value in {"source", "document"}:
            for affected_version in r.units:
                if affected_version.document_id in affected_docs:
                    affected_units.add(affected_version.id)
                    affected_lineages.add(affected_version.lineage_id)
        require(rev.affected_document_ids == tuple(sorted(affected_docs)))
        require(rev.affected_unit_ids == tuple(sorted(affected_units)))
        require(rev.affected_lineage_ids == tuple(sorted(affected_lineages)))
        links(
            rev.links,
            (
                *(("document", identifier) for identifier in sorted(affected_docs)),
                *(("unit", identifier) for identifier in sorted(affected_units)),
                *(("lineage", identifier) for identifier in sorted(affected_lineages)),
            ),
        )
    # Every publication and each synthetic lineage's four revisions must be retained.
    require(len(r.revisions) == 16)
    for entity_id in (source, *lineages):
        chain = sorted(rev.revision for rev in r.revisions if rev.entity_id == entity_id)
        require(chain == [1, 2, 3, 4])
    for job in r.jobs:
        links(job.links, tuple(("revision", identifier) for identifier in job.trigger_revision_ids))
        publications = [
            revisions[i]
            for i in job.trigger_revision_ids
            if revisions[i].entity_type.value == "source"
        ]
        require(len(publications) == 1)
        require(
            publications[0].navigation.document_id
            == ordered_documents[story_ids.index(job.id) + 1].id
        )

    pairs = tuple((diff.new_document_id, diff.old_document_id) for diff in r.diffs)
    require(len(pairs) == len(set(pairs)), "REPLAY_DUPLICATE_ID")
    require(set(pairs) == {(new, old) for new in documents for old in documents})
    for diff in r.diffs:
        _page(diff.changes)
        require(diff.source_id == source, "REPLAY_SCOPE_INVALID")
        require(diff.new_document_id in documents and diff.old_document_id in documents)
        counts = Counter(item.kind.value for item in diff.changes.items)
        require(
            diff.counts.model_dump()
            == {name: counts[name] for name in type(diff.counts).model_fields}
        )
        seen: set[UUID] = set()
        for item in diff.changes.items:
            require(item.lineage_id in lineages and item.lineage_id not in seen)
            seen.add(item.lineage_id)
            for version, doc_id in (
                (item.old, diff.old_document_id),
                (item.new, diff.new_document_id),
            ):
                if version is not None:
                    require(units.get(version.id) == version)
                    require(version.document_id == doc_id and version.lineage_id == item.lineage_id)
            require(item.old is not None or item.new is not None)
            if item.old is None:
                require(item.kind.value == "added")
            elif item.new is None:
                require(item.kind.value == "removed")
            elif item.old.content_hash != item.new.content_hash:
                require(item.kind.value == "modified")
            else:
                require(
                    item.kind.value
                    == ("moved" if item.old.ordinal != item.new.ordinal else "unchanged")
                )
        require(seen == {u.lineage_id for u in r.units if u.document_id in pairs_for_diff(diff)})
        links(diff.links, (("document", diff.old_document_id), ("document", diff.new_document_id)))
    return bundle


def pairs_for_diff(diff: DocumentDiffDTO) -> set[UUID]:
    return {diff.old_document_id, diff.new_document_id}


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, "REPLAY_DUPLICATE_KEY")
        result[key] = value
    return result


def loads_validate(data: bytes) -> ReplayBundle:
    """Reject unknown fields, duplicate keys, coercions, oversized input and broken graphs."""
    if not data or len(data) > MAX_BYTES:
        raise ReplayError("REPLAY_SIZE_INVALID")
    try:
        # Pydantic JSON strict mode preserves UUID/datetime wire types, forbids int coercion.
        raw = json.loads(data, object_pairs_hook=_object)
        require(isinstance(raw, dict), "REPLAY_SCHEMA_INVALID")
        require(type(raw.get("schema_version")) is int, "REPLAY_SCHEMA_INVALID")
        bundle = ReplayBundle.model_validate_json(data, strict=True)
        return validate_bundle(bundle)
    except ReplayError:
        raise
    except (ValidationError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise ReplayError("REPLAY_SCHEMA_INVALID") from None


def load_validate(path: Path | str) -> ReplayBundle:
    """Only a generated static JSON file is accepted; validation performs zero writes."""
    from knowledge.replay.files import read_static

    return loads_validate(read_static(Path(path)))


def encode_bundle(bundle: ReplayBundle) -> bytes:
    data = (bundle.model_dump_json(indent=2) + "\n").encode()
    loads_validate(data)
    return data
