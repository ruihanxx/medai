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


class RemoteComputePlan(StrictModel):
    provider: str = Field(min_length=1)
    state_path: str
    remote_working_directory: str
    setup_hints: list[str]


class CodegenPlan(StrictModel):
    files: list[PlannedFile] = Field(min_length=1)
    dependency_order: list[str] = Field(min_length=1)
    entry_points: list[str] = Field(min_length=1)
    shared_state: str
    ambiguities: list[Ambiguity]
    remote_compute: RemoteComputePlan | None


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


class ResearchBrief(StrictModel):
    problem: str = Field(min_length=1)
    context: str = Field(min_length=1)
    proposed_method: str = Field(min_length=1)
    datasets: list[str] = Field(min_length=1)


class EligibilityResult(StrictModel):
    eligible: bool
    reason: str = Field(min_length=1)
    evidence_paths: list[str]
    research_brief: ResearchBrief | None = None

    @model_validator(mode="after")
    def eligible_run_has_research_brief(self) -> "EligibilityResult":
        if self.eligible and self.research_brief is None:
            raise ValueError("Eligible Auto Research runs must define a research brief")
        if not self.eligible and self.research_brief is not None:
            raise ValueError("Ineligible Auto Research runs cannot define a research brief")
        return self


class ExperimentImportance(StrictModel):
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    weight: float = Field(gt=0, le=1)
    rationale: str = Field(min_length=1)


class ExperimentWeights(StrictModel):
    experiments: list[ExperimentImportance] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids_and_normalized_weights(self) -> "ExperimentWeights":
        experiment_ids = [experiment.experiment_id for experiment in self.experiments]
        if len(experiment_ids) != len(set(experiment_ids)):
            raise ValueError("Experiment-weight IDs must be unique")
        if not math.isclose(
            sum(experiment.weight for experiment in self.experiments),
            1.0,
            rel_tol=1e-6,
            abs_tol=1e-9,
        ):
            raise ValueError("Experiment weights must sum to 1")
        return self


class ExperimentContract(StrictModel):
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    baseline_entry_points: list[str] = Field(min_length=1)
    model_implementation_paths: list[str] = Field(min_length=1)
    integration_paths: list[str] = Field(min_length=1)
    input_contract: str = Field(min_length=1)
    target_contract: str = Field(min_length=1)
    output_contract: str = Field(min_length=1)
    training_contract: str = Field(min_length=1)
    evaluation_contract: str = Field(min_length=1)
    metrics: list[str] = Field(min_length=1)
    primary_metric: str = Field(min_length=1)
    metric_direction: Literal["higher", "lower"]

    @model_validator(mode="after")
    def primary_metric_is_declared(self) -> "ExperimentContract":
        if self.primary_metric not in self.metrics:
            raise ValueError("Experiment primary_metric must appear in metrics")
        return self


class ExperimentContracts(StrictModel):
    experiments: list[ExperimentContract] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_experiment_ids(self) -> "ExperimentContracts":
        experiment_ids = [experiment.experiment_id for experiment in self.experiments]
        if len(experiment_ids) != len(set(experiment_ids)):
            raise ValueError("Experiment-contract IDs must be unique")
        return self


class IdeaChangePoint(StrictModel):
    path: str = Field(min_length=1)
    change: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class IdeaExperimentIntegration(StrictModel):
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    integration_changes: list[IdeaChangePoint] = Field(min_length=1)
    baseline_entry_points: list[str] = Field(min_length=1)
    refinement_entry_points: list[str] = Field(min_length=1)


class IdeaImplementationPlan(StrictModel):
    idea_id: str = Field(pattern=r"^R\d{2}-I\d{2}$")
    summary: str = Field(min_length=1)
    model_description: str = Field(min_length=1)
    new_model_files: list[str] = Field(min_length=1)
    experiment_integrations: list[IdeaExperimentIntegration] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_model_files_and_experiment_ids(self) -> "IdeaImplementationPlan":
        if len(self.new_model_files) != len(set(self.new_model_files)):
            raise ValueError("new_model_files must be unique")
        experiment_ids = [
            integration.experiment_id for integration in self.experiment_integrations
        ]
        if len(experiment_ids) != len(set(experiment_ids)):
            raise ValueError("Implementation experiment IDs must be unique")
        return self


ContractAspect = Literal["input", "target", "output", "training", "evaluation"]


