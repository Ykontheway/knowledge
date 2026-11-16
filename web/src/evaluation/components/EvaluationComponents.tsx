import React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

import { formatFull, shortId } from "../../lib/format";
import { lifecycleJobHash, lifecycleRevisionHash } from "../../management/route";
import type { JobDTO, Page } from "../../management/types";
import { getManagementErrorMessage } from "../../management/types";
import { HashLink } from "../../management/components/HashLink";
import { PaginationBar } from "../../management/components/PaginationBar";
import { StatusBadge, statusLabel } from "../../management/components/StatusBadge";
import { formatMetricDelta, formatMetricValue, type CheckComparison, type JobComparison, type MetricComparison } from "../comparison";

export type RoleKey = "reference" | "candidate" | "normal" | "fault" | "restore";

const ROLE_LABELS: Record<RoleKey, string> = {
  reference: "参考任务",
  candidate: "候选任务",
  normal: "正常阶段",
  fault: "故障阶段",
  restore: "恢复阶段",
};

const HIGHLIGHT_METRICS = new Set(["mean_recall", "mean_reciprocal_rank", "no_answer_accuracy", "citation_coverage", "stale_hits"]);

export const InvalidRouteNotice: React.FC<{ readonly title: string }> = ({ title }) => (
  <section className="rounded-2xl border border-amber-200 bg-amber-50 p-6 text-sm leading-6 text-amber-900" role="alert">
    <h2 className="text-lg font-semibold text-amber-950">{title}</h2>
    <p className="mt-2">链接包含重复查询、未知参数、非法 UUID、多余问号或编码路径。页面已停在只读安全提示，不会请求数据，也不会回显原始 hash。</p>
  </section>
);

export const QueryPanel: React.FC<{
  readonly title: string;
  readonly description: string;
  readonly loading: boolean;
  readonly refreshing: boolean;
  readonly error: unknown;
  readonly onRefresh: () => void;
  readonly children: React.ReactNode;
}> = ({ title, description, loading, refreshing, error, onRefresh, children }) => (
  <section className="space-y-4">
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          <p className="text-sm font-semibold uppercase tracking-[0.16em] text-[#d39b3b]">实时工作台 / 只读</p>
          <h2 className="text-2xl font-semibold text-slate-900">{title}</h2>
          <p className="max-w-4xl text-sm leading-6 text-slate-600">{description}</p>
        </div>
        <button className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#1f2a44] px-4 py-2 text-sm font-semibold text-[#f4efe6] hover:bg-[#2d3b5a] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#d39b3b]" onClick={onRefresh} type="button">
          <RefreshCw className={refreshing ? "animate-spin" : ""} size={16} />
          <span>{refreshing ? "刷新中" : "刷新"}</span>
        </button>
      </div>
    </div>
    {error ? <ErrorBox error={error} onRetry={onRefresh} /> : loading ? <div className="rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-600">正在读取真实任务列表……</div> : children}
  </section>
);

export const ErrorBox: React.FC<{ readonly error: unknown; readonly onRetry: () => void }> = ({ error, onRetry }) => (
  <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900" role="alert">
    <div className="flex items-start gap-3">
      <AlertTriangle className="mt-0.5 flex-shrink-0" size={18} />
      <div>
        <div className="font-semibold">管理服务暂不可用</div>
        <p>{getManagementErrorMessage(error)}页面不会改用示例数据；请确认真实库服务后重试。</p>
        <button className="mt-3 rounded-lg border border-amber-300 bg-white px-3 py-1.5 font-semibold" onClick={onRetry} type="button">重试</button>
      </div>
    </div>
  </div>
);

