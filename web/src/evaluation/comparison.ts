import type { JobDTO } from "../management/types";

type JobReport = NonNullable<JobDTO["report"]>;
type ReportCheck = JobReport["checks"][number];
type CheckName = ReportCheck["name"];

type MetricKey =
  | "case_count"
  | "answerable_count"
  | "no_answer_count"
  | "mean_recall"
  | "mean_precision"
  | "mean_reciprocal_rank"
  | "mean_ndcg"
  | "hit_rate"
  | "no_answer_accuracy"
  | "citation_coverage"
  | "stale_hits";

type MetricBag = Readonly<Record<MetricKey, number | null>>;

type CheckEntry = Readonly<{
  key: string;
  name: CheckName;
  threshold: string | null;
  passed: boolean;
  actual: boolean | number | null;
}>;

type AnalyzedJob = Readonly<{
  report: JobReport | null;
  metrics: MetricBag | null;
  checks: readonly CheckEntry[] | null;
  evaluatedAtMs: number | null;
}>;

type MetricDefinition = Readonly<{
  key: MetricKey;
  label: string;
  description: string;
  unit: MetricComparison["unit"];
  direction: MetricComparison["direction"];
}>;

export interface JobComparison {
  readonly comparable: boolean;
  readonly reasons: readonly string[];
  readonly warnings: readonly string[];
  readonly metrics: readonly MetricComparison[];
  readonly checks: readonly CheckComparison[];
}

export interface MetricComparison {
  readonly key: string;
  readonly label: string;
  readonly description: string;
  readonly reference: number | null;
  readonly candidate: number | null;
  readonly delta: number | null;
  readonly unit: "ratio" | "count";
  readonly direction: "higher" | "lower" | "neutral";
}

export interface CheckComparison {
  readonly name: string;
  readonly label: string;
  readonly referencePassed: boolean | null;
  readonly candidatePassed: boolean | null;
  readonly referenceActual: boolean | number | null;
  readonly candidateActual: boolean | number | null;
  readonly referenceThreshold: string | null;
  readonly candidateThreshold: string | null;
}

const TERMINAL_STATUSES = new Set<JobDTO["status"]>(["passed", "failed"]);
const QUALITY_GATE_FAILURE = "QUALITY_GATE_FAILED";

// B1 默认报告固定包含这 8 项；regression_gate 仅按回归配置追加。
const REQUIRED_CHECKS: Readonly<Record<Exclude<CheckName, "regression_gate">, true>> = {
  top_k_contract: true,
  recall_at_k: true,
  mean_reciprocal_rank: true,
  no_answer_accuracy: true,
  retrieval_evidence_citation_coverage: true,
  stale_or_retired_hits: true,
  stale_isolation_configuration: true,
  retrieval_degradation: true,
};

export const CHECK_LABELS: Readonly<Record<CheckName, string>> = {
  top_k_contract: "top_k 合同",
  recall_at_k: "Recall@K 门槛",
  mean_reciprocal_rank: "MRR 门槛",
  no_answer_accuracy: "No-answer Accuracy 门槛",
  retrieval_evidence_citation_coverage: "证据引用覆盖率",
  stale_or_retired_hits: "陈旧/退役命中",
  stale_isolation_configuration: "陈旧检索隔离配置",
  retrieval_degradation: "检索退化",
  regression_gate: "回归门禁",
};

export const METRIC_EXPLANATIONS: Readonly<Record<MetricKey, string>> = {
  case_count: "评测样本总数，只用于确认口径一致，不代表质量高低。",
  answerable_count: "有标准答案的样本数，只用于确认口径一致。",
  no_answer_count: "期望检索为空的样本数，只用于确认口径一致。",
  mean_recall: "answerable 样本的平均 Recall，越高越好。",
  mean_precision: "answerable 样本的平均 Precision，越高越好。",
  mean_reciprocal_rank: "answerable 样本的平均倒数排名（MRR），展示为百分比仅便于阅读，并非概率。",
  mean_ndcg: "answerable 样本的平均 NDCG，展示为百分比仅便于阅读，并非概率。",
  hit_rate: "answerable 样本命中至少一个正确 lineage 的比例，越高越好。",
  no_answer_accuracy:
    "no-answer 样本中检索结果为空的比例；这不是拒答正确性，没有 no-answer 样本时应为未评估。",
  citation_coverage: "检索证据中可验证引用的覆盖率；这不衡量生成答案是否正确。",
  stale_hits: "报告中的 stale_hits 计数，越低越好；以前端拿到的报告数值为准，不从持久化 unit.status 追溯。",
};

