import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { managementClient } from "./client";
import { type ManagementClient } from "./client";
import { type ManagementMode } from "./mode";
import { createReplayClient, loadReplayBundle, type ReplayBundle } from "./replay";

interface RuntimeValue {
  readonly mode: ManagementMode;
  readonly status: "ready" | "loading" | "error";
  readonly client: ManagementClient | null;
  readonly error: unknown;
  readonly bundle: ReplayBundle | null;
  readonly reload: () => void;
}

const noop = () => undefined;
const liveRuntime: RuntimeValue = {
  mode: "live",
  status: "ready",
  client: managementClient,
  error: null,
  bundle: null,
  reload: noop,
};

const replayLoadingRuntime: Omit<RuntimeValue, "reload"> = {
  mode: "replay",
  status: "loading",
  client: null,
  error: null,
  bundle: null,
};

const ManagementRuntimeContext = createContext<RuntimeValue>(liveRuntime);

export const ManagementRuntimeProvider: React.FC<{
  readonly mode: ManagementMode;
  readonly children: React.ReactNode;
}> = ({ mode, children }) => {
  const [reloadToken, setReloadToken] = useState(0);
  const [state, setState] = useState<Omit<RuntimeValue, "reload">>(() => (mode === "replay" ? replayLoadingRuntime : liveRuntime));

  useEffect(() => {
    if (mode !== "replay") {
      setState(liveRuntime);
      return undefined;
    }
    const controller = new AbortController();
    setState(replayLoadingRuntime);
    void loadReplayBundle(controller.signal)
      .then((bundle) => {
        if (controller.signal.aborted) return;
        setState({ mode: "replay", status: "ready", client: createReplayClient(bundle), error: null, bundle });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ mode: "replay", status: "error", client: null, error, bundle: null });
      });
    return () => controller.abort();
  }, [mode, reloadToken]);

  const reload = useCallback(() => {
    if (mode === "replay") setReloadToken((value) => value + 1);
  }, [mode]);

  const value = useMemo<RuntimeValue>(() => {
    if (mode !== "replay") return liveRuntime;
    const replayState = state.mode === "replay" ? state : replayLoadingRuntime;
    return { ...replayState, reload };
  }, [mode, reload, state]);
  return <ManagementRuntimeContext.Provider value={value}>{children}</ManagementRuntimeContext.Provider>;
};

export function useManagementRuntime(): RuntimeValue {
  return useContext(ManagementRuntimeContext);
}

export function useManagementClient(): ManagementClient | null {
  return useManagementRuntime().client;
}

export function useReplayBundle(): ReplayBundle | null {
  const runtime = useManagementRuntime();
  return runtime.mode === "replay" && runtime.status === "ready" ? runtime.bundle : null;
}