class CodegenAuditCheck(StrictModel):
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    aspect: ContractAspect
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
    model_only: bool
    scope_evidence: list[str] = Field(min_length=1)
    scope_issue: str | None = None
    checks: list[CodegenAuditCheck] = Field(min_length=1)
    required_fixes: list[str]

    @model_validator(mode="after")
    def verdict_matches_scope_and_checks(self) -> "CodegenAudit":
        pairs = [(check.experiment_id, check.aspect) for check in self.checks]
        if len(pairs) != len(set(pairs)):
            raise ValueError("Codegen audit experiment/aspect checks must be unique")
        if not self.model_only and not self.scope_issue:
            raise ValueError("A non-model-only audit must describe the scope issue")
        if self.model_only and self.scope_issue:
            raise ValueError("A model-only audit cannot report a scope issue")
        expected_verdict = (
            "pass"
            if self.model_only and all(check.verdict == "pass" for check in self.checks)
            else "fail"
        )
        if self.verdict != expected_verdict:
            raise ValueError("codegen audit verdict does not match its checks")
        if self.verdict == "fail" and not self.required_fixes:
            raise ValueError("A failed codegen audit must list required fixes")
        if self.verdict == "pass" and self.required_fixes:
            raise ValueError("A passing codegen audit cannot list required fixes")
        return self


class RefinementExperimentPlan(StrictModel):
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    steps: list[ReplicationStep] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def unique_step_ids(self) -> "RefinementExperimentPlan":
        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Refinement experiment step IDs must be unique")
        return self


class AutoResearchExperimentPlan(StrictModel):
    environment: PlanEnvironment
    experiments: list[RefinementExperimentPlan] = Field(min_length=1)
    remote_compute: RemoteComputePlan | None = None

    @model_validator(mode="after")
    def unique_experiment_ids(self) -> "AutoResearchExperimentPlan":
        experiment_ids = [experiment.experiment_id for experiment in self.experiments]
        if len(experiment_ids) != len(set(experiment_ids)):
            raise ValueError("Auto Research experiment-plan IDs must be unique")
        return self


class RefinementExperimentLog(StrictModel):
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    step_outcomes: list[ReplicationStepOutcome] = Field(min_length=1)


class AutoResearchExperimentLog(StrictModel):
    experiments: list[RefinementExperimentLog] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_experiment_ids(self) -> "AutoResearchExperimentLog":
        experiment_ids = [experiment.experiment_id for experiment in self.experiments]
        if len(experiment_ids) != len(set(experiment_ids)):
            raise ValueError("Auto Research experiment-log IDs must be unique")
        return self


class ExperimentMetricComparison(StrictModel):
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    metric_name: str = Field(min_length=1)
    direction: Literal["higher", "lower"]
    weight: float = Field(gt=0, le=1)
    baseline_value: float | None
    refined_value: float | None
    absolute_delta: float | None
    relative_delta: float | None
    score: float | None
    weighted_score: float | None
    evidence_paths: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_comparison(self) -> "ExperimentMetricComparison":
        if self.baseline_value is None or self.refined_value is None:
            if any(
                value is not None
                for value in (
                    self.absolute_delta,
                    self.relative_delta,
                    self.score,
                    self.weighted_score,
                )
            ):
                raise ValueError("An incomplete comparison cannot define derived scores")
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
            if any(
                value is not None
                for value in (self.relative_delta, self.score, self.weighted_score)
            ):
                raise ValueError(
                    "Relative and weighted scores must be null when baseline_value is zero"
                )
        else:
            expected_relative = expected_delta / abs(self.baseline_value)
            if self.relative_delta is None or not math.isclose(
                self.relative_delta,
                expected_relative,
                rel_tol=1e-6,
                abs_tol=1e-9,
            ):
                raise ValueError("relative_delta is inconsistent with the metric values")
            expected_score = (
                expected_relative if self.direction == "higher" else -expected_relative
            )
            if self.score is None or not math.isclose(
                self.score,
                expected_score,
                rel_tol=1e-6,
                abs_tol=1e-9,
            ):
                raise ValueError("score is inconsistent with metric direction")
            expected_weighted = expected_score * self.weight
            if self.weighted_score is None or not math.isclose(
                self.weighted_score,
                expected_weighted,
                rel_tol=1e-6,
                abs_tol=1e-9,
            ):
                raise ValueError("weighted_score is inconsistent with score and weight")
        return self


class IdeaAssessment(StrictModel):
    idea_id: str = Field(pattern=r"^R\d{2}-I\d{2}$")
    verdict: Literal["valid", "invalid", "inconclusive"]
    summary: str = Field(min_length=1)
    audit_passed: bool
    protocol_consistent: bool
    experiments: list[ExperimentMetricComparison]
    weighted_score: float | None
    threshold: float = Field(ge=0)
    failure_reasons: list[str]

    @model_validator(mode="after")
    def verdict_matches_weighted_score(self) -> "IdeaAssessment":
        experiment_ids = [experiment.experiment_id for experiment in self.experiments]
        if len(experiment_ids) != len(set(experiment_ids)):
            raise ValueError("Assessment experiment IDs must be unique")
        expected_score = None
        if self.experiments and all(
            experiment.weighted_score is not None for experiment in self.experiments
        ):
            expected_score = sum(
                experiment.weighted_score
                for experiment in self.experiments
                if experiment.weighted_score is not None
            )
        if expected_score is None:
            if self.weighted_score is not None:
                raise ValueError("Incomplete experiment comparisons require a null weighted score")
        elif self.weighted_score is None or not math.isclose(
            self.weighted_score,
            expected_score,
            rel_tol=1e-6,
            abs_tol=1e-9,
        ):
            raise ValueError("Assessment weighted score does not match experiment scores")

        if (not self.audit_passed or not self.protocol_consistent) and self.verdict != "invalid":
            raise ValueError(
                "A failed audit or inconsistent protocol requires an invalid verdict"
            )
        if self.audit_passed and self.protocol_consistent:
            expected_verdict = (
                "inconclusive"
                if expected_score is None
                else "valid"
                if expected_score > self.threshold
                else "invalid"
            )
            if self.verdict != expected_verdict:
                raise ValueError("Assessment verdict does not match its weighted score")
        if self.verdict == "valid" and self.failure_reasons:
            raise ValueError("A valid refinement cannot list failure reasons")
        if self.verdict != "valid" and not self.failure_reasons:
            raise ValueError("A non-valid refinement must list failure reasons")
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