const METRICS: readonly MetricDefinition[] = [
  { key: "case_count", label: "用例数", description: METRIC_EXPLANATIONS.case_count, unit: "count", direction: "neutral" },
  { key: "answerable_count", label: "可回答用例", description: METRIC_EXPLANATIONS.answerable_count, unit: "count", direction: "neutral" },
  { key: "no_answer_count", label: "No-answer 用例", description: METRIC_EXPLANATIONS.no_answer_count, unit: "count", direction: "neutral" },
  { key: "mean_recall", label: "平均 Recall", description: METRIC_EXPLANATIONS.mean_recall, unit: "ratio", direction: "higher" },
  { key: "mean_precision", label: "平均 Precision", description: METRIC_EXPLANATIONS.mean_precision, unit: "ratio", direction: "higher" },
  { key: "mean_reciprocal_rank", label: "MRR", description: METRIC_EXPLANATIONS.mean_reciprocal_rank, unit: "ratio", direction: "higher" },
  { key: "mean_ndcg", label: "NDCG", description: METRIC_EXPLANATIONS.mean_ndcg, unit: "ratio", direction: "higher" },
  { key: "hit_rate", label: "Hit Rate", description: METRIC_EXPLANATIONS.hit_rate, unit: "ratio", direction: "higher" },
  { key: "no_answer_accuracy", label: "No-answer Accuracy", description: METRIC_EXPLANATIONS.no_answer_accuracy, unit: "ratio", direction: "higher" },
  { key: "citation_coverage", label: "Citation Coverage", description: METRIC_EXPLANATIONS.citation_coverage, unit: "ratio", direction: "higher" },
  { key: "stale_hits", label: "stale hits", description: METRIC_EXPLANATIONS.stale_hits, unit: "count", direction: "lower" },
];

export function compareJobs(reference: JobDTO, candidate: JobDTO): JobComparison {
  const reasons: string[] = [];
  const warnings: string[] = [];

  if (reference.id === candidate.id) {
    pushUnique(reasons, "不能把同一任务同时作为参考任务和候选任务。");
  }

  const analyzedReference = analyzeJob(reference, "参考", reasons);
  const analyzedCandidate = analyzeJob(candidate, "候选", reasons);

  validateJobPins(reference, candidate, reasons, warnings);
  validateTimeline(analyzedReference.evaluatedAtMs, analyzedCandidate.evaluatedAtMs, reasons, warnings);

  if (reference.config_fingerprint === candidate.config_fingerprint) {
    if (reference.config_generation !== candidate.config_generation) {
      pushUnique(
        warnings,
        "config_generation 不同但 config_fingerprint 一致；这里仍按同一评测策略看待，不把 generation 变化视为策略变化。",
      );
    }
    if (reference.knowledge_fingerprint === candidate.knowledge_fingerprint) {
      pushUnique(
        warnings,
        "knowledge_fingerprint 未变化，结果可能只是重试或重复评测；不要直接把差异称为“修复”或“回退原因”。",
      );
    } else {
      pushUnique(
        warnings,
        "knowledge_fingerprint 不同，表示比较对象来自不同知识快照；结果只能视为两次观测差异，不能自动归因。",
      );
    }
  }

  validateComparableReports(analyzedReference, analyzedCandidate, reasons);

  const comparable = reasons.length === 0;
  return {
    comparable,
    reasons,
    warnings,
    metrics: buildMetricComparisons(analyzedReference.metrics, analyzedCandidate.metrics, comparable),
    checks: buildCheckComparisons(analyzedReference.checks, analyzedCandidate.checks),
  };
}

export function formatMetricValue(value: number | null, unit: MetricComparison["unit"]): string {
  if (value === null) return "未评估";
  const normalized = normalizeZero(value);
  return unit === "ratio" ? `${formatNumber(normalized * 100)}%` : formatNumber(normalized);
}

export function formatMetricDelta(value: number | null, unit: MetricComparison["unit"]): string {
  if (value === null) return "—";
  const normalized = normalizeZero(value);
  return unit === "ratio"
    ? `${formatSignedNumber(normalized * 100)} 个百分点`
    : formatSignedNumber(normalized);
}

