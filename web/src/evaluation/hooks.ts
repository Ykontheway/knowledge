import { useCallback, useMemo } from "react";

import { managementClient } from "../management/client";
import { MANAGEMENT_PAGE_LIMIT, useManagementQuery, type ManagementQueryState } from "../management/hooks";
import type { JobDTO, Page } from "../management/types";

export function useEvaluationJobs(offset: number): ManagementQueryState<Page<JobDTO>> {
  const key = useMemo(() => `evaluation-jobs:${offset}`, [offset]);
  const load = useCallback(
    (signal: AbortSignal) => managementClient.listJobs({ limit: MANAGEMENT_PAGE_LIMIT, offset }, signal),
    [offset],
  );
  return useManagementQuery({ key, load, isEmpty: (page) => page.items.length === 0 });
}

export interface SelectedJobs {
  readonly reference: JobDTO | null;
  readonly candidate: JobDTO | null;
}

export function useSelectedJobs(referenceId?: string, candidateId?: string): ManagementQueryState<SelectedJobs> {
  const key = useMemo(() => `evaluation-pair:${referenceId ?? "-"}:${candidateId ?? "-"}`, [candidateId, referenceId]);
  const load = useCallback(
    async (signal: AbortSignal): Promise<SelectedJobs> => {
      const [reference, candidate] = await Promise.all([
        referenceId ? managementClient.getJob(referenceId, signal) : Promise.resolve(null),
        candidateId ? managementClient.getJob(candidateId, signal) : Promise.resolve(null),
      ]);
      return { reference, candidate };
    },
    [candidateId, referenceId],
  );
  return useManagementQuery({ key, load });
}

export interface GuideJobs {
  readonly normal: JobDTO | null;
  readonly fault: JobDTO | null;
  readonly restore: JobDTO | null;
}

export function useGuideJobs(normalId?: string, faultId?: string, restoreId?: string): ManagementQueryState<GuideJobs> {
  const key = useMemo(
    () => `guide-jobs:${normalId ?? "-"}:${faultId ?? "-"}:${restoreId ?? "-"}`,
    [faultId, normalId, restoreId],
  );
  const load = useCallback(
    async (signal: AbortSignal): Promise<GuideJobs> => {
      const [normal, fault, restore] = await Promise.all([
        normalId ? managementClient.getJob(normalId, signal) : Promise.resolve(null),
        faultId ? managementClient.getJob(faultId, signal) : Promise.resolve(null),
        restoreId ? managementClient.getJob(restoreId, signal) : Promise.resolve(null),
      ]);
      return { normal, fault, restore };
    },
    [faultId, normalId, restoreId],
  );
  return useManagementQuery({ key, load });
}
