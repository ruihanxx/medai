from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provenance(StrictModel):
    page: int = Field(ge=1)
    section: str


class Claim(StrictModel):
    claim_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    statement: str
    kind: Literal["text", "numeric"]
    paper_result: Any
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


class CodegenPlan(StrictModel):
    files: list[PlannedFile] = Field(min_length=1)
    dependency_order: list[str] = Field(min_length=1)
    entry_points: list[str] = Field(min_length=1)
    shared_state: str
    ambiguities: list[Ambiguity]


class ReplicationStep(StrictModel):
    step_id: str
    description: str
    command: str
    expected_outputs: list[str]


class ReplicationExperiment(StrictModel):
    experiment_id: str
    claims: list[str]
    artifacts: list[str]
    steps: list[ReplicationStep] = Field(min_length=1)


class ReplicationPlan(StrictModel):
    experiments: list[ReplicationExperiment] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_experiment_ids(self) -> "ReplicationPlan":
        experiment_ids = [experiment.experiment_id for experiment in self.experiments]
        if len(experiment_ids) != len(set(experiment_ids)):
            raise ValueError("Replication-plan experiment IDs must be unique")
        return self


class ClaimResult(StrictModel):
    claim_id: str
    reproduced_result: Any
    evidence: list[str] = Field(min_length=1)


class ArtifactResult(StrictModel):
    artifact_id: str
    path: str


class ExperimentResult(StrictModel):
    experiment_id: str
    claims: list[ClaimResult]
    artifacts: list[ArtifactResult]
    commands: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_result_mappings(self) -> "ExperimentResult":
        claim_ids = [claim.claim_id for claim in self.claims]
        artifact_ids = [artifact.artifact_id for artifact in self.artifacts]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("Result claim IDs must be unique")
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("Result artifact IDs must be unique")
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
        experiment.experiment_id: (set(experiment.claims), set(experiment.artifacts))
        for experiment in todo.experiments
    }
    actual = {
        experiment.experiment_id: (set(experiment.claims), set(experiment.artifacts))
        for experiment in plan.experiments
    }
    if expected != actual:
        raise ValueError("Replication plan does not match experiment claim/artifact mappings")


def validate_experiment_result(experiment: Experiment, result: ExperimentResult) -> None:
    if result.experiment_id != experiment.experiment_id:
        raise ValueError(
            f"Result ID {result.experiment_id} does not match {experiment.experiment_id}"
        )
    expected_claims = set(experiment.claims)
    actual_claims = {claim.claim_id for claim in result.claims}
    expected_artifacts = set(experiment.artifacts)
    actual_artifacts = {artifact.artifact_id for artifact in result.artifacts}
    if expected_claims != actual_claims:
        raise ValueError(f"Result claim coverage does not match {experiment.experiment_id}")
    if expected_artifacts != actual_artifacts:
        raise ValueError(f"Result artifact coverage does not match {experiment.experiment_id}")
