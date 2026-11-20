import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { compareJobs } from "./comparison";
import { useEvaluationJobs, useSelectedJobs } from "./hooks";
import { useBoundedRefresh } from "./useBoundedRefresh";
import {
  ComparisonTables,
  ErrorBox,
  InvalidRouteNotice,
  JobPickerList,
  JobSummaryCard,
  QueryPanel,
  SelectedPairOverview,
  type RoleKey,
} from "./components/EvaluationComponents";
import { MANAGEMENT_PAGE_LIMIT } from "../management/hooks";
import { useReplayBundle } from "../management/runtime";
import { ReplayBanner } from "../management/components/ReplayBanner";
import { evaluationHash, type EvaluationRoute } from "../management/route";

interface EvaluationPageProps {
  readonly route: EvaluationRoute;
  readonly navigate: (hash: string) => void;
}

export const EvaluationPage: React.FC<EvaluationPageProps> = ({ route, navigate }) => {
  if (route.kind === "invalid") return <InvalidRouteNotice title="评测对照链接无效" />;
  return <EvaluationCompareView navigate={navigate} route={route} />;
};

const EvaluationCompareView: React.FC<{
  readonly route: Extract<EvaluationRoute, { kind: "compare" }>;
  readonly navigate: (hash: string) => void;
}> = ({ route, navigate }) => {
  const replayBundle = useReplayBundle();
  const referenceId = route.mode === "replay" ? route.reference ?? replayBundle?.story.reference_job_id : route.reference;
  const candidateId = route.mode === "replay" ? route.candidate ?? replayBundle?.story.candidate_job_id : route.candidate;
  const list = useEvaluationJobs(route.offset);
  const pair = useSelectedJobs(referenceId, candidateId);
  const [newJobsNotice, setNewJobsNotice] = useState<string | null>(null);
  const headBeforeRefresh = useRef<string | null>(null);
  const latestHead = list.data?.items.map((job) => job.id).slice(0, 3).join(",") ?? "";
  const hasSelection = Boolean(referenceId || candidateId);
  const busy = list.status === "loading" || list.refreshing || pair.status === "loading" || pair.refreshing;

  const refreshList = useCallback(() => {
    headBeforeRefresh.current = latestHead;
    setNewJobsNotice(null);
    list.reload();
    if (hasSelection) pair.reload();
  }, [hasSelection, latestHead, list, pair]);

  const bounded = useBoundedRefresh({
    busy,
    error: list.error ?? pair.error,
    refresh: refreshList,
    scopeKey: `evaluation:${route.mode}:${route.offset}:${referenceId ?? ""}:${candidateId ?? ""}`,
  });

  useEffect(() => {
    if (headBeforeRefresh.current === null || list.status !== "ready") return;
    if (headBeforeRefresh.current !== latestHead) {
      setNewJobsNotice("检测到任务列表头部有新变化；已选参考/候选会保持不变，需要时可手动改选。");
    }
    headBeforeRefresh.current = null;
  }, [latestHead, list.status]);

  const updateRole = (role: RoleKey, id: string) => {
    if (role !== "reference" && role !== "candidate") return;
    navigate(evaluationHash({
      reference: role === "reference" ? id : referenceId,
      candidate: role === "candidate" ? id : candidateId,
      offset: route.offset,
      mode: route.mode,
    }));
  };
  const pageChange = (offset: number) => {
    bounded.stop();
    navigate(evaluationHash({ reference: referenceId, candidate: candidateId, offset, mode: route.mode }));
  };
  const comparison = useMemo(() => {
    if (!pair.data?.reference || !pair.data.candidate) return null;
    return compareJobs(pair.data.reference, pair.data.candidate);
  }, [pair.data]);
  const picker = list.data ? <JobPickerList mode={route.mode} onPageChange={pageChange} onPick={updateRole} page={list.data} roles={["reference", "candidate"]} selected={{ reference: referenceId, candidate: candidateId }} /> : null;

  return (
    <div className="space-y-5" aria-live="polite">
      {route.mode === "replay" ? <ReplayBanner /> : null}
      <QueryPanel
        description={route.mode === "replay"
          ? "纯只读读取静态回放 bundle。参考/候选默认来自故事线显式 job ID，不会观察新任务，也不会把离线结果当作实时监控。"
          : "纯只读读取真实评测任务。参考任务不是已接受 baseline；跨时刻结果仅用于观察，数值可升可降，页面不自动判断原因。"}
        error={list.error}
        loading={list.status === "loading" && !list.refreshing}
        mode={route.mode}
        onRefresh={refreshList}
        refreshing={list.refreshing || pair.refreshing}
        title="评测对照"
      >
        <div className="rounded-2xl border border-slate-200 bg-white p-4 text-sm leading-6 text-slate-600 shadow-sm">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <p>{route.mode === "replay" ? "列表每页 20 条，分页与角色选择都会保留 #replay 前缀。URL 未显式选择时，会优先使用 bundle.story 中的 reference / candidate job。" : `列表每页 ${MANAGEMENT_PAGE_LIMIT} 条。请选择参考任务和候选任务；跨页选择会保存在 URL，并按所选 ID 重新读取任务详情，避免用列表摘要做对照。`}</p>
            {route.mode === "replay" ? <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-900">静态回放不会启动 observer 定时器，也不会探测实时新任务。</div> : <div className="flex flex-wrap gap-2"><button className="rounded-lg border border-[#d39b3b] px-3 py-1.5 font-semibold text-[#1f2a44]" onClick={bounded.start} type="button">观察新任务（5分钟）</button>{bounded.active ? <button className="rounded-lg border border-slate-300 px-3 py-1.5 font-semibold" onClick={bounded.stop} type="button">停止观察</button> : null}</div>}
          </div>
          <p className="mt-2 text-xs text-slate-500">{route.mode === "replay" ? "模式：静态回放，仅合成公开语料，不会请求 /v1 live API。" : `观察状态：${bounded.active ? `开启，剩余 ${bounded.remainingSeconds}s，已刷新 ${bounded.refreshCount} 次` : bounded.reason ?? "未开启"}`}</p>
        </div>
        {route.mode === "replay" ? null : newJobsNotice ? <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900" role="status">{newJobsNotice}</div> : null}
        {hasSelection ? null : picker}
      </QueryPanel>

      {hasSelection ? <SelectedPairOverview candidate={pair.data?.candidate ?? null} mode={route.mode} reference={pair.data?.reference ?? null} /> : null}
      {pair.error ? <ErrorBox error={pair.error} mode={route.mode} onRetry={pair.reload} /> : null}
      {pair.status === "loading" && hasSelection ? <div className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-600">正在读取选中任务详情……</div> : null}
      {comparison ? <ComparisonTables comparison={comparison} /> : <div className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-600">请选择两侧任务后再查看 delta。dataset pin 和 config fingerprint 完全一致时才输出 delta；null 一律显示为未评估。</div>}

      {hasSelection ? (
        <details className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <summary className="cursor-pointer text-sm font-semibold text-slate-900">查看完整任务元数据</summary>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <JobSummaryCard job={pair.data?.reference ?? null} mode={route.mode} title="参考任务" />
            <JobSummaryCard job={pair.data?.candidate ?? null} mode={route.mode} title="候选任务" />
          </div>
        </details>
      ) : null}
      {hasSelection && picker ? <section className="space-y-3" aria-label="更换参考或候选任务"><h3 className="text-lg font-semibold text-slate-900">更换任务</h3>{picker}</section> : null}
    </div>
  );
};
