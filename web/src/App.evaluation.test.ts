// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const clientMocks = vi.hoisted(() => ({
  managementClient: {
    listJobs: vi.fn(),
    getJob: vi.fn(),
    getRevision: vi.fn(),
    getDocument: vi.fn(),
    getLineage: vi.fn(),
    getDocumentDiff: vi.fn(),
    getUnit: vi.fn(),
    getEvidence: vi.fn(),
  },
}));

vi.mock("./management/client", async () => {
  const actual = await vi.importActual<typeof import("./management/client")>("./management/client");
  return { ...actual, managementClient: clientMocks.managementClient };
});

import App from "./App";
import { makeReplayBundle, replayIds } from "./management/replayTestUtils";
import { ManagementError, type JobDTO, type Page, type SafeCheck } from "./management/types";

const actEnvironment = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean };
const previousFetch = globalThis.fetch;
const previousActEnvironment = actEnvironment.IS_REACT_ACT_ENVIRONMENT;
const roots = new Set<Root>();

beforeAll(() => { actEnvironment.IS_REACT_ACT_ENVIRONMENT = true; });
afterAll(() => {
  if (previousActEnvironment === undefined) delete actEnvironment.IS_REACT_ACT_ENVIRONMENT;
  else actEnvironment.IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;
});
beforeEach(() => { window.history.replaceState(null, "", "#overview"); });
afterEach(async () => {
  await act(async () => { for (const root of roots) root.unmount(); });
  roots.clear();
  document.body.innerHTML = "";
  window.history.replaceState(null, "", "#overview");
  globalThis.fetch = previousFetch;
  vi.useRealTimers();
  vi.resetAllMocks();
});

const ids = {
  normal: "11111111-1111-1111-1111-111111111111",
  fault: "22222222-2222-2222-2222-222222222222",
  restore: "33333333-3333-3333-3333-333333333333",
  newJob: "44444444-4444-4444-4444-444444444444",
  revA: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  revB: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
};
const dataset = "99999999-9999-9999-9999-999999999999";
const baseDate = "2026-11-13T10:00:00+00:00";
const hash = (seed: string): string => seed.repeat(64);

type JobReport = NonNullable<JobDTO["report"]>;

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

function makeReport(passed: boolean, overrides: Partial<Omit<JobReport, "metrics" | "checks">> & { readonly checks?: readonly SafeCheck[] } = {}): JobReport {
  return {
    passed,
    metrics: {
      case_count: 4,
      answerable_count: 3,
      no_answer_count: 1,
      mean_recall: passed ? 0.9 : 0.7,
      mean_precision: passed ? 0.8 : 0.6,
      mean_reciprocal_rank: passed ? 0.9 : 0.5,
      mean_ndcg: passed ? 0.85 : 0.55,
      hit_rate: passed ? 1 : 0.75,
      no_answer_accuracy: passed ? 1 : 0,
    },
    citation_coverage: passed ? 1 : 0.5,
    stale_hits: passed ? 0 : 1,
    degraded: false,
    checks: overrides.checks ?? makeChecks(passed ? {} : {
      recall_at_k: { passed: false, actual: 0.7 },
      mean_reciprocal_rank: { passed: false, actual: 0.5 },
      no_answer_accuracy: { passed: false, actual: 0 },
      retrieval_evidence_citation_coverage: { passed: false, actual: 0.5 },
      stale_or_retired_hits: { passed: false, actual: 1 },
    }),
    ...overrides,
  };
}

function job(id: string, status: JobDTO["status"], evaluated_at: string, knowledge_fingerprint: string, trigger_revision_ids: readonly string[] = [], reportOverride?: JobDTO["report"]): JobDTO {
  const terminal = status === "passed" || status === "failed";
  const passed = status === "passed";
  return {
    id,
    parent_job_id: null,
    status,
    config_generation: 1,
    config_fingerprint: hash("a"),
    dataset_id: dataset,
    dataset_version: 7,
    dataset_hash: hash("b"),
    knowledge_fingerprint,
    created_at: evaluated_at,
    evaluated_at,
    started_at: evaluated_at,
    finished_at: evaluated_at,
    attempt_count: 1,
    error_code: status === "failed" ? "QUALITY_GATE_FAILED" : null,
    report: reportOverride === undefined ? (terminal ? makeReport(passed) : null) : reportOverride,
    trigger_revision_ids,
    links: [],
  };
}

