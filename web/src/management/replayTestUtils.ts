import type { DocumentDTO, DocumentDiffDTO, EvidenceDTO, JobDTO, LineageDTO, RevisionDTO, SafeCheck, UnitDTO } from "./types";
import type { ReplayBundle } from "./replay";

export const replayIds = {
  reference: "11111111-1111-1111-1111-111111111111",
  candidate: "22222222-2222-2222-2222-222222222222",
  recovery: "33333333-3333-3333-3333-333333333333",
  revisionA: "44444444-4444-4444-4444-444444444444",
  revisionB: "55555555-5555-5555-5555-555555555555",
  oldDocument: "66666666-6666-6666-6666-666666666666",
  newDocument: "77777777-7777-7777-7777-777777777777",
  lineage: "88888888-8888-8888-8888-888888888888",
  oldUnit: "99999999-9999-9999-9999-999999999999",
  newUnit: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  dataset: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
} as const;

const baseDate = new Date("2026-11-13T10:00:00+00:00");

function hash(seed: string): string {
  return seed.repeat(64);
}

function isoAt(minutes: number): string {
  return new Date(baseDate.getTime() + minutes * 60_000).toISOString();
}

function makeChecks(overrides: Partial<Record<SafeCheck["name"], Partial<Omit<SafeCheck, "name">>>> = {}): readonly SafeCheck[] {
  const base: Record<SafeCheck["name"], SafeCheck> = {
    top_k_contract: { name: "top_k_contract", passed: true, actual: 5, threshold: "==5" },
    recall_at_k: { name: "recall_at_k", passed: true, actual: 0.9, threshold: ">=0.8" },
    mean_reciprocal_rank: { name: "mean_reciprocal_rank", passed: true, actual: 0.85, threshold: ">=0.65" },
    no_answer_accuracy: { name: "no_answer_accuracy", passed: true, actual: 1, threshold: ">=1" },
    retrieval_evidence_citation_coverage: { name: "retrieval_evidence_citation_coverage", passed: true, actual: 1, threshold: ">=1" },
    stale_or_retired_hits: { name: "stale_or_retired_hits", passed: true, actual: 0, threshold: "<=0" },
    stale_isolation_configuration: { name: "stale_isolation_configuration", passed: true, actual: 0, threshold: "0 include_stale cases" },
    retrieval_degradation: { name: "retrieval_degradation", passed: true, actual: false, threshold: "false" },
    regression_gate: { name: "regression_gate", passed: true, actual: true, threshold: "pass" },
  };
  return Object.values(base)
    .filter((check) => check.name !== "regression_gate")
    .map((check) => ({ ...check, ...overrides[check.name] }));
}

function makeReport(passed: boolean): NonNullable<JobDTO["report"]> {
  return {
    passed,
    metrics: {
      case_count: 8,
      answerable_count: 6,
      no_answer_count: 2,
      mean_recall: passed ? 0.92 : 0.63,
      mean_precision: passed ? 0.86 : 0.58,
      mean_reciprocal_rank: passed ? 0.88 : 0.52,
      mean_ndcg: passed ? 0.84 : 0.55,
      hit_rate: passed ? 1 : 0.75,
      no_answer_accuracy: passed ? 1 : 0.5,
    },
    citation_coverage: passed ? 1 : 0.5,
    stale_hits: passed ? 0 : 2,
    degraded: false,
    checks: makeChecks(
      passed
        ? {}
        : {
            recall_at_k: { passed: false, actual: 0.63 },
            mean_reciprocal_rank: { passed: false, actual: 0.52 },
            no_answer_accuracy: { passed: false, actual: 0.5 },
            retrieval_evidence_citation_coverage: { passed: false, actual: 0.5 },
            stale_or_retired_hits: { passed: false, actual: 2 },
            regression_gate: { passed: false, actual: false, threshold: "pass" },
          },
    ),
  };
}

function makeJob(id: string, status: JobDTO["status"], minute: number, knowledgeSeed: string, triggerRevisionIds: readonly string[] = []): JobDTO {
  const passed = status === "passed";
  const terminal = status === "passed" || status === "failed";
  return {
    id,
    parent_job_id: null,
    status,
    config_generation: 1,
    config_fingerprint: hash("a"),
    dataset_id: replayIds.dataset,
    dataset_version: 7,
    dataset_hash: hash("b"),
    knowledge_fingerprint: hash(knowledgeSeed),
    created_at: isoAt(minute),
    evaluated_at: isoAt(minute),
    started_at: isoAt(minute),
    finished_at: isoAt(minute + 1),
    attempt_count: 1,
    error_code: status === "failed" ? "QUALITY_GATE_FAILED" : null,
    report: terminal ? makeReport(passed) : null,
    trigger_revision_ids: triggerRevisionIds,
    links: [],
  };
}

function makeExtraJob(index: number): JobDTO {
  const hex = index.toString(16).padStart(12, "0");
  const id = `00000000-0000-0000-0000-${hex}`;
  const knowledgeSeed = ["a", "b", "c", "d", "e", "f"][index % 6]!;
  return makeJob(id, "passed", 30 + index, knowledgeSeed);
}

