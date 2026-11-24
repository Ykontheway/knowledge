"""Retrieval evaluation, portable baselines, and deterministic regression gates."""

from knowledge.domain.evaluation import EvaluationItem, EvaluationSet, dump_evaluation_set
from knowledge.evaluation.baselines import (
    BaselineCase,
    EvaluationBaseline,
    baseline_from_report,
    dump_baseline,
)
from knowledge.evaluation.gates import (
    EvaluationComparison,
    GateCheck,
    GatePolicy,
    GateResult,
    GateRule,
    MetricDelta,
    MetricName,
    compare_baseline,
    dump_gate_policy,
    evaluate_gate,
)
from knowledge.evaluation.metrics import aggregate_metrics, score_ranked_lineages
from knowledge.evaluation.models import (
    AggregateMetrics,
    EvaluationCaseResult,
    EvaluationReport,
    ItemMetrics,
)
from knowledge.evaluation.service import (
    EvaluationImportResult,
    EvaluationService,
    EvaluationSetNotFoundError,
)
from knowledge.evaluation.validation import validate_evaluation_report

__all__ = [
    "AggregateMetrics",
    "BaselineCase",
    "EvaluationBaseline",
    "EvaluationCaseResult",
    "EvaluationComparison",
    "EvaluationImportResult",
    "EvaluationItem",
    "EvaluationReport",
    "EvaluationService",
    "EvaluationSet",
    "EvaluationSetNotFoundError",
    "GateCheck",
    "GatePolicy",
    "GateResult",
    "GateRule",
    "ItemMetrics",
    "MetricDelta",
    "MetricName",
    "aggregate_metrics",
    "baseline_from_report",
    "compare_baseline",
    "dump_baseline",
    "dump_evaluation_set",
    "dump_gate_policy",
    "evaluate_gate",
    "score_ranked_lineages",
    "validate_evaluation_report",
]
