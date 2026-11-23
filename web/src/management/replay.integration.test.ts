// @vitest-environment jsdom

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath, URL as NodeURL } from "node:url";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { compareJobs, CHECK_LABELS, formatMetricDelta, formatMetricValue } from "../evaluation/comparison";
import { formatFull } from "../lib/format";
import { ManagementClient } from "./client";
import { createReplayClient, createReplayFetcher, loadReplayBundle, replayBundleUrl, validateReplayBundle, type ReplayBundle } from "./replay";
import { validateManagementResponse } from "./validation";
import { evaluationHash, lifecycleDiffHash, lifecycleDocumentHash, lifecycleEvidenceHash, lifecycleJobHash, lifecycleLineageHash, lifecycleRevisionHash, parseHashRoute } from "./route";
import type { Page, ResourceLink } from "./types";

// 唯一数据源是父流程导出的可提交文件；不使用 replayTestUtils，也不补写任何资源。
const exportPath = fileURLToPath(new NodeURL("../../public/replay.json", import.meta.url));
const exportedBytes = readFileSync(exportPath);
const exportedText = exportedBytes.toString("utf8");
const diskHash = createHash("sha256").update(exportedBytes).digest("hex");
const getBundle = () => validateReplayBundle(JSON.parse(exportedText) as unknown);
const response = () => new Response(exportedText, { headers: { "content-type": "application/json" } });
const mode = { mode: "replay" as const };
const strictGet: RequestInit = { method: "GET", credentials: "omit", redirect: "error", headers: { accept: "application/json" } };
const checkNames = ["top_k_contract", "recall_at_k", "mean_reciprocal_rank", "no_answer_accuracy", "retrieval_evidence_citation_coverage", "stale_or_retired_hits", "stale_isolation_configuration", "retrieval_degradation"].sort();
const roots = new Set<Root>();
let networkPaths: string[];
let manifestResponse: (() => Promise<Response>) | undefined;
let fetchMock: ReturnType<typeof vi.fn<typeof globalThis.fetch>>;
let previousActEnvironment: boolean | undefined;
const actEnvironment = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean };

beforeEach(() => {
  previousActEnvironment = actEnvironment.IS_REACT_ACT_ENVIRONMENT;
  actEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
  networkPaths = [];
  manifestResponse = undefined;
  fetchMock = vi.fn<typeof globalThis.fetch>(async (input, init) => {
    const path = String(input);
    if (path !== replayBundleUrl()) {
      networkPaths.push(path);
      throw new Error(`整合测试禁止真实网络请求：${path}`);
    }
    expect(init).toMatchObject(strictGet);
    expect(init?.body).toBeUndefined();
    return manifestResponse ? manifestResponse() : response();
  });
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState(null, "", "#overview");
});

afterEach(async () => {
  await act(async () => { for (const root of roots) root.unmount(); });
  roots.clear();
  document.body.innerHTML = "";
  window.history.replaceState(null, "", "#overview");
  if (previousActEnvironment === undefined) delete actEnvironment.IS_REACT_ACT_ENVIRONMENT;
  else actEnvironment.IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;
  vi.unstubAllGlobals();
  expect(networkPaths, "即使生产代码捕获网络异常，也不允许漏报 live 请求").toEqual([]);
  expect(createHash("sha256").update(readFileSync(exportPath)).digest("hex"), "不得改写真实导出正文以迁就前端契约").toBe(diskHash);
});

async function storyJobs() {
  const bundle = getBundle();
  const client = createReplayClient(bundle);
  const jobs = await Promise.all([bundle.story.reference_job_id, bundle.story.candidate_job_id, bundle.story.recovery_job_id].map((id) => client.getJob(id)));
  return { bundle, client, normal: jobs[0]!, fault: jobs[1]!, restore: jobs[2]! };
}

