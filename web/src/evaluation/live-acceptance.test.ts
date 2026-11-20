// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { spawnSync } from "node:child_process";

import { compareJobs, formatMetricDelta } from "./comparison";
import { EvaluationPage } from "./EvaluationPage";
import { ManagementClient, type ManagementFetcher } from "../management/client";
import type { JobDTO, Page } from "../management/types";

const enabled = process.env.KNOWLEDGE_ACCEPTANCE === "1";
const config = enabled
  ? {
      webOrigin: requireEnv("KNOWLEDGE_ACCEPTANCE_WEB_ORIGIN"),
      repoRoot: requireEnv("KNOWLEDGE_ACCEPTANCE_REPO_ROOT"),
      runRoot: requireEnv("KNOWLEDGE_ACCEPTANCE_RUN_ROOT"),
      seedReport: requireEnv("KNOWLEDGE_ACCEPTANCE_SEED_REPORT"),
      database: requireEnv("KNOWLEDGE_ACCEPTANCE_DATABASE"),
      docCopy: requireEnv("KNOWLEDGE_ACCEPTANCE_DOC_COPY"),
      frontendReport: requireEnv("KNOWLEDGE_ACCEPTANCE_FRONTEND_REPORT"),
      followupAnchor: requireEnv("KNOWLEDGE_ACCEPTANCE_FOLLOWUP_ANCHOR"),
      followupNote: requireEnv("KNOWLEDGE_ACCEPTANCE_FOLLOWUP_NOTE"),
    }
  : null;

const describeIf = enabled ? describe : describe.skip;
const actEnvironment = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean };
const previousActEnvironment = actEnvironment.IS_REACT_ACT_ENVIRONMENT;
const roots = new Set<Root>();
const containers = new Set<HTMLDivElement>();
const originalFetch = globalThis.fetch;

beforeAll(() => {
  actEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
});

afterAll(() => {
  if (previousActEnvironment === undefined) delete actEnvironment.IS_REACT_ACT_ENVIRONMENT;
  else actEnvironment.IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;
  globalThis.fetch = originalFetch;
});

afterEach(async () => {
  await act(async () => {
    for (const root of roots) root.unmount();
  });
  roots.clear();
  for (const container of containers) container.remove();
  containers.clear();
  globalThis.fetch = originalFetch;
});

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`missing env: ${name}`);
  return value;
}

function setupDom(): { container: HTMLDivElement; root: Root } {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.add(root);
  containers.add(container);
  return { container, root };
}

async function flush(action: () => void = () => {}): Promise<void> {
  await act(async () => {
    action();
    await Promise.resolve();
  });
}

async function waitFor(predicate: () => boolean, timeoutMs = 30_000): Promise<void> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (predicate()) return;
    await flush();
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("waitFor timeout");
}

function buttonByText(container: HTMLElement, label: string): HTMLButtonElement {
  const match = Array.from(container.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.trim() === label,
  );
  expect(match).toBeTruthy();
  return match as HTMLButtonElement;
}

function makeOriginFetcher(origin: string): ManagementFetcher {
  if (typeof originalFetch !== "function") throw new Error("fetch unavailable");
  return async (input: string, init: RequestInit) => {
    const absolute = new URL(input, origin).toString();
    return originalFetch(absolute, init);
  };
}

function patchGlobalFetch(origin: string): void {
  const fetcher = makeOriginFetcher(origin);
  globalThis.fetch = (input: string | URL | Request, init?: RequestInit) => {
    if (typeof input === "string") return fetcher(input, init ?? {});
    if (input instanceof URL) return fetcher(input.toString(), init ?? {});
    return fetcher(input.url, init ?? {});
  };
}

function jobById(page: Page<JobDTO>, id: string): JobDTO {
  const match = page.items.find((job) => job.id === id);
  expect(match).toBeDefined();
  return match!;
}

function metricDelta(comparison: ReturnType<typeof compareJobs>, key: string): number {
  const match = comparison.metrics.find((metric) => metric.key === key);
  expect(match).toBeDefined();
  expect(match?.delta).not.toBeNull();
  return match?.delta as number;
}

