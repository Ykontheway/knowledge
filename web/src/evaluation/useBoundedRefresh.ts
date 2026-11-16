import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

const DEFAULT_INTERVAL_MS = 10_000;
const DEFAULT_DURATION_MS = 5 * 60_000;
const DEFAULT_MAX_REFRESH_COUNT = 30;
const REMAINING_TICK_MS = 1_000;

export const BOUNDED_REFRESH_REASONS = {
  maxDuration: "已到5分钟观察上限",
  hidden: "页面已隐藏，观察已停止",
  error: "服务读取失败，观察已停止",
  manual: "已手动停止",
  busy: "当前读取中，请稍后开启观察",
  scopeChanged: "观察范围已变化，观察已停止",
} as const;

type StopReason = (typeof BOUNDED_REFRESH_REASONS)[keyof typeof BOUNDED_REFRESH_REASONS];

export interface UseBoundedRefreshArgs {
  readonly busy: boolean;
  readonly error: unknown;
  readonly refresh: () => void;
  readonly scopeKey: string;
  /** Test-only tightening knobs: interval can only stay at/above the production default. */
  readonly intervalMs?: number;
  readonly maxDurationMs?: number;
  readonly maxRefreshCount?: number;
}

export interface BoundedRefreshState {
  readonly active: boolean;
  readonly reason: string | null;
  readonly refreshCount: number;
  readonly remainingSeconds: number;
  readonly start: () => void;
  readonly stop: () => void;
}

interface RuntimeState {
  readonly active: boolean;
  readonly reason: string | null;
  readonly refreshCount: number;
  readonly remainingSeconds: number;
}

interface CommittedArgs {
  readonly busy: boolean;
  readonly error: unknown;
  readonly refresh: () => void;
  readonly scopeKey: string;
  readonly intervalMs: number;
  readonly maxDurationMs: number;
  readonly maxRefreshCount: number;
}

function safePositiveInteger(value: number | undefined, fallback: number, mode: "min-default" | "max-default") {
  if (value === undefined || !Number.isFinite(value)) return fallback;
  const integer = Math.floor(value);
  if (integer <= 0) return fallback;
  return mode === "min-default" ? Math.max(fallback, integer) : Math.min(fallback, integer);
}

function normalizeArgs(args: UseBoundedRefreshArgs): CommittedArgs {
  return {
    busy: args.busy,
    error: args.error,
    refresh: args.refresh,
    scopeKey: args.scopeKey,
    intervalMs: safePositiveInteger(args.intervalMs, DEFAULT_INTERVAL_MS, "min-default"),
    maxDurationMs: safePositiveInteger(args.maxDurationMs, DEFAULT_DURATION_MS, "max-default"),
    maxRefreshCount: safePositiveInteger(args.maxRefreshCount, DEFAULT_MAX_REFRESH_COUNT, "max-default"),
  };
}

function visibleDocument() {
  if (typeof document === "undefined") return true;
  return document.visibilityState !== "hidden";
}

function remainingSeconds(deadlineMs: number) {
  return Math.max(0, Math.ceil((deadlineMs - Date.now()) / 1_000));
}