async function checkSlices<T>(page: Page<T>, read: (limit: number, offset: number) => Promise<Page<T>>) {
  expect(page).toMatchObject({ offset: 0, limit: 100, total: page.items.length });
  expect(page.items.length).toBeGreaterThan(0);
  expect(page.items.length).toBeLessThanOrEqual(100);
  const rebuilt: T[] = [];
  for (let offset = 0; offset < page.total; offset += 2) {
    const slice = await read(2, offset);
    expect(slice).toEqual({ items: page.items.slice(offset, offset + 2), total: page.total, limit: 2, offset });
    rebuilt.push(...slice.items);
  }
  expect(rebuilt).toEqual(page.items);
  expect(await read(2, page.total)).toEqual({ items: [], total: page.total, limit: 2, offset: page.total });
}

function assertNoPrivateFields(value: unknown, path = "$", insideEvidence = false): void {
  if (Array.isArray(value)) { value.forEach((item, index) => assertNoPrivateFields(item, `${path}[${index}]`, insideEvidence)); return; }
  if (value === null || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    expect(key, path).not.toMatch(/query|locator|raw.?payload|token|authorization|credential|local.?path/i);
    if (!insideEvidence) expect(key, path).not.toMatch(/^(text|body|content|payload)$/i);
    assertNoPrivateFields(child, `${path}.${key}`, insideEvidence || path === "$.resources" && key === "evidence");
  }
}

async function mount(hash: string) {
  window.history.replaceState(null, "", hash);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.add(root);
  await act(async () => { root.render(createElement(App)); });
  return container;
}

