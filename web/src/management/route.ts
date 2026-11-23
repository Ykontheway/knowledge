import type { ManagementMode } from "./mode";
import type { JobStatus } from "./types";

export type DemoView = "overview" | "trace" | "diff";
export type View = DemoView | "lifecycle" | "evaluation" | "guide" | "changes";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const INTEGER_PATTERN = /^(0|[1-9]\d*)$/;
const MAX_OFFSET = 100_000;
const JOB_STATUSES: readonly JobStatus[] = ["queued", "running", "passed", "failed", "blocked", "superseded"];
const JOB_STATUS_SET = new Set<string>(JOB_STATUSES);

type InvalidReason = "unknown" | "invalid_id" | "invalid_query";

interface ManagedRouteBase {
  readonly mode: ManagementMode;
}

export interface DemoRoute {
  readonly view: DemoView;
}

export interface LifecycleJobsRoute extends ManagedRouteBase {
  readonly view: "lifecycle";
  readonly kind: "jobs";
  readonly status?: JobStatus;
  readonly offset: number;
}

export interface LifecycleJobRoute extends ManagedRouteBase {
  readonly view: "lifecycle";
  readonly kind: "job";
  readonly id: string;
}

export interface LifecycleRevisionRoute extends ManagedRouteBase {
  readonly view: "lifecycle";
  readonly kind: "revision";
  readonly id: string;
}

export interface LifecycleDocumentRoute extends ManagedRouteBase {
  readonly view: "lifecycle";
  readonly kind: "document";
  readonly id: string;
  readonly offset: number;
}

export interface LifecycleDiffRoute extends ManagedRouteBase {
  readonly view: "lifecycle";
  readonly kind: "diff";
  readonly newId: string;
  readonly oldId: string;
  readonly offset: number;
}

export interface LifecycleLineageRoute extends ManagedRouteBase {
  readonly view: "lifecycle";
  readonly kind: "lineage";
  readonly id: string;
  readonly offset: number;
}

export interface LifecycleEvidenceRoute extends ManagedRouteBase {
  readonly view: "lifecycle";
  readonly kind: "evidence";
  readonly id: string;
}

export interface LifecycleInvalidRoute extends ManagedRouteBase {
  readonly view: "lifecycle";
  readonly kind: "invalid";
  readonly reason: InvalidReason;
  readonly requestedHash: string;
}

export interface EvaluationCompareRoute extends ManagedRouteBase {
  readonly view: "evaluation";
  readonly kind: "compare";
  readonly reference?: string;
  readonly candidate?: string;
  readonly offset: number;
}

export interface EvaluationInvalidRoute extends ManagedRouteBase {
  readonly view: "evaluation";
  readonly kind: "invalid";
  readonly reason: InvalidReason;
  readonly requestedHash: string;
}

export interface GuideCompareRoute extends ManagedRouteBase {
  readonly view: "guide";
  readonly kind: "steps";
  readonly normal?: string;
  readonly fault?: string;
  readonly restore?: string;
  readonly offset: number;
}