def validate_experiment_weights(
    todo: ExperimentTodo,
    weights: ExperimentWeights,
) -> None:
    expected = [experiment.experiment_id for experiment in todo.experiments]
    actual = [experiment.experiment_id for experiment in weights.experiments]
    if actual != expected:
        raise ValueError("Experiment weights must cover every experiment in order")


def validate_experiment_contracts(
    todo: ExperimentTodo,
    contracts: ExperimentContracts,
) -> None:
    expected = [experiment.experiment_id for experiment in todo.experiments]
    actual = [experiment.experiment_id for experiment in contracts.experiments]
    if actual != expected:
        raise ValueError("Experiment contracts must cover every experiment in order")


def validate_idea_implementation_plan(
    contracts: ExperimentContracts,
    plan: IdeaImplementationPlan,
) -> None:
    expected = [experiment.experiment_id for experiment in contracts.experiments]
    actual = [integration.experiment_id for integration in plan.experiment_integrations]
    if actual != expected:
        raise ValueError("Implementation plan must integrate the model into every experiment")


def validate_codegen_audit(
    contracts: ExperimentContracts,
    audit: CodegenAudit,
) -> None:
    aspects = ["input", "target", "output", "training", "evaluation"]
    expected = [
        (experiment.experiment_id, aspect)
        for experiment in contracts.experiments
        for aspect in aspects
    ]
    actual = [(check.experiment_id, check.aspect) for check in audit.checks]
    if actual != expected:
        raise ValueError(
            "Codegen audit must check every experiment contract aspect in order"
        )


def validate_autoresearch_experiment_plan(
    contracts: ExperimentContracts,
    implementation: IdeaImplementationPlan,
    plan: AutoResearchExperimentPlan,
) -> None:
    expected = [experiment.experiment_id for experiment in contracts.experiments]
    actual = [experiment.experiment_id for experiment in plan.experiments]
    if actual != expected:
        raise ValueError(
            "Auto Research experiment plan must cover every experiment in order"
        )
    integrations = {
        integration.experiment_id: integration
        for integration in implementation.experiment_integrations
    }
    for experiment in plan.experiments:
        commands = {step.command_hint.strip() for step in experiment.steps}
        integration = integrations[experiment.experiment_id]
        baseline_commands = {
            command.strip() for command in integration.baseline_entry_points
        }
        if commands & baseline_commands:
            raise ValueError(
                f"Auto Research plan reruns a baseline: {experiment.experiment_id}"
            )
        refinement_commands = {
            command.strip() for command in integration.refinement_entry_points
        }
        if not commands & refinement_commands:
            raise ValueError(
                f"Auto Research plan is missing a refinement entry point: "
                f"{experiment.experiment_id}"
            )


def validate_autoresearch_experiment_log(
    plan: AutoResearchExperimentPlan,
    log: AutoResearchExperimentLog,
) -> None:
    expected = [experiment.experiment_id for experiment in plan.experiments]
    actual = [experiment.experiment_id for experiment in log.experiments]
    if actual != expected:
        raise ValueError("Auto Research experiment log must cover every experiment in order")
    for planned_experiment, logged_experiment in zip(
        plan.experiments,
        log.experiments,
        strict=True,
    ):
        planned_ids = [step.id for step in planned_experiment.steps]
        outcome_ids = [outcome.step_id for outcome in logged_experiment.step_outcomes]
        if outcome_ids != planned_ids:
            raise ValueError(
                f"Experiment log must cover steps in order: {planned_experiment.experiment_id}"
            )
        outcomes_by_id = {
            outcome.step_id: outcome for outcome in logged_experiment.step_outcomes
        }
        missing_outputs = [
            step.id
            for step in planned_experiment.steps
            if step.verifies and not outcomes_by_id[step.id].output_files
        ]
        if missing_outputs:
            raise ValueError(
                "Result-producing Auto Research steps have no output files for "
                f"{planned_experiment.experiment_id}: {missing_outputs}"
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
