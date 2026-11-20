import { ManagementClient, type ManagementFetcher } from "./client";
import { ManagementError, type DocumentDTO, type DocumentDiffDTO, type EvidenceDTO, type JobDTO, type JobStatus, type LineageDTO, type ListJobsQuery, type Page, type PaginationQuery, type RevisionDTO, type UnitDTO } from "./types";
import { MAX_MANAGEMENT_RESPONSE_BYTES, validateManagementResponse } from "./validation";
import { ResponseByteLimitError, readBoundedBytes } from "../shared/readBoundedBytes";
import { HASH_PATTERN, UUID_PATTERN, validUnicode } from "../shared/validation";

const JSON_HEADERS = Object.freeze({ accept: "application/json" });
const ISO_AWARE_PATTERN = /(?:[zZ]|[+-]\d{2}:\d{2})$/;
const JOB_STATUS_SET = new Set<JobStatus>(["queued", "running", "passed", "failed", "blocked", "superseded"]);
const DEFAULT_PAGE_LIMIT = 20;
const MAX_PAGE_ITEMS = 100;

type ResourceDTO = JobDTO | RevisionDTO | DocumentDTO | LineageDTO | UnitDTO | EvidenceDTO | DocumentDiffDTO;

type ReplayStory = Readonly<{
  reference_job_id: string;
  candidate_job_id: string;
  recovery_job_id: string;
}>;

type ReplayResources = Readonly<{
  jobs: readonly JobDTO[];
  revisions: readonly RevisionDTO[];
  documents: readonly DocumentDTO[];
  lineages: readonly LineageDTO[];
  units: readonly UnitDTO[];
  evidence: readonly EvidenceDTO[];
  diffs: readonly DocumentDiffDTO[];
}>;

export type ReplayBundle = Readonly<{
  schema_version: 1;
  mode: "replay";
  generated_at: string;
  story: ReplayStory;
  resources: ReplayResources;
}>;

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function exactObject(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (!isObject(value)) throw new ManagementError("invalid_response");
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new ManagementError("invalid_response");
  }
  return value;
}

function exactArray<T>(value: unknown): readonly T[] {
  if (!Array.isArray(value)) throw new ManagementError("invalid_response");
  return value as readonly T[];
}

function assertIsoAware(value: unknown): string {
  if (typeof value !== "string" || !ISO_AWARE_PATTERN.test(value) || Number.isNaN(Date.parse(value))) {
    throw new ManagementError("invalid_response");
  }
  return value;
}

function assertBoundedPage<T>(page: Page<T>): void {
  if (page.offset !== 0 || page.limit !== MAX_PAGE_ITEMS || page.total !== page.items.length || page.items.length > MAX_PAGE_ITEMS) {
    throw new ManagementError("invalid_response");
  }
}

function idMap<T extends { readonly id: string }>(items: readonly T[]): ReadonlyMap<string, T> {
  const map = new Map<string, T>();
  for (const item of items) {
    if (!UUID_PATTERN.test(item.id) || map.has(item.id)) throw new ManagementError("invalid_response");
    map.set(item.id, item);
  }
  return map;
}

function diffKey(newId: string, oldId: string): string {
  return `${newId}\u0000${oldId}`;
}

function sameJson(left: ResourceDTO, right: ResourceDTO): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function assertKnownHash(value: string | null | undefined): void {
  if (value === null || value === undefined) return;
  if (!HASH_PATTERN.test(value)) throw new ManagementError("invalid_response");
}

function assertEmbeddedMatch<T extends ResourceDTO>(embedded: T, map: ReadonlyMap<string, T>): T {
  const resolved = map.get((embedded as { readonly id: string }).id);
  if (!resolved || !sameJson(embedded, resolved)) throw new ManagementError("invalid_response");
  return resolved;
}

