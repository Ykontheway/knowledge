// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { MutationError } from "./mutations/types";
import { forgetKnown, forgetPending, pendingCommand } from "./mutations/hooks";
import { mutationClient } from "./mutations/client";
import { command, deferred, document as docFixture, hashA, hashB, ids, json, makePreview, previewRequest, session } from "./mutations/tests/fixtures";

const environment = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean };
const previousEnvironment = environment.IS_REACT_ACT_ENVIRONMENT;
const roots = new Set<Root>();
let transport: ReturnType<typeof vi.fn<(path: string, init: RequestInit) => Promise<Response>>>;
beforeAll(() => { environment.IS_REACT_ACT_ENVIRONMENT = true; });
afterAll(() => {
  if (previousEnvironment === undefined) delete environment.IS_REACT_ACT_ENVIRONMENT;
  else environment.IS_REACT_ACT_ENVIRONMENT = previousEnvironment;
});
beforeEach(() => {
  window.history.replaceState(null, "", "#changes");
  transport = vi.fn(async (path: string) => {
    if (path === "/v1/mutations/session") return json(session);
    if (path === `/v1/mutations/documents/${ids.document}`) return json(docFixture);
    if (path === "/v1/mutations/previews") return json(makePreview());
    if (path === "/v1/mutations/commands" || path === `/v1/mutations/commands/${ids.command}`) return json(command);
    if (path.startsWith("/v1/mutations/commands/")) return json({ error: "not found" }, 404);
    throw new Error("unexpected test path");
  });
  vi.stubGlobal("fetch", transport);
  vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(ids.key as ReturnType<Crypto["randomUUID"]>);
});
afterEach(async () => {
  await act(async () => { for (const root of roots) root.unmount(); });
  roots.clear(); document.body.replaceChildren();
  window.history.replaceState(null, "", "#overview");
  forgetPending(ids.key); forgetKnown(ids.command); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers();
});
async function tick(action: () => void = () => undefined) {
  await act(async () => { action(); await new Promise<void>(resolve => setTimeout(resolve, 0)); });
}
async function mount(hash = "#changes") {
  window.history.replaceState(null, "", hash);
  const container = document.createElement("div"); document.body.appendChild(container);
  const root = createRoot(container); roots.add(root);
  await act(async () => { root.render(createElement(App)); });
  await tick();
  return { container, root };
}
function button(container: HTMLElement, label: string) {
  const found = [...container.querySelectorAll("button")].find(item => item.textContent?.trim() === label);
  expect(found, label).toBeTruthy(); return found!;
}
async function click(container: HTMLElement, label: string) { await tick(() => button(container, label).click()); }
async function edit(container: HTMLElement, text = previewRequest.text) {
  const textarea = container.querySelector<HTMLTextAreaElement>("textarea[aria-label='文档草稿']")!;
  await tick(() => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea, text);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function check(container: HTMLElement) { await tick(() => container.querySelector<HTMLInputElement>("input[type=checkbox]")!.click()); }
function requests(path: string) { return transport.mock.calls.filter(([url]) => url === `/v1/mutations/${path}`); }
async function preview(container: HTMLElement) { await edit(container); await click(container, "预览变更"); }
async function setHash(hash: string) {
  await tick(() => { window.history.replaceState(null, "", hash); window.dispatchEvent(new HashChangeEvent("hashchange")); });
}

describe("App B4 controlled mutations", () => {
  it("does not probe a mutation service on static pages and has a clearly isolated sidebar", async () => {
    const { container } = await mount("#overview");
    expect(transport).not.toHaveBeenCalled();
    expect(container.textContent).toContain("受控更新 / 默认关闭");
    expect(container.textContent).toContain("仅演示副本");
  });
  it.each([503, 404, 403, 401])("stays safe and disables edits when session status is %i", async status => {
    transport.mockResolvedValue(json({ detail: "RAW_SERVER_SECRET" }, status));
    const { container } = await mount();
    expect(container.textContent).not.toContain("RAW_SERVER_SECRET");
    expect(container.querySelector("textarea")!.disabled).toBe(true);
    expect(button(container, "预览变更").disabled).toBe(true);
    if (status === 403 || status === 401) expect(container.textContent).toContain("没有演示副本的更新权限");
    else if (status === 503) expect(container.textContent).toContain("未启用或暂不可用");
    expect(requests("previews")).toHaveLength(0);
    await setHash("#overview"); expect(container.textContent).toContain("总览");
  });
  it.each(["#changes?token=SECRET_DONT_ECHO", "#changes?document=bad", `#changes?document=${ids.document}&command=${ids.command}`])("does not fetch or echo illegal route %s", async hash => {
    const { container } = await mount(hash);
    expect(container.textContent).toContain("链接无效，已停在安全页");
    expect(container.textContent).not.toContain("SECRET_DONT_ECHO"); expect(transport).not.toHaveBeenCalled();
  });
  it("does not fetch a document outside the explicit session whitelist", async () => {
    const { container } = await mount(`#changes?document=${ids.newDocument}`);
    expect(container.textContent).toContain("没有演示副本的更新权限");
    expect(transport).toHaveBeenCalledTimes(1); expect(button(container, "预览变更").disabled).toBe(true);
  });
  it("edit -> preview -> explicit confirmation -> committed/gatefailed with B2/B3 links", async () => {
    const { container } = await mount();
    expect(container.textContent).toContain(session.actor_id);
    expect(container.querySelector("textarea")!.value).toBe(docFixture.text);
    await preview(container);
    expect(requests("commands")).toHaveLength(0);
    expect(JSON.parse(requests("previews")[0]![1].body as string)).toEqual(previewRequest);
    expect(container.textContent).toContain(hashA); expect(container.textContent).toContain(hashB);
    expect(button(container, "确认并提交").disabled).toBe(true);
    await check(container); await check(container);
    expect(button(container, "确认并提交").disabled).toBe(true);
    await check(container); await click(container, "确认并提交"); await tick();
    expect(container.textContent).toContain("知识变更已成功提交");
    expect(container.textContent).toContain("评测门禁失败"); expect(container.textContent).toContain("失败评测不是回滚");
    expect(window.location.hash).toBe(`#changes?command=${ids.command}`);
    expect(container.querySelector(`a[href='#lifecycle/jobs/${ids.job}']`)).toBeTruthy();
    expect(container.querySelector(`a[href='#lifecycle/revisions/${ids.revision}']`)).toBeTruthy();
    expect(container.querySelector(`a[href='#lifecycle/documents/${ids.newDocument}/diff?old=${ids.document}']`)).toBeTruthy();
    expect(container.querySelector("a[href='#evaluation']")).toBeTruthy();
    expect(container.textContent).not.toContain("s".repeat(43)); expect(window.location.hash).not.toContain("s".repeat(43));
  });
  it("invalidates preview/checkbox on draft changes and rejects oversize Unicode", async () => {
    const { container } = await mount(); await preview(container); await check(container);
    await edit(container, "另一个草稿😀");
    expect(container.querySelector("input[type=checkbox]")).toBeNull();
    expect(container.textContent).toContain("原预览失效"); expect(requests("commands")).toHaveLength(0);
    await edit(container, "😀".repeat(16385)); expect(button(container, "预览变更").disabled).toBe(true);
    await edit(container, "😀".repeat(16384)); expect(button(container, "预览变更").disabled).toBe(false);
    expect(container.textContent).toContain("字符数（Unicode codepoint）：16384");
  });
  it("finishes no-change preview without POST command or evaluation", async () => {
    const real = transport.getMockImplementation()!;
    transport.mockImplementation((path, init) => path === "/v1/mutations/previews" ? Promise.resolve(json(makePreview(false))) : real(path, init));
    const { container } = await mount(); await click(container, "预览变更");
    expect(container.textContent).toContain("内容无变更，无需提交"); expect(container.querySelector("input[type=checkbox]")).toBeNull();
    await click(container, "结束无变更预览"); expect(requests("commands")).toHaveLength(0);
    expect(container.textContent).toContain("没有触发评测");
  });
  it("serializes duplicate clicks and preserves exact token/key/payload on uncertain retries", async () => {
    const failed = deferred<Response>(); const real = transport.getMockImplementation()!;
    let writes = 0;
    transport.mockImplementation((path, init) => path === "/v1/mutations/commands" && writes++ === 0 ? failed.promise : real(path, init));
    const { container } = await mount(); await preview(container); await check(container);
    await tick(() => { button(container, "确认并提交").click(); button(container, "确认并提交").click(); });
    expect(requests("commands")).toHaveLength(1);
    await tick(() => failed.reject(new Error("secret network response"))); await tick();
    expect(window.location.hash).toBe(`#changes?command=${ids.key}`);
    expect(container.textContent).toContain("服务器可能已提交");
    expect(container.textContent).toContain("尚未查到已提交记录，请用原请求重试或等待");
    expect(container.textContent).not.toContain("secret network response");
    await click(container, "用原请求重试（同一幂等键）"); await tick();
    expect(requests("commands")).toHaveLength(2);
    expect(requests("commands")[1]![1].body).toBe(requests("commands")[0]![1].body);
    expect(globalThis.crypto.randomUUID).toHaveBeenCalledTimes(1);
    expect(window.location.hash).toBe(`#changes?command=${ids.command}`);
    expect(container.textContent).toContain("知识变更已成功提交");
  });
  it("retains same key after retry expiry and does not offer a fresh write", async () => {
    const real = transport.getMockImplementation()!; let writes = 0;
    transport.mockImplementation((path, init) => path === "/v1/mutations/commands" ? writes++ === 0
      ? Promise.reject(new Error("lost")) : Promise.resolve(json({}, 410)) : real(path, init));
    const { container } = await mount(); await preview(container); await check(container); await click(container, "确认并提交"); await tick();
    await click(container, "用原请求重试（同一幂等键）");
    expect(pendingCommand(ids.key)).toBeDefined(); expect(container.querySelector("textarea")).toBeNull();
    expect(container.textContent).toContain("服务器可能已提交");
    expect(requests("commands")[1]![1].body).toBe(requests("commands")[0]![1].body);
  });
  it("stops waiting without promising cancellation and ignores a late response after unmount", async () => {
    const late = deferred<Response>(); const real = transport.getMockImplementation()!;
    transport.mockImplementation((path, init) => path === "/v1/mutations/commands" ? late.promise : real(path, init));
    const { container } = await mount(); await preview(container); await check(container); await click(container, "确认并提交");
    await click(container, "停止等待（不取消后端操作）"); await tick();
    expect(container.textContent).toContain("服务器可能已提交"); expect(pendingCommand(ids.key)).toBeDefined();
    await setHash("#overview"); await tick(() => late.resolve(json(command)));
    expect(window.location.hash).toBe("#overview"); expect(container.textContent).not.toContain("知识变更已成功提交");
  });
  it("times out an apply and retains its exact request, with safe 404 recovery", async () => {
    vi.spyOn(mutationClient, "applyCommand").mockRejectedValueOnce(new MutationError("timeout"));
    const { container } = await mount(); await preview(container); await check(container); await click(container, "确认并提交"); await tick();
    expect(pendingCommand(ids.key)?.request.idempotency_key).toBe(ids.key);
    expect(container.textContent).toContain("尚未查到已提交记录");
    await click(container, "回查提交记录"); expect(container.textContent).toContain("服务器可能已提交");
  });
  it("URL reload without a token does only GET, then requires a fresh authorized document before editing", async () => {
    const { container } = await mount(`#changes?command=${ids.key}`);
    expect(container.textContent).toContain("原令牌已丢失");
    expect(requests("session")).toHaveLength(0); expect(requests("commands")).toHaveLength(0);
    expect(container.querySelector("textarea")).toBeNull();
    expect([...container.querySelectorAll("button")].some(b => b.textContent?.includes("用原请求重试"))).toBe(false);
    await setHash("#changes"); expect(requests("session")).toHaveLength(1);
    expect(container.querySelector("textarea")!.value).toBe(docFixture.text);
  });
  it("reloads a conflicted current head without overwriting the user draft", async () => {
    const real = transport.getMockImplementation()!; let updated = false;
    transport.mockImplementation((path, init) => {
      if (path === "/v1/mutations/previews") { updated = true; return Promise.resolve(json({}, 409)); }
      if (updated && path === "/v1/mutations/session") return Promise.resolve(json({ ...session, sources: [{ ...session.sources[0], document_id: ids.newDocument, checksum: hashB }] }));
      if (path === `/v1/mutations/documents/${ids.newDocument}`) return Promise.resolve(json({ ...docFixture, document_id: ids.newDocument, checksum: hashB, text: "服务器新正文" }));
      return real(path, init);
    });
    const { container } = await mount(); await preview(container);
    expect(container.textContent).toContain("冲突");
    await click(container, "重新加载当前文档（保留草稿）");
    expect(container.querySelector("textarea")!.value).toBe(previewRequest.text);
    expect(container.textContent).toContain("当前文档版本已更新");
    expect(container.textContent).toContain(ids.newDocument); expect(container.textContent).toContain(hashB);
  });
  it("handles explicit 410 and only gives a new idempotency key for a new preview", async () => {
    vi.spyOn(mutationClient, "applyCommand").mockRejectedValueOnce(new MutationError("expired", 410));
    const { container } = await mount(); await preview(container); await check(container); await click(container, "确认并提交");
    expect(container.textContent).toContain("预览已过期"); expect(container.querySelector("textarea")!.value).toBe(previewRequest.text);
    expect(pendingCommand(ids.key)).toBeUndefined();
    await click(container, "预览变更"); expect(globalThis.crypto.randomUUID).toHaveBeenCalledTimes(2);
    expect(button(container, "确认并提交").disabled).toBe(true);
  });
  it("makes expired previews non-submittable locally", async () => {
    const { container } = await mount(); await preview(container); await check(container);
    vi.spyOn(Date, "now").mockReturnValue(Date.now() + 301_000);
    await click(container, "确认并提交");
    expect(container.textContent).toContain("预览已过期"); expect(requests("commands")).toHaveLength(0);
  });
  it("never accepts an old preview response after editing and never renders text as HTML", async () => {
    const late = deferred<Response>(); const real = transport.getMockImplementation()!;
    transport.mockImplementation((path, init) => path === "/v1/mutations/previews" ? late.promise : real(path, init));
    const { container } = await mount(); await preview(container); await edit(container, "后来的草稿");
    await tick(() => late.resolve(json(makePreview())));
    expect(container.querySelector("input[type=checkbox]")).toBeNull();
    const html = "<img src=x onerror=alert(1)><script>alert('x')</script>";
    transport.mockImplementation((path, init) => path === "/v1/mutations/previews" ? Promise.resolve(json({ ...makePreview(), diff: [{ kind: "modified", old_text: html, new_text: html }] })) : real(path, init));
    await click(container, "预览变更");
    expect(container.querySelector("img")).toBeNull(); expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain(html);
  });
  it("ignores an old document response when the hash switches to a different editor", async () => {
    const late = deferred<Response>(); const real = transport.getMockImplementation()!;
    transport.mockImplementation((path, init) => path === `/v1/mutations/documents/${ids.document}` ? late.promise : real(path, init));
    const { container } = await mount(); await setHash(`#changes?document=${ids.newDocument}`);
    await tick(() => late.resolve(json(docFixture)));
    expect(container.textContent).toContain("没有演示副本的更新权限"); expect(container.querySelector("textarea")!.value).toBe("");
  });
});


describe("B4 recovery and refresh boundaries", () => {
  it("keeps the confirmed POST result even if the follow-up GET is unavailable", async () => {
    const real = transport.getMockImplementation()!;
    transport.mockImplementation((path, init) => path === `/v1/mutations/commands/${ids.command}` ? Promise.resolve(json({}, 503)) : real(path, init));
    const { container } = await mount(); await preview(container); await check(container); await click(container, "确认并提交"); await tick();
    expect(container.textContent).toContain("知识变更已成功提交");
    expect(container.textContent).toContain("committed：true");
    expect(container.textContent).not.toContain("提交结果不确定");
  });
  it("recovers outstanding in-memory requests after navigating away, and blocks new preview", async () => {
    vi.spyOn(mutationClient, "applyCommand").mockRejectedValueOnce(new MutationError("network"));
    const { container } = await mount(); await preview(container); await check(container); await click(container, "确认并提交"); await tick();
    await setHash("#overview"); await setHash("#changes"); await tick();
    expect(window.location.hash).toBe(`#changes?command=${ids.key}`);
    expect(container.querySelector("textarea")).toBeNull();
    expect(container.textContent).toContain("原请求"); expect(requests("previews")).toHaveLength(1);
  });
  it("keeps a draft through a failed current-head reload and a later successful reload", async () => {
    const { container } = await mount(); await edit(container, "不可丢的草稿😀");
    const real = transport.getMockImplementation()!; let fail = true;
    transport.mockImplementation((path, init) => path === "/v1/mutations/session" && fail ? Promise.resolve(json({}, 503)) : real(path, init));
    await click(container, "重新加载当前文档（保留草稿）");
    expect(container.querySelector("textarea")!.value).toBe("不可丢的草稿😀");
    fail = false; await click(container, "重新加载当前文档（保留草稿）");
    expect(container.querySelector("textarea")!.value).toBe("不可丢的草稿😀");
  });
  it("refreshes session on source selection and fetches that source's new document id", async () => {
    const second = { ...session.sources[0]!, source_id: ids.revision, document_id: ids.newDocument, checksum: hashB, label: "第二份副本" };
    const real = transport.getMockImplementation()!;
    transport.mockImplementation((path, init) => {
      if (path === "/v1/mutations/session") return Promise.resolve(json({ ...session, sources: [...session.sources, second] }));
      if (path === `/v1/mutations/documents/${ids.newDocument}`) return Promise.resolve(json({ ...docFixture, source_id: second.source_id, document_id: ids.newDocument, checksum: hashB, text: "第二份原文" }));
      return real(path, init);
    });
    const { container } = await mount(); await edit(container, "保留草稿");
    await tick(() => {
      const select = container.querySelector<HTMLSelectElement>("select[aria-label='授权来源']")!;
      select.value = second.source_id; select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(requests("session")).toHaveLength(2);
    expect(transport.mock.calls.some(([path]) => path === `/v1/mutations/documents/${ids.newDocument}`)).toBe(true);
    expect(container.querySelector("textarea")!.value).toBe("保留草稿");
    expect(container.textContent).toContain(ids.newDocument); expect(container.textContent).toContain(hashB);
  });
  it.each(["passed", "pending", "not_triggered", "unavailable"] as const)("shows committed separately from evaluation %s without triggering evaluation", async evaluation_status => {
    const real = transport.getMockImplementation()!;
    transport.mockImplementation((path, init) => path === `/v1/mutations/commands/${ids.command}` ? Promise.resolve(json({ ...command, evaluation_status, job_ids: [ids.job, ids.key] })) : real(path, init));
    const { container } = await mount(`#changes?command=${ids.command}`);
    expect(container.textContent).toContain("知识变更已成功提交"); expect(container.textContent).toContain("committed：true");
    expect(container.querySelector(`a[href='#lifecycle/jobs/${ids.job}']`)).toBeTruthy();
    expect(container.querySelector(`a[href='#lifecycle/jobs/${ids.key}']`)).toBeTruthy();
    expect(container.querySelector("a[href^='#evaluation?']")).toBeNull();
    expect(requests("commands")).toHaveLength(0); expect(requests("session")).toHaveLength(0);
    expect(transport).toHaveBeenCalledTimes(1);
  });
});