function analyzeJob(job: JobDTO, role: "参考" | "候选", reasons: string[]): AnalyzedJob {
  if (!isNonBlank(job.config_fingerprint) || !isNonBlank(job.dataset_hash) || !isNonBlank(job.knowledge_fingerprint)) {
    pushUnique(reasons, `${role}任务缺少必要的 hash / fingerprint，无法可信对照。`);
  }
  if (!isNonBlank(job.dataset_id)) {
    pushUnique(reasons, `${role}任务缺少 dataset_id，无法可信对照。`);
  }

  const evaluatedAtMs = parseTimestamp(job.evaluated_at);
  if (evaluatedAtMs === null) {
    pushUnique(reasons, `${role}任务的 evaluated_at 无法解析，不能可靠标记前后顺序。`);
  }

  if (!TERMINAL_STATUSES.has(job.status)) {
    pushUnique(reasons, `${role}任务不是带完整报告的 passed/failed 终态，不能用于质量对照。`);
  }
  if (job.report === null) {
    pushUnique(reasons, `${role}任务缺少 report，不能计算改善或退化。`);
    return { report: null, metrics: null, checks: null, evaluatedAtMs };
  }

  const report = job.report;
  if (job.status === "passed") {
    if (report.passed !== true || job.error_code !== null) {
      pushUnique(reasons, `${role}任务的状态、错误码与 report.passed 不一致。`);
    }
  } else if (job.status === "failed") {
    if (report.passed !== false || job.error_code !== QUALITY_GATE_FAILURE) {
      pushUnique(reasons, `${role}任务不是可对照的质量门禁失败结果。`);
    }
  }

  return {
    report,
    metrics: validateMetrics(report, role, reasons),
    checks: validateChecks(report.checks, role, reasons),
    evaluatedAtMs,
  };
}

function validateJobPins(reference: JobDTO, candidate: JobDTO, reasons: string[], warnings: string[]): void {
  if (
    reference.dataset_id !== candidate.dataset_id
    || reference.dataset_version !== candidate.dataset_version
    || reference.dataset_hash !== candidate.dataset_hash
  ) {
    pushUnique(reasons, "dataset id / version / hash 必须完全一致，才能按同一评测样本口径比较。");
  }
  if (reference.config_fingerprint !== candidate.config_fingerprint) {
    pushUnique(reasons, "config_fingerprint 不一致，不能视为同一检索配置。");
  }
  if (reference.evaluated_at !== candidate.evaluated_at) {
    pushUnique(
      warnings,
      "这是两个评测时刻的观察结果，不是固定时点对照；即使候选更晚，也不能自动归因到候选任务本身。",
    );
  }
}

function validateTimeline(
  referenceEvaluatedAtMs: number | null,
  candidateEvaluatedAtMs: number | null,
  reasons: string[],
  warnings: string[],
): void {
  if (referenceEvaluatedAtMs === null || candidateEvaluatedAtMs === null) {
    pushUnique(warnings, "至少一个任务的评测时间不可用，不能安全标记为 before / after 对照。");
    return;
  }
  if (candidateEvaluatedAtMs < referenceEvaluatedAtMs) {
    pushUnique(reasons, "候选任务的 evaluated_at 早于参考任务，参考/候选角色顺序不成立。");
    pushUnique(warnings, "当前角色顺序不能按时间解释为 before / after。");
  }
}

function validateComparableReports(reference: AnalyzedJob, candidate: AnalyzedJob, reasons: string[]): void {
  if (reference.report === null || candidate.report === null || reference.metrics === null || candidate.metrics === null) {
    return;
  }

  if (
    reference.metrics.case_count !== candidate.metrics.case_count
    || reference.metrics.answerable_count !== candidate.metrics.answerable_count
    || reference.metrics.no_answer_count !== candidate.metrics.no_answer_count
  ) {
    pushUnique(reasons, "两次评测的 case / answerable / no-answer 计数不一致，无法确认同一统计口径。");
  }

  if (reference.report.degraded || candidate.report.degraded) {
    pushUnique(reasons, "至少一侧任务标记为 degraded，不能计算可靠的改善幅度。");
  }

  for (const definition of METRICS) {
    const referenceValue = reference.metrics[definition.key];
    const candidateValue = candidate.metrics[definition.key];
    if ((referenceValue === null) !== (candidateValue === null)) {
      pushUnique(reasons, `指标 ${definition.label} 的有无状态不一致，不能把 null 当成 0 对照。`);
    }
  }

  if (reference.checks === null || candidate.checks === null) {
    return;
  }

  const referenceKeys = new Set(reference.checks.map((check) => check.key));
  const candidateKeys = new Set(candidate.checks.map((check) => check.key));
  if (referenceKeys.size !== reference.checks.length || candidateKeys.size !== candidate.checks.length) {
    pushUnique(reasons, "质量检查存在重复 name + threshold 组合，无法唯一对照。");
    return;
  }
  if (!sameSet(referenceKeys, candidateKeys)) {
    pushUnique(reasons, "质量检查的 name + threshold 集合不一致，无法在同一门禁口径下对照。");
  }

  const referenceTopK = reference.checks.find((check) => check.name === "top_k_contract")?.actual;
  const candidateTopK = candidate.checks.find((check) => check.name === "top_k_contract")?.actual;
  if (referenceTopK !== undefined && candidateTopK !== undefined) {
    if (!isPositiveInteger(referenceTopK) || !isPositiveInteger(candidateTopK)) {
      pushUnique(reasons, "top_k_contract 的 actual 必须是正整数。");
    } else if (referenceTopK !== candidateTopK) {
      pushUnique(reasons, "top_k_contract 的 actual 不一致，不能视为同一 top_k 合同。");
    }
  }
}