export function validateReplayBundle(payload: unknown): ReplayBundle {
  const root = exactObject(payload, ["schema_version", "mode", "generated_at", "story", "resources"]);
  if (root.schema_version !== 1 || root.mode !== "replay") throw new ManagementError("invalid_response");
  const generated_at = assertIsoAware(root.generated_at);
  const storyObject = exactObject(root.story, ["reference_job_id", "candidate_job_id", "recovery_job_id"]);
  const story: ReplayStory = {
    reference_job_id: String(storyObject.reference_job_id),
    candidate_job_id: String(storyObject.candidate_job_id),
    recovery_job_id: String(storyObject.recovery_job_id),
  };
  if (![story.reference_job_id, story.candidate_job_id, story.recovery_job_id].every((id) => UUID_PATTERN.test(id))) {
    throw new ManagementError("invalid_response");
  }
  const resourceObject = exactObject(root.resources, ["jobs", "revisions", "documents", "lineages", "units", "evidence", "diffs"]);
  const resources: ReplayResources = {
    jobs: exactArray<JobDTO>(resourceObject.jobs).map((item) => validateManagementResponse("GetJobResponse", item)),
    revisions: exactArray<RevisionDTO>(resourceObject.revisions).map((item) => validateManagementResponse("GetRevisionResponse", item)),
    documents: exactArray<DocumentDTO>(resourceObject.documents).map((item) => validateManagementResponse("GetDocumentResponse", item)),
    lineages: exactArray<LineageDTO>(resourceObject.lineages).map((item) => validateManagementResponse("GetLineageResponse", item)),
    units: exactArray<UnitDTO>(resourceObject.units).map((item) => validateManagementResponse("GetUnitResponse", item)),
    evidence: exactArray<EvidenceDTO>(resourceObject.evidence).map((item) => validateManagementResponse("GetEvidenceResponse", item)),
    diffs: exactArray<DocumentDiffDTO>(resourceObject.diffs).map((item) => validateManagementResponse("GetDocumentDiffResponse", item)),
  };
  const jobs = idMap(resources.jobs);
  const revisions = idMap(resources.revisions);
  const documents = idMap(resources.documents);
  const lineages = idMap(resources.lineages);
  const units = idMap(resources.units);
  const evidence = new Map<string, EvidenceDTO>();
  for (const item of resources.evidence) {
    if (evidence.has(item.unit_id)) throw new ManagementError("invalid_response");
    evidence.set(item.unit_id, item);
  }
  const diffs = new Map<string, DocumentDiffDTO>();
  for (const item of resources.diffs) {
    if (diffs.has(diffKey(item.new_document_id, item.old_document_id))) throw new ManagementError("invalid_response");
    diffs.set(diffKey(item.new_document_id, item.old_document_id), item);
  }
  const storyJobs = [story.reference_job_id, story.candidate_job_id, story.recovery_job_id].map((id) => jobs.get(id));
  if (!storyJobs[0] || storyJobs[0].status !== "passed" || storyJobs[0].report?.passed !== true || storyJobs[0].error_code !== null) throw new ManagementError("invalid_response");
  if (!storyJobs[1] || storyJobs[1].status !== "failed" || storyJobs[1].report?.passed !== false || storyJobs[1].error_code !== "QUALITY_GATE_FAILED") throw new ManagementError("invalid_response");
  if (!storyJobs[2] || storyJobs[2].status !== "passed" || storyJobs[2].report?.passed !== true || storyJobs[2].error_code !== null) throw new ManagementError("invalid_response");
  for (const job of resources.jobs) {
    assertKnownHash(job.config_fingerprint);
    assertKnownHash(job.dataset_hash);
    assertKnownHash(job.knowledge_fingerprint);
    if (job.parent_job_id !== null && !jobs.has(job.parent_job_id)) throw new ManagementError("invalid_response");
    if (job.trigger_revision_ids.some((id) => !revisions.has(id))) throw new ManagementError("invalid_response");
  }
  for (const revision of resources.revisions) {
    const nav = revision.navigation;
    if (nav.document_id != null && !documents.has(nav.document_id)) throw new ManagementError("invalid_response");
    if (nav.previous_document_id != null && !documents.has(nav.previous_document_id)) throw new ManagementError("invalid_response");
    if (nav.unit_id != null && !units.has(nav.unit_id)) throw new ManagementError("invalid_response");
    if (nav.previous_unit_id != null && !units.has(nav.previous_unit_id)) throw new ManagementError("invalid_response");
    if (revision.affected_document_ids.some((id) => !documents.has(id)) || revision.affected_unit_ids.some((id) => !units.has(id)) || revision.affected_lineage_ids.some((id) => !lineages.has(id))) throw new ManagementError("invalid_response");
  }
  for (const unit of resources.units) {
    assertKnownHash(unit.content_hash);
    if (!documents.has(unit.document_id) || !lineages.has(unit.lineage_id)) throw new ManagementError("invalid_response");
    const text = evidence.get(unit.id);
    if (!text || text.unit_id !== unit.id || text.document_id !== unit.document_id || text.lineage_id !== unit.lineage_id || text.content_hash !== unit.content_hash || !validUnicode(text.text)) throw new ManagementError("invalid_response");
  }
  for (const document of resources.documents) {
    assertKnownHash(document.checksum);
    assertBoundedPage(document.units);
    if (document.previous_document_id !== null && !documents.has(document.previous_document_id)) throw new ManagementError("invalid_response");
    if (document.next_document_id !== null && !documents.has(document.next_document_id)) throw new ManagementError("invalid_response");
    for (const embedded of document.units.items) {
      const unit = assertEmbeddedMatch(embedded, units);
      if (unit.document_id !== document.id) throw new ManagementError("invalid_response");
    }
  }
  for (const lineage of resources.lineages) {
    assertBoundedPage(lineage.versions);
    for (const embedded of lineage.versions.items) {
      const unit = assertEmbeddedMatch(embedded, units);
      if (unit.lineage_id !== lineage.id) throw new ManagementError("invalid_response");
    }
  }
  for (const item of resources.evidence) {
    assertKnownHash(item.content_hash);
    assertKnownHash(item.document_checksum);
    if (!units.has(item.unit_id) || !documents.has(item.document_id) || !lineages.has(item.lineage_id) || item.revision_ids.some((id) => !revisions.has(id))) {
      throw new ManagementError("invalid_response");
    }
  }
  for (const diff of resources.diffs) {
    if (!documents.has(diff.old_document_id) || !documents.has(diff.new_document_id)) throw new ManagementError("invalid_response");
    assertBoundedPage(diff.changes);
    for (const change of diff.changes.items) {
      if (!lineages.has(change.lineage_id)) throw new ManagementError("invalid_response");
      if (change.old && (assertEmbeddedMatch(change.old, units).document_id !== diff.old_document_id || change.old.lineage_id !== change.lineage_id)) throw new ManagementError("invalid_response");
      if (change.new && (assertEmbeddedMatch(change.new, units).document_id !== diff.new_document_id || change.new.lineage_id !== change.lineage_id)) throw new ManagementError("invalid_response");
    }
  }
  return { schema_version: 1, mode: "replay", generated_at, story, resources };
}

