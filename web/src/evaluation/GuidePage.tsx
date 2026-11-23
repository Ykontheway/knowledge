import React, { useCallback, useMemo, useState } from "react";

import { compareJobs } from "./comparison";
import { useEvaluationJobs, useGuideJobs } from "./hooks";
import {
  ErrorBox,
  InvalidRouteNotice,
  JobPickerList,
  JobSummaryCard,
  QueryPanel,
  type RoleKey,
} from "./components/EvaluationComponents";
import { useReplayBundle } from "../management/runtime";
import { evaluationHash, guideHash, type GuideRoute } from "../management/route";
import { ReplayBanner } from "../management/components/ReplayBanner";
import { HashLink } from "../management/components/HashLink";
import type { JobDTO } from "../management/types";

interface GuidePageProps {
  readonly route: GuideRoute;
  readonly navigate: (hash: string) => void;
}

export const GuidePage: React.FC<GuidePageProps> = ({ route, navigate }) => {
  if (route.kind === "invalid") return <InvalidRouteNotice title="使用导览链接无效" />;
  return <GuideStepsView navigate={navigate} route={route} />;
};

const GuideStepsView: React.FC<{
  readonly route: Extract<GuideRoute, { kind: "steps" }>;
  readonly navigate: (hash: string) => void;
}> = ({ route, navigate }) => {
  const replayBundle = useReplayBundle();
  const resolvedNormal = route.mode === "replay" ? route.normal ?? replayBundle?.story.reference_job_id : route.normal;
  const resolvedFault = route.mode === "replay" ? route.fault ?? replayBundle?.story.candidate_job_id : route.fault;
  const resolvedRestore = route.mode === "replay" ? route.restore ?? replayBundle?.story.recovery_job_id : route.restore;
  const resolvedSelection = { normal: resolvedNormal, fault: resolvedFault, restore: resolvedRestore };
  const list = useEvaluationJobs(route.offset);
  const stages = useGuideJobs(resolvedNormal, resolvedFault, resolvedRestore);
  const [openStep, setOpenStep] = useState(0);
  const hasSelection = Boolean(resolvedNormal || resolvedFault || resolvedRestore);
  const updateRole = (role: RoleKey, id: string) => {
    if (role !== "normal" && role !== "fault" && role !== "restore") return;
    navigate(
      guideHash({
        normal: role === "normal" ? id : resolvedNormal,
        fault: role === "fault" ? id : resolvedFault,
        restore: role === "restore" ? id : resolvedRestore,
        offset: route.offset,
        mode: route.mode,
      }),
    );
  };
  const refreshGuide = useCallback(() => {
    list.reload();
    if (hasSelection) stages.reload();
  }, [hasSelection, list, stages]);
  const validation = useMemo(
    () => validateGuide(stages.data?.normal ?? null, stages.data?.fault ?? null, stages.data?.restore ?? null, route.mode),
    [route.mode, stages.data],
  );
  const picker = list.data ? (
    <JobPickerList
      mode={route.mode}
      onPageChange={(offset) =>
        navigate(
          guideHash({
            normal: resolvedNormal,
            fault: resolvedFault,
            restore: resolvedRestore,
            offset,
            mode: route.mode,
          }),
        )
      }
      onPick={updateRole}
      page={list.data}
      roles={["normal", "fault", "restore"]}
      selected={resolvedSelection}
    />
  ) : null;
  const steps =
    route.mode === "replay"
      ? [
          { title: "正常阶段", body: "回放默认指向 bundle.story.reference_job_id，对应通过的基线任务。" },
          { title: "故障阶段", body: "回放默认指向 bundle.story.candidate_job_id，对应 QUALITY_GATE_FAILED 的失败任务。" },
          { title: "恢复阶段", body: "回放默认指向 bundle.story.recovery_job_id，对应恢复后再次通过的任务。" },
        ]
      : [
          { title: "正常阶段", body: "确认初始检索质量门禁通过，并记录触发 revision。" },
          { title: "故障阶段", body: "隔离验收库更新后刷新，选择 QUALITY_GATE_FAILED 的失败任务。" },
          { title: "恢复阶段", body: "授权 CLI 修复后刷新，选择再次通过的任务。" },
        ];

  return (
    <div className="space-y-5" aria-live="polite">
      {route.mode === "replay" ? <ReplayBanner /> : null}
      <QueryPanel
        description={
          route.mode === "replay"
            ? "静态回放从 replay.json 读取三阶段故事，页面只读、非实时，不会请求 live API，也不会把 pass/fail/pass 直接当成因果结论。"
            : "由用户手动选择正常、故障、恢复三阶段。页面只读展示，不按时间顺序自动填充，也不把 pass/fail/pass 直接当成故障注入结论；条件满足后仍需核验 CLI 实操。"
        }
        error={list.error}
        loading={list.status === "loading" && !list.refreshing}
        mode={route.mode}
        onRefresh={refreshGuide}
        refreshing={list.refreshing || stages.refreshing}
        title="使用导览"
      >
        <div className="rounded-2xl border border-slate-200 bg-white p-4 text-sm leading-6 text-slate-600 shadow-sm">
          <p className="font-semibold text-slate-900">操作说明</p>
          {route.mode === "replay" ? (
            <>
              <p>回放模式使用父流程生成的静态 bundle，默认带入 normal / fault / restore 三阶段，可继续切换到同一 bundle 中的其他任务。</p>
              <p className="mt-2">页面不会执行命令、拼接本机路径、展示原始查询参数，也不会写入任何数据；如缺少 replay.json，请先由父流程生成 web/public/replay.json。</p>
            </>
          ) : (
            <>
              <p>在隔离验收库中使用已授权的 CLI 完成更新，再回到本页刷新并手动选择对应阶段。</p>
              <p className="mt-2">页面不会执行命令、拼接本机路径、展示原始查询参数，也不会写入任何数据。无数据时，请先按真实库启动文档启动管理服务和后端。</p>
            </>
          )}
        </div>
        {hasSelection ? null : picker}
      </QueryPanel>

      {stages.error ? <ErrorBox error={stages.error} mode={route.mode} onRetry={stages.reload} /> : null}
      {stages.status === "loading" && hasSelection ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-600">
          {route.mode === "replay" ? "正在读取回放三阶段详情……" : "正在读取已选阶段详情……"}
        </div>
      ) : null}
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">阶段判定</h3>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-6 text-slate-600">
          {validation.messages.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
        <p className="mt-3 text-sm text-slate-600">no-answer、stale、citation 解释来自评测汇总与检查项，只能帮助定位触发变更，不自动认定原因。</p>
        {validation.ready ? (
          <div className="mt-4 flex flex-wrap gap-3 text-sm">
            <HashLink href={evaluationHash({ reference: resolvedNormal, candidate: resolvedFault, mode: route.mode })}>对照 normal → fault</HashLink>
            <HashLink href={evaluationHash({ reference: resolvedFault, candidate: resolvedRestore, mode: route.mode })}>对照 fault → restore</HashLink>
          </div>
        ) : null}
      </section>
      {hasSelection ? (
        <details className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <summary className="cursor-pointer text-sm font-semibold text-slate-900">查看三阶段任务元数据</summary>
          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <JobSummaryCard job={stages.data?.normal ?? null} mode={route.mode} title="正常阶段" />
            <JobSummaryCard job={stages.data?.fault ?? null} mode={route.mode} title="故障阶段" />
            <JobSummaryCard job={stages.data?.restore ?? null} mode={route.mode} title="恢复阶段" />
          </div>
        </details>
      ) : null}
      <section className="space-y-3">
        {steps.map((step, index) => (
          <article className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" key={step.title}>
            <button className="flex w-full items-center justify-between text-left font-semibold text-slate-900" onClick={() => setOpenStep(openStep === index ? -1 : index)} type="button"><span>{step.title}</span><span>{openStep === index ? "收起" : "展开"}</span></button>
            {openStep === index ? <div className="mt-3 text-sm leading-6 text-slate-600"><p>{step.body}</p><button className="mt-3 rounded-lg border border-slate-300 px-3 py-1.5 font-semibold" onClick={() => setOpenStep(Math.min(index + 1, 2))} type="button">下一步</button></div> : null}
          </article>
        ))}
      </section>
      {hasSelection && picker ? <section className="space-y-3" aria-label="更换已选阶段"><h3 className="text-lg font-semibold text-slate-900">更换阶段</h3>{picker}</section> : null}
    </div>
  );
};

