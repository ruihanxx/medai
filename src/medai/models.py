from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provenance(StrictModel):
    page: int = Field(ge=1)
    section: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=200)


class Claim(StrictModel):
    claim_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    statement: str = Field(min_length=1)
    role: Literal["final", "validation"]
    kind: Literal["text", "numeric"]
    paper_result: Any = None
    provenance: Provenance


class ClaimsFile(StrictModel):
    claims: list[Claim]

    @model_validator(mode="after")
    def unique_claim_ids(self) -> "ClaimsFile":
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim_id values must be unique")
        return self


class Experiment(StrictModel):
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    description: str
    claims: list[str] = Field(min_length=1)
    artifacts: list[str]

    @model_validator(mode="after")
    def unique_mappings(self) -> "Experiment":
        if len(self.claims) != len(set(self.claims)):
            raise ValueError("Experiment claim IDs must be unique")
        if len(self.artifacts) != len(set(self.artifacts)):
            raise ValueError("Experiment artifact labels must be unique")
        return self


class ExperimentTodo(StrictModel):
    experiments: list[Experiment] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_experiment_ids(self) -> "ExperimentTodo":
        experiment_ids = [experiment.experiment_id for experiment in self.experiments]
        if len(experiment_ids) != len(set(experiment_ids)):
            raise ValueError("experiment_id values must be unique")
        return self


class PlannedFile(StrictModel):
    path: str
    responsibility: str


class Ambiguity(StrictModel):
    question: str
    assumption: str


class DatasetPatch(StrictModel):
    file_name: str = Field(alias="file name", min_length=1)
    patch_content: Any


class DatasetPatchFile(RootModel[list[DatasetPatch]]):
    pass


class CodegenPlan(StrictModel):
    files: list[PlannedFile] = Field(min_length=1)
    dependency_order: list[str] = Field(min_length=1)
    entry_points: list[str] = Field(min_length=1)
    shared_state: str
    ambiguities: list[Ambiguity]


class PlanEnvironment(StrictModel):
    language: str
    key_dependencies: list[str]
    setup_hints: str


class ReplicationStep(StrictModel):
    id: int = Field(ge=1)
    description: str
    command_hint: str
    expected_outcome: str
    verifies: list[str]


class RemoteComputePlan(StrictModel):
    provider: Literal["autodl"]
    state_path: str
    remote_working_directory: str
    setup_hints: list[str]


class ReplicationPlan(StrictModel):
    environment: PlanEnvironment
    steps: list[ReplicationStep] = Field(min_length=3, max_length=10)
    remote_compute: RemoteComputePlan | None = None

    @model_validator(mode="after")
    def unique_step_ids(self) -> "ReplicationPlan":
        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Replication-plan step IDs must be unique")
        return self


class ReplicationFix(StrictModel):
    file_path: str
    description: str
    original_error: str
    diff_snippet: str


class ReplicationStepOutcome(StrictModel):
    step_id: int = Field(ge=1)
    description: str
    command_executed: str
    exit_code: int
    stdout: str
    stderr: str
    output_files: list[str]
    duration_seconds: float = Field(ge=0)
    fixes_applied: list[ReplicationFix]
    code_modified: bool
    notes: str


class ReplicationLog(StrictModel):
    step_outcomes: list[ReplicationStepOutcome] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_step_ids(self) -> "ReplicationLog":
        step_ids = [outcome.step_id for outcome in self.step_outcomes]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Replication-log step IDs must be unique")
        return self


class EvidenceEnvironment(StrictModel):
    model_config = ConfigDict(extra="allow")

    python_version: str
    gpu_available: bool
    gpu_model: str | None
    key_packages: dict[str, str]


class EvidenceSummary(StrictModel):
    environment: EvidenceEnvironment


class SmartReplicateRound(StrictModel):
    round: int = Field(ge=1, le=5)
    observed_result: Any
    anchor_comparison: str
    hypothesis: str
    changes: list[str] = Field(min_length=1)
    commands: list[str] = Field(min_length=1)
    result_after_change: Any
    conclusion: str


class SmartReplicateLog(StrictModel):
    experiment_id: str
    baseline_result: Any
    anchors: dict[str, Any]
    rounds: list[SmartReplicateRound] = Field(max_length=5)
    final_result: Any

    @model_validator(mode="after")
    def sequential_rounds(self) -> "SmartReplicateLog":
        round_numbers = [round_record.round for round_record in self.rounds]
        if round_numbers != list(range(1, len(self.rounds) + 1)):
            raise ValueError("Smart-replicate rounds must be sequential from 1")
        return self