function assertOwnedPath(rootPath: string, targetPath: string, expectedSuffix: string): void {
  const relative = path.relative(rootPath, targetPath);
  expect(relative).not.toBe("");
  expect(relative.startsWith("..")).toBe(false);
  expect(path.isAbsolute(relative)).toBe(false);
  expect(relative.replace(/\\/g, "/").endsWith(expectedSuffix)).toBe(true);
}

async function renderPage(root: Root, reference: string, candidate: string): Promise<void> {
  await act(async () => {
    root.render(
      createElement(EvaluationPage, {
        route: { view: "evaluation", kind: "compare", reference, candidate, offset: 0, mode: "live" },
        navigate: () => undefined,
      }),
    );
  });
}

async function loadSeedIds(seedReportPath: string): Promise<{
  normal: string;
  fault: string;
  restore: string;
}> {
  const payload = JSON.parse(await readFile(seedReportPath, "utf8")) as {
    steps: Array<{ name: string; job: { id: string } }>;
  };
  const steps = new Map(payload.steps.map((step) => [step.name, step.job.id] as const));
  const normal = steps.get("positive");
  const fault = steps.get("fault");
  const restore = steps.get("restore");
  expect(normal).toBeTruthy();
  expect(fault).toBeTruthy();
  expect(restore).toBeTruthy();
  return {
    normal: normal!,
    fault: fault!,
    restore: restore!,
  };
}

async function createFollowupJob(docCopy: string, database: string, repoRoot: string, anchor: string, note: string): Promise<void> {
  const original = await readFile(docCopy, "utf8");
  expect(original.includes(anchor)).toBe(true);
  expect(original.includes(note)).toBe(false);
  const updated = original.replace(anchor, `${anchor}\n${note}`);
  expect(updated).not.toBe(original);
  await writeFile(docCopy, updated, "utf8");
  const result = spawnSync(
    "uv",
    ["run", "knowledge", "import", docCopy, "-d", database],
    {
      cwd: repoRoot,
      encoding: "utf8",
      env: { ...process.env, NO_COLOR: "1", TERM: "dumb" },
    },
  );
  expect(result.status).toBe(0);
}

