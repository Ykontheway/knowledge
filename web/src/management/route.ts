import type { JobStatus } from "./types";

export type DemoView = "overview" | "trace" | "diff";
export type View = DemoView | "lifecycle" | "evaluation" | "guide" | "changes";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const INTEGER_PATTERN = /^(0|[1-9]\d*)$/;
const MAX_OFFSET = 100_000;
const JOB_STATUSES: readonly JobStatus[] = ["queued", "running", "passed", "failed", "blocked", "superseded"];
const JOB_STATUS_SET = new Set<string>(JOB_STATUSES);

type InvalidReason = "unknown" | "invalid_id" | "invalid_query";

export interface DemoRoute {
  readonly view: DemoView;
}

export interface LifecycleJobsRoute {
  readonly view: "lifecycle";
  readonly kind: "jobs";
  readonly status?: JobStatus;
  readonly offset: number;
}

export interface LifecycleJobRoute {
  readonly view: "lifecycle";
  readonly kind: "job";
  readonly id: string;
}

export interface LifecycleRevisionRoute {
  readonly view: "lifecycle";
  readonly kind: "revision";
  readonly id: string;
}

export interface LifecycleDocumentRoute {
  readonly view: "lifecycle";
  readonly kind: "document";
  readonly id: string;
  readonly offset: number;
}

export interface LifecycleDiffRoute {
  readonly view: "lifecycle";
  readonly kind: "diff";
  readonly newId: string;
  readonly oldId: string;
  readonly offset: number;
}

export interface LifecycleLineageRoute {
  readonly view: "lifecycle";
  readonly kind: "lineage";
  readonly id: string;
  readonly offset: number;
}

export interface LifecycleEvidenceRoute {
  readonly view: "lifecycle";
  readonly kind: "evidence";
  readonly id: string;
}

export interface LifecycleInvalidRoute {
  readonly view: "lifecycle";
  readonly kind: "invalid";
  readonly reason: InvalidReason;
  readonly requestedHash: string;
}

export interface EvaluationCompareRoute {
  readonly view: "evaluation";
  readonly kind: "compare";
  readonly reference?: string;
  readonly candidate?: string;
  readonly offset: number;
}

export interface EvaluationInvalidRoute {
  readonly view: "evaluation";
  readonly kind: "invalid";
  readonly reason: InvalidReason;
  readonly requestedHash: string;
}

export interface GuideCompareRoute {
  readonly view: "guide";
  readonly kind: "steps";
  readonly normal?: string;
  readonly fault?: string;
  readonly restore?: string;
  readonly offset: number;
}

export interface GuideInvalidRoute {
  readonly view: "guide";
  readonly kind: "invalid";
  readonly reason: InvalidReason;
  readonly requestedHash: string;
}

export type ChangesRoute =
  | { readonly view: "changes"; readonly kind: "edit"; readonly documentId?: string }
  | { readonly view: "changes"; readonly kind: "command"; readonly commandId: string };

export interface ChangesInvalidRoute {
  readonly view: "changes";
  readonly kind: "invalid";
  readonly reason: InvalidReason;
}

export type LifecycleRoute =
  | LifecycleJobsRoute
  | LifecycleJobRoute
  | LifecycleRevisionRoute
  | LifecycleDocumentRoute
  | LifecycleDiffRoute
  | LifecycleLineageRoute
  | LifecycleEvidenceRoute
  | LifecycleInvalidRoute;
export type EvaluationRoute = EvaluationCompareRoute | EvaluationInvalidRoute;
export type GuideRoute = GuideCompareRoute | GuideInvalidRoute;
export type ChangesHashRoute = ChangesRoute | ChangesInvalidRoute;
export type HashRoute = DemoRoute | LifecycleRoute | EvaluationRoute | GuideRoute | ChangesHashRoute;

export interface BreadcrumbMeta {
  readonly section: string;
  readonly title: string;
  readonly tone: "demo" | "live";
}

function parseOffset(value: string | null): number | null {
  if (value === null) return 0;
  if (!INTEGER_PATTERN.test(value)) return null;
  const parsed = Number(value);
  return parsed <= MAX_OFFSET ? parsed : null;
}

function isUuid(value: string): boolean {
  return UUID_PATTERN.test(value);
}

function decodeSegment(value: string): string | null {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}