AnchorName = Literal[
    "task_and_prediction_target",
    "dataset_cohort_and_io",
    "metrics_and_protocol",
    "baseline_method",
]


class ResearchAnchors(StrictModel):
    task: str = Field(min_length=1)
    prediction_target: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    cohort: str = Field(min_length=1)
    inputs: list[str] = Field(min_length=1)
    outputs: list[str] = Field(min_length=1)
    metrics: list[str] = Field(min_length=1)
    experiment_protocol: list[str] = Field(min_length=1)
    baseline_method: str = Field(min_length=1)


class EligibilityResult(StrictModel):
    eligible: bool
    reason: str = Field(min_length=1)
    evidence_paths: list[str]
    anchors: ResearchAnchors | None = None

    @model_validator(mode="after")
    def eligible_run_has_anchors(self) -> "EligibilityResult":
        if self.eligible and self.anchors is None:
            raise ValueError("Eligible Auto Research runs must define research anchors")
        return self


class IdeaChangePoint(StrictModel):
    path: str = Field(min_length=1)
    change: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class IdeaImplementationPlan(StrictModel):
    idea_id: str = Field(pattern=r"^R\d{2}-I\d{2}$")
    summary: str = Field(min_length=1)
    change_points: list[IdeaChangePoint] = Field(min_length=1)
    baseline_entry_points: list[str] = Field(min_length=1)
    refinement_entry_points: list[str] = Field(min_length=1)
    preserved_anchors: list[AnchorName]

    @model_validator(mode="after")
    def preserves_every_anchor(self) -> "IdeaImplementationPlan":
        expected = {
            "task_and_prediction_target",
            "dataset_cohort_and_io",
            "metrics_and_protocol",
            "baseline_method",
        }
        if len(self.preserved_anchors) != len(set(self.preserved_anchors)):
            raise ValueError("preserved_anchors must be unique")
        if set(self.preserved_anchors) != expected:
            raise ValueError("implementation plan must preserve all four research anchors")
        return self


class CodegenAuditCheck(StrictModel):
    anchor: AnchorName
    verdict: Literal["pass", "fail"]
    evidence: list[str] = Field(min_length=1)
    issue: str | None = None

    @model_validator(mode="after")
    def failed_check_has_issue(self) -> "CodegenAuditCheck":
        if self.verdict == "fail" and not self.issue:
            raise ValueError("A failed codegen audit check must describe its issue")
        return self


class CodegenAudit(StrictModel):
    idea_id: str = Field(pattern=r"^R\d{2}-I\d{2}$")
    verdict: Literal["pass", "fail"]
    checks: list[CodegenAuditCheck]
    required_fixes: list[str]

    @model_validator(mode="after")
    def covers_exact_anchor_contract(self) -> "CodegenAudit":
        anchors = [check.anchor for check in self.checks]
        expected = {
            "task_and_prediction_target",
            "dataset_cohort_and_io",
            "metrics_and_protocol",
            "baseline_method",
        }
        if len(anchors) != 4 or set(anchors) != expected:
            raise ValueError("codegen audit must check each research anchor exactly once")
        expected_verdict = "pass" if all(check.verdict == "pass" for check in self.checks) else "fail"
        if self.verdict != expected_verdict:
            raise ValueError("codegen audit verdict does not match its checks")
        if self.verdict == "fail" and not self.required_fixes:
            raise ValueError("A failed codegen audit must list required fixes")
        if self.verdict == "pass" and self.required_fixes:
            raise ValueError("A passing codegen audit cannot list required fixes")
        return self