export const JobPickerList: React.FC<{
  readonly page: Page<JobDTO>;
  readonly selected: Partial<Record<RoleKey, string | undefined>>;
  readonly roles: readonly RoleKey[];
  readonly onPick: (role: RoleKey, id: string) => void;
  readonly onPageChange: (offset: number) => void;
}> = ({ page, selected, roles, onPick, onPageChange }) => (
  <div className="space-y-4">
    <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-3">任务</th>
            <th className="px-4 py-3">时间 / 配置</th>
            <th className="px-4 py-3">选择角色</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {page.items.map((job) => (
            <tr key={job.id} className="align-top">
              <td className="px-4 py-4"><JobTiny job={job} /></td>
              <td className="px-4 py-4 text-slate-600">
                <div>{formatFull(job.evaluated_at)}</div>
                <div className="break-all font-mono text-xs">dataset {job.dataset_id} v{job.dataset_version}</div>
                <div className="break-all font-mono text-xs">config {job.config_fingerprint}</div>
              </td>
              <td className="px-4 py-4">
                <div className="flex flex-wrap gap-2">
                  {roles.map((role) => (
                    <button aria-label={`选为${ROLE_LABELS[role]}`} className={`rounded-lg border px-3 py-1.5 font-semibold ${selected[role] === job.id ? "border-[#d39b3b] bg-amber-50 text-amber-900" : "border-slate-300 bg-white text-slate-700"}`} key={role} onClick={() => onPick(role, job.id)} type="button">选为{ROLE_LABELS[role]}</button>
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    {page.items.length === 0 ? <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-600">暂无真实任务。请先启动管理服务和真实库，再刷新本页。</div> : null}
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><PaginationBar page={page} onPageChange={onPageChange} /></div>
  </div>
);

export const JobSummaryCard: React.FC<{ readonly title: string; readonly job: JobDTO | null }> = ({ title, job }) => (
  <article className="min-w-0 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
    <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
    {job ? (
      <div className="mt-3 space-y-3 text-sm text-slate-600">
        <JobTiny job={job} />
        <p>状态：<StatusBadge compact status={job.status} /> {job.status === "blocked" || job.status === "superseded" ? "这类任务只作为历史观测展示，不解释数值变化原因。" : null}</p>
        <dl className="grid gap-2">
          <Info label="评测时间" value={formatFull(job.evaluated_at)} />
          <Info label="配置" value={`${job.config_generation} / ${job.config_fingerprint}`} />
          <Info label="dataset pin" value={`${job.dataset_id} v${job.dataset_version} / ${job.dataset_hash}`} />
          <Info label="知识指纹" value={job.knowledge_fingerprint} />
          <Info label="用例" value={job.report ? `${job.report.metrics.case_count} 个，answerable ${job.report.metrics.answerable_count}，no-answer ${job.report.metrics.no_answer_count}` : "未评估"} />
        </dl>
        <RevisionLinks job={job} />
      </div>
    ) : <p className="mt-3 text-sm text-slate-500">尚未选择。</p>}
  </article>
);

export const SelectedPairOverview: React.FC<{
  readonly reference: JobDTO | null;
  readonly candidate: JobDTO | null;
}> = ({ reference, candidate }) => (
  <section className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm lg:grid-cols-2" aria-label="已选任务概览">
    <SelectedJobLine label="参考" job={reference} />
    <SelectedJobLine label="候选" job={candidate} />
  </section>
);

const SelectedJobLine: React.FC<{ readonly label: string; readonly job: JobDTO | null }> = ({ label, job }) => (
  <div className="min-w-0 rounded-xl bg-slate-50 p-3 text-sm">
    <div className="text-xs font-semibold text-slate-500">{label}</div>
    {job ? (
      <div className="mt-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2"><StatusBadge compact status={job.status} /><HashLink href={lifecycleJobHash(job.id)}>job {shortId(job.id)}</HashLink></div>
        <div className="text-xs text-slate-500">{formatFull(job.evaluated_at)}</div>
      </div>
    ) : <div className="mt-1 text-slate-500">尚未选择</div>}
  </div>
);

export const ComparisonTables: React.FC<{ readonly comparison: JobComparison }> = ({ comparison }) => {
  const highlighted = comparison.metrics.filter((metric) => HIGHLIGHT_METRICS.has(metric.key));
  return (
    <section className="space-y-4" aria-labelledby="main-results-title">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 id="main-results-title" className="text-lg font-semibold text-slate-900">核心结果</h3>
        <p className="mt-1 text-sm leading-6 text-slate-600">先看 Recall、MRR、No-answer、Citation 与 stale 命中。完整指标和检查项在下方表格中保留。</p>
        <MetricHighlights metrics={highlighted} comparable={comparison.comparable} />
      </div>
      {comparison.reasons.length > 0 ? <MessageList title="本组任务暂不输出 delta" items={comparison.reasons} tone="amber" /> : null}
      {comparison.warnings.length > 0 ? <MessageList title="观察提醒" items={comparison.warnings} tone="blue" /> : null}
      <MetricTable metrics={comparison.metrics} comparable={comparison.comparable} />
      <CheckTable checks={comparison.checks} />
    </section>
  );
};

const MetricHighlights: React.FC<{ readonly metrics: readonly MetricComparison[]; readonly comparable: boolean }> = ({ metrics, comparable }) => (
  <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
    {metrics.length ? metrics.map((metric) => (
      <article className="rounded-xl border border-slate-200 bg-slate-50 p-3" key={metric.key}>
        <div className="text-sm font-semibold text-slate-900">{metric.label}</div>
        <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-600">
          <div><span className="block text-slate-500">参考</span>{formatMetricValue(metric.reference, metric.unit)}</div>
          <div><span className="block text-slate-500">候选</span>{formatMetricValue(metric.candidate, metric.unit)}</div>
        </div>
        <div className="mt-2 text-sm font-semibold text-[#1f2a44]">delta {comparable ? formatMetricDelta(metric.delta, metric.unit) : "—"}</div>
      </article>
    )) : <div className="rounded-xl border border-dashed border-slate-300 p-4 text-sm text-slate-500">报告未评估，暂无核心指标。</div>}
  </div>
);

const MetricTable: React.FC<{ readonly metrics: readonly MetricComparison[]; readonly comparable: boolean }> = ({ metrics, comparable }) => (
  <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm">
    <table className="min-w-full divide-y divide-slate-200 text-sm">
      <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
        <tr><th className="px-4 py-3">指标</th><th className="px-4 py-3">参考</th><th className="px-4 py-3">候选</th><th className="px-4 py-3">delta</th></tr>
      </thead>
      <tbody className="divide-y divide-slate-100">
        {metrics.length ? metrics.map((metric) => (
          <tr key={metric.key}>
            <td className="px-4 py-3"><div className="font-semibold text-slate-900">{metric.label}</div><div className="max-w-lg text-xs leading-5 text-slate-500">{metric.description}</div></td>
            <td className="px-4 py-3">{formatMetricValue(metric.reference, metric.unit)}</td>
            <td className="px-4 py-3">{formatMetricValue(metric.candidate, metric.unit)}</td>
            <td className="px-4 py-3">{comparable ? formatMetricDelta(metric.delta, metric.unit) : "—"}</td>
          </tr>
        )) : <tr><td className="px-4 py-6 text-slate-500" colSpan={4}>null 或缺报告显示为未评估。</td></tr>}
      </tbody>
    </table>
  </div>
);

const CheckTable: React.FC<{ readonly checks: readonly CheckComparison[] }> = ({ checks }) => (
  <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm">
    <table className="min-w-full divide-y divide-slate-200 text-sm">
      <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
        <tr><th className="px-4 py-3">检查项</th><th className="px-4 py-3">参考当时结果</th><th className="px-4 py-3">候选当时结果</th><th className="px-4 py-3">threshold</th></tr>
      </thead>
      <tbody className="divide-y divide-slate-100">
        {checks.length ? checks.map((check) => (
          <tr key={`${check.name}:${check.referenceThreshold}:${check.candidateThreshold}`}><td className="px-4 py-3 font-semibold">{check.label}</td><td className="px-4 py-3">{formatCheck(check.referencePassed, check.referenceActual)}</td><td className="px-4 py-3">{formatCheck(check.candidatePassed, check.candidateActual)}</td><td className="break-all px-4 py-3 font-mono text-xs">{check.referenceThreshold ?? "—"} / {check.candidateThreshold ?? "—"}</td></tr>
        )) : <tr><td className="px-4 py-6 text-slate-500" colSpan={4}>暂无可唯一对照的检查项；这里不会重算 U16 gate。</td></tr>}
      </tbody>
    </table>
  </div>
);

const JobTiny: React.FC<{ readonly job: JobDTO }> = ({ job }) => <div className="space-y-2"><div className="flex flex-wrap items-center gap-2"><StatusBadge status={job.status} /><HashLink href={lifecycleJobHash(job.id)}>job {shortId(job.id)}</HashLink><span className="break-all font-mono text-xs text-slate-500">{job.id}</span></div><div className="text-xs text-slate-500">{statusLabel(job.status)} · error {job.error_code ?? "—"}</div></div>;
const Info: React.FC<{ readonly label: string; readonly value: string }> = ({ label, value }) => <div><dt className="text-xs font-semibold uppercase text-slate-500">{label}</dt><dd className="break-all font-mono text-xs text-slate-700">{value}</dd></div>;
const RevisionLinks: React.FC<{ readonly job: JobDTO }> = ({ job }) => job.trigger_revision_ids.length ? <div className="flex flex-wrap gap-2">{job.trigger_revision_ids.map((id) => <HashLink href={lifecycleRevisionHash(id)} key={id}>revision {shortId(id)}</HashLink>)}</div> : <p className="text-xs text-slate-500">没有 trigger revision；汇总数据只能定位触发变更，不自动认定原因。</p>;
const MessageList: React.FC<{ readonly title: string; readonly items: readonly string[]; readonly tone: "amber" | "blue" }> = ({ title, items, tone }) => <div className={`rounded-2xl border p-4 text-sm leading-6 ${tone === "amber" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-blue-200 bg-blue-50 text-blue-900"}`}><div className="font-semibold">{title}</div><ul className="mt-2 list-disc space-y-1 pl-5">{items.map((item) => <li key={item}>{item}</li>)}</ul></div>;
function formatCheck(passed: boolean | null, actual: boolean | number | null): string {
  const result = passed === null ? "未评估" : passed ? "通过" : "未通过";
  const value = actual === null ? "null" : String(actual);
  return `${result} / actual ${value}`;
}
