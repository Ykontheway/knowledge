// @vitest-environment jsdom

import { act, createElement, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { BOUNDED_REFRESH_REASONS, useBoundedRefresh, type BoundedRefreshState, type UseBoundedRefreshArgs } from "./useBoundedRefresh";

const actEnvironment = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean };
const previousActEnvironment = actEnvironment.IS_REACT_ACT_ENVIRONMENT;
const roots = new Set<Root>();
const containers = new Set<HTMLDivElement>();

beforeAll(() => {
  actEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
});

afterAll(() => {
  if (previousActEnvironment === undefined) delete actEnvironment.IS_REACT_ACT_ENVIRONMENT;
  else actEnvironment.IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;
});

afterEach(async () => {
  await act(async () => {
    for (const root of roots) root.unmount();
  });
  roots.clear();
  for (const container of containers) container.remove();
  containers.clear();
  setVisibility("visible");
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function setupDom() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.add(root);
  containers.add(container);
  return { container, root };
}

async function flush(action: () => void = () => {}) {
  await act(async () => {
    action();
    await Promise.resolve();
  });
}

async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
    await Promise.resolve();
  });
}

function setVisibility(value: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", { configurable: true, value });
  Object.defineProperty(document, "hidden", { configurable: true, value: value === "hidden" });
}

function text(container: HTMLElement, testId: string) {
  return container.querySelector(`[data-testid='${testId}']`)?.textContent;
}

function click(container: HTMLElement, testId: string) {
  container.querySelector<HTMLButtonElement>(`[data-testid='${testId}']`)!.click();
}

function Harness(props: UseBoundedRefreshArgs & { readonly onState?: (state: BoundedRefreshState) => void }) {
  const state = useBoundedRefresh(props);
  props.onState?.(state);
  return createElement(
    "div",
    {},
    createElement("button", { "data-testid": "start", onClick: state.start, type: "button" }, "start"),
    createElement("button", { "data-testid": "stop", onClick: state.stop, type: "button" }, "stop"),
    createElement("span", { "data-testid": "active" }, String(state.active)),
    createElement("span", { "data-testid": "reason" }, state.reason ?? "none"),
    createElement("span", { "data-testid": "count" }, String(state.refreshCount)),
    createElement("span", { "data-testid": "remaining" }, String(state.remainingSeconds)),
  );
}

function renderHarness(root: Root, props: UseBoundedRefreshArgs & { readonly onState?: (state: BoundedRefreshState) => void }) {
  root.render(createElement(Harness, props));
}