function invalid(hash: string, reason: InvalidReason): LifecycleInvalidRoute {
  return { view: "lifecycle", kind: "invalid", reason, requestedHash: hash };
}

function evaluationInvalid(hash: string, reason: InvalidReason): EvaluationInvalidRoute {
  return { view: "evaluation", kind: "invalid", reason, requestedHash: hash };
}

function guideInvalid(hash: string, reason: InvalidReason): GuideInvalidRoute {
  return { view: "guide", kind: "invalid", reason, requestedHash: hash };
}

function parseChangesRoute(hash: string): ChangesHashRoute {
  const fail = (reason: InvalidReason): ChangesInvalidRoute => ({ view: "changes", kind: "invalid", reason });
  // Unlike read-only routes, never preserve raw input: it may contain a token.
  const parts = hash.replace(/^#/, "").split("?");
  if (parts[0] !== "changes" || parts.length > 2) return fail("invalid_query");
  const search = parts[1];
  if (search === undefined || search === "") return { view: "changes", kind: "edit" };
  if (search.split("&").some(part => !part)) return fail("invalid_query");
  const query = new URLSearchParams(search);
  if (!hasOnlyKeys(query, new Set(["document", "command"])) || [...query.keys()].length !== 1) return fail("invalid_query");
  const id = query.get("document") ?? query.get("command");
  if (!id || !isUuid(id)) return fail("invalid_id");
  return query.has("document") ? { view: "changes", kind: "edit", documentId: id }
    : { view: "changes", kind: "command", commandId: id };
}

function hasDuplicateKeys(query: URLSearchParams): boolean {
  const seen = new Set<string>();
  for (const key of query.keys()) {
    if (seen.has(key)) return true;
    seen.add(key);
  }
  return false;
}

function hasOnlyKeys(query: URLSearchParams, allowed: ReadonlySet<string>): boolean {
  if (hasDuplicateKeys(query)) return false;
  for (const key of query.keys()) {
    if (!allowed.has(key)) return false;
  }
  return true;
}

function parseOptionalUuid(query: URLSearchParams, key: string): string | undefined | null {
  const value = query.get(key);
  if (value === null || value === "") return undefined;
  return isUuid(value) ? value : null;
}

function parseJobsRoute(query: URLSearchParams, rawHash: string): LifecycleRoute {
  if (!hasOnlyKeys(query, new Set(["status", "offset"]))) return invalid(rawHash, "invalid_query");
  const status = query.get("status");
  const offset = parseOffset(query.get("offset"));
  if (offset === null) return invalid(rawHash, "invalid_query");
  if (status !== null && !JOB_STATUS_SET.has(status)) return invalid(rawHash, "invalid_query");
  return { view: "lifecycle", kind: "jobs", status: status === null ? undefined : (status as JobStatus), offset };
}

function parsePagedIdRoute(
  kind: "document" | "lineage",
  id: string,
  query: URLSearchParams,
  rawHash: string,
): LifecycleRoute {
  if (!hasOnlyKeys(query, new Set(["offset"]))) return invalid(rawHash, "invalid_query");
  const offset = parseOffset(query.get("offset"));
  if (!isUuid(id)) return invalid(rawHash, "invalid_id");
  if (offset === null) return invalid(rawHash, "invalid_query");
  return { view: "lifecycle", kind, id, offset };
}

function parseEvaluationRoute(query: URLSearchParams, rawHash: string): EvaluationRoute {
  if (!hasOnlyKeys(query, new Set(["reference", "candidate", "offset"]))) return evaluationInvalid(rawHash, "invalid_query");
  const offset = parseOffset(query.get("offset"));
  const reference = parseOptionalUuid(query, "reference");
  const candidate = parseOptionalUuid(query, "candidate");
  if (offset === null || reference === null || candidate === null) return evaluationInvalid(rawHash, "invalid_query");
  return { view: "evaluation", kind: "compare", reference, candidate, offset };
}

function parseGuideRoute(query: URLSearchParams, rawHash: string): GuideRoute {
  if (!hasOnlyKeys(query, new Set(["normal", "fault", "restore", "offset"]))) return guideInvalid(rawHash, "invalid_query");
  const offset = parseOffset(query.get("offset"));
  const normal = parseOptionalUuid(query, "normal");
  const fault = parseOptionalUuid(query, "fault");
  const restore = parseOptionalUuid(query, "restore");
  if (offset === null || normal === null || fault === null || restore === null) return guideInvalid(rawHash, "invalid_query");
  return { view: "guide", kind: "steps", normal, fault, restore, offset };
}

export function parseHashRoute(rawHash: string): HashRoute {
  if (/^#?\/*changes(?:$|[?/%\\\s])/i.test(rawHash)) return parseChangesRoute(rawHash);
  const normalized = rawHash.replace(/^#/, "").trim();
  if (!normalized || normalized === "/") return { view: "overview" };
  if ((normalized.match(/\?/g) ?? []).length > 1) {
    const firstPath = normalized.split("?", 1)[0]?.replace(/^\/+|\/+$/g, "");
    if (firstPath === "evaluation") return evaluationInvalid(rawHash, "invalid_query");
    if (firstPath === "guide") return guideInvalid(rawHash, "invalid_query");
    return invalid(rawHash, "invalid_query");
  }

  const [rawPathPart = "", searchPart = ""] = normalized.split("?", 2);
  if (/%2f|%5c/i.test(rawPathPart)) return invalid(rawHash, "invalid_query");
  const decodedPath = decodeSegment(rawPathPart.replace(/^\/+|\/+$/g, ""));
  if (decodedPath === null) return invalid(rawHash, "invalid_query");
  if (!decodedPath) return { view: "overview" };

  const segments = decodedPath.split("/").filter(Boolean);
  const query = new URLSearchParams(searchPart);
  const second = segments[1];
  const third = segments[2];
  const fourth = segments[3];

  if (segments.length === 1 && ["overview", "trace", "diff"].includes(segments[0] ?? "")) {
    if ([...query.keys()].length > 0) return invalid(rawHash, "invalid_query");
    return { view: segments[0] as DemoView };
  }

  if (segments.length === 1 && segments[0] === "evaluation") return parseEvaluationRoute(query, rawHash);
  if (segments.length === 1 && segments[0] === "guide") return parseGuideRoute(query, rawHash);
  if (segments[0] === "evaluation") return evaluationInvalid(rawHash, "unknown");
  if (segments[0] === "guide") return guideInvalid(rawHash, "unknown");

  if (segments[0] !== "lifecycle") return { view: "overview" };

  if (segments.length === 1) return parseJobsRoute(query, rawHash);
  if (second === "jobs") {
    if (segments.length === 2) return parseJobsRoute(query, rawHash);
    if (segments.length === 3 && third && isUuid(third)) {
      if ([...query.keys()].length > 0) return invalid(rawHash, "invalid_query");
      return { view: "lifecycle", kind: "job", id: third };
    }
    return invalid(rawHash, third ? "invalid_id" : "unknown");
  }
  if (second === "revisions") {
    if (segments.length !== 3 || !third) return invalid(rawHash, "unknown");
    if (!isUuid(third)) return invalid(rawHash, "invalid_id");
    if ([...query.keys()].length > 0) return invalid(rawHash, "invalid_query");
    return { view: "lifecycle", kind: "revision", id: third };
  }
  if (second === "documents") {
    if (segments.length === 3 && third) return parsePagedIdRoute("document", third, query, rawHash);
    if (segments.length === 4 && fourth === "diff" && third) {
      if (!isUuid(third)) return invalid(rawHash, "invalid_id");
      if (!hasOnlyKeys(query, new Set(["old", "offset"]))) return invalid(rawHash, "invalid_query");
      const oldId = query.get("old");
      const offset = parseOffset(query.get("offset"));
      if (!oldId || !isUuid(oldId) || offset === null) return invalid(rawHash, "invalid_query");
      return { view: "lifecycle", kind: "diff", newId: third, oldId, offset };
    }
    return invalid(rawHash, "unknown");
  }
  if (second === "lineages") {
    if (segments.length !== 3 || !third) return invalid(rawHash, "unknown");
    return parsePagedIdRoute("lineage", third, query, rawHash);
  }
  if (second === "evidence") {
    if (segments.length !== 3 || !third) return invalid(rawHash, "unknown");
    if (!isUuid(third)) return invalid(rawHash, "invalid_id");
    if ([...query.keys()].length > 0) return invalid(rawHash, "invalid_query");
    return { view: "lifecycle", kind: "evidence", id: third };
  }

  return invalid(rawHash, "unknown");
}

function buildHash(path: string, query?: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === "") continue;
    params.set(key, String(value));
  }
  const search = params.toString();
  return search ? `#${path}?${search}` : `#${path}`;
}

export function demoHash(view: DemoView): string {
  return `#${view}`;
}

export function lifecycleJobsHash(options: { status?: JobStatus; offset?: number } = {}): string {
  return buildHash("lifecycle/jobs", { status: options.status, offset: options.offset && options.offset > 0 ? options.offset : undefined });
}

export function lifecycleJobHash(id: string): string {
  return `#lifecycle/jobs/${id}`;
}

export function lifecycleRevisionHash(id: string): string {
  return `#lifecycle/revisions/${id}`;
}

export function lifecycleDocumentHash(id: string, offset = 0): string {
  return buildHash(`lifecycle/documents/${id}`, { offset: offset > 0 ? offset : undefined });
}

export function lifecycleDiffHash(newId: string, oldId: string, offset = 0): string {
  return buildHash(`lifecycle/documents/${newId}/diff`, { old: oldId, offset: offset > 0 ? offset : undefined });
}

export function lifecycleLineageHash(id: string, offset = 0): string {
  return buildHash(`lifecycle/lineages/${id}`, { offset: offset > 0 ? offset : undefined });
}

export function lifecycleEvidenceHash(id: string): string {
  return `#lifecycle/evidence/${id}`;
}

export function lifecycleEntryHash(): string {
  return lifecycleJobsHash();
}

export function evaluationHash(options: { reference?: string; candidate?: string; offset?: number } = {}): string {
  return buildHash("evaluation", {
    reference: options.reference,
    candidate: options.candidate,
    offset: options.offset && options.offset > 0 ? options.offset : undefined,
  });
}

export function guideHash(options: { normal?: string; fault?: string; restore?: string; offset?: number } = {}): string {
  return buildHash("guide", {
    normal: options.normal,
    fault: options.fault,
    restore: options.restore,
    offset: options.offset && options.offset > 0 ? options.offset : undefined,
  });
}

export function changesHash(options: { document?: string; command?: string } = {}): string {
  if (Object.keys(options).some(key => !["document", "command"].includes(key)) ||
      (options.document !== undefined && options.command !== undefined) ||
      Object.values(options).some(id => id !== undefined && (typeof id !== "string" || !isUuid(id)))) {
    throw new Error("invalid_changes_route");
  }
  return buildHash("changes", options);
}

export function getBreadcrumbMeta(route: HashRoute): BreadcrumbMeta {
  switch (route.view) {
    case "overview":
      return { section: "静态演示", title: "总览", tone: "demo" };
    case "trace":
      return { section: "静态演示", title: "原文溯源", tone: "demo" };
    case "diff":
      return { section: "静态演示", title: "版本 Diff", tone: "demo" };
    case "changes":
      return { section: "受控更新 / 仅演示副本", title: route.kind === "invalid" ? "安全提示" : "受控变更", tone: "live" };
    case "evaluation":
      return { section: "实时工作台 / 只读", title: route.kind === "invalid" ? "安全提示" : "评测对照", tone: "live" };
    case "guide":
      return { section: "实时工作台 / 只读", title: route.kind === "invalid" ? "安全提示" : "演示导览", tone: "live" };
    case "lifecycle":
      switch (route.kind) {
        case "jobs":
          return { section: "实时工作台 / 只读", title: "任务时间线", tone: "live" };
        case "job":
          return { section: "实时工作台 / 只读", title: "任务详情", tone: "live" };
        case "revision":
          return { section: "实时工作台 / 只读", title: "Revision 详情", tone: "live" };
        case "document":
          return { section: "实时工作台 / 只读", title: "文档版本", tone: "live" };
        case "diff":
          return { section: "实时工作台 / 只读", title: "历史 Diff", tone: "live" };
        case "lineage":
          return { section: "实时工作台 / 只读", title: "Lineage 历史", tone: "live" };
        case "evidence":
          return { section: "实时工作台 / 只读", title: "历史证据", tone: "live" };
        case "invalid":
          return { section: "实时工作台 / 只读", title: "安全提示", tone: "live" };
      }
  }
}

export function isLifecycleRoute(route: HashRoute): route is LifecycleRoute {
  return route.view === "lifecycle";
}

export function isEvaluationRoute(route: HashRoute): route is EvaluationRoute {
  return route.view === "evaluation";
}

export function isGuideRoute(route: HashRoute): route is GuideRoute {
  return route.view === "guide";
}