const normalJob = job(ids.normal, "passed", baseDate, hash("c"), [ids.revA]);
const faultJob = job(ids.fault, "failed", "2026-11-13T10:10:00+00:00", hash("d"), [ids.revA]);
const restoreJob = job(ids.restore, "passed", "2026-11-13T10:20:00+00:00", hash("e"), [ids.revB]);
const newJob = job(ids.newJob, "passed", "2026-11-13T10:30:00+00:00", hash("f"));
const page: Page<JobDTO> = { items: [normalJob, faultJob, restoreJob], total: 41, limit: 20, offset: 0 };
const pageWithNewHead: Page<JobDTO> = { ...page, items: [newJob, normalJob, faultJob] };

function setupDom(): { container: HTMLDivElement; root: Root } {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.add(root);
  return { container, root };
}
async function renderApp(root: Root): Promise<void> { await act(async () => { root.render(createElement(App)); }); }
async function setHash(hashValue: string): Promise<void> {
  if (window.location.hash === hashValue) return;
  await act(async () => {
    const changed = new Promise<void>((resolve) => { window.addEventListener("hashchange", () => resolve(), { once: true }); });
    window.location.hash = hashValue;
    await changed;
  });
}
async function tick(action: () => void = () => {}): Promise<void> { await act(async () => { action(); await Promise.resolve(); }); }
async function advance(ms: number): Promise<void> { await act(async () => { vi.advanceTimersByTime(ms); await Promise.resolve(); }); }
function button(container: HTMLElement, label: string): HTMLButtonElement {
  const match = Array.from(container.querySelectorAll("button")).find((item) => item.textContent?.trim() === label);
  expect(match).toBeTruthy();
  return match!;
}
function selectedOverview(container: HTMLElement): string {
  return container.querySelector("section[aria-label='已选任务概览']")?.textContent ?? "";
}
function mockGetJobFromMap(map: ReadonlyMap<string, JobDTO>): void {
  clientMocks.managementClient.getJob.mockImplementation((id: string) => Promise.resolve(map.get(id)!));
}

function mockReplayFetch(bundle = makeReplayBundle()) {
  const fetchMock = vi.fn<typeof globalThis.fetch>(async () =>
    new Response(JSON.stringify(bundle), { status: 200, headers: { "content-type": "application/json" } }),
  );
  globalThis.fetch = fetchMock;
  return fetchMock;
}

class Deferred<T> {
  readonly promise: Promise<T>;
  private resolveValue!: (value: T) => void;
  constructor() { this.promise = new Promise<T>((resolve) => { this.resolveValue = resolve; }); }
  resolve(value: T) { this.resolveValue(value); }
}

