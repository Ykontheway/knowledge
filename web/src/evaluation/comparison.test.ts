import { describe, expect, it } from "vitest";

import { CHECK_LABELS, compareJobs, formatMetricDelta, formatMetricValue } from "./comparison";
import type { JobDTO, SafeCheck } from "../management/types";

type JobReport = NonNullable<JobDTO["report"]>;
type ReportCheck = SafeCheck;

const DATASET_ID = "22222222-2222-2222-2222-222222222222";
const OTHER_DATASET_ID = "33333333-3333-3333-3333-333333333333";
const hash = (seed: string): string => seed.repeat(64);

function makeChecks(
  overrides: Partial<Record<ReportCheck["name"], Partial<Omit<ReportCheck, "name">>>> = {},
): readonly ReportCheck[] {
  const base: Record<ReportCheck["name"], ReportCheck> = {
    top_k_contract: { name: "top_k_contract", passed: true, actual: 5, threshold: "==5" },
    recall_at_k: { name: "recall_at_k", passed: true, actual: 0.8, threshold: ">=0.8" },
    mean_reciprocal_rank: { name: "mean_reciprocal_rank", passed: true, actual: 0.75, threshold: ">=0.65" },
    no_answer_accuracy: { name: "no_answer_accuracy", passed: true, actual: 1, threshold: ">=1" },
    retrieval_evidence_citation_coverage: {
      name: "retrieval_evidence_citation_coverage",
      passed: true,
      actual: 1,
      threshold: ">=1",
    },
    stale_or_retired_hits: { name: "stale_or_retired_hits", passed: true, actual: 0, threshold: "<=0" },
    stale_isolation_configuration: {
      name: "stale_isolation_configuration",
      passed: true,
      actual: 0,
      threshold: "0 include_stale cases",
    },
    retrieval_degradation: { name: "retrieval_degradation", passed: true, actual: false, threshold: "false" },
    regression_gate: { name: "regression_gate", passed: true, actual: true, threshold: "pass" },
  };

  // 未配置回归门禁时，B1 默认报告只有 8 项检查。
  return Object.values(base)
    .filter((check) => check.name !== "regression_gate" || overrides.regression_gate !== undefined)
    .map((check) => ({ ...check, ...overrides[check.name] }));
}

function makeReport(
  overrides: Partial<Omit<JobReport, "metrics" | "checks">> & {
    metrics?: Partial<JobReport["metrics"]>;
    checks?: readonly ReportCheck[];
  } = {},
): JobReport {
  const base: JobReport = {
    passed: true,
    metrics: {
      case_count: 4,
      answerable_count: 3,
      no_answer_count: 1,
      mean_recall: 0.8,
      mean_precision: 0.7,
      mean_reciprocal_rank: 0.75,
      mean_ndcg: 0.72,
      hit_rate: 1,
      no_answer_accuracy: 1,
    },
    citation_coverage: 1,
    stale_hits: 0,
    degraded: false,
    checks: makeChecks(),
  };

  return {
    ...base,
    ...overrides,
    metrics: {
      ...base.metrics,
      ...(overrides.metrics ?? {}),
    },
    checks: overrides.checks ?? base.checks,
  } as JobReport;
}

function makeJob(
  overrides: Partial<Omit<JobDTO, "report">> & {
    report?: JobDTO["report"];
  } = {},
): JobDTO {
  const base: JobDTO = {
    id: "11111111-1111-1111-1111-111111111111",
    parent_job_id: null,
    status: "passed",
    config_generation: 1,
    config_fingerprint: hash("a"),
    dataset_id: DATASET_ID,
    dataset_version: 1,
    dataset_hash: hash("b"),
    knowledge_fingerprint: hash("c"),
    created_at: "2026-11-13T10:00:00+00:00",
    evaluated_at: "2026-11-13T10:01:00+00:00",
    started_at: "2026-11-13T10:00:05+00:00",
    finished_at: "2026-11-13T10:01:00+00:00",
    attempt_count: 1,
    error_code: null,
    report: makeReport(),
    trigger_revision_ids: [],
    links: [],
  };
  return { ...base, ...overrides } as JobDTO;
}