function validateMetrics(report: JobReport, role: "参考" | "候选", reasons: string[]): MetricBag | null {
  const { metrics } = report;
  if (!isNonNegativeInteger(metrics.case_count) || metrics.case_count <= 0) {
    pushUnique(reasons, `${role}任务的 case_count 必须是大于 0 的整数。`);
    return null;
  }
  if (!isNonNegativeInteger(metrics.answerable_count) || !isNonNegativeInteger(metrics.no_answer_count)) {
    pushUnique(reasons, `${role}任务的 answerable_count / no_answer_count 必须是非负整数。`);
    return null;
  }
  if (metrics.answerable_count + metrics.no_answer_count !== metrics.case_count) {
    pushUnique(reasons, `${role}任务的 case_count 与 answerable / no-answer 汇总不一致。`);
    return null;
  }

  const answerableMetrics = [
    metrics.mean_recall,
    metrics.mean_precision,
    metrics.mean_reciprocal_rank,
    metrics.mean_ndcg,
    metrics.hit_rate,
  ];
  if (metrics.answerable_count === 0) {
    if (answerableMetrics.some((value) => value !== null)) {
      pushUnique(reasons, `${role}任务没有 answerable 样本时，排名指标必须全部为 null。`);
      return null;
    }
  } else if (!answerableMetrics.every(isRatioOrNull) || answerableMetrics.some((value) => value === null)) {
    pushUnique(reasons, `${role}任务的 answerable 排名指标缺失或越界。`);
    return null;
  }

  if (metrics.no_answer_count === 0) {
    if (metrics.no_answer_accuracy !== null) {
      pushUnique(reasons, `${role}任务没有 no-answer 样本时，no_answer_accuracy 必须为 null。`);
      return null;
    }
  } else if (!isRatio(metrics.no_answer_accuracy)) {
    pushUnique(reasons, `${role}任务的 no_answer_accuracy 缺失或越界。`);
    return null;
  }

  if (!isRatioOrNull(report.citation_coverage)) {
    pushUnique(reasons, `${role}任务的 citation_coverage 缺失或越界。`);
    return null;
  }
  if (!isNonNegativeInteger(report.stale_hits)) {
    pushUnique(reasons, `${role}任务的 stale_hits 必须是非负整数。`);
    return null;
  }

  return {
    case_count: metrics.case_count,
    answerable_count: metrics.answerable_count,
    no_answer_count: metrics.no_answer_count,
    mean_recall: metrics.mean_recall,
    mean_precision: metrics.mean_precision,
    mean_reciprocal_rank: metrics.mean_reciprocal_rank,
    mean_ndcg: metrics.mean_ndcg,
    hit_rate: metrics.hit_rate,
    no_answer_accuracy: metrics.no_answer_accuracy,
    citation_coverage: report.citation_coverage,
    stale_hits: report.stale_hits,
  };
}