class MetricComparison(StrictModel):
    name: str = Field(min_length=1)
    direction: Literal["higher", "lower"]
    baseline_value: float | None
    refined_value: float | None
    absolute_delta: float | None
    relative_delta: float | None
    uncertainty_available: bool
    noise_threshold: float | None = Field(default=None, ge=0)
    uncertainty_method: str | None = None
    improvement_supported: bool

    @model_validator(mode="after")
    def validate_comparison(self) -> "MetricComparison":
        if self.baseline_value is None or self.refined_value is None:
            if self.improvement_supported:
                raise ValueError("A metric without both values cannot support improvement")
            return self

        expected_delta = self.refined_value - self.baseline_value
        if self.absolute_delta is None or not math.isclose(
            self.absolute_delta,
            expected_delta,
            rel_tol=1e-6,
            abs_tol=1e-9,
        ):
            raise ValueError("absolute_delta must equal refined_value - baseline_value")
        if self.baseline_value == 0:
            if self.relative_delta is not None:
                raise ValueError("relative_delta must be null when baseline_value is zero")
        else:
            expected_relative = expected_delta / abs(self.baseline_value)
            if self.relative_delta is None or not math.isclose(
                self.relative_delta,
                expected_relative,
                rel_tol=1e-6,
                abs_tol=1e-9,
            ):
                raise ValueError("relative_delta is inconsistent with the metric values")

        if self.uncertainty_available:
            if self.noise_threshold is None or not self.uncertainty_method:
                raise ValueError(
                    "Metrics with uncertainty must record its method and noise threshold"
                )
            threshold = self.noise_threshold
        else:
            if self.noise_threshold is not None or self.uncertainty_method is not None:
                raise ValueError(
                    "Metrics without uncertainty cannot record an uncertainty threshold"
                )
            threshold = 0.0
        directed_delta = expected_delta if self.direction == "higher" else -expected_delta
        if self.improvement_supported != (directed_delta > threshold):
            raise ValueError("improvement_supported does not match the declared criterion")
        return self


class IdeaAssessment(StrictModel):
    idea_id: str = Field(pattern=r"^R\d{2}-I\d{2}$")
    verdict: Literal["valid", "invalid", "inconclusive"]
    summary: str = Field(min_length=1)
    audit_passed: bool
    protocol_consistent: bool
    primary_metric: MetricComparison | None
    secondary_metrics: list[MetricComparison]
    evidence_paths: list[str]
    failure_reasons: list[str]

    @model_validator(mode="after")
    def valid_verdict_has_supported_improvement(self) -> "IdeaAssessment":
        supported = self.primary_metric is not None and self.primary_metric.improvement_supported
        if (not self.audit_passed or not self.protocol_consistent) and self.verdict != "invalid":
            raise ValueError(
                "A failed audit or inconsistent protocol requires an invalid verdict"
            )
        if self.verdict == "valid" and not (
            self.audit_passed and self.protocol_consistent and supported
        ):
            raise ValueError(
                "A valid refinement requires a passing audit, consistent protocol, "
                "and supported primary-metric improvement"
            )
        if self.verdict == "valid" and self.failure_reasons:
            raise ValueError("A valid refinement cannot list failure reasons")
        if self.verdict != "valid" and not self.failure_reasons:
            raise ValueError("A non-valid refinement must list failure reasons")
        if self.verdict == "inconclusive" and supported:
            raise ValueError("An inconclusive refinement cannot claim supported improvement")
        return self


class RoundIdeaSummary(StrictModel):
    idea_id: str = Field(pattern=r"^R\d{2}-I\d{2}$")
    verdict: Literal["valid", "invalid", "inconclusive"]
    reason: str = Field(min_length=1)
    assessment_path: str = Field(min_length=1)


class RoundSummary(StrictModel):
    round: int = Field(ge=1, le=10)
    ideas: list[RoundIdeaSummary]
    has_valid_refinement: bool

    @model_validator(mode="after")
    def summarizes_three_unique_ideas(self) -> "RoundSummary":
        idea_ids = [idea.idea_id for idea in self.ideas]
        expected = [f"R{self.round:02d}-I{index:02d}" for index in range(1, 4)]
        if idea_ids != expected:
            raise ValueError("round summary must list its three ideas in order")
        if self.has_valid_refinement != any(idea.verdict == "valid" for idea in self.ideas):
            raise ValueError("has_valid_refinement does not match idea verdicts")
        return self


def validate_experiment_coverage(claims: ClaimsFile, todo: ExperimentTodo) -> None:
    known_claims = {claim.claim_id for claim in claims.claims}
    referenced_claims = {
        claim_id for experiment in todo.experiments for claim_id in experiment.claims
    }
    unknown_claims = referenced_claims - known_claims
    missing_claims = known_claims - referenced_claims
    if unknown_claims:
        raise ValueError(f"Experiments reference unknown claims: {sorted(unknown_claims)}")
    if missing_claims:
        raise ValueError(f"Claims missing from experiments: {sorted(missing_claims)}")


