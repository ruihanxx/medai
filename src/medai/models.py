from __future__ import annotations

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