export function makeReplayBundle(): ReplayBundle {
  const oldUnit: UnitDTO = {
    id: replayIds.oldUnit,
    source_id: replayIds.lineage,
    document_id: replayIds.oldDocument,
    lineage_id: replayIds.lineage,
    ordinal: 1,
    status: "active",
    start_char: 0,
    end_char: 12,
    content_hash: hash("c"),
    links: [],
  };
  const newUnit: UnitDTO = {
    id: replayIds.newUnit,
    source_id: replayIds.lineage,
    document_id: replayIds.newDocument,
    lineage_id: replayIds.lineage,
    ordinal: 1,
    status: "active",
    start_char: 0,
    end_char: 14,
    content_hash: hash("d"),
    links: [],
  };
  const oldDocument: DocumentDTO = {
    id: replayIds.oldDocument,
    source_id: replayIds.lineage,
    content_type: "markdown",
    checksum: hash("e"),
    ingested_at: isoAt(1),
    previous_document_id: null,
    next_document_id: replayIds.newDocument,
    units: { items: [oldUnit], total: 1, limit: 100, offset: 0 },
    links: [],
  };
  const newDocument: DocumentDTO = {
    id: replayIds.newDocument,
    source_id: replayIds.lineage,
    content_type: "markdown",
    checksum: hash("f"),
    ingested_at: isoAt(10),
    previous_document_id: replayIds.oldDocument,
    next_document_id: null,
    units: { items: [newUnit], total: 1, limit: 100, offset: 0 },
    links: [],
  };
  const lineage: LineageDTO = {
    id: replayIds.lineage,
    versions: { items: [newUnit, oldUnit], total: 2, limit: 100, offset: 0 },
  };
  const revisionA: RevisionDTO = {
    id: replayIds.revisionA,
    entity_type: "knowledge_unit",
    entity_id: replayIds.lineage,
    revision: 7,
    change_type: "update",
    created_at: isoAt(10),
    navigation: {
      event: "modified",
      document_id: replayIds.newDocument,
      previous_document_id: replayIds.oldDocument,
      unit_id: replayIds.newUnit,
      previous_unit_id: replayIds.oldUnit,
      document_checksum: hash("f"),
      content_hash: hash("d"),
      previous_content_hash: hash("c"),
      reverted: false,
    },
    affected_document_ids: [replayIds.oldDocument, replayIds.newDocument],
    affected_unit_ids: [replayIds.oldUnit, replayIds.newUnit],
    affected_lineage_ids: [replayIds.lineage],
    links: [],
  };
  const revisionB: RevisionDTO = {
    id: replayIds.revisionB,
    entity_type: "knowledge_unit",
    entity_id: replayIds.lineage,
    revision: 8,
    change_type: "update",
    created_at: isoAt(20),
    navigation: {
      event: "modified",
      document_id: replayIds.newDocument,
      previous_document_id: replayIds.oldDocument,
      unit_id: replayIds.newUnit,
      previous_unit_id: replayIds.oldUnit,
      document_checksum: hash("f"),
      content_hash: hash("d"),
      previous_content_hash: hash("c"),
      reverted: false,
    },
    affected_document_ids: [replayIds.oldDocument, replayIds.newDocument],
    affected_unit_ids: [replayIds.oldUnit, replayIds.newUnit],
    affected_lineage_ids: [replayIds.lineage],
    links: [],
  };
  const evidenceOld: EvidenceDTO = {
    source_id: replayIds.lineage,
    document_id: replayIds.oldDocument,
    unit_id: replayIds.oldUnit,
    lineage_id: replayIds.lineage,
    start_char: 0,
    end_char: 12,
    text: "旧值改成 10",
    content_hash: hash("c"),
    document_checksum: hash("e"),
    revision_ids: [replayIds.revisionA],
    links: [],
  };
  const evidenceNew: EvidenceDTO = {
    source_id: replayIds.lineage,
    document_id: replayIds.newDocument,
    unit_id: replayIds.newUnit,
    lineage_id: replayIds.lineage,
    start_char: 0,
    end_char: 14,
    text: "旧值改成 20 ✅",
    content_hash: hash("d"),
    document_checksum: hash("f"),
    revision_ids: [replayIds.revisionA, replayIds.revisionB],
    links: [],
  };
  const diff: DocumentDiffDTO = {
    source_id: replayIds.lineage,
    old_document_id: replayIds.oldDocument,
    new_document_id: replayIds.newDocument,
    counts: { added: 0, modified: 1, moved: 0, unchanged: 0, removed: 0 },
    changes: {
      items: [
        {
          kind: "modified",
          lineage_id: replayIds.lineage,
          old: oldUnit,
          new: newUnit,
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    },
    links: [],
  };
  const jobs = [
    makeJob(replayIds.reference, "passed", 0, "c", [replayIds.revisionA]),
    makeJob(replayIds.candidate, "failed", 10, "d", [replayIds.revisionA]),
    makeJob(replayIds.recovery, "passed", 20, "e", [replayIds.revisionB]),
    ...Array.from({ length: 18 }, (_, index) => makeExtraJob(index + 1)),
  ];
  return {
    schema_version: 1,
    mode: "replay",
    generated_at: "2026-11-20T10:30:00+08:00",
    story: {
      reference_job_id: replayIds.reference,
      candidate_job_id: replayIds.candidate,
      recovery_job_id: replayIds.recovery,
    },
    resources: {
      jobs,
      revisions: [revisionA, revisionB],
      documents: [oldDocument, newDocument],
      lineages: [lineage],
      units: [oldUnit, newUnit],
      evidence: [evidenceOld, evidenceNew],
      diffs: [diff],
    },
  };
}