function metricByKey(comparison: ReturnType<typeof compareJobs>, key: string) {
  const metric = comparison.metrics.find((entry) => entry.key === key);
  expect(metric).toBeDefined();
  return metric!;
}

function checksByName(comparison: ReturnType<typeof compareJobs>, name: string) {
  return comparison.checks.filter((entry) => entry.name === name);
}

function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value as Record<string, unknown>)) {
      deepFreeze(child);
    }
  }
  return value;
}

describe("compareJobs", () => {
  it("B1 默认 8 项检查不需要 regression_gate，故障与恢复仍可比较", () => {
    const expectedNames = [
      "top_k_contract",
      "recall_at_k",
      "mean_reciprocal_rank",
      "no_answer_accuracy",
      "retrieval_evidence_citation_coverage",
      "stale_or_retired_hits",
      "stale_isolation_configuration",
      "retrieval_degradation",
    ];
    const checks = makeChecks();
    expect(checks.map((check) => check.name)).toEqual(expectedNames);

    const normal = makeJob();
    const fault = makeJob({
      id: "99999999-9999-9999-9999-999999999999",
      status: "failed",
      error_code: "QUALITY_GATE_FAILED",
      evaluated_at: "2026-11-14T10:01:00+00:00",
      knowledge_fingerprint: hash("d"),
      report: makeReport({
        passed: false,
        metrics: { mean_recall: 0.6 },
        checks: [...makeChecks({ recall_at_k: { passed: false, actual: 0.6 } })].reverse(),
      }),
    });
    const restore = makeJob({
      id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      evaluated_at: "2026-11-15T10:01:00+00:00",
    });
    const normalToFault = compareJobs(normal, fault);
    const faultToRestore = compareJobs(fault, restore);

    for (const comparison of [normalToFault, faultToRestore]) {
      expect(comparison.comparable).toBe(true);
      expect(comparison.reasons).toEqual([]);
      expect(comparison.checks.map((check) => check.name)).toEqual(
        [...expectedNames].sort((left, right) => left.localeCompare(right)),
      );
      expect(checksByName(comparison, "regression_gate")).toEqual([]);
      expect(checksByName(comparison, "stale_isolation_configuration")).toEqual([{
        name: "stale_isolation_configuration",
        label: CHECK_LABELS.stale_isolation_configuration,
        referencePassed: true,
        candidatePassed: true,
        referenceActual: 0,
        candidateActual: 0,
        referenceThreshold: "0 include_stale cases",
        candidateThreshold: "0 include_stale cases",
      }]);
    }
    expect(metricByKey(normalToFault, "mean_recall").delta).toBeCloseTo(-0.2);
    expect(metricByKey(faultToRestore, "mean_recall").delta).toBeCloseTo(0.2);
  });

  it.each(makeChecks().map((check) => check.name))("两侧同时缺少必需检查 %s 也不可比", (name) => {
    const checks = makeChecks().filter((check) => check.name !== name);
    const comparison = compareJobs(
      makeJob({ report: makeReport({ checks }) }),
      makeJob({ id: "99999999-9999-9999-9999-999999999999", report: makeReport({ checks }) }),
    );

    expect(comparison.comparable).toBe(false);
    expect(comparison.reasons).toEqual([
      `参考任务缺少必需质量检查 ${name}，无法确认完整门禁口径。`,
      `候选任务缺少必需质量检查 ${name}，无法确认完整门禁口径。`,
    ]);
    expect(comparison.metrics).toHaveLength(11);
    expect(comparison.metrics.every((metric) => metric.delta === null)).toBe(true);
  });

  it("单侧缺少 stale_isolation_configuration 会阻断 delta 并保留缺项视图", () => {
    const comparison = compareJobs(
      makeJob(),
      makeJob({
        id: "99999999-9999-9999-9999-999999999999",
        report: makeReport({
          checks: makeChecks().filter((check) => check.name !== "stale_isolation_configuration"),
        }),
      }),
    );

    expect(comparison.comparable).toBe(false);
    expect(comparison.reasons).toContain(
      "候选任务缺少必需质量检查 stale_isolation_configuration，无法确认完整门禁口径。",
    );
    expect(comparison.reasons).toContain("质量检查的 name + threshold 集合不一致，无法在同一门禁口径下对照。");
    expect(checksByName(comparison, "stale_isolation_configuration")).toEqual([{
      name: "stale_isolation_configuration",
      label: CHECK_LABELS.stale_isolation_configuration,
      referencePassed: true,
      candidatePassed: null,
      referenceActual: 0,
      candidateActual: null,
      referenceThreshold: "0 include_stale cases",
      candidateThreshold: null,
    }]);
    expect(comparison.metrics).toHaveLength(11);
    expect(comparison.metrics.every((metric) => metric.delta === null)).toBe(true);
  });

  it("支持 passed 对 failed 的同口径比较，并保留 boolean check actual", () => {
    const reference = makeJob({ report: makeReport({ checks: makeChecks({ regression_gate: {} }) }) });
    const candidate = makeJob({
      id: "99999999-9999-9999-9999-999999999999",
      status: "failed",
      error_code: "QUALITY_GATE_FAILED",
      evaluated_at: "2026-11-14T10:01:00+00:00",
      report: makeReport({
        passed: false,
        metrics: {
          mean_recall: 0.65,
          mean_precision: 0.6,
          mean_reciprocal_rank: 0.6,
          mean_ndcg: 0.58,
          hit_rate: 0.9,
          no_answer_accuracy: 1,
        },
        citation_coverage: 0.5,
        stale_hits: 2,
        checks: makeChecks({
          recall_at_k: { passed: false, actual: 0.65 },
          mean_reciprocal_rank: { passed: false, actual: 0.6 },
          retrieval_evidence_citation_coverage: { passed: false, actual: 0.5 },
          stale_or_retired_hits: { passed: false, actual: 2, threshold: "<=0" },
          regression_gate: { passed: false, actual: false },
        }),
      }),
    });

    const comparison = compareJobs(reference, candidate);

    expect(comparison.comparable).toBe(true);
    expect(comparison.reasons).toEqual([]);
    expect(comparison.warnings).toContain(
      "这是两个评测时刻的观察结果，不是固定时点对照；即使候选更晚，也不能自动归因到候选任务本身。",
    );
    expect(comparison.warnings).toContain(
      "knowledge_fingerprint 未变化，结果可能只是重试或重复评测；不要直接把差异称为“修复”或“回退原因”。",
    );

    const meanRecall = metricByKey(comparison, "mean_recall");
    expect(meanRecall.reference).toBe(0.8);
    expect(meanRecall.candidate).toBe(0.65);
    expect(meanRecall.delta).toBeCloseTo(-0.15);
    expect(meanRecall.unit).toBe("ratio");
    expect(formatMetricDelta(meanRecall.delta, meanRecall.unit)).toBe("-15 个百分点");

    const staleHits = metricByKey(comparison, "stale_hits");
    expect(staleHits.direction).toBe("lower");
    expect(staleHits.delta).toBe(2);

    const [regressionGate] = checksByName(comparison, "regression_gate");
    expect(regressionGate).toEqual({
      name: "regression_gate",
      label: CHECK_LABELS.regression_gate,
      referencePassed: true,
      candidatePassed: false,
      referenceActual: true,
      candidateActual: false,
      referenceThreshold: "pass",
      candidateThreshold: "pass",
    });
  });

  it("支持 failed 参考任务与 passed 候选任务的恢复比较", () => {
    const reference = makeJob({
      status: "failed",
      error_code: "QUALITY_GATE_FAILED",
      report: makeReport({
        passed: false,
        metrics: {
          mean_recall: 0.6,
          mean_precision: 0.55,
          mean_reciprocal_rank: 0.58,
          mean_ndcg: 0.5,
          hit_rate: 0.8,
        },
        citation_coverage: 0.6,
        stale_hits: 1,
        checks: makeChecks({
          recall_at_k: { passed: false, actual: 0.6 },
          mean_reciprocal_rank: { passed: false, actual: 0.58 },
          retrieval_evidence_citation_coverage: { passed: false, actual: 0.6 },
          stale_or_retired_hits: { passed: false, actual: 1 },
          regression_gate: { passed: false, actual: false },
        }),
      }),
    });
    const candidate = makeJob({
      id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      config_generation: 2,
      evaluated_at: "2026-11-14T10:01:00+00:00",
      report: makeReport({ checks: makeChecks({ regression_gate: {} }) }),
    });

    const comparison = compareJobs(reference, candidate);

    expect(comparison.comparable).toBe(true);
    expect(comparison.reasons).toEqual([]);
    expect(comparison.warnings).toContain(
      "config_generation 不同但 config_fingerprint 一致；这里仍按同一评测策略看待，不把 generation 变化视为策略变化。",
    );
    expect(metricByKey(comparison, "mean_recall").delta).toBeCloseTo(0.2);
    expect(checksByName(comparison, "regression_gate")[0]?.candidatePassed).toBe(true);
  });

  it("拒绝把同一 job 同时当作参考和候选", () => {
    const job = makeJob();
    const comparison = compareJobs(job, { ...job });

    expect(comparison.comparable).toBe(false);
    expect(comparison.reasons).toContain("不能把同一任务同时作为参考任务和候选任务。");
  });

  it("真实 3 task 特征：同 config_fingerprint 但 dataset_version 不同仍不可比", () => {
    const jobA = makeJob({ id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", config_generation: 1, dataset_version: 1 });
    const jobB = makeJob({ id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", config_generation: 2, dataset_version: 2 });
    const jobC = makeJob({ id: "cccccccc-cccc-cccc-cccc-cccccccccccc", config_generation: 3, dataset_version: 3 });

    const firstDiff = compareJobs(jobA, jobB);
    const secondDiff = compareJobs(jobB, jobC);

    expect(firstDiff.comparable).toBe(false);
    expect(secondDiff.comparable).toBe(false);
    expect(firstDiff.reasons).toContain("dataset id / version / hash 必须完全一致，才能按同一评测样本口径比较。");
    expect(firstDiff.reasons).not.toContain("config_fingerprint 不一致，不能视为同一检索配置。");
  });

  it.each([
    ["dataset_id", { dataset_id: OTHER_DATASET_ID }, "dataset id / version / hash 必须完全一致，才能按同一评测样本口径比较。"],
    ["dataset_hash", { dataset_hash: hash("d") }, "dataset id / version / hash 必须完全一致，才能按同一评测样本口径比较。"],
    ["config_fingerprint", { config_fingerprint: hash("e") }, "config_fingerprint 不一致，不能视为同一检索配置。"],
  ])("拒绝 %s 差异", (_name, overrides, reason) => {
    const comparison = compareJobs(makeJob(), makeJob({ id: "f-f-f-f-f".replace(/-/g, "f"), ...overrides } as Partial<JobDTO>));

    expect(comparison.comparable).toBe(false);
    expect(comparison.reasons).toContain(reason);
  });

  it.each([
    ["running", makeJob({ status: "running", report: makeReport() }), "参考任务不是带完整报告的 passed/failed 终态，不能用于质量对照。"],
    [
      "passed-report-mismatch",
      makeJob({ report: makeReport({ passed: false }), error_code: null }),
      "参考任务的状态、错误码与 report.passed 不一致。",
    ],
    [
      "failed-non-gate-error",
      makeJob({ status: "failed", error_code: "INVALID_EVALUATION", report: makeReport({ passed: false }) }),
      "参考任务不是可对照的质量门禁失败结果。",
    ],
    ["missing-report", makeJob({ report: null }), "参考任务缺少 report，不能计算改善或退化。"],
  ])("拒绝非终态或状态/report 不一致：%s", (_name, reference, reason) => {
    const comparison = compareJobs(reference, makeJob({ id: "99999999-9999-9999-9999-999999999999" }));

    expect(comparison.comparable).toBe(false);
    expect(comparison.reasons).toContain(reason);
  });

  it("degraded 任一侧为 true 都会阻断 delta", () => {
    const comparison = compareJobs(
      makeJob(),
      makeJob({
        id: "99999999-9999-9999-9999-999999999999",
        evaluated_at: "2026-11-14T10:01:00+00:00",
        report: makeReport({ degraded: true, checks: makeChecks({ retrieval_degradation: { passed: false, actual: true } }) }),
      }),
    );

    expect(comparison.comparable).toBe(false);
    expect(comparison.reasons).toContain("至少一侧任务标记为 degraded，不能计算可靠的改善幅度。");
    expect(comparison.metrics.every((metric) => metric.delta === null)).toBe(true);
  });

  it("无效时间戳和候选早于参考任务都会阻断角色顺序", () => {
    const invalidTime = compareJobs(
      makeJob({ evaluated_at: "not-a-time" }),
      makeJob({ id: "99999999-9999-9999-9999-999999999999", evaluated_at: "2026-11-14T10:01:00+00:00" }),
    );
    const reversedTime = compareJobs(
      makeJob({ evaluated_at: "2026-11-14T10:01:00+00:00" }),
      makeJob({ id: "99999999-9999-9999-9999-999999999999", evaluated_at: "2026-11-13T10:01:00+00:00" }),
    );

    expect(invalidTime.comparable).toBe(false);
    expect(invalidTime.reasons).toContain("参考任务的 evaluated_at 无法解析，不能可靠标记前后顺序。");
    expect(invalidTime.warnings).toContain("至少一个任务的评测时间不可用，不能安全标记为 before / after 对照。");

    expect(reversedTime.comparable).toBe(false);
    expect(reversedTime.reasons).toContain("候选任务的 evaluated_at 早于参考任务，参考/候选角色顺序不成立。");
    expect(reversedTime.warnings).toContain("当前角色顺序不能按时间解释为 before / after。");
  });

  it("严格校验计数与 null 语义，不把 null 当成 0", () => {
    const badNoAnswer = compareJobs(
      makeJob(),
      makeJob({
        id: "99999999-9999-9999-9999-999999999999",
        report: makeReport({ metrics: { no_answer_accuracy: null } }),
      }),
    );
    const badCounts = compareJobs(
      makeJob(),
      makeJob({
        id: "88888888-8888-8888-8888-888888888888",
        report: makeReport({ metrics: { case_count: 5 } }),
      }),
    );

    expect(badNoAnswer.comparable).toBe(false);
    expect(badNoAnswer.reasons).toContain("候选任务的 no_answer_accuracy 缺失或越界。");
    expect(badCounts.comparable).toBe(false);
    expect(badCounts.reasons).toContain("候选任务的 case_count 与 answerable / no-answer 汇总不一致。");
  });

  it("空 checks 列表会被拒绝", () => {
    const comparison = compareJobs(
      makeJob(),
      makeJob({
        id: "99999999-9999-9999-9999-999999999999",
        report: makeReport({ checks: [] }),
      }),
    );

    expect(comparison.comparable).toBe(false);
    expect(comparison.reasons).toContain("候选任务的质量检查列表为空，无法确认门禁口径。");
    expect(comparison.checks).toEqual([]);
  });

  it("threshold 变化会按不同 check 集合处理，并保留 union 视图", () => {
    const comparison = compareJobs(
      makeJob(),
      makeJob({
        id: "99999999-9999-9999-9999-999999999999",
        report: makeReport({
          checks: makeChecks({
            recall_at_k: { threshold: ">=0.85", actual: 0.8, passed: false },
          }),
        }),
      }),
    );

    expect(comparison.comparable).toBe(false);
    expect(comparison.reasons).toContain("质量检查的 name + threshold 集合不一致，无法在同一门禁口径下对照。");
    const recallChecks = checksByName(comparison, "recall_at_k");
    expect(recallChecks).toHaveLength(2);
    expect(recallChecks.map((entry) => entry.referenceThreshold ?? entry.candidateThreshold)).toEqual([">=0.8", ">=0.85"]);
  });

  it("重复 checks 会阻断唯一对照", () => {
    const duplicateChecks = [
      ...makeChecks({ regression_gate: {} }),
      { name: "regression_gate", passed: true, actual: true, threshold: "pass" } as const,
    ] as const;
    const comparison = compareJobs(
      makeJob(),
      makeJob({
        id: "99999999-9999-9999-9999-999999999999",
        report: makeReport({ checks: duplicateChecks }),
      }),
    );

    expect(comparison.comparable).toBe(false);
    expect(comparison.reasons).toContain("质量检查存在重复 name + threshold 组合，无法唯一对照。");
  });

  it("缺失 checks 会阻断同门禁比较", () => {
    const comparison = compareJobs(
      makeJob({ report: makeReport({ checks: makeChecks({ regression_gate: {} }) }) }),
      makeJob({
        id: "99999999-9999-9999-9999-999999999999",
        report: makeReport({ checks: makeChecks().filter((check) => check.name !== "regression_gate") }),
      }),
    );

    expect(comparison.comparable).toBe(false);
    expect(comparison.reasons).toContain("质量检查的 name + threshold 集合不一致，无法在同一门禁口径下对照。");
  });

  it("top_k_contract actual 必须一致且为整数", () => {
    const mismatch = compareJobs(
      makeJob(),
      makeJob({
        id: "99999999-9999-9999-9999-999999999999",
        report: makeReport({ checks: makeChecks({ top_k_contract: { actual: 10 } }) }),
      }),
    );
    const nonInteger = compareJobs(
      makeJob(),
      makeJob({
        id: "88888888-8888-8888-8888-888888888888",
        report: makeReport({ checks: makeChecks({ top_k_contract: { actual: 5.5 } }) }),
      }),
    );

    expect(mismatch.comparable).toBe(false);
    expect(mismatch.reasons).toContain("top_k_contract 的 actual 不一致，不能视为同一 top_k 合同。");
    expect(nonInteger.comparable).toBe(false);
    expect(nonInteger.reasons).toContain("top_k_contract 的 actual 必须是正整数。");
  });

  it("格式化 ratio / count 时使用百分数与百分点，并保留 null 语义", () => {
    expect(formatMetricValue(null, "ratio")).toBe("未评估");
    expect(formatMetricValue(1, "ratio")).toBe("100%");
    expect(formatMetricValue(-0, "ratio")).toBe("0%");
    expect(formatMetricValue(12, "count")).toBe("12");
    expect(formatMetricDelta(1 / 3, "ratio")).toBe("+33.33 个百分点");
    expect(formatMetricDelta(-0, "count")).toBe("0");
    expect(formatMetricDelta(null, "count")).toBe("—");
  });

  it("不会修改输入 DTO", () => {
    const reference = deepFreeze(makeJob());
    const candidate = deepFreeze(
      makeJob({ id: "99999999-9999-9999-9999-999999999999", evaluated_at: "2026-11-14T10:01:00+00:00" }),
    );
    const beforeReference = structuredClone(reference);
    const beforeCandidate = structuredClone(candidate);

    const comparison = compareJobs(reference, candidate);

    expect(comparison.comparable).toBe(true);
    expect(reference).toEqual(beforeReference);
    expect(candidate).toEqual(beforeCandidate);
  });
});
