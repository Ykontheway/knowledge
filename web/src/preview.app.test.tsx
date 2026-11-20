// @vitest-environment jsdom

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath, URL as NodeURL } from "node:url";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// 只替换 build 开关；App、Layout、各页面、runtime/client 和校验器全部真实运行。
vi.mock("./preview", async () => {
  const actual = await vi.importActual<typeof import("./preview")>("./preview");
  return { ...actual, isReplayPreview: vi.fn(() => true) };
});

import App from "./App";
import { snapshot } from "./data";
import { formatFull } from "./lib/format";
import { validateReplayBundle } from "./management/replay";
import {
  evaluationHash, lifecycleDiffHash, lifecycleDocumentHash, lifecycleEvidenceHash,
  lifecycleJobHash, lifecycleLineageHash, lifecycleRevisionHash, parseHashRoute,
} from "./management/route";
import { initialHash, isReplayPreview } from "./preview";

// 不使用合成 fixture、不补资源；成功响应逐字读取父流程的公开导出。
const exportPath = fileURLToPath(new NodeURL("../public/replay.json", import.meta.url));
const exportedText = readFileSync(exportPath, "utf8");
const digest = (text: string) => createHash("sha256").update(text).digest("hex");
const diskHash = digest(exportedText);
const bundle = () => validateReplayBundle(JSON.parse(exportedText) as unknown);
const mode = { mode: "replay" as const };
const strictGet = { method: "GET", credentials: "omit", redirect: "error", headers: { accept: "application/json" } };
const assetResponse = () => new Response(exportedText, { headers: { "content-type": "application/json" } });
const roots = new Set<Root>();
const actEnvironment = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean };
let previousActEnvironment: boolean | undefined;
let unexpectedNetwork: string[];
let manifestResponse: () => Response;
let fetchMock: ReturnType<typeof vi.fn<typeof globalThis.fetch>>;

beforeEach(() => {
  previousActEnvironment = actEnvironment.IS_REACT_ACT_ENVIRONMENT;
  actEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
  // initialHash 的默认参数调用模块内函数，不能靠替换导出改变其词法绑定。
  // 设置显式 replay MODE，保留真实 initialHash / previewRouteAllowed 的实现。
  vi.stubEnv("MODE", "replay");
  // Vitest 默认 BASE_URL 为 /；显式构建沿用 vite.config.ts 的相对 base。
  vi.stubEnv("BASE_URL", "./");
  unexpectedNetwork = [];
  manifestResponse = assetResponse;
  fetchMock = vi.fn<typeof globalThis.fetch>(async (input) => {
    const path = String(input);
    if (path !== "./replay.json") {
      unexpectedNetwork.push(path);
      throw new Error(`预览 App 测试禁止网络请求：${path}`);
    }
    return manifestResponse();
  });
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
});

afterEach(async () => {
  try {
    // 断言失败也先卸载：移除 hash listener，abort Provider 请求及页面状态更新。
    await act(async () => { for (const root of roots) root.unmount(); });
    await settle();
  } finally {
    roots.clear();
    document.body.innerHTML = "";
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    if (previousActEnvironment === undefined) delete actEnvironment.IS_REACT_ACT_ENVIRONMENT;
    else actEnvironment.IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  }
  expect(unexpectedNetwork, "生产代码即使捕获异常，也不能掩盖 live/mutations 请求").toEqual([]);
  for (const [input, init] of fetchMock.mock.calls) {
    expect(input).toBe("./replay.json");
    expect(init).toMatchObject(strictGet);
    expect(init?.body).toBeUndefined();
  }
  expect(digest(readFileSync(exportPath, "utf8")), "不得修改公开 JSON 迁就生产契约").toBe(diskHash);
});