describe("App evaluation and guide views", () => {
  it("selects a pair, preserves selection across pagination, renders main results and revision links", async () => {
    clientMocks.managementClient.listJobs.mockResolvedValue(page);
    mockGetJobFromMap(new Map([[ids.normal, normalJob], [ids.fault, faultJob]]));
    const { container, root } = setupDom();
    await setHash("#evaluation");
    await renderApp(root);

    await tick(() => button(container, "选为参考任务").click());
    const candidateButtons = Array.from(container.querySelectorAll("button")).filter((item) => item.textContent === "选为候选任务");
    await act(async () => { candidateButtons[1]!.click(); await Promise.resolve(); });
    await tick();

    expect(window.location.hash).toContain(`reference=${ids.normal}`);
    expect(window.location.hash).toContain(`candidate=${ids.fault}`);
    expect(container.querySelector("#main-results-title")?.textContent).toBe("核心结果");
    expect(container.textContent).toContain("平均 Recall");
    expect(container.textContent).toContain("MRR");
    expect(container.textContent).toContain("No-answer Accuracy");
    expect(container.textContent).toContain("Citation Coverage");
    expect(container.textContent).toContain("stale hits");
    expect(container.textContent).toContain("个百分点");
    expect(container.querySelector(`a[href='#lifecycle/revisions/${ids.revA}']`)).toBeTruthy();

    await act(async () => { button(container, "下一页").click(); });
    expect(window.location.hash).toContain("offset=20");
    expect(window.location.hash).toContain(`reference=${ids.normal}`);
  });

  it("shows manual refresh error and recovers without sample data", async () => {
    clientMocks.managementClient.listJobs.mockRejectedValueOnce(new ManagementError("unavailable", { status: 503 })).mockResolvedValueOnce(page);
    const { container, root } = setupDom();
    await setHash("#evaluation");
    await renderApp(root);
    expect(container.textContent).toContain("不会改用示例数据");
    await tick(() => button(container, "重试").click());
    expect(container.textContent).toContain("评测对照");
    expect(clientMocks.managementClient.listJobs).toHaveBeenCalledTimes(2);
  });

  it("blocks illegal evaluation query without echoing the raw hash or fetching", async () => {
    const { container, root } = setupDom();
    await setHash("#evaluation?reference=not-a-uuid&token=secret");
    await renderApp(root);
    expect(container.textContent).toContain("评测对照链接无效");
    expect(container.textContent).not.toContain("secret");
    expect(clientMocks.managementClient.listJobs).not.toHaveBeenCalled();
  });

  it("manual refresh detects new tasks but keeps the chosen pair", async () => {
    clientMocks.managementClient.listJobs.mockResolvedValueOnce(page).mockResolvedValueOnce(pageWithNewHead);
    mockGetJobFromMap(new Map([[ids.normal, normalJob], [ids.fault, faultJob]]));
    const { container, root } = setupDom();
    await setHash(`#evaluation?reference=${ids.normal}&candidate=${ids.fault}`);
    await renderApp(root);
    expect(selectedOverview(container)).toContain(ids.normal.slice(0, 8));
    expect(selectedOverview(container)).toContain(ids.fault.slice(0, 8));

    await tick(() => button(container, "刷新").click());

    expect(container.textContent).toContain("检测到任务列表头部有新变化");
    expect(window.location.hash).toContain(`reference=${ids.normal}`);
    expect(window.location.hash).toContain(`candidate=${ids.fault}`);
    expect(selectedOverview(container)).not.toContain(ids.newJob.slice(0, 8));
    expect(clientMocks.managementClient.getJob).toHaveBeenCalledTimes(4);
  });

  it("auto observation detects a new task notice", async () => {
    clientMocks.managementClient.listJobs.mockResolvedValueOnce(page).mockResolvedValueOnce(pageWithNewHead);
    const { container, root } = setupDom();
    await setHash("#evaluation");
    vi.useFakeTimers({ now: 1_000_000 });
    await renderApp(root);
    await tick(() => button(container, "观察新任务（5分钟）").click());

    await advance(10_000);

    expect(clientMocks.managementClient.listJobs).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain("检测到任务列表头部有新变化");
  });

  it("selected running job is refreshed into a report without replacing IDs", async () => {
    const running = job(ids.fault, "running", "2026-11-13T10:10:00+00:00", hash("d"), [ids.revA]);
    clientMocks.managementClient.listJobs.mockResolvedValue(page);
    clientMocks.managementClient.getJob.mockImplementation((id: string) => {
      if (id === ids.normal) return Promise.resolve(normalJob);
      const candidateCalls = clientMocks.managementClient.getJob.mock.calls.filter(([calledId]) => calledId === ids.fault).length;
      return Promise.resolve(candidateCalls <= 1 ? running : faultJob);
    });
    const { container, root } = setupDom();
    await setHash(`#evaluation?reference=${ids.normal}&candidate=${ids.fault}`);
    await renderApp(root);
    expect(container.textContent).toContain("候选任务不是带完整报告的 passed/failed 终态");

    await tick(() => button(container, "刷新").click());

    expect(window.location.hash).toContain(`candidate=${ids.fault}`);
    expect(container.textContent).toContain("Citation Coverage");
    expect(container.textContent).toContain("未通过");
  });

  it("pair error stops observation and retry recovers selected details", async () => {
    clientMocks.managementClient.listJobs.mockResolvedValue(page);
    clientMocks.managementClient.getJob
      .mockResolvedValueOnce(normalJob)
      .mockResolvedValueOnce(faultJob)
      .mockResolvedValueOnce(normalJob)
      .mockRejectedValueOnce(new ManagementError("unavailable", { status: 503 }))
      .mockResolvedValueOnce(normalJob)
      .mockResolvedValueOnce(faultJob);
    const { container, root } = setupDom();
    await setHash(`#evaluation?reference=${ids.normal}&candidate=${ids.fault}`);
    vi.useFakeTimers({ now: 2_000_000 });
    await renderApp(root);
    await tick(() => button(container, "观察新任务（5分钟）").click());

    await advance(10_000);
    await tick();

    expect(container.textContent).toContain("服务读取失败，观察已停止");
    expect(container.textContent).toContain("管理服务暂不可用");
    await tick(() => button(container, "重试").click());
    expect(container.textContent).toContain("核心结果");
  });

  it("does not let an old selected-pair response cover the new route", async () => {
    clientMocks.managementClient.listJobs.mockResolvedValue(page);
    const oldCandidate = new Deferred<JobDTO>();
    clientMocks.managementClient.getJob.mockImplementation((id: string) => {
      if (id === ids.fault) return oldCandidate.promise;
      if (id === ids.restore) return Promise.resolve(restoreJob);
      return Promise.resolve(normalJob);
    });
    const { container, root } = setupDom();
    await setHash(`#evaluation?reference=${ids.normal}&candidate=${ids.fault}`);
    await renderApp(root);
    await setHash(`#evaluation?reference=${ids.normal}&candidate=${ids.restore}`);
    await tick();
    oldCandidate.resolve(faultJob);
    await tick();

    expect(window.location.hash).toContain(`candidate=${ids.restore}`);
    expect(selectedOverview(container)).toContain(ids.restore.slice(0, 8));
    expect(selectedOverview(container)).not.toContain(ids.fault.slice(0, 8));
  });

  it("blocks delta in UI when both sides miss the same required check", async () => {
    const missingChecks = makeChecks().filter((check) => check.name !== "stale_isolation_configuration");
    const badNormal = job(ids.normal, "passed", baseDate, hash("c"), [ids.revA], makeReport(true, { checks: missingChecks }));
    const badFault = job(ids.fault, "failed", "2026-11-13T10:10:00+00:00", hash("d"), [ids.revA], makeReport(false, { checks: missingChecks }));
    clientMocks.managementClient.listJobs.mockResolvedValue(page);
    mockGetJobFromMap(new Map([[ids.normal, badNormal], [ids.fault, badFault]]));
    const { container, root } = setupDom();
    await setHash(`#evaluation?reference=${ids.normal}&candidate=${ids.fault}`);
    await renderApp(root);

    expect(container.textContent).toContain("本组任务暂不输出 delta");
    expect(container.textContent).toContain("缺少必需质量检查 stale_isolation_configuration");
  });

  it("builds a three-stage guide and offers comparison links before task details", async () => {
    clientMocks.managementClient.listJobs.mockResolvedValue(page);
    mockGetJobFromMap(new Map([[ids.normal, normalJob], [ids.fault, faultJob], [ids.restore, restoreJob]]));
    const { container, root } = setupDom();
    await setHash(`#guide?normal=${ids.normal}&fault=${ids.fault}&restore=${ids.restore}`);
    await renderApp(root);

    const judgementIndex = container.textContent?.indexOf("阶段判定") ?? -1;
    const detailsIndex = container.textContent?.indexOf("查看三阶段任务元数据") ?? -1;
    expect(judgementIndex).toBeGreaterThanOrEqual(0);
    expect(detailsIndex).toBeGreaterThan(judgementIndex);
    expect(container.textContent).toContain("已选择的演示阶段条件");
    expect(container.textContent).toContain("在隔离演示库中使用已授权的 CLI 完成更新");
    expect(container.querySelector(`a[href='#evaluation?reference=${ids.normal}&candidate=${ids.fault}']`)).toBeTruthy();
    expect(container.querySelector(`a[href='#evaluation?reference=${ids.fault}&candidate=${ids.restore}']`)).toBeTruthy();
    expect(container.textContent).toContain("no-answer、stale、citation");
  });

  it("loads replay evaluation defaults without live fetch or observer controls, and keeps replay pagination", async () => {
    const fetchMock = mockReplayFetch();
    const { container, root } = setupDom();
    await setHash("#replay/evaluation");
    await renderApp(root);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(clientMocks.managementClient.listJobs).not.toHaveBeenCalled();
    expect(container.textContent).toContain("静态回放 · 非实时 / 仅合成公开语料");
    expect(container.textContent).toContain("模式：静态回放，仅合成公开语料，不会请求 /v1 live API。");
    expect(container.textContent).not.toContain("观察新任务（5分钟）");
    expect(selectedOverview(container)).toContain(replayIds.reference.slice(0, 8));
    expect(selectedOverview(container)).toContain(replayIds.candidate.slice(0, 8));
    expect(container.querySelector(`a[href='#replay/lifecycle/jobs/${replayIds.reference}']`)).toBeTruthy();

    await act(async () => {
      button(container, "下一页").click();
    });

    expect(window.location.hash).toContain("#replay/evaluation?");
    expect(window.location.hash).toContain("offset=20");
    expect(window.location.hash).toContain(`reference=${replayIds.reference}`);
    expect(window.location.hash).toContain(`candidate=${replayIds.candidate}`);

    await tick(() => button(container, "刷新").click());
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("loads replay guide defaults and links the three-stage story with replay-prefixed comparisons", async () => {
    const fetchMock = mockReplayFetch();
    const { container, root } = setupDom();
    await setHash("#replay");
    await renderApp(root);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(clientMocks.managementClient.listJobs).not.toHaveBeenCalled();
    expect(container.textContent).toContain("回放模式使用父流程生成的静态 bundle");
    expect(container.textContent).toContain("三阶段满足回放故事条件");
    expect(container.querySelector(`a[href='#replay/evaluation?reference=${replayIds.reference}&candidate=${replayIds.candidate}']`)).toBeTruthy();
    expect(container.querySelector(`a[href='#replay/evaluation?reference=${replayIds.candidate}&candidate=${replayIds.recovery}']`)).toBeTruthy();
    expect(container.textContent).toContain("回放默认指向 bundle.story.reference_job_id");
  });
});