function validateGuide(
  normal: JobDTO | null,
  fault: JobDTO | null,
  restore: JobDTO | null,
  mode: "live" | "replay",
): { readonly ready: boolean; readonly messages: readonly string[] } {
  const messages: string[] = [];
  if (!normal || !fault || !restore) {
    return {
      ready: false,
      messages: [mode === "replay" ? "回放 bundle 未提供完整的 normal / fault / restore 三阶段任务。" : "请先从同一真实任务列表手动选择正常、故障、恢复三阶段。"],
    };
  }
  if (normal.status !== "passed") messages.push("正常阶段必须是 passed。角色不满足时只展示安全提示，不讲故事。");
  if (fault.status !== "failed" || fault.error_code !== "QUALITY_GATE_FAILED") messages.push("故障阶段必须是 failed 且 error_code 为 QUALITY_GATE_FAILED。");
  if (restore.status !== "passed") messages.push("恢复阶段必须是 passed。");
  if (Date.parse(normal.evaluated_at) > Date.parse(fault.evaluated_at) || Date.parse(fault.evaluated_at) > Date.parse(restore.evaluated_at)) messages.push("三阶段评测时间顺序不成立，不能用于三阶段对照。");
  if (normal.knowledge_fingerprint === fault.knowledge_fingerprint || fault.knowledge_fingerprint === restore.knowledge_fingerprint) messages.push("相邻阶段 knowledge_fingerprint 未变化；请核验是否真的对应知识更新/恢复。");
  if (fault.trigger_revision_ids.length === 0 || restore.trigger_revision_ids.length === 0) messages.push("故障或恢复阶段缺少 trigger revision，无法链接触发变更。");
  const first = compareJobs(normal, fault);
  const second = compareJobs(fault, restore);
  if (!first.comparable) messages.push(`normal→fault 暂不可对照：${first.reasons.join("；")}`);
  if (!second.comparable) messages.push(`fault→restore 暂不可对照：${second.reasons.join("；")}`);
  const ready = messages.length === 0;
  return {
    ready,
    messages: ready
      ? [
          mode === "replay"
            ? "三阶段满足回放故事条件：正常 passed、故障 QUALITY_GATE_FAILED、恢复 passed、两两可对照、时间顺序成立，并能链接 trigger revision。页面仅做静态展示，不能声明因果。"
            : "三阶段满足已选择的阶段对照条件：正常 passed、故障 QUALITY_GATE_FAILED、恢复 passed、两两可对照、时间顺序成立，并能链接 trigger revision。仍请核验 CLI 实操，不能声明因果。",
          ...[...new Set([...fault.trigger_revision_ids, ...restore.trigger_revision_ids])].map((id) => `触发 revision：${id}`),
        ]
      : messages,
  };
}