// Response stream、React effects 和 jsdom 原生 hash/history 事件正常提交几轮即可。
// 不使用 fake timers、重叠 act、轮询 waitFor 或放大 test timeout。
async function settle(): Promise<void> {
  for (let round = 0; round < 4; round++) {
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
  }
}
async function interact(action: () => void): Promise<void> {
  await act(async () => { action(); });
  await settle();
}
async function mount(hash = ""): Promise<HTMLDivElement> {
  window.history.replaceState(null, "", hash || `${window.location.pathname}${window.location.search}`);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.add(root);
  await interact(() => root.render(createElement(App)));
  return container;
}
function navButton(container: HTMLElement, label: string): HTMLButtonElement {
  const nav = container.querySelector("nav[aria-label='主导航']");
  expect(nav, "必须使用真实 Layout 主导航").toBeTruthy();
  const found = Array.from(nav!.querySelectorAll("button")).find((item) => item.querySelector("span span")?.textContent === label);
  expect(found, `找不到真实导航按钮：${label}`).toBeTruthy();
  return found!;
}
function link(container: HTMLElement, href: string): HTMLAnchorElement {
  const found = Array.from(container.querySelectorAll<HTMLAnchorElement>("a[href]")).find((item) => item.getAttribute("href") === href);
  expect(found, `找不到真实资源链接：${href}`).toBeTruthy();
  return found!;
}
async function follow(container: HTMLElement, href: string): Promise<void> {
  await interact(() => link(container, href).click());
  expect(window.location.hash).toBe(href);
}
function heading(container: HTMLElement, title: string): void {
  expect(Array.from(container.querySelectorAll("main h2, main h3")).map((item) => item.textContent)).toContain(title);
}
function assertReadonly(container: HTMLElement): void {
  const controls = Array.from(container.querySelectorAll("button, input, select, textarea"));
  expect(controls.filter((item) => /Observer|观察新任务|停止观察|受控变更|预览变更|确认并提交|确认更新演示副本/i.test(`${item.textContent} ${item.getAttribute("aria-label")}`))).toEqual([]);
  expect(container.querySelector("form, textarea, #mutation-draft, input[type='submit'], input[type='checkbox'], select[aria-label='授权来源']")).toBeNull();
  expect(Array.from(container.querySelectorAll("a[href]")).filter((item) => /^#(?:changes|lifecycle|evaluation|guide)(?:[/?]|$)|\/v1\//.test(item.getAttribute("href") ?? ""))).toEqual([]);
  expect(container.querySelector("nav")?.textContent).toContain("静态回放 · 非实时");
  expect(container.querySelector("nav")?.textContent).not.toContain("受控更新 / 默认关闭");
}
function assertReplay(container: HTMLElement): void {
  expect(container.querySelector("main header")?.textContent).toContain("静态回放 · 非实时 / 仅合成公开语料");
  assertReadonly(container);
}
function assertOverview(container: HTMLElement): void {
  expect(snapshot.schema_version).toBe(1);
  expect(container.querySelector("main header")?.textContent).toContain("Snapshot v1 / 静态演示");
  expect(container.querySelector("main header")?.textContent).not.toContain("静态回放 · 非实时 / 仅合成公开语料");
  expect(container.querySelector("nav")?.textContent).toContain("Snapshot V1 历史故事");
  heading(container, snapshot.title);
  expect(container.querySelector("main")?.textContent).toContain(snapshot.as_of);
  assertReadonly(container);
}
function assertGuide(container: HTMLElement): void {
  const real = bundle();
  const ids = [real.story.reference_job_id, real.story.candidate_job_id, real.story.recovery_job_id];
  const labels = ["正常阶段", "故障阶段", "恢复阶段"];
  const statuses = ["passed", "failed", "passed"];
  expect(container.querySelector("main")?.textContent).toContain("三阶段满足回放故事条件");
  const cards = Array.from(container.querySelectorAll("details article"));
  expect(cards).toHaveLength(3);
  ids.forEach((id, index) => {
    const job = real.resources.jobs.find((item) => item.id === id)!;
    expect(job.status).toBe(statuses[index]);
    const card = cards.find((item) => item.querySelector("h3")?.textContent === labels[index]);
    expect(card?.textContent).toContain(job.id);
    expect(card?.textContent).toContain(index === 1 ? "失败" : "通过");
    expect(card?.textContent).toContain(formatFull(job.evaluated_at));
    link(container, lifecycleJobHash(job.id, mode));
  });
  link(container, evaluationHash({ reference: ids[0], candidate: ids[1], ...mode }));
  link(container, evaluationHash({ reference: ids[1], candidate: ids[2], ...mode }));
  assertReplay(container);
}
function assertBlocked(container: HTMLElement): string {
  const main = container.querySelector("main")!;
  const notice = main.querySelector("section[role='status']");
  expect(notice?.querySelector("h2")?.textContent).toBe("此预览仅开放静态回放");
  expect(notice?.textContent).toContain("本预览不会连接后端或提交变更");
  // 内容区必须只有真实 PreviewRouteNotice，而非 ChangesPage 的错误/disabled 编辑器。
  expect(Array.from(main.querySelectorAll("h2, h3")).map((item) => item.textContent)).toEqual(["此预览仅开放静态回放"]);
  expect(main.querySelectorAll("section")).toHaveLength(1);
  expect(main.querySelector("button, form, textarea, input, select, table, ol")).toBeNull();
  expect(main.textContent).not.toMatch(/选择授权来源|文档草稿|命令回查与结果恢复|正在读取真实任务/);
  const recovery = notice!.querySelector<HTMLAnchorElement>("a[href]");
  expect(recovery?.textContent).toBe("查看三阶段回放");
  const href = recovery!.getAttribute("href")!;
  // 点击真实 Notice 的入口；入口的精确默认字符串由空 hash 用例单独严格检查。
  expect(href).toMatch(/^#replay(?:\/|$)/);
  expect(parseHashRoute(href)).toMatchObject({ view: "guide", kind: "steps", mode: "replay", offset: 0 });
  assertReplay(container);
  return href;
}

describe("显式 replay preview build：真实 App 的只读隔离", () => {
  it("空 hash 默认解析为 #replay/guide，呈现公开 JSON 的真实三阶段且只读", async () => {
    const container = await mount();
    expect(isReplayPreview()).toBe(true);
    // 现有合同只提供默认路由，不强制重写地址栏；不能由测试补写 hash。
    expect(window.location.hash).toBe("");
    assertGuide(container);
    expect(initialHash(window.location.hash)).toBe("#replay/guide");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each(["#changes", "#changes?document", "#changes?command"])("手打 %s 只显示 PreviewRouteNotice，不挂载真实变更编辑器或请求 mutations", async (prefix) => {
    const real = bundle();
    const hash = prefix === "#changes" ? prefix : `${prefix}=${real.resources.documents[0]!.id}`;
    const container = await mount("#replay/guide");
    assertGuide(container);
    await interact(() => { window.location.hash = hash; });
    expect(window.location.hash).toBe(hash);
    const recoveryHash = assertBlocked(container);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await follow(container, recoveryHash);
    assertGuide(container);
    await interact(() => window.history.back());
    expect(window.location.hash).toBe(hash);
    assertBlocked(container);
  });

  it.each(["#lifecycle", "#evaluation", "#guide"])("直达旧 live hash %s 被阻断，无法启动 live 页面或 fetch", async (hash) => {
    const container = await mount(hash);
    expect(window.location.hash).toBe(hash);
    const recoveryHash = assertBlocked(container);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await follow(container, recoveryHash);
    assertGuide(container);
    await interact(() => window.history.back());
    expect(window.location.hash).toBe(hash);
    assertBlocked(container);
  });

  it("#overview 保留真实 Snapshot V1 内容和 V1 标识，但不暴露 Live/B4 控件", async () => {
    const container = await mount("#overview");
    assertOverview(container);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["生命周期工作台", "#replay/lifecycle/jobs", "任务时间线"],
    ["评测对照", "#replay/evaluation", "核心结果"],
    ["演示导览", "#replay/guide", "演示导览"],
  ])("从 V1 总览点击%s仍生成 %s，back/forward 恢复真实 DOM", async (label, hash, title) => {
    const container = await mount("#overview");
    assertOverview(container);
    await interact(() => navButton(container, label).click());
    expect(window.location.hash).toBe(hash);
    heading(container, title);
    assertReplay(container);
    if (hash === "#replay/guide") assertGuide(container);
    await interact(() => window.history.back());
    expect(window.location.hash).toBe("#overview");
    assertOverview(container);
    await interact(() => window.history.forward());
    expect(window.location.hash).toBe(hash);
    heading(container, title);
    assertReplay(container);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("真实 job→revision→diff→evidence→lineage→document 全链及完整 back/forward 均保留 replay", async () => {
    const real = bundle();
    const fault = real.resources.jobs.find((item) => item.id === real.story.candidate_job_id)!;
    const revision = real.resources.revisions.find((item) => fault.trigger_revision_ids.includes(item.id) && item.navigation.document_id && item.navigation.previous_document_id)!;
    expect(revision, "真实故障必须含可导航的前后文档 revision").toBeTruthy();
    const diff = real.resources.diffs.find((item) => item.new_document_id === revision.navigation.document_id && item.old_document_id === revision.navigation.previous_document_id)!;
    const unit = diff.changes.items.find((item) => item.old && item.new)?.new;
    expect(unit).toBeTruthy();
    const evidence = real.resources.evidence.find((item) => item.unit_id === unit!.id)!;
    const path = [
      ["#replay/lifecycle/jobs", "任务时间线"],
      [lifecycleJobHash(fault.id, mode), "任务详情"],
      [lifecycleRevisionHash(revision.id, mode), "Revision 详情"],
      [lifecycleDiffHash(diff.new_document_id, diff.old_document_id, 0, mode), "历史 Diff"],
      [lifecycleEvidenceHash(evidence.unit_id, mode), "历史证据"],
      [lifecycleLineageHash(evidence.lineage_id, 0, mode), "Lineage 历史"],
      [lifecycleDocumentHash(evidence.document_id, 0, mode), "文档版本"],
    ] as const;
    const container = await mount("#overview");
    await interact(() => navButton(container, "生命周期工作台").click());
    heading(container, path[0][1]);
    for (const [hash, title] of path.slice(1)) {
      await follow(container, hash);
      heading(container, title);
      assertReplay(container);
      if (title === "历史证据") {
        expect(container.querySelector("pre")?.textContent).toBe(evidence.text);
        expect(container.querySelector("main")?.textContent).toContain(evidence.content_hash);
        expect(container.querySelector("main")?.textContent).toContain(evidence.document_checksum);
      }
    }
    for (const [hash, title] of path.slice(0, -1).reverse()) {
      await interact(() => window.history.back());
      expect(window.location.hash).toBe(hash);
      heading(container, title);
      assertReplay(container);
    }
    await interact(() => window.history.back());
    expect(window.location.hash).toBe("#overview");
    assertOverview(container);
    for (const [hash, title] of path) {
      await interact(() => window.history.forward());
      expect(window.location.hash).toBe(hash);
      heading(container, title);
      assertReplay(container);
    }
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["缺失 asset (404)", () => new Response("", { status: 404 }), "请求的管理资源不存在。"],
    ["损坏 JSON", () => new Response("{", { headers: { "content-type": "application/json" } }), "管理数据响应格式无效。"],
    ["契约无效 JSON", () => new Response("{}", { headers: { "content-type": "application/json" } }), "管理数据响应格式无效。"],
  ])("%s 显示明确错误，重试仍只读 asset、不 fallback", async (_label, respond, message) => {
    // 仅替换 HTTP 响应模拟失败；绝不改写磁盘 JSON，也不放宽校验器。
    manifestResponse = respond;
    const container = await mount();
    const assertError = () => {
      const alerts = Array.from(container.querySelectorAll("main [role='alert']"));
      expect(alerts.some((item) => item.textContent?.includes("静态回放数据不可用"))).toBe(true);
      expect(alerts.some((item) => item.textContent?.includes(message))).toBe(true);
      expect(alerts.some((item) => item.textContent?.includes("页面不会回退到 fixture"))).toBe(true);
      expect(container.querySelectorAll("details article, ol[aria-label='任务时间线']")).toHaveLength(0);
      expect(container.querySelector("main")?.textContent).not.toContain("三阶段满足回放故事条件");
      expect(container.querySelector("main")?.textContent).not.toContain(snapshot.title);
      for (const id of Object.values(bundle().story)) expect(container.querySelector("main")?.textContent).not.toContain(id);
      assertReplay(container);
    };
    assertError();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const retry = Array.from(container.querySelectorAll<HTMLButtonElement>("main [role='alert'] button")).find((item) => item.textContent === "重试");
    expect(retry).toBeTruthy();
    await interact(() => retry!.click());
    assertError();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