describe("useBoundedRefresh", () => {
  it("默认不自动启动；start 后等待 10s 才触发首个网络刷新", async () => {
    vi.useFakeTimers({ now: 1_000_000 });
    const refresh = vi.fn();
    const { container, root } = setupDom();
    await flush(() => renderHarness(root, { busy: false, error: null, refresh, scopeKey: "jobs" }));

    expect(text(container, "active")).toBe("false");
    expect(text(container, "remaining")).toBe("0");
    expect(refresh).not.toHaveBeenCalled();

    await flush(() => click(container, "start"));
    expect(text(container, "active")).toBe("true");
    expect(text(container, "remaining")).toBe("300");
    await advance(9_999);
    expect(refresh).not.toHaveBeenCalled();
    expect(text(container, "count")).toBe("0");
    await advance(1);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(text(container, "count")).toBe("1");
  });

  it("网络间隔不可被 options 调低，计数上限可收紧用于测试", async () => {
    vi.useFakeTimers({ now: 2_000_000 });
    const refresh = vi.fn();
    const { container, root } = setupDom();
    await flush(() => renderHarness(root, { busy: false, error: null, refresh, scopeKey: "jobs", intervalMs: 1, maxRefreshCount: 2 }));
    await flush(() => click(container, "start"));

    await advance(9_999);
    expect(refresh).not.toHaveBeenCalled();
    await advance(1);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(text(container, "active")).toBe("true");
    await advance(10_000);
    expect(refresh).toHaveBeenCalledTimes(2);
    expect(text(container, "active")).toBe("false");
    expect(text(container, "reason")).toBe(BOUNDED_REFRESH_REASONS.maxDuration);
    await advance(60_000);
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("busy 会跳过刷新且不计数，deadline 不会因为 busy 被延长", async () => {
    vi.useFakeTimers({ now: 3_000_000 });
    const refresh = vi.fn();
    const { container, root } = setupDom();
    await flush(() => renderHarness(root, { busy: false, error: null, refresh, scopeKey: "jobs", maxDurationMs: 30_000 }));
    await flush(() => click(container, "start"));
    await flush(() => renderHarness(root, { busy: true, error: null, refresh, scopeKey: "jobs", maxDurationMs: 30_000 }));

    await advance(30_000);
    expect(refresh).not.toHaveBeenCalled();
    expect(text(container, "count")).toBe("0");
    expect(text(container, "active")).toBe("false");
    expect(text(container, "reason")).toBe(BOUNDED_REFRESH_REASONS.maxDuration);
  });

  it("busy 状态不能新启动，避免与已有读取重叠", async () => {
    vi.useFakeTimers({ now: 3_500_000 });
    const refresh = vi.fn();
    const { container, root } = setupDom();
    await flush(() => renderHarness(root, { busy: true, error: null, refresh, scopeKey: "jobs" }));
    await flush(() => click(container, "start"));

    expect(text(container, "active")).toBe("false");
    expect(text(container, "reason")).toBe(BOUNDED_REFRESH_REASONS.busy);
    await advance(20_000);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("error 会拒绝/停止观察；stop 立即取消未来 tick，手动重启会重置计数", async () => {
    vi.useFakeTimers({ now: 4_000_000 });
    const refresh = vi.fn();
    const { container, root } = setupDom();
    await flush(() => renderHarness(root, { busy: false, error: new Error("503"), refresh, scopeKey: "jobs" }));
    await flush(() => click(container, "start"));
    expect(text(container, "active")).toBe("false");
    expect(text(container, "reason")).toBe(BOUNDED_REFRESH_REASONS.error);

    await flush(() => renderHarness(root, { busy: false, error: null, refresh, scopeKey: "jobs" }));
    await flush(() => click(container, "start"));
    await advance(10_000);
    expect(refresh).toHaveBeenCalledTimes(1);
    await flush(() => click(container, "stop"));
    expect(text(container, "active")).toBe("false");
    expect(text(container, "reason")).toBe(BOUNDED_REFRESH_REASONS.manual);
    expect(text(container, "count")).toBe("1");
    await advance(30_000);
    expect(refresh).toHaveBeenCalledTimes(1);

    await flush(() => click(container, "start"));
    expect(text(container, "count")).toBe("0");
    await advance(10_000);
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("页面 hidden 时拒绝 start，运行中 hidden 会停止且不会自动 resume", async () => {
    vi.useFakeTimers({ now: 5_000_000 });
    const refresh = vi.fn();
    const { container, root } = setupDom();
    setVisibility("hidden");
    await flush(() => renderHarness(root, { busy: false, error: null, refresh, scopeKey: "jobs" }));
    await flush(() => click(container, "start"));
    expect(text(container, "active")).toBe("false");
    expect(text(container, "reason")).toBe(BOUNDED_REFRESH_REASONS.hidden);

    setVisibility("visible");
    await flush(() => click(container, "start"));
    expect(text(container, "active")).toBe("true");
    setVisibility("hidden");
    await flush(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(text(container, "active")).toBe("false");
    expect(text(container, "reason")).toBe(BOUNDED_REFRESH_REASONS.hidden);
    setVisibility("visible");
    await advance(20_000);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("scopeKey 变更会停止、重置计数，旧 key 的 tick 不会在新 key commit 后运行", async () => {
    vi.useFakeTimers({ now: 6_000_000 });
    const oldRefresh = vi.fn();
    const newRefresh = vi.fn();
    const { container, root } = setupDom();
    await flush(() => renderHarness(root, { busy: false, error: null, refresh: oldRefresh, scopeKey: "old" }));
    await flush(() => click(container, "start"));
    await advance(5_000);
    await flush(() => renderHarness(root, { busy: false, error: null, refresh: newRefresh, scopeKey: "new" }));

    expect(text(container, "active")).toBe("false");
    expect(text(container, "count")).toBe("0");
    expect(text(container, "reason")).toBe(BOUNDED_REFRESH_REASONS.scopeChanged);
    await advance(20_000);
    expect(oldRefresh).not.toHaveBeenCalled();
    expect(newRefresh).not.toHaveBeenCalled();

    await flush(() => click(container, "start"));
    await advance(10_000);
    expect(newRefresh).toHaveBeenCalledTimes(1);
    expect(oldRefresh).not.toHaveBeenCalled();
  });

  it("同 scope 的新 callback 不会重置计时，并使用最新 committed refresh", async () => {
    vi.useFakeTimers({ now: 7_000_000 });
    const firstRefresh = vi.fn();
    const latestRefresh = vi.fn();
    const { container, root } = setupDom();
    await flush(() => renderHarness(root, { busy: false, error: null, refresh: firstRefresh, scopeKey: "same" }));
    await flush(() => click(container, "start"));
    await advance(5_000);
    await flush(() => renderHarness(root, { busy: false, error: null, refresh: latestRefresh, scopeKey: "same" }));
    await advance(4_999);
    expect(firstRefresh).not.toHaveBeenCalled();
    expect(latestRefresh).not.toHaveBeenCalled();
    await advance(1);
    expect(firstRefresh).not.toHaveBeenCalled();
    expect(latestRefresh).toHaveBeenCalledTimes(1);
    expect(text(container, "count")).toBe("1");
  });

  it("刷新触发后若外部 busy 持续为 true，后续 tick 不会重叠调用", async () => {
    vi.useFakeTimers({ now: 8_000_000 });
    const refresh = vi.fn();
    const { container, root } = setupDom();
    await flush(() => renderHarness(root, { busy: false, error: null, refresh, scopeKey: "jobs" }));
    await flush(() => click(container, "start"));
    await advance(10_000);
    expect(refresh).toHaveBeenCalledTimes(1);
    await flush(() => renderHarness(root, { busy: true, error: null, refresh, scopeKey: "jobs" }));
    await advance(30_000);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(text(container, "count")).toBe("1");
  });

  it("StrictMode/unmount 会清理 timeout 和 visibility listener", async () => {
    vi.useFakeTimers({ now: 9_000_000 });
    const refresh = vi.fn();
    const addSpy = vi.spyOn(document, "addEventListener");
    const removeSpy = vi.spyOn(document, "removeEventListener");
    const { container, root } = setupDom();
    await flush(() => root.render(createElement(StrictMode, {}, createElement(Harness, { busy: false, error: null, refresh, scopeKey: "jobs" }))));
    await flush(() => click(container, "start"));
    expect(addSpy.mock.calls.some((call) => call[0] === "visibilitychange")).toBe(true);
    await flush(() => root.unmount());
    roots.delete(root);
    expect(removeSpy.mock.calls.some((call) => call[0] === "visibilitychange")).toBe(true);
    await advance(60_000);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("timer 更新包在 act 中时不产生 React act warning", async () => {
    vi.useFakeTimers({ now: 10_000_000 });
    const refresh = vi.fn();
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { container, root } = setupDom();
    await flush(() => renderHarness(root, { busy: false, error: null, refresh, scopeKey: "jobs" }));
    await flush(() => click(container, "start"));
    await advance(10_000);

    expect(errorSpy.mock.calls.flat().join("\n")).not.toContain("not wrapped in act");
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});