def validate_replication_plan(todo: ExperimentTodo, plan: ReplicationPlan) -> None:
    expected = {
        reference
        for experiment in todo.experiments
        for reference in (*experiment.claims, *experiment.artifacts)
    }
    actual = {reference for step in plan.steps for reference in step.verifies}
    unknown = actual - expected
    missing = expected - actual
    if unknown:
        raise ValueError(f"Replication plan verifies unknown references: {sorted(unknown)}")
    if missing:
        raise ValueError(f"Replication plan is missing references: {sorted(missing)}")


def validate_replication_log(plan: ReplicationPlan, log: ReplicationLog) -> None:
    planned_ids = [step.id for step in plan.steps]
    outcome_ids = [outcome.step_id for outcome in log.step_outcomes]
    if outcome_ids != planned_ids:
        raise ValueError("Replication log must cover plan steps in order")
    outcomes_by_id = {outcome.step_id: outcome for outcome in log.step_outcomes}
    missing_outputs = [
        step.id
        for step in plan.steps
        if step.verifies and not outcomes_by_id[step.id].output_files
    ]
    if missing_outputs:
        raise ValueError(
            f"Result-producing replication steps have no output files: {missing_outputs}"
        )


def validate_smart_replicate_log(
    experiment: Experiment,
    log: SmartReplicateLog,
    anchors: dict[str, Any],
) -> None:
    if log.experiment_id != experiment.experiment_id:
        raise ValueError(
            f"Smart-replicate log ID {log.experiment_id} does not match "
            f"{experiment.experiment_id}"
        )
    if set(anchors) != set(experiment.claims):
        raise ValueError(
            f"Expected smart-replicate anchors do not match {experiment.experiment_id}"
        )
    if log.anchors != anchors:
        raise ValueError(
            f"Smart-replicate log anchors do not match {experiment.experiment_id}"
        )


def validate_reproduction_report(
    report_text: str,
    claims: ClaimsFile,
    experiments: ExperimentTodo,
    codegen_plan: CodegenPlan,
) -> None:
    required_sections = [
        "## 1. Per-experiment reports",
        "## 2. Validation claim assessment",
        "## 3. Replication risk list",
    ]
    invalid_sections = [
        section for section in required_sections if report_text.count(section) != 1
    ]
    if invalid_sections:
        raise ValueError(
            "Report must contain exactly one of each required section: "
            f"{invalid_sections}"
        )
    section_positions = [report_text.index(section) for section in required_sections]
    if section_positions != sorted(section_positions):
        raise ValueError("Report required sections are out of order")
    per_experiment_text = report_text.split(required_sections[0], 1)[1].split(
        required_sections[1], 1
    )[0]
    validation_text = report_text.split(required_sections[1], 1)[1].split(
        required_sections[2], 1
    )[0]
    risk_text = report_text.split(required_sections[2], 1)[1]

    def contains_identifier(text: str, identifier: str) -> bool:
        return re.search(
            rf"(?<![A-Za-z0-9_.-]){re.escape(identifier)}(?![A-Za-z0-9_.-])",
            text,
        ) is not None

    missing_experiments = [
        experiment.experiment_id
        for experiment in experiments.experiments
        if not contains_identifier(per_experiment_text, experiment.experiment_id)
    ]
    if missing_experiments:
        raise ValueError(f"Report is missing experiments: {missing_experiments}")
    missing_claims = [
        claim.claim_id
        for claim in claims.claims
        if not contains_identifier(per_experiment_text, claim.claim_id)
    ]
    if missing_claims:
        raise ValueError(f"Report is missing claims: {missing_claims}")
    missing_artifacts = [
        artifact
        for experiment in experiments.experiments
        for artifact in experiment.artifacts
        if artifact not in per_experiment_text
    ]
    if missing_artifacts:
        raise ValueError(f"Report is missing artifacts: {missing_artifacts}")
    missing_validation_claims = [
        claim.claim_id
        for claim in claims.claims
        if claim.role == "validation"
        and not contains_identifier(validation_text, claim.claim_id)
    ]
    if missing_validation_claims:
        raise ValueError(
            f"Report is missing validation claim assessments: {missing_validation_claims}"
        )
    missing_ambiguities = [
        ambiguity.question
        for ambiguity in codegen_plan.ambiguities
        if ambiguity.question not in risk_text or ambiguity.assumption not in risk_text
    ]
    if missing_ambiguities:
        raise ValueError(f"Report is missing ambiguity risks: {missing_ambiguities}")
