import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { ManagementError } from "./types";
import { useManagementClient, useManagementRuntime } from "./runtime";
import type {
  DocumentDTO,
  DocumentDiffDTO,
  EvidenceDTO,
  JobDTO,
  JobStatus,
  LineageDTO,
  Page,
  RevisionDTO,
} from "./types";

export const MANAGEMENT_PAGE_LIMIT = 20;

type QueryStatus = "loading" | "ready" | "empty" | "error";

export interface ManagementQueryState<T> {
  readonly data: T | null;
  readonly error: unknown;
  readonly refreshing: boolean;
  readonly status: QueryStatus;
  readonly reload: () => void;
}

interface QueryOptions<T> {
  // key 必须编码所有影响请求的参数；inline options/回调的引用变化不是刷新信号。
  readonly key: string;
  readonly load: (signal: AbortSignal) => Promise<T>;
  readonly isEmpty?: (value: T) => boolean;
}

type QuerySnapshot<T> = Omit<ManagementQueryState<T>, "reload"> & { readonly key: string };

export function useManagementQuery<T>({ key, load, isEmpty }: QueryOptions<T>): ManagementQueryState<T> {
  const runtime = useManagementRuntime();
  const runtimeKey = `${runtime.mode}:${runtime.status}:${key}`;
  const [reloadToken, setReloadToken] = useState(0);
  const [state, setState] = useState<QuerySnapshot<T>>({
    key: runtimeKey,
    data: null,
    error: null,
    refreshing: false,
    status: runtime.status === "error" ? "error" : "loading",
  });
  const optionsRef = useRef({ key: runtimeKey, load, isEmpty, reloadToken });
  const requestRef = useRef(0);

  useLayoutEffect(() => {
    optionsRef.current = { key: runtimeKey, load, isEmpty, reloadToken };
  });

  useEffect(() => {
    if (runtime.status === "error") {
      setState({ key: runtimeKey, data: null, error: runtime.error, refreshing: false, status: "error" });
      return undefined;
    }
    if (runtime.status === "loading" || runtime.client === null) {
      setState({ key: runtimeKey, data: null, error: null, refreshing: false, status: "loading" });
      return undefined;
    }
    const controller = new AbortController();
    const requestId = ++requestRef.current;
    const options = optionsRef.current;
    const isCurrent = () => !controller.signal.aborted && requestRef.current === requestId && optionsRef.current.key === runtimeKey && optionsRef.current.reloadToken === reloadToken;

    setState((current) => {
      const sameKey = current.key === runtimeKey;
      return {
        key: runtimeKey,
        data: sameKey ? current.data : null,
        error: null,
        refreshing: sameKey && current.data !== null,
        status: sameKey && current.data !== null ? current.status : "loading",
      };
    });

    void (async () => {
      try {
        const value = await options.load(controller.signal);
        if (!isCurrent()) return;
        setState({ key: runtimeKey, data: value, error: null, refreshing: false, status: options.isEmpty?.(value) ? "empty" : "ready" });
      } catch (error: unknown) {
        if (!isCurrent()) return;
        if (error instanceof Error && error.name === "AbortError") return;
        setState({ key: runtimeKey, data: null, error, refreshing: false, status: "error" });
      }
    })();

    return () => controller.abort();
  }, [runtime.client, runtime.error, runtime.mode, runtime.status, runtimeKey, reloadToken]);

  const reload = useCallback(() => {
    if (runtime.status !== "ready") {
      runtime.reload();
      return;
    }
    setReloadToken((value) => value + 1);
  }, [runtime]);

  if (state.key !== runtimeKey) {
    return { data: null, error: null, refreshing: false, status: runtime.status === "error" ? "error" : "loading", reload };
  }
  return { data: state.data, error: state.error, refreshing: state.refreshing, status: state.status, reload };
}

function requireClient(client: ReturnType<typeof useManagementClient>) {
  if (client === null) throw new ManagementError("unavailable");
  return client;
}

export function useJobsPage(status: JobStatus | undefined, offset: number): ManagementQueryState<Page<JobDTO>> {
  const client = useManagementClient();
  const key = useMemo(() => `jobs:${status ?? "all"}:${offset}`, [offset, status]);
  const load = useCallback(
    (signal: AbortSignal) => {
      const query = {
        limit: MANAGEMENT_PAGE_LIMIT,
        offset,
        ...(status ? { status } : {}),
      };
      return requireClient(client).listJobs(query, signal);
    },
    [client, offset, status],
  );
  return useManagementQuery({ key, load, isEmpty: (page) => page.items.length === 0 });
}

export function useJobPage(id: string): ManagementQueryState<JobDTO> {
  const client = useManagementClient();
  const key = useMemo(() => `job:${id}`, [id]);
  const load = useCallback((signal: AbortSignal) => requireClient(client).getJob(id, signal), [client, id]);
  return useManagementQuery({ key, load });
}

export function useRevisionPage(id: string): ManagementQueryState<RevisionDTO> {
  const client = useManagementClient();
  const key = useMemo(() => `revision:${id}`, [id]);
  const load = useCallback((signal: AbortSignal) => requireClient(client).getRevision(id, signal), [client, id]);
  return useManagementQuery({ key, load });
}

export function useDocumentPage(id: string, offset: number): ManagementQueryState<DocumentDTO> {
  const client = useManagementClient();
  const key = useMemo(() => `document:${id}:${offset}`, [id, offset]);
  const load = useCallback(
    (signal: AbortSignal) => requireClient(client).getDocument(id, { limit: MANAGEMENT_PAGE_LIMIT, offset }, signal),
    [client, id, offset],
  );
  return useManagementQuery({ key, load });
}

export function useLineagePage(id: string, offset: number): ManagementQueryState<LineageDTO> {
  const client = useManagementClient();
  const key = useMemo(() => `lineage:${id}:${offset}`, [id, offset]);
  const load = useCallback(
    (signal: AbortSignal) => requireClient(client).getLineage(id, { limit: MANAGEMENT_PAGE_LIMIT, offset }, signal),
    [client, id, offset],
  );
  return useManagementQuery({ key, load });
}

export function useDocumentDiffPage(
  newId: string,
  oldId: string,
  offset: number,
): ManagementQueryState<DocumentDiffDTO> {
  const client = useManagementClient();
  const key = useMemo(() => `diff:${newId}:${oldId}:${offset}`, [newId, oldId, offset]);
  const load = useCallback(
    (signal: AbortSignal) => requireClient(client).getDocumentDiff(newId, oldId, { limit: MANAGEMENT_PAGE_LIMIT, offset }, signal),
    [client, newId, oldId, offset],
  );
  return useManagementQuery({ key, load });
}

export function useEvidencePage(id: string): ManagementQueryState<EvidenceDTO> {
  const client = useManagementClient();
  const key = useMemo(() => `evidence:${id}`, [id]);
  const load = useCallback((signal: AbortSignal) => requireClient(client).getEvidence(id, signal), [client, id]);
  return useManagementQuery({ key, load });
}