function pageSlice<T>(page: Page<T>, query?: PaginationQuery): Page<T> {
  const limit = query?.limit ?? DEFAULT_PAGE_LIMIT;
  const offset = query?.offset ?? 0;
  return { items: page.items.slice(offset, offset + limit), total: page.total, limit, offset };
}

export class ReplayIndex {
  private readonly jobs: ReadonlyMap<string, JobDTO>;
  private readonly revisions: ReadonlyMap<string, RevisionDTO>;
  private readonly documents: ReadonlyMap<string, DocumentDTO>;
  private readonly lineages: ReadonlyMap<string, LineageDTO>;
  private readonly units: ReadonlyMap<string, UnitDTO>;
  private readonly evidence: ReadonlyMap<string, EvidenceDTO>;
  private readonly diffs: ReadonlyMap<string, DocumentDiffDTO>;

  constructor(readonly bundle: ReplayBundle) {
    this.jobs = idMap(bundle.resources.jobs);
    this.revisions = idMap(bundle.resources.revisions);
    this.documents = idMap(bundle.resources.documents);
    this.lineages = idMap(bundle.resources.lineages);
    this.units = idMap(bundle.resources.units);
    this.evidence = new Map(bundle.resources.evidence.map((item) => [item.unit_id, item] as const));
    this.diffs = new Map(bundle.resources.diffs.map((item) => [diffKey(item.new_document_id, item.old_document_id), item] as const));
  }

  listJobs(query?: ListJobsQuery): Page<JobDTO> {
    const limit = query?.limit ?? DEFAULT_PAGE_LIMIT;
    const offset = query?.offset ?? 0;
    const filtered = this.bundle.resources.jobs.filter((job) => (!query?.status || job.status === query.status) && (!query?.dataset_id || job.dataset_id === query.dataset_id) && (query?.dataset_version === undefined || job.dataset_version === query.dataset_version) && (!query?.parent_job_id || job.parent_job_id === query.parent_job_id));
    return { items: filtered.slice(offset, offset + limit), total: filtered.length, limit, offset };
  }