// loadReplayBundle 读取 Response stream 后才 ready；不把 pending manifest Promise 当作已完成。
async function waitDom(check: () => void): Promise<void> {
  const deadline = Date.now() + 2500;
  let lastError: unknown;
  // 顺序等待每个 act 完成；vi.waitFor(async callback) 在超时边界会留下重叠的 act。
  do {
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    try { check(); return; } catch (error) { lastError = error; }
    await new Promise<void>((resolve) => setTimeout(resolve, 10));
  } while (Date.now() < deadline);
  throw lastError;
}
async function interact(action: () => void): Promise<void> {
  await act(async () => { action(); await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
}
async function setHash(hash: string): Promise<void> {
  await interact(() => { window.history.replaceState(null, "", hash); window.dispatchEvent(new HashChangeEvent("hashchange")); });
}
function button(container: HTMLElement, label: string): HTMLButtonElement {
  const found = Array.from(container.querySelectorAll("button")).find((item) => item.textContent?.trim() === label);
  expect(found, `找不到按钮：${label}`).toBeTruthy();
  return found!;
}
function link(container: HTMLElement, href: string): HTMLAnchorElement {
  const found = Array.from(container.querySelectorAll<HTMLAnchorElement>("a[href]")).find((item) => item.getAttribute("href") === href);
  expect(found, `找不到真实资源 hash anchor：${href}`).toBeTruthy();
  return found!;
}
function assertReadonly(container: HTMLElement) {
  expect(container.querySelector("main header")?.textContent).toContain("静态回放 · 非实时 / 仅合成公开语料");
  expect(Array.from(container.querySelectorAll("button")).some((item) => /观察新任务|停止观察/.test(item.textContent ?? ""))).toBe(false);
  expect(container.querySelector("main form, main textarea, main input[type='submit']")).toBeNull();
  expect(fetchMock).toHaveBeenCalledTimes(1);
}
function metricRow(container: HTMLElement, label: string): string[] {
  const row = Array.from(container.querySelectorAll("tbody tr")).find((item) => item.querySelector("td div")?.textContent === label);
  expect(row, `找不到真实指标行：${label}`).toBeTruthy();
  return Array.from(row!.querySelectorAll("td")).slice(1).map((item) => item.textContent ?? "");
}

describe("真实 web/public/replay.json：严格契约与离线 client", () => {
  // 仅独立定位契约阻塞；这里的原始解析绝不用于创建 runtime/client 或替代 getBundle。
  it.each([
    ["jobs", "GetJobResponse"], ["revisions", "GetRevisionResponse"],
    ["documents", "GetDocumentResponse"], ["lineages", "GetLineageResponse"],
    ["units", "GetUnitResponse"], ["evidence", "GetEvidenceResponse"],
    ["diffs", "GetDocumentDiffResponse"],
  ] as const)("分资源诊断：真实 %s 必须通过 %s（不改 fixture）", (collection, schema) => {
    const raw = JSON.parse(exportedText) as ReplayBundle;
    expect(raw.resources[collection].length).toBeGreaterThan(0);
    const rejected: string[] = [];
    raw.resources[collection].forEach((item, index) => {
      try { expect(validateManagementResponse(schema, item)).toEqual(item); }
      catch (error) {
        const id = "id" in item ? item.id : "unit_id" in item ? item.unit_id : `${item.new_document_id} ← ${item.old_document_id}`;
        const navigation = "navigation" in item ? ` navigation=${JSON.stringify(item.navigation)}` : "";
        rejected.push(`resources.${collection}[${index}] id=${id}${navigation} error=${String(error)}`);
      }
    });
    expect(rejected, rejected.join("\n")).toEqual([]);
  });

  it("未修改导出文件即可通过 validateReplayBundle 和有界静态 GET 加载", async () => {
    const bundle = getBundle(); // 失败就是 export/frontend contract blocker，绝不期望 invalid_response 为成功。
    expect(bundle).toEqual(JSON.parse(exportedText));
    expect(Number.isNaN(Date.parse(bundle.generated_at))).toBe(false);
    expect(await loadReplayBundle()).toEqual(bundle);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(replayBundleUrl());
    assertNoPrivateFields(bundle);
  });

  it("真实故事是 passed→failed→passed、8 checks、同 config/dataset，并保留 as-of 报告事实", async () => {
    const { bundle, client, normal, fault, restore } = await storyJobs();
    expect([normal.status, fault.status, restore.status]).toEqual(["passed", "failed", "passed"]);
    expect([normal.error_code, fault.error_code, restore.error_code]).toEqual([null, "QUALITY_GATE_FAILED", null]);
    expect([normal.report?.passed, fault.report?.passed, restore.report?.passed]).toEqual([true, false, true]);
    expect([normal.report?.metrics.mean_recall, fault.report?.metrics.mean_recall, restore.report?.metrics.mean_recall]).toEqual([1, 2 / 3, 1]);
    expect(new Set([normal, fault, restore].map((job) => job.knowledge_fingerprint)).size).toBe(3);
    const timestamps = [normal, fault, restore].map((job) => Date.parse(job.evaluated_at));
    expect(timestamps[0]).toBeLessThan(timestamps[1]!);
    expect(timestamps[1]).toBeLessThan(timestamps[2]!);
    for (const job of [normal, fault, restore]) {
      for (const key of ["config_generation", "config_fingerprint", "dataset_id", "dataset_version", "dataset_hash"] as const) expect(job[key]).toBe(normal[key]);
      expect(job.report?.checks.map((check) => check.name).sort()).toEqual(checkNames);
      expect(job.report).toMatchObject({ citation_coverage: 1, stale_hits: 0, degraded: false, metrics: { case_count: 4, answerable_count: 3, no_answer_count: 1, no_answer_accuracy: 1 } });
      expect(job.report?.checks.find((check) => check.name === "recall_at_k")).toMatchObject({ actual: job.report?.metrics.mean_recall, passed: job.status === "passed", threshold: ">=0.8" });
      expect(job.report?.checks.find((check) => check.name === "retrieval_evidence_citation_coverage")).toMatchObject({ actual: 1, passed: true });
      expect(job.report?.checks.find((check) => check.name === "stale_or_retired_hits")).toMatchObject({ actual: 0, passed: true });
      expect(job.trigger_revision_ids.length).toBeGreaterThan(0);
      expect(Date.parse(job.finished_at!)).toBeLessThanOrEqual(Date.parse(bundle.generated_at));
      for (const id of job.trigger_revision_ids) expect(Date.parse((await client.getRevision(id)).created_at)).toBeLessThanOrEqual(Date.parse(job.evaluated_at));
    }
    // 持久化历史 unit 已 superseded，不可据此改写历史报告 stale_hits / 当时的 passed。
    expect(bundle.resources.units.some((unit) => unit.status === "superseded")).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each(["normal→fault", "fault→restore"] as const)("strict compare engine 支持真实 %s，不降级 gate", async (stage) => {
    const { normal, fault, restore } = await storyJobs();
    const first = stage === "normal→fault";
    const comparison = compareJobs(first ? normal : fault, first ? fault : restore);
    expect(comparison.comparable, comparison.reasons.join("；")).toBe(true);
    expect(comparison.reasons).toEqual([]);
    expect(comparison.checks).toHaveLength(8);
    expect(comparison.metrics.find((item) => item.key === "mean_recall")).toMatchObject({ reference: first ? 1 : 2 / 3, candidate: first ? 2 / 3 : 1 });
    expect(comparison.metrics.find((item) => item.key === "mean_recall")?.delta).toBeCloseTo(first ? -1 / 3 : 1 / 3);
    expect(comparison.metrics.find((item) => item.key === "citation_coverage")).toMatchObject({ reference: 1, candidate: 1, delta: 0 });
    expect(comparison.metrics.find((item) => item.key === "stale_hits")).toMatchObject({ reference: 0, candidate: 0, delta: 0 });
    expect(comparison.warnings.join("；")).toContain("不能自动归因");
  });

  it("全部 job/revision 导航 ID 与当前/前版 hash 锚点可通过真实 client 解析", async () => {
    const bundle = getBundle();
    const client = createReplayClient(bundle);
    expect(await client.listJobs({ limit: 100, offset: 0 })).toEqual({ items: bundle.resources.jobs, total: bundle.resources.jobs.length, limit: 100, offset: 0 });
    for (const job of bundle.resources.jobs) expect(await client.getJob(job.id)).toEqual(job);
    for (const expected of bundle.resources.revisions) {
      const revision = await client.getRevision(expected.id);
      expect(revision).toEqual(expected);
      const nav = revision.navigation;
      if (nav.document_id) expect((await client.getDocument(nav.document_id)).checksum).toBe(nav.document_checksum);
      if (nav.unit_id) expect((await client.getUnit(nav.unit_id)).content_hash).toBe(nav.content_hash);
      if (nav.previous_unit_id) expect((await client.getUnit(nav.previous_unit_id)).content_hash).toBe(nav.previous_content_hash);
      if (nav.document_id && nav.previous_document_id) expect(await client.getDocumentDiff(nav.document_id, nav.previous_document_id)).toMatchObject({ new_document_id: nav.document_id, old_document_id: nav.previous_document_id });
      for (const id of revision.affected_document_ids) expect((await client.getDocument(id)).id).toBe(id);
      for (const id of revision.affected_unit_ids) expect((await client.getEvidence(id)).unit_id).toBe(id);
      for (const id of revision.affected_lineage_ids) expect((await client.getLineage(id)).id).toBe(id);
    }
  });

  it("全部 document.units 与 lineage.versions 使用 actual B1 items，完整 GET 与分页无丢失", async () => {
    const bundle = getBundle();
    const client = createReplayClient(bundle);
    for (const document of bundle.resources.documents) {
      expect(await client.getDocument(document.id, { limit: 100, offset: 0 })).toEqual(document);
      await checkSlices(document.units, async (limit, offset) => (await client.getDocument(document.id, { limit, offset })).units);
      for (const unit of document.units.items) expect(await client.getUnit(unit.id)).toEqual(unit);
      if (document.previous_document_id) expect((await client.getDocument(document.previous_document_id)).next_document_id).toBe(document.id);
      if (document.next_document_id) expect((await client.getDocument(document.next_document_id)).previous_document_id).toBe(document.id);
    }
    for (const lineage of bundle.resources.lineages) {
      expect(await client.getLineage(lineage.id, { limit: 100, offset: 0 })).toEqual(lineage);
      await checkSlices(lineage.versions, async (limit, offset) => (await client.getLineage(lineage.id, { limit, offset })).versions);
      for (const unit of lineage.versions.items) expect(await client.getUnit(unit.id)).toEqual(unit);
    }
  });

  it("真实全部 16 diff（含 self/reverse）完整 offset=0 limit=100，计数与 old/new unit 可导航", async () => {
    const bundle = getBundle();
    const client = createReplayClient(bundle);
    expect(bundle.resources.diffs).toHaveLength(16);
    for (const diff of bundle.resources.diffs) {
      expect(await client.getDocumentDiff(diff.new_document_id, diff.old_document_id, { limit: 100, offset: 0 })).toEqual(diff);
      await checkSlices(diff.changes, async (limit, offset) => (await client.getDocumentDiff(diff.new_document_id, diff.old_document_id, { limit, offset })).changes);
      expect(Object.values(diff.counts).reduce((sum, count) => sum + count, 0)).toBe(diff.changes.total);
      for (const [kind, count] of Object.entries(diff.counts)) expect(diff.changes.items.filter((item) => item.kind === kind)).toHaveLength(count);
      for (const change of diff.changes.items) {
        expect((await client.getLineage(change.lineage_id)).id).toBe(change.lineage_id);
        for (const [unit, documentId] of [[change.old, diff.old_document_id], [change.new, diff.new_document_id]] as const) {
          if (!unit) continue;
          expect(await client.getUnit(unit.id)).toEqual(unit);
          expect(await client.getEvidence(unit.id)).toMatchObject({ document_id: documentId, lineage_id: change.lineage_id, content_hash: unit.content_hash });
        }
      }
    }
  });

  it("全部 exact unit evidence 正文、code point 范围、SHA256 和 revision 锚点保真，资源 links 仅本地 GET", async () => {
    const bundle = getBundle();
    const client = createReplayClient(bundle);
    const replayFetcher = createReplayFetcher(bundle);
    for (const expected of bundle.resources.evidence) {
      const evidence = await client.getEvidence(expected.unit_id);
      expect(evidence).toEqual(expected);
      const unit = await client.getUnit(evidence.unit_id);
      expect(evidence).toMatchObject({ document_id: unit.document_id, lineage_id: unit.lineage_id, start_char: unit.start_char, end_char: unit.end_char, content_hash: unit.content_hash });
      expect(Array.from(evidence.text)).toHaveLength(evidence.end_char - evidence.start_char);
      expect(createHash("sha256").update(evidence.text, "utf8").digest("hex")).toBe(evidence.content_hash);
      expect((await client.getDocument(evidence.document_id)).checksum).toBe(evidence.document_checksum);
      expect(evidence.revision_ids.length).toBeGreaterThan(0);
      for (const id of evidence.revision_ids) expect((await client.getRevision(id)).affected_unit_ids).toContain(evidence.unit_id);
    }
    const links: ResourceLink[] = [...bundle.resources.jobs, ...bundle.resources.revisions, ...bundle.resources.documents, ...bundle.resources.units, ...bundle.resources.evidence, ...bundle.resources.diffs].flatMap((item) => [...item.links]);
    expect(links.length).toBeGreaterThan(0);
    for (const item of links) {
      const canonical = item.kind === "evidence" ? `/v1/management/units/${item.id}/evidence` : `/v1/management/${item.kind}s/${item.id}`;
      expect(item.href).toBe(canonical);
      const result = await replayFetcher(item.href, strictGet);
      expect(result.status).toBe(200);
      const resource = await result.json() as { id?: string; unit_id?: string };
      expect(item.kind === "evidence" ? resource.unit_id : resource.id).toBe(item.id);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("离线 replayFetcher 只读，不接受 mutation/凭证/额外参数，也不转发 live API", async () => {
    const bundle = getBundle();
    const replayFetcher = createReplayFetcher(bundle);
    const path = `/v1/management/jobs/${bundle.story.reference_job_id}`;
    const requests: Array<[string, RequestInit, number]> = [
      ...["POST", "PUT", "PATCH", "DELETE"].map((method): [string, RequestInit, number] => [path, { ...strictGet, method }, 400]),
      [path, { ...strictGet, body: "{}" }, 400],
      [path, { ...strictGet, credentials: "include" }, 400],
      [path, { ...strictGet, redirect: "follow" }, 400],
      [`${path}?query=not-exported`, strictGet, 400],
      ["/v1/management/jobs?status=passed&status=failed", strictGet, 400],
      ["/v1/management/commands", strictGet, 404],
      ["/v1/retrieve", strictGet, 404],
    ];
    for (const [input, init, status] of requests) expect((await replayFetcher(input, init)).status).toBe(status);
    const calls: RequestInit[] = [];
    const client = new ManagementClient(async (input, init) => { calls.push(init); return replayFetcher(input, init); });
    await client.getJob(bundle.story.reference_job_id);
    expect(calls).toEqual([expect.objectContaining(strictGet)]);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("真实 App + ManagementRuntimeProvider：静态回放 DOM", () => {
  it("等待 pending replay.json 后才显示真实三阶段 guide；只读、非实时且两个比较链接可用", async () => {
    let release!: (value: Response) => void;
    const pendingManifest = new Promise<Response>((resolve) => { release = resolve; });
    manifestResponse = () => pendingManifest;
    const container = await mount("#replay/guide");
    expect(container.textContent).toContain("正在加载静态回放数据");
    expect(container.textContent).not.toContain("三阶段满足回放故事条件");
    await act(async () => { release(response()); await pendingManifest; });
    await waitDom(() => expect(container.textContent).toContain("三阶段满足回放故事条件"));
    const { normal, fault, restore } = await storyJobs();
    assertReadonly(container);
    for (const [label, job] of [["正常阶段", normal], ["故障阶段", fault], ["恢复阶段", restore]] as const) {
      const card = Array.from(container.querySelectorAll("details article")).find((item) => item.querySelector("h3")?.textContent === label);
      expect(card?.textContent).toContain(job.id);
      expect(card?.textContent).toContain(job.status === "failed" ? "失败" : "通过");
      expect(card?.textContent).toContain(formatFull(job.evaluated_at));
      link(container, lifecycleJobHash(job.id, mode));
      for (const id of job.trigger_revision_ids) link(container, lifecycleRevisionHash(id, mode));
    }
    link(container, evaluationHash({ reference: normal.id, candidate: fault.id, ...mode }));
    link(container, evaluationHash({ reference: fault.id, candidate: restore.id, ...mode }));
    expect(container.textContent).toContain("不能声明因果");
    await interact(() => button(container, "刷新").click());
    await waitDom(() => expect(container.textContent).toContain("三阶段满足回放故事条件"));
    assertReadonly(container);
  });

  it.each(["默认 normal→fault", "显式 fault→restore"] as const)("真实 evaluation：%s 显示 Recall delta 和全部 8 项原始 checks", async (stage) => {
    const first = stage === "默认 normal→fault";
    // 路由借用真实 story ID，Provider 仍必须自行载入并验证完整磁盘响应。
    const raw = JSON.parse(exportedText) as ReplayBundle;
    const container = await mount(first ? "#replay/evaluation" : evaluationHash({ reference: raw.story.candidate_job_id, candidate: raw.story.recovery_job_id, ...mode }));
    await waitDom(() => expect(container.querySelector("#main-results-title")?.textContent).toBe("核心结果"));
    const { normal, fault, restore } = await storyJobs();
    const reference = first ? normal : fault;
    const candidate = first ? fault : restore;
    assertReadonly(container);
    expect(container.textContent).not.toContain("本组任务暂不输出 delta");
    link(container, lifecycleJobHash(reference.id, mode));
    link(container, lifecycleJobHash(candidate.id, mode));
    const comparison = compareJobs(reference, candidate);
    for (const key of ["mean_recall", "citation_coverage", "stale_hits"]) {
      const metric = comparison.metrics.find((item) => item.key === key)!;
      expect(metricRow(container, metric.label)).toEqual([formatMetricValue(metric.reference, metric.unit), formatMetricValue(metric.candidate, metric.unit), formatMetricDelta(metric.delta, metric.unit)]);
    }
    const checkTable = Array.from(container.querySelectorAll("table")).find((item) => item.querySelector("th")?.textContent === "检查项");
    expect(checkTable?.querySelectorAll("tbody tr")).toHaveLength(8);
    for (const check of reference.report!.checks) {
      const other = candidate.report!.checks.find((item) => item.name === check.name)!;
      const row = Array.from(checkTable!.querySelectorAll("tbody tr")).find((item) => item.querySelector("td")?.textContent === CHECK_LABELS[check.name]);
      expect(Array.from(row!.querySelectorAll("td")).slice(1).map((item) => item.textContent)).toEqual([`${check.passed ? "通过" : "未通过"} / actual ${check.actual}`, `${other.passed ? "通过" : "未通过"} / actual ${other.actual}`, `${check.threshold} / ${other.threshold}`]);
    }
    // 真实资源只有 3 个 job，不能靠添加假任务启用下一页。
    expect(button(container, "下一页").disabled).toBe(true);
    await setHash(evaluationHash({ reference: reference.id, candidate: candidate.id, offset: 20, ...mode }));
    await waitDom(() => expect(container.textContent).toContain("回放 bundle 当前页没有可选任务"));
    await interact(() => button(container, "上一页").click());
    await waitDom(() => expect(window.location.hash).toBe(evaluationHash({ reference: reference.id, candidate: candidate.id, ...mode })));
    expect(container.querySelector("section[aria-label='已选任务概览']")?.textContent).toContain(reference.id.slice(0, 8));
    expect(container.querySelector("section[aria-label='已选任务概览']")?.textContent).toContain(candidate.id.slice(0, 8));
    assertReadonly(container);
  });

  it("主导航、真实状态 filter 与空页返回均保留 replay，不请求 live 或重载 manifest", async () => {
    const container = await mount("#replay/evaluation");
    await waitDom(() => expect(container.querySelector("#main-results-title")).toBeTruthy());
    const { fault } = await storyJobs();
    const nav = container.querySelector<HTMLElement>("nav[aria-label='主导航']")!;
    const navButton = (label: string) => {
      const found = Array.from(nav.querySelectorAll("button")).find((item) => item.querySelector("span span")?.textContent === label);
      expect(found).toBeTruthy();
      return found!;
    };
    await interact(() => navButton("生命周期工作台").click());
    await waitDom(() => expect(container.querySelector("select[aria-label='按状态过滤任务']")).toBeTruthy());
    expect(window.location.hash).toBe("#replay/lifecycle/jobs");
    const filter = container.querySelector<HTMLSelectElement>("select[aria-label='按状态过滤任务']")!;
    await interact(() => { filter.value = "failed"; filter.dispatchEvent(new Event("change", { bubbles: true })); });
    await waitDom(() => expect(window.location.hash).toBe("#replay/lifecycle/jobs?status=failed"));
    await waitDom(() => expect(container.querySelector("ol[aria-label='任务时间线']")?.textContent).toContain(fault.id));
    expect(container.querySelectorAll("ol[aria-label='任务时间线'] > li")).toHaveLength(1);
    link(container, lifecycleJobHash(fault.id, mode));
    await setHash("#replay/lifecycle/jobs?status=failed&offset=20");
    await waitDom(() => expect(button(container, "上一页").disabled).toBe(false));
    await interact(() => button(container, "上一页").click());
    await waitDom(() => expect(window.location.hash).toBe("#replay/lifecycle/jobs?status=failed"));
    await interact(() => navButton("使用导览").click());
    await waitDom(() => expect(container.textContent).toContain("三阶段满足回放故事条件"));
    expect(window.location.hash).toBe("#replay/guide");
    await interact(() => navButton("评测对照").click());
    await waitDom(() => expect(container.querySelector("#main-results-title")).toBeTruthy());
    expect(window.location.hash).toBe("#replay/evaluation");
    assertReadonly(container);
  });

  it("真实 job→revision→diff→evidence→lineage/document anchors 连通，历史正文/hash 不被实时状态覆盖", async () => {
    const container = await mount("#replay/evaluation");
    await waitDom(() => expect(container.querySelector("#main-results-title")).toBeTruthy());
    const { bundle, fault } = await storyJobs();
    const revision = bundle.resources.revisions.find((item) => fault.trigger_revision_ids.includes(item.id) && item.navigation.document_id && item.navigation.previous_document_id)!;
    expect(revision).toBeTruthy();
    const diff = bundle.resources.diffs.find((item) => item.new_document_id === revision.navigation.document_id && item.old_document_id === revision.navigation.previous_document_id)!;
    const unit = diff.changes.items.find((item) => item.new && item.old)?.new;
    expect(unit).toBeTruthy();
    const evidence = bundle.resources.evidence.find((item) => item.unit_id === unit!.id)!;
    await interact(() => link(container, lifecycleJobHash(fault.id, mode)).click());
    await waitDom(() => link(container, lifecycleRevisionHash(revision.id, mode)));
    await interact(() => link(container, lifecycleRevisionHash(revision.id, mode)).click());
    const diffHash = lifecycleDiffHash(diff.new_document_id, diff.old_document_id, 0, mode);
    await waitDom(() => link(container, diffHash));
    expect(container.textContent).toContain(revision.navigation.document_checksum);
    await interact(() => link(container, diffHash).click());
    await waitDom(() => link(container, lifecycleEvidenceHash(evidence.unit_id, mode)));
    await interact(() => link(container, lifecycleEvidenceHash(evidence.unit_id, mode)).click());
    await waitDom(() => expect(container.querySelector("pre")?.textContent).toBe(evidence.text));
    expect(container.textContent).toContain(evidence.content_hash);
    expect(container.textContent).toContain(evidence.document_checksum);
    expect(container.textContent).toContain(`[${evidence.start_char}, ${evidence.end_char})`);
    for (const id of evidence.revision_ids) link(container, lifecycleRevisionHash(id, mode));
    await interact(() => link(container, lifecycleLineageHash(evidence.lineage_id, 0, mode)).click());
    await waitDom(() => link(container, lifecycleDocumentHash(evidence.document_id, 0, mode)));
    await interact(() => link(container, lifecycleDocumentHash(evidence.document_id, 0, mode)).click());
    await waitDom(() => expect(container.textContent).toContain(evidence.document_checksum));
    expect(window.location.hash).toBe(lifecycleDocumentHash(evidence.document_id, 0, mode));
    assertReadonly(container);
  });

  it.each(["#replay/changes", "#replay/changes?document", "#replay/changes?command"])("%s 不能开启 write，不回显原 hash，不发请求", async (prefix) => {
    // 非法路由必须在载入 bundle 前拒绝；只借用磁盘真实 ID，不绕过成功页面的校验门槛。
    const raw = JSON.parse(exportedText) as ReplayBundle;
    const hash = prefix.includes("?") ? `${prefix}=${raw.resources.documents[0]!.id}` : prefix;
    expect(parseHashRoute(hash)).toMatchObject({ view: "lifecycle", kind: "invalid", mode: "replay" });
    const container = await mount(hash);
    await waitDom(() => expect(container.textContent).toContain("不发起任何管理请求"));
    expect(container.querySelector("main")?.textContent).not.toContain(hash);
    expect(container.querySelector("main form, main textarea, main input")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
