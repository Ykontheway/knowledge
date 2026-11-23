import React, { useMemo } from "react";

import { formatFull, shortId } from "../../lib/format";
import { evaluationHash, guideHash, lifecycleEntryHash, lifecycleJobHash } from "../route";
import { StatusBadge } from "./StatusBadge";
import { HashLink } from "./HashLink";
import { useReplayBundle } from "../runtime";

export const ReplayBanner: React.FC = () => {
  const bundle = useReplayBundle();
  const storyJobs = useMemo(() => {
    if (!bundle) return [];
    const byId = new Map(bundle.resources.jobs.map((job) => [job.id, job] as const));
    return [
      { label: "正常阶段", job: byId.get(bundle.story.reference_job_id)! },
      { label: "故障阶段", job: byId.get(bundle.story.candidate_job_id)! },
      { label: "恢复阶段", job: byId.get(bundle.story.recovery_job_id)! },
    ];
  }, [bundle]);

  if (!bundle) return null;
  return (
    <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 text-sm leading-6 text-blue-950 shadow-sm">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="space-y-2">
          <p className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-700">静态回放 · 非实时 / 仅合成公开语料</p>
          <h2 className="text-2xl font-semibold text-slate-900">回放预览</h2>
          <p className="max-w-4xl text-sm text-slate-700">
            当前页面只读取静态 replay.json，不请求 /v1 管理 API，不自动观察新任务，也不会回退到 fixture。所有深链接和分页都会保留 #replay 前缀。
          </p>
          <p className="text-xs text-slate-600">snapshot generated_at：{formatFull(bundle.generated_at)}</p>
        </div>
        <div className="rounded-xl border border-blue-200 bg-white/80 px-4 py-3 text-xs text-slate-700">
          <div className="font-semibold text-slate-900">快速入口</div>
          <div className="mt-2 flex flex-wrap gap-3">
            <HashLink href={guideHash({ mode: "replay" })}>三阶段导览</HashLink>
            <HashLink href={evaluationHash({ mode: "replay", reference: bundle.story.reference_job_id, candidate: bundle.story.candidate_job_id })}>normal → fault</HashLink>
            <HashLink href={evaluationHash({ mode: "replay", reference: bundle.story.candidate_job_id, candidate: bundle.story.recovery_job_id })}>fault → restore</HashLink>
            <HashLink href={lifecycleEntryHash({ mode: "replay" })}>任务时间线</HashLink>
          </div>
        </div>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        {storyJobs.map(({ label, job }) => (
          <article className="rounded-xl border border-blue-200 bg-white p-4" key={label}>
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <StatusBadge compact status={job.status} />
              <HashLink href={lifecycleJobHash(job.id, { mode: "replay" })}>job {shortId(job.id)}</HashLink>
            </div>
            <div className="mt-2 text-xs text-slate-600">{formatFull(job.evaluated_at)}</div>
            <div className="mt-2 break-all font-mono text-xs text-slate-600">dataset {job.dataset_id} v{job.dataset_version}</div>
          </article>
        ))}
      </div>
    </section>
  );
};