  getJob(id: string): JobDTO { return this.jobs.get(id) ?? notFound(); }
  getRevision(id: string): RevisionDTO { return this.revisions.get(id) ?? notFound(); }
  getUnit(id: string): UnitDTO { return this.units.get(id) ?? notFound(); }
  getEvidence(id: string): EvidenceDTO { return this.evidence.get(id) ?? notFound(); }
  getDocument(id: string, query?: PaginationQuery): DocumentDTO { const item = this.documents.get(id) ?? notFound(); return { ...item, units: pageSlice(item.units, query) }; }
  getLineage(id: string, query?: PaginationQuery): LineageDTO { const item = this.lineages.get(id) ?? notFound(); return { ...item, versions: pageSlice(item.versions, query) }; }
  getDocumentDiff(newId: string, oldId: string, query?: PaginationQuery): DocumentDiffDTO { const item = this.diffs.get(diffKey(newId, oldId)) ?? notFound(); return { ...item, changes: pageSlice(item.changes, query) }; }
}

function notFound(): never { throw new ManagementError("not_found", { status: 404 }); }

function single(search: URLSearchParams, key: string): string | null {
  const values = search.getAll(key);
  if (values.length > 1) throw new ManagementError("invalid_request", { status: 400 });
  return values[0] ?? null;
}

function integerParam(search: URLSearchParams, key: string, options: { min: number; max: number; fallback: number }): number {
  const value = single(search, key);
  if (value === null || value === "") return options.fallback;
  if (!/^\d+$/.test(value)) throw new ManagementError("invalid_request", { status: 400 });
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < options.min || parsed > options.max) throw new ManagementError("invalid_request", { status: 400 });
  return parsed;
}

function uuidParam(search: URLSearchParams, key: string): string | undefined {
  const value = single(search, key);
  if (value === null || value === "") return undefined;
  if (!UUID_PATTERN.test(value)) throw new ManagementError("invalid_request", { status: 400 });
  return value;
}

function hasOnlyKeys(search: URLSearchParams, allowed: readonly string[]): boolean {
  const allowedSet = new Set(allowed);
  const seen = new Set<string>();
  for (const [key] of search) {
    if (seen.has(key) || !allowedSet.has(key)) return false;
    seen.add(key);
  }
  return true;
}

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}

