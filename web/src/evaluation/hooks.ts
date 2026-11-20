import { useCallback, useMemo } from "react";

import { ManagementError } from "../management/types";
import { useManagementClient } from "../management/runtime";
import { MANAGEMENT_PAGE_LIMIT, useManagementQuery, type ManagementQueryState } from "../management/hooks";
import type { JobDTO, Page } from "../management/types";

function requireClient(client: ReturnType<typeof useManagementClient>) {
  if (client === null) throw new ManagementError("unavailable");
  return client;
}

export function useEvaluationJobs(offset: number): ManagementQueryState<Page<JobDTO>> {
  const client = useManagementClient();
  const key = useMemo(() => `evaluation-jobs:${offset}`, [offset]);
  const load = useCallback(
    (signal: AbortSignal) => requireClient(client).listJobs({ limit: MANAGEMENT_PAGE_LIMIT, offset }, signal),
    [client, offset],
  );
  return useManagementQuery({ key, load, isEmpty: (page) => page.items.length === 0 });
}

export interface SelectedJobs {
  readonly reference: JobDTO | null;
  readonly candidate: JobDTO | null;
}

export function useSelectedJobs(referenceId?: string, candidateId?: string): ManagementQueryState<SelectedJobs> {
  const client = useManagementClient();
  const key = useMemo(() => `evaluation-pair:${referenceId ?? "-"}:${candidateId ?? "-"}`, [candidateId, referenceId]);
  const load = useCallback(
    async (signal: AbortSignal): Promise<SelectedJobs> => {
      const resolved = requireClient(client);
      const [reference, candidate] = await Promise.all([
        referenceId ? resolved.getJob(referenceId, signal) : Promise.resolve(null),
        candidateId ? resolved.getJob(candidateId, signal) : Promise.resolve(null),
      ]);
      return { reference, candidate };
    },
    [candidateId, client, referenceId],
  );
  return useManagementQuery({ key, load });
}

export interface GuideJobs {
  readonly normal: JobDTO | null;
  readonly fault: JobDTO | null;
  readonly restore: JobDTO | null;
}

export function useGuideJobs(normalId?: string, faultId?: string, restoreId?: string): ManagementQueryState<GuideJobs> {
  const client = useManagementClient();
  const key = useMemo(
    () => `guide-jobs:${normalId ?? "-"}:${faultId ?? "-"}:${restoreId ?? "-"}`,
    [faultId, normalId, restoreId],
  );
  const load = useCallback(
    async (signal: AbortSignal): Promise<GuideJobs> => {
      const resolved = requireClient(client);
      const [normal, fault, restore] = await Promise.all([
        normalId ? resolved.getJob(normalId, signal) : Promise.resolve(null),
        faultId ? resolved.getJob(faultId, signal) : Promise.resolve(null),
        restoreId ? resolved.getJob(restoreId, signal) : Promise.resolve(null),
      ]);
      return { normal, fault, restore };
    },
    [client, faultId, normalId, restoreId],
  );
  return useManagementQuery({ key, load });
}