describeIf("EvaluationPage live acceptance", () => {
  it("用真实 loopback 管理服务验证 compare delta、UI 渲染与刷新看到新任务", async () => {
    if (!config) throw new Error("acceptance config missing");
    assertOwnedPath(config.runRoot, config.seedReport, "report.json");
    assertOwnedPath(config.runRoot, config.docCopy, "documents/docs/auto-evaluation.md");
    assertOwnedPath(config.runRoot, config.database, "knowledge.db");
    patchGlobalFetch(config.webOrigin);

    const ids = await loadSeedIds(config.seedReport);
    const client = new ManagementClient(makeOriginFetcher(config.webOrigin));
    const initialPage = await client.listJobs({ limit: 20, offset: 0 });
    expect(initialPage.items.length).toBeGreaterThanOrEqual(3);

    const normal = await client.getJob(ids.normal);
    const fault = await client.getJob(ids.fault);
    const restore = await client.getJob(ids.restore);
    expect(jobById(initialPage, ids.fault).status).toBe("failed");

    expect(normal.dataset_id).toBe(fault.dataset_id);
    expect(fault.dataset_id).toBe(restore.dataset_id);
    expect(normal.dataset_version).toBe(fault.dataset_version);
    expect(fault.dataset_version).toBe(restore.dataset_version);
    expect(normal.dataset_hash).toBe(fault.dataset_hash);
    expect(fault.dataset_hash).toBe(restore.dataset_hash);
    expect(normal.config_fingerprint).toBe(fault.config_fingerprint);
    expect(fault.config_fingerprint).toBe(restore.config_fingerprint);

    const normalToFault = compareJobs(normal, fault);
    const faultToRestore = compareJobs(fault, restore);
    expect(normalToFault.comparable).toBe(true);
    expect(faultToRestore.comparable).toBe(true);
    expect(metricDelta(normalToFault, "mean_recall")).toBeLessThan(0);
    expect(metricDelta(faultToRestore, "mean_recall")).toBeGreaterThan(0);
    expect(normalToFault.warnings.some((message) => message.includes("不能自动归因"))).toBe(true);
    expect(faultToRestore.warnings.some((message) => message.includes("不能自动归因"))).toBe(true);

    const normalFaultRecall = normalToFault.metrics.find((metric) => metric.key === "mean_recall");
    const faultRestoreRecall = faultToRestore.metrics.find((metric) => metric.key === "mean_recall");
    expect(normalFaultRecall).toBeDefined();
    expect(faultRestoreRecall).toBeDefined();

    const { container, root } = setupDom();
    await renderPage(root, normal.id, fault.id);
    await waitFor(() => container.textContent?.includes("评测对照") === true);
    await waitFor(
      () =>
        container.textContent?.includes(
          formatMetricDelta(normalFaultRecall?.delta ?? null, normalFaultRecall?.unit ?? "ratio"),
        ) === true,
    );
    expect(container.textContent).toContain("观察提醒");
    expect(container.textContent).toContain("平均 Recall");

    await renderPage(root, fault.id, restore.id);
    await waitFor(
      () =>
        container.textContent?.includes(
          formatMetricDelta(faultRestoreRecall?.delta ?? null, faultRestoreRecall?.unit ?? "ratio"),
        ) === true,
    );

    const beforeIds = initialPage.items.map((job) => job.id);
    await createFollowupJob(
      config.docCopy,
      config.database,
      config.repoRoot,
      config.followupAnchor,
      config.followupNote,
    );
    await flush(() => buttonByText(container, "刷新").click());
    await waitFor(
      () => container.textContent?.includes("检测到任务列表头部有新变化") === true,
    );

    const refreshedPage = await client.listJobs({ limit: 20, offset: 0 });
    const newJob = refreshedPage.items.find((job) => !beforeIds.includes(job.id));
    expect(newJob).toBeDefined();
    if (!newJob) throw new Error("new job not found");
    expect(newJob.status).toBe("passed");
    expect(refreshedPage.items.some((job) => job.id === fault.id && job.status === "failed")).toBe(true);
    await waitFor(() => container.textContent?.includes(newJob.id) === true);
    expect(container.textContent).toContain(fault.id);
    expect(container.textContent).toContain(restore.id);

    const newest = await client.getJob(newJob.id);
    expect(newest.report).not.toBeNull();

    await writeFile(
      config.frontendReport,
      `${JSON.stringify(
        {
          status: "passed",
          tests: { passed: 1, skipped: 0 },
          jobs: {
            normal: {
              id: normal.id,
              status: normal.status,
              dataset_hash: normal.dataset_hash,
              config_fingerprint: normal.config_fingerprint,
            },
            fault: {
              id: fault.id,
              status: fault.status,
              dataset_hash: fault.dataset_hash,
              config_fingerprint: fault.config_fingerprint,
            },
            restore: {
              id: restore.id,
              status: restore.status,
              dataset_hash: restore.dataset_hash,
              config_fingerprint: restore.config_fingerprint,
            },
            newest_after_refresh: {
              id: newest.id,
              status: newest.status,
              dataset_hash: newest.dataset_hash,
              config_fingerprint: newest.config_fingerprint,
            },
          },
          comparison: {
            normal_to_fault: {
              comparable: normalToFault.comparable,
              mean_recall_delta: metricDelta(normalToFault, "mean_recall"),
              warnings: normalToFault.warnings,
            },
            fault_to_restore: {
              comparable: faultToRestore.comparable,
              mean_recall_delta: metricDelta(faultToRestore, "mean_recall"),
              warnings: faultToRestore.warnings,
            },
          },
          refresh: {
            before_head_ids: beforeIds.slice(0, 3),
            after_head_ids: refreshedPage.items.map((job) => job.id).slice(0, 3),
            new_job_seen: true,
            new_job_id: newest.id,
            failure_preserved: refreshedPage.items.some((job) => job.id === fault.id),
            ui_notice_seen: container.textContent?.includes("检测到任务列表头部有新变化") === true,
            selection_preserved:
              container.textContent?.includes(fault.id) === true
              && container.textContent?.includes(restore.id) === true,
          },
        },
        null,
        2,
      )}\n`,
      "utf8",
    );
  }, 120_000);
});