export function createReplayFetcher(bundle: ReplayBundle): ManagementFetcher {
  const index = new ReplayIndex(bundle);
  return async (input, init) => {
    try {
      if (init.method !== "GET" || init.body !== undefined || init.credentials !== "omit" || init.redirect !== "error") {
        throw new ManagementError("invalid_request", { status: 400 });
      }
      const url = new URL(input, "https://replay.local");
      const path = url.pathname;
      const search = url.searchParams;
      if (path === "/v1/management/jobs") {
        if (!hasOnlyKeys(search, ["status", "limit", "offset", "dataset_id", "dataset_version", "parent_job_id"])) {
          throw new ManagementError("invalid_request", { status: 400 });
        }
        const status = single(search, "status");
        if (status !== null && !JOB_STATUS_SET.has(status as JobStatus)) throw new ManagementError("invalid_request", { status: 400 });
        return json(index.listJobs({ limit: integerParam(search, "limit", { min: 1, max: 100, fallback: DEFAULT_PAGE_LIMIT }), offset: integerParam(search, "offset", { min: 0, max: 100_000, fallback: 0 }), status: status === null ? undefined : (status as JobStatus), dataset_id: uuidParam(search, "dataset_id"), dataset_version: single(search, "dataset_version") === null ? undefined : integerParam(search, "dataset_version", { min: 1, max: Number.MAX_SAFE_INTEGER, fallback: 1 }), parent_job_id: uuidParam(search, "parent_job_id") }));
      }
      const parts = path.split("/").filter(Boolean);
      if (parts[0] !== "v1" || parts[1] !== "management") throw new ManagementError("not_found", { status: 404 });
      if (parts[2] === "jobs" && parts.length === 4) {
        if (!hasOnlyKeys(search, [])) throw new ManagementError("invalid_request", { status: 400 });
        return json(index.getJob(parts[3]!));
      }
      if (parts[2] === "revisions" && parts.length === 4) {
        if (!hasOnlyKeys(search, [])) throw new ManagementError("invalid_request", { status: 400 });
        return json(index.getRevision(parts[3]!));
      }
      if (parts[2] === "units" && parts.length === 5 && parts[4] === "evidence") {
        if (!hasOnlyKeys(search, [])) throw new ManagementError("invalid_request", { status: 400 });
        return json(index.getEvidence(parts[3]!));
      }
      if (parts[2] === "units" && parts.length === 4) {
        if (!hasOnlyKeys(search, [])) throw new ManagementError("invalid_request", { status: 400 });
        return json(index.getUnit(parts[3]!));
      }
      const query = { limit: integerParam(search, "limit", { min: 1, max: 100, fallback: DEFAULT_PAGE_LIMIT }), offset: integerParam(search, "offset", { min: 0, max: 100_000, fallback: 0 }) };
      if (parts[2] === "documents" && parts.length === 5 && parts[4] === "diff") {
        if (!hasOnlyKeys(search, ["old_document_id", "limit", "offset"])) throw new ManagementError("invalid_request", { status: 400 });
        const oldId = uuidParam(search, "old_document_id");
        if (!oldId) throw new ManagementError("invalid_request", { status: 400 });
        return json(index.getDocumentDiff(parts[3]!, oldId, query));
      }
      if (parts[2] === "documents" && parts.length === 4) {
        if (!hasOnlyKeys(search, ["limit", "offset"])) throw new ManagementError("invalid_request", { status: 400 });
        return json(index.getDocument(parts[3]!, query));
      }
      if (parts[2] === "lineages" && parts.length === 4) {
        if (!hasOnlyKeys(search, ["limit", "offset"])) throw new ManagementError("invalid_request", { status: 400 });
        return json(index.getLineage(parts[3]!, query));
      }
      throw new ManagementError("not_found", { status: 404 });
    } catch (error) {
      if (error instanceof ManagementError) return json({}, error.status ?? 500);
      throw error;
    }
  };
}

function fetchLike(): typeof globalThis.fetch {
  if (typeof globalThis.fetch !== "function") throw new ManagementError("unavailable");
  return globalThis.fetch.bind(globalThis);
}

export function replayBundleUrl(baseUrl = import.meta.env.BASE_URL): string {
  return `${baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`}replay.json`;
}

export async function loadReplayBundle(signal?: AbortSignal, fetcher = fetchLike(), url = replayBundleUrl()): Promise<ReplayBundle> {
  try {
    const response = await fetcher(url, { method: "GET", credentials: "omit", redirect: "error", headers: JSON_HEADERS, signal });
    if (!response.ok) {
      if (response.status === 404) throw new ManagementError("not_found", { status: 404 });
      if (response.status === 401 || response.status === 403) throw new ManagementError("unauthorized", { status: response.status });
      if (response.status === 429 || response.status >= 500) throw new ManagementError("unavailable", { status: response.status });
      throw new ManagementError("invalid_response", { status: response.status });
    }
    let bytes: Uint8Array;
    try {
      bytes = await readBoundedBytes(response, MAX_MANAGEMENT_RESPONSE_BYTES);
    } catch (error) {
      if (error instanceof ResponseByteLimitError) throw new ManagementError("invalid_response", { status: response.status });
      throw error;
    }
    let text: string;
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } catch (error) {
      throw new ManagementError("invalid_response", { status: response.status, cause: error });
    }
    if (!text.trim() || /^\s*</.test(text)) throw new ManagementError("invalid_response", { status: response.status });
    let payload: unknown;
    try {
      payload = JSON.parse(text) as unknown;
    } catch (error) {
      throw new ManagementError("invalid_response", { status: response.status, cause: error });
    }
    return validateReplayBundle(payload);
  } catch (error) {
    if (error instanceof ManagementError) throw error;
    if (error instanceof Error && error.name === "AbortError") throw new ManagementError("aborted", { cause: error });
    if (error instanceof Error && error.name === "TimeoutError") throw new ManagementError("timeout", { cause: error });
    if (error instanceof Error && /redirect/i.test(error.message)) throw new ManagementError("invalid_response", { cause: error });
    throw new ManagementError("network", { cause: error });
  }
}

export function createReplayClient(bundle: ReplayBundle): ManagementClient {
  return new ManagementClient(createReplayFetcher(bundle));
}