function validateChecks(
  checks: JobReport["checks"],
  role: "参考" | "候选",
  reasons: string[],
): readonly CheckEntry[] | null {
  if (checks.length === 0) {
    pushUnique(reasons, `${role}任务的质量检查列表为空，无法确认门禁口径。`);
    return null;
  }

  const names = new Set<string>(checks.map((check) => check.name));
  for (const name of Object.keys(REQUIRED_CHECKS)) {
    if (!names.has(name)) {
      pushUnique(reasons, `${role}任务缺少必需质量检查 ${name}，无法确认完整门禁口径。`);
    }
  }

  const normalized: CheckEntry[] = [];
  for (const check of checks) {
    if (check.threshold !== undefined && check.threshold !== null && !isNonBlank(check.threshold)) {
      pushUnique(reasons, `${role}任务存在空白 threshold，无法可信展示。`);
      return null;
    }
    if (typeof check.passed !== "boolean") {
      pushUnique(reasons, `${role}任务的质量检查 passed 字段不合法。`);
      return null;
    }
    if (typeof check.actual === "number" && !Number.isFinite(check.actual)) {
      pushUnique(reasons, `${role}任务的质量检查 actual 存在非有限数值。`);
      return null;
    }
    if (typeof check.actual !== "boolean" && typeof check.actual !== "number" && check.actual !== null) {
      pushUnique(reasons, `${role}任务的质量检查 actual 类型不支持。`);
      return null;
    }
    normalized.push({
      key: makeCheckKey(check.name, check.threshold ?? null),
      name: check.name,
      threshold: check.threshold ?? null,
      passed: check.passed,
      actual: typeof check.actual === "number" ? normalizeZero(check.actual) : check.actual,
    });
  }
  return normalized;
}

function buildMetricComparisons(
  referenceMetrics: MetricBag | null,
  candidateMetrics: MetricBag | null,
  comparable: boolean,
): readonly MetricComparison[] {
  if (referenceMetrics === null || candidateMetrics === null) {
    return [];
  }
  return METRICS.map((definition) => {
    const referenceValue = referenceMetrics[definition.key];
    const candidateValue = candidateMetrics[definition.key];
    return {
      key: definition.key,
      label: definition.label,
      description: definition.description,
      reference: referenceValue,
      candidate: candidateValue,
      delta:
        comparable && referenceValue !== null && candidateValue !== null
          ? normalizeZero(candidateValue - referenceValue)
          : null,
      unit: definition.unit,
      direction: definition.direction,
    };
  });
}

function buildCheckComparisons(
  referenceChecks: readonly CheckEntry[] | null,
  candidateChecks: readonly CheckEntry[] | null,
): readonly CheckComparison[] {
  if (referenceChecks === null || candidateChecks === null) {
    return [];
  }

  const referenceMap = new Map(referenceChecks.map((check) => [check.key, check] as const));
  const candidateMap = new Map(candidateChecks.map((check) => [check.key, check] as const));
  const keys = [...new Set([...referenceMap.keys(), ...candidateMap.keys()])].sort((left, right) => {
    const [leftName = "", leftThreshold = ""] = left.split("\u0000");
    const [rightName = "", rightThreshold = ""] = right.split("\u0000");
    return leftName.localeCompare(rightName) || leftThreshold.localeCompare(rightThreshold);
  });

  return keys.map((key) => {
    const reference = referenceMap.get(key) ?? null;
    const candidate = candidateMap.get(key) ?? null;
    const name = (reference?.name ?? candidate?.name ?? "regression_gate") as CheckName;
    return {
      name,
      label: CHECK_LABELS[name],
      referencePassed: reference?.passed ?? null,
      candidatePassed: candidate?.passed ?? null,
      referenceActual: reference?.actual ?? null,
      candidateActual: candidate?.actual ?? null,
      referenceThreshold: reference?.threshold ?? null,
      candidateThreshold: candidate?.threshold ?? null,
    };
  });
}

function makeCheckKey(name: CheckName, threshold: string | null): string {
  return `${name}\u0000${threshold ?? ""}`;
}

function parseTimestamp(value: string): number | null {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function sameSet(left: ReadonlySet<string>, right: ReadonlySet<string>): boolean {
  if (left.size !== right.size) return false;
  for (const value of left) {
    if (!right.has(value)) return false;
  }
  return true;
}

function isNonBlank(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isRatio(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}

function isRatioOrNull(value: unknown): value is number | null {
  return value === null || isRatio(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function normalizeZero(value: number): number {
  return Object.is(value, -0) ? 0 : value;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: Number.isInteger(value) ? 0 : 2,
    useGrouping: false,
  })
    .format(value)
    .replace(/\.00$/, "");
}

function formatSignedNumber(value: number): string {
  const formatted = formatNumber(Math.abs(value));
  if (value > 0) return `+${formatted}`;
  if (value < 0) return `-${formatted}`;
  return formatted;
}

function pushUnique(target: string[], message: string): void {
  if (!target.includes(message)) {
    target.push(message);
  }
}