export interface GuideInvalidRoute extends ManagedRouteBase {
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
  readonly tone: "demo" | "live" | "replay";
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

function invalid(hash: string, reason: InvalidReason, mode: ManagementMode): LifecycleInvalidRoute {
  return { view: "lifecycle", kind: "invalid", reason, requestedHash: hash, mode };
}

function evaluationInvalid(hash: string, reason: InvalidReason, mode: ManagementMode): EvaluationInvalidRoute {
  return { view: "evaluation", kind: "invalid", reason, requestedHash: hash, mode };
}

function guideInvalid(hash: string, reason: InvalidReason, mode: ManagementMode): GuideInvalidRoute {
  return { view: "guide", kind: "invalid", reason, requestedHash: hash, mode };
}

function parseChangesRoute(hash: string): ChangesHashRoute {
  const fail = (reason: InvalidReason): ChangesInvalidRoute => ({ view: "changes", kind: "invalid", reason });
  const parts = hash.replace(/^#/, "").split("?");
  if (parts[0] !== "changes" || parts.length > 2) return fail("invalid_query");
  const search = parts[1];
  if (search === undefined || search === "") return { view: "changes", kind: "edit" };
  if (search.split("&").some((part) => !part)) return fail("invalid_query");
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

function parseJobsRoute(query: URLSearchParams, rawHash: string, mode: ManagementMode): LifecycleRoute {
  if (!hasOnlyKeys(query, new Set(["status", "offset"]))) return invalid(rawHash, "invalid_query", mode);
  const status = query.get("status");
  const offset = parseOffset(query.get("offset"));
  if (offset === null) return invalid(rawHash, "invalid_query", mode);
  if (status !== null && !JOB_STATUS_SET.has(status)) return invalid(rawHash, "invalid_query", mode);
  return { view: "lifecycle", kind: "jobs", status: status === null ? undefined : (status as JobStatus), offset, mode };
}

function parsePagedIdRoute(kind: "document" | "lineage", id: string, query: URLSearchParams, rawHash: string, mode: ManagementMode): LifecycleRoute {
  if (!hasOnlyKeys(query, new Set(["offset"]))) return invalid(rawHash, "invalid_query", mode);
  const offset = parseOffset(query.get("offset"));
  if (!isUuid(id)) return invalid(rawHash, "invalid_id", mode);
  if (offset === null) return invalid(rawHash, "invalid_query", mode);
  return { view: "lifecycle", kind, id, offset, mode };
}

function parseEvaluationRoute(query: URLSearchParams, rawHash: string, mode: ManagementMode): EvaluationRoute {
  if (!hasOnlyKeys(query, new Set(["reference", "candidate", "offset"]))) return evaluationInvalid(rawHash, "invalid_query", mode);
  const offset = parseOffset(query.get("offset"));
  const reference = parseOptionalUuid(query, "reference");
  const candidate = parseOptionalUuid(query, "candidate");
  if (offset === null || reference === null || candidate === null) return evaluationInvalid(rawHash, "invalid_query", mode);
  return { view: "evaluation", kind: "compare", reference, candidate, offset, mode };
}

function parseGuideRoute(query: URLSearchParams, rawHash: string, mode: ManagementMode): GuideRoute {
  if (!hasOnlyKeys(query, new Set(["normal", "fault", "restore", "offset"]))) return guideInvalid(rawHash, "invalid_query", mode);
  const offset = parseOffset(query.get("offset"));
  const normal = parseOptionalUuid(query, "normal");
  const fault = parseOptionalUuid(query, "fault");
  const restore = parseOptionalUuid(query, "restore");
  if (offset === null || normal === null || fault === null || restore === null) return guideInvalid(rawHash, "invalid_query", mode);
  return { view: "guide", kind: "steps", normal, fault, restore, offset, mode };
}

function parseManagedSegments(segments: readonly string[], rawHash: string, searchPart: string, mode: ManagementMode): HashRoute {
  const query = new URLSearchParams(searchPart);
  const second = segments[1];
  const third = segments[2];
  const fourth = segments[3];
  if (segments.length === 0) {
    if ([...query.keys()].length > 0) return guideInvalid(rawHash, "invalid_query", mode);
    return { view: "guide", kind: "steps", normal: undefined, fault: undefined, restore: undefined, offset: 0, mode };
  }
  if (segments.length === 1 && segments[0] === "evaluation") return parseEvaluationRoute(query, rawHash, mode);
  if (segments.length === 1 && segments[0] === "guide") return parseGuideRoute(query, rawHash, mode);
  if (segments[0] === "evaluation") return evaluationInvalid(rawHash, "unknown", mode);
  if (segments[0] === "guide") return guideInvalid(rawHash, "unknown", mode);
  if (segments[0] !== "lifecycle") return invalid(rawHash, "unknown", mode);
  if (segments.length === 1) return parseJobsRoute(query, rawHash, mode);
  if (second === "jobs") {
    if (segments.length === 2) return parseJobsRoute(query, rawHash, mode);
    if (segments.length === 3 && third && isUuid(third)) {
      if ([...query.keys()].length > 0) return invalid(rawHash, "invalid_query", mode);
      return { view: "lifecycle", kind: "job", id: third, mode };
    }
    return invalid(rawHash, third ? "invalid_id" : "unknown", mode);
  }
  if (second === "revisions") {
    if (segments.length !== 3 || !third) return invalid(rawHash, "unknown", mode);
    if (!isUuid(third)) return invalid(rawHash, "invalid_id", mode);
    if ([...query.keys()].length > 0) return invalid(rawHash, "invalid_query", mode);
    return { view: "lifecycle", kind: "revision", id: third, mode };
  }
  if (second === "documents") {
    if (segments.length === 3 && third) return parsePagedIdRoute("document", third, query, rawHash, mode);
    if (segments.length === 4 && fourth === "diff" && third) {
      if (!isUuid(third)) return invalid(rawHash, "invalid_id", mode);
      if (!hasOnlyKeys(query, new Set(["old", "offset"]))) return invalid(rawHash, "invalid_query", mode);
      const oldId = query.get("old");
      const offset = parseOffset(query.get("offset"));
      if (!oldId || !isUuid(oldId) || offset === null) return invalid(rawHash, "invalid_query", mode);
      return { view: "lifecycle", kind: "diff", newId: third, oldId, offset, mode };
    }
    return invalid(rawHash, "unknown", mode);
  }
  if (second === "lineages") {
    if (segments.length !== 3 || !third) return invalid(rawHash, "unknown", mode);
    return parsePagedIdRoute("lineage", third, query, rawHash, mode);
  }
  if (second === "evidence") {
    if (segments.length !== 3 || !third) return invalid(rawHash, "unknown", mode);
    if (!isUuid(third)) return invalid(rawHash, "invalid_id", mode);
    if ([...query.keys()].length > 0) return invalid(rawHash, "invalid_query", mode);
    return { view: "lifecycle", kind: "evidence", id: third, mode };
  }
  return invalid(rawHash, "unknown", mode);
}

export function parseHashRoute(rawHash: string): HashRoute {
  if (/^#?\/*changes(?:$|[?/%\\\s])/i.test(rawHash)) return parseChangesRoute(rawHash);
  const normalized = rawHash.replace(/^#/, "").trim();
  if (!normalized || normalized === "/") return { view: "overview" };
  if ((normalized.match(/\?/g) ?? []).length > 1) {
    const firstPath = normalized.split("?", 1)[0]?.replace(/^\/+|\/+$/g, "");
    if (firstPath === "evaluation") return evaluationInvalid(rawHash, "invalid_query", "live");
    if (firstPath === "guide") return guideInvalid(rawHash, "invalid_query", "live");
    if (firstPath === "replay" || firstPath?.startsWith("replay/")) return invalid(rawHash, "invalid_query", "replay");
    return invalid(rawHash, "invalid_query", "live");
  }
  const [rawPathPart = "", searchPart = ""] = normalized.split("?", 2);
  const trimmedPathPart = rawPathPart.replace(/^\/+|\/+$/g, "");
  if (/%2f|%5c/i.test(rawPathPart)) return trimmedPathPart.startsWith("replay") ? invalid(rawHash, "invalid_query", "replay") : invalid(rawHash, "invalid_query", "live");
  const decodedPath = decodeSegment(trimmedPathPart);
  if (decodedPath === null) return invalid(rawHash, "invalid_query", "live");
  if (!decodedPath) return { view: "overview" };
  const segments = decodedPath.split("/").filter(Boolean);
  if (segments[0] === "replay") return parseManagedSegments(segments.slice(1), rawHash, searchPart, "replay");
  if (segments.length === 1 && ["overview", "trace", "diff"].includes(segments[0] ?? "")) {
    if ([...new URLSearchParams(searchPart).keys()].length > 0) return invalid(rawHash, "invalid_query", "live");
    return { view: segments[0] as DemoView };
  }
  if (!["lifecycle", "evaluation", "guide"].includes(segments[0] ?? "")) {
    return { view: "overview" };
  }
  return parseManagedSegments(segments, rawHash, searchPart, "live");
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

function managedPath(path: string, mode: ManagementMode): string {
  return mode === "replay" ? `replay/${path}` : path;
}

export function demoHash(view: DemoView): string {
  return `#${view}`;
}

export function lifecycleJobsHash(options: { status?: JobStatus; offset?: number; mode?: ManagementMode } = {}): string {
  return buildHash(managedPath("lifecycle/jobs", options.mode ?? "live"), { status: options.status, offset: options.offset && options.offset > 0 ? options.offset : undefined });
}

export function lifecycleJobHash(id: string, options: { mode?: ManagementMode } = {}): string {
  return `#${managedPath(`lifecycle/jobs/${id}`, options.mode ?? "live")}`;
}

export function lifecycleRevisionHash(id: string, options: { mode?: ManagementMode } = {}): string {
  return `#${managedPath(`lifecycle/revisions/${id}`, options.mode ?? "live")}`;
}

export function lifecycleDocumentHash(id: string, offset = 0, options: { mode?: ManagementMode } = {}): string {
  return buildHash(managedPath(`lifecycle/documents/${id}`, options.mode ?? "live"), { offset: offset > 0 ? offset : undefined });
}

export function lifecycleDiffHash(newId: string, oldId: string, offset = 0, options: { mode?: ManagementMode } = {}): string {
  return buildHash(managedPath(`lifecycle/documents/${newId}/diff`, options.mode ?? "live"), { old: oldId, offset: offset > 0 ? offset : undefined });
}

export function lifecycleLineageHash(id: string, offset = 0, options: { mode?: ManagementMode } = {}): string {
  return buildHash(managedPath(`lifecycle/lineages/${id}`, options.mode ?? "live"), { offset: offset > 0 ? offset : undefined });
}

export function lifecycleEvidenceHash(id: string, options: { mode?: ManagementMode } = {}): string {
  return `#${managedPath(`lifecycle/evidence/${id}`, options.mode ?? "live")}`;
}

export function lifecycleEntryHash(options: { mode?: ManagementMode } = {}): string {
  return lifecycleJobsHash({ mode: options.mode ?? "live" });
}

export function replayEntryHash(): string {
  return "#replay";
}

export function evaluationHash(options: { reference?: string; candidate?: string; offset?: number; mode?: ManagementMode } = {}): string {
  return buildHash(managedPath("evaluation", options.mode ?? "live"), { reference: options.reference, candidate: options.candidate, offset: options.offset && options.offset > 0 ? options.offset : undefined });
}

export function guideHash(options: { normal?: string; fault?: string; restore?: string; offset?: number; mode?: ManagementMode } = {}): string {
  return buildHash(managedPath("guide", options.mode ?? "live"), { normal: options.normal, fault: options.fault, restore: options.restore, offset: options.offset && options.offset > 0 ? options.offset : undefined });
}

export function changesHash(options: { document?: string; command?: string } = {}): string {
  if (Object.keys(options).some((key) => !["document", "command"].includes(key)) || (options.document !== undefined && options.command !== undefined) || Object.values(options).some((id) => id !== undefined && (typeof id !== "string" || !isUuid(id)))) {
    throw new Error("invalid_changes_route");
  }
  return buildHash("changes", options);
}

function breadcrumbSection(mode: ManagementMode): { readonly section: string; readonly tone: "live" | "replay" } {
  return mode === "replay" ? { section: "静态回放 / 只读", tone: "replay" } : { section: "实时工作台 / 只读", tone: "live" };
}

export function getBreadcrumbMeta(route: HashRoute): BreadcrumbMeta {
  switch (route.view) {
    case "overview":
      return { section: "版本快照", title: "总览", tone: "demo" };
    case "trace":
      return { section: "版本快照", title: "原文溯源", tone: "demo" };
    case "diff":
      return { section: "版本快照", title: "版本 Diff", tone: "demo" };
    case "changes":
      return { section: "受控更新 / 仅隔离副本", title: route.kind === "invalid" ? "安全提示" : "受控变更", tone: "live" };
    case "evaluation": {
      const meta = breadcrumbSection(route.mode);
      return { ...meta, title: route.kind === "invalid" ? "安全提示" : "评测对照" };
    }
    case "guide": {
      const meta = breadcrumbSection(route.mode);
      return { ...meta, title: route.kind === "invalid" ? "安全提示" : "使用导览" };
    }
    case "lifecycle": {
      const meta = breadcrumbSection(route.mode);
      switch (route.kind) {
        case "jobs":
          return { ...meta, title: "任务时间线" };
        case "job":
          return { ...meta, title: "任务详情" };
        case "revision":
          return { ...meta, title: "Revision 详情" };
        case "document":
          return { ...meta, title: "文档版本" };
        case "diff":
          return { ...meta, title: "历史 Diff" };
        case "lineage":
          return { ...meta, title: "Lineage 历史" };
        case "evidence":
          return { ...meta, title: "历史证据" };
        case "invalid":
          return { ...meta, title: "安全提示" };
      }
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