export function useBoundedRefresh(args: UseBoundedRefreshArgs): BoundedRefreshState {
  const [state, setState] = useState<RuntimeState>({
    active: false,
    reason: null,
    refreshCount: 0,
    remainingSeconds: 0,
  });
  const stateRef = useRef(state);
  const committedRef = useRef<CommittedArgs>(normalizeArgs(args));
  const generationRef = useRef(0);
  const deadlineRef = useRef(0);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const remainingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const updateState = useCallback((next: RuntimeState | ((current: RuntimeState) => RuntimeState)) => {
    const value = typeof next === "function" ? (next as (current: RuntimeState) => RuntimeState)(stateRef.current) : next;
    stateRef.current = value;
    setState(value);
  }, []);

  const clearTimers = useCallback(() => {
    if (refreshTimerRef.current !== null) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
    if (remainingTimerRef.current !== null) {
      clearTimeout(remainingTimerRef.current);
      remainingTimerRef.current = null;
    }
  }, []);

  const stopInternal = useCallback((reason: StopReason, resetCount = false) => {
    generationRef.current += 1;
    clearTimers();
    deadlineRef.current = 0;
    updateState((current) => ({
      active: false,
      reason,
      refreshCount: resetCount ? 0 : current.refreshCount,
      remainingSeconds: 0,
    }));
  }, [clearTimers, updateState]);

  const scheduleRemaining = useCallback((generation: number) => {
    if (remainingTimerRef.current !== null) clearTimeout(remainingTimerRef.current);
    remainingTimerRef.current = setTimeout(() => {
      remainingTimerRef.current = null;
      if (generationRef.current !== generation || !stateRef.current.active) return;
      const seconds = remainingSeconds(deadlineRef.current);
      if (seconds <= 0) {
        stopInternal(BOUNDED_REFRESH_REASONS.maxDuration);
        return;
      }
      updateState((current) => ({ ...current, remainingSeconds: seconds }));
      scheduleRemaining(generation);
    }, REMAINING_TICK_MS);
  }, [stopInternal, updateState]);

  const scheduleRefresh = useCallback((generation: number) => {
    if (refreshTimerRef.current !== null) clearTimeout(refreshTimerRef.current);
    const committed = committedRef.current;
    const delayMs = Math.min(committed.intervalMs, Math.max(0, deadlineRef.current - Date.now()));
    refreshTimerRef.current = setTimeout(() => {
      refreshTimerRef.current = null;
      if (generationRef.current !== generation || !stateRef.current.active) return;
      const latest = committedRef.current;
      if (latest.scopeKey !== committed.scopeKey) return;
      if (!visibleDocument()) {
        stopInternal(BOUNDED_REFRESH_REASONS.hidden);
        return;
      }
      if (latest.error !== null && latest.error !== undefined) {
        stopInternal(BOUNDED_REFRESH_REASONS.error);
        return;
      }
      if (Date.now() > deadlineRef.current) {
        stopInternal(BOUNDED_REFRESH_REASONS.maxDuration);
        return;
      }
      if (latest.busy) {
        scheduleRefresh(generation);
        return;
      }

      latest.refresh();
      const nextCount = stateRef.current.refreshCount + 1;
      updateState((current) => ({
        ...current,
        refreshCount: nextCount,
        remainingSeconds: remainingSeconds(deadlineRef.current),
      }));
      if (nextCount >= latest.maxRefreshCount || Date.now() >= deadlineRef.current) {
        stopInternal(BOUNDED_REFRESH_REASONS.maxDuration);
        return;
      }
      scheduleRefresh(generation);
    }, delayMs);
  }, [stopInternal, updateState]);

  useLayoutEffect(() => {
    const next = normalizeArgs(args);
    const previous = committedRef.current;
    if (previous.scopeKey !== next.scopeKey) {
      stopInternal(BOUNDED_REFRESH_REASONS.scopeChanged, true);
    }
    committedRef.current = next;
    if (stateRef.current.active && next.error !== null && next.error !== undefined) {
      stopInternal(BOUNDED_REFRESH_REASONS.error);
    }
  });

  const start = useCallback(() => {
    const committed = committedRef.current;
    if (!visibleDocument()) {
      stopInternal(BOUNDED_REFRESH_REASONS.hidden, true);
      return;
    }
    if (committed.error !== null && committed.error !== undefined) {
      stopInternal(BOUNDED_REFRESH_REASONS.error, true);
      return;
    }
    if (committed.busy) {
      stopInternal(BOUNDED_REFRESH_REASONS.busy, true);
      return;
    }

    generationRef.current += 1;
    const generation = generationRef.current;
    clearTimers();
    deadlineRef.current = Date.now() + committed.maxDurationMs;
    updateState({
      active: true,
      reason: null,
      refreshCount: 0,
      remainingSeconds: remainingSeconds(deadlineRef.current),
    });
    scheduleRefresh(generation);
    scheduleRemaining(generation);
  }, [clearTimers, scheduleRefresh, scheduleRemaining, stopInternal, updateState]);

  const stop = useCallback(() => {
    stopInternal(BOUNDED_REFRESH_REASONS.manual);
  }, [stopInternal]);

  const onVisibilityChange = useCallback(() => {
    if (stateRef.current.active && !visibleDocument()) {
      stopInternal(BOUNDED_REFRESH_REASONS.hidden);
    }
  }, [stopInternal]);

  useEffect(() => {
    if (!state.active || typeof document === "undefined") return undefined;
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
  }, [onVisibilityChange, state.active]);

  useEffect(() => () => {
    generationRef.current += 1;
    clearTimers();
  }, [clearTimers]);

  return { ...state, start, stop };
}
