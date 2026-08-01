from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provenance(StrictModel):
    page: int = Field(ge=1)
    section: str


class Claim(StrictModel):
    claim_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    statement: str
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


class InventoryDataset(StrictModel):
    id: str | None
    root: str | None
    adapter: str | None
    status: Literal["explored", "not_supplied"]


class InventoryScan(StrictModel):
    files_scanned: int = Field(ge=0)
    bytes_scanned: int = Field(ge=0)
    truncated: bool
    limits: dict[str, int]


class DataInventory(StrictModel):
    schema_version: Literal[1]
    dataset: InventoryDataset
    scan: InventoryScan
    catalog: list[dict[str, Any]]
    explored_files: list[dict[str, Any]]
    warnings: list[str]


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


class ReplicationStep(StrictModel):
    step_id: str
    description: str
    command: str
    expected_outputs: list[str]
    verifies: list[str]


class ReplicationExperiment(StrictModel):
    experiment_id: str
    claims: list[str]
    artifacts: list[str]
    steps: list[ReplicationStep] = Field(min_length=1)

    @model_validator(mode="after")
    def mapped_outputs_are_covered(self) -> "ReplicationExperiment":
        expected = set(self.claims) | set(self.artifacts)
        verified = {item for step in self.steps for item in step.verifies}
        unknown = verified - expected
        missing = expected - verified
        if unknown:
            raise ValueError(f"Plan steps verify unknown claims/artifacts: {sorted(unknown)}")
        if missing:
            raise ValueError(f"Plan steps do not cover claims/artifacts: {sorted(missing)}")
        return self


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


def validate_data_inventory(data_dir: Path | None, inventory: DataInventory) -> None:
    if data_dir is None:
        if inventory.dataset.status != "not_supplied":
            raise ValueError("Data inventory must report not_supplied when no data is configured")
        if any(
            (
                inventory.dataset.id is not None,
                inventory.dataset.root is not None,
                inventory.dataset.adapter is not None,
                inventory.scan.files_scanned != 0,
                inventory.scan.bytes_scanned != 0,
                inventory.scan.truncated,
                bool(inventory.scan.limits),
                bool(inventory.catalog),
                bool(inventory.explored_files),
            )
        ):
            raise ValueError("not_supplied data inventory must be empty")
        return

    if inventory.dataset.status != "explored":
        raise ValueError("Data inventory must report explored when data is configured")
    if inventory.dataset.root is None:
        raise ValueError("Explored data inventory must record the data root")
    if Path(inventory.dataset.root).expanduser().resolve() != data_dir.resolve():
        raise ValueError("Data inventory root does not match the configured data directory")
    if not inventory.dataset.id or not inventory.dataset.adapter:
        raise ValueError("Explored data inventory must identify its dataset and adapter")


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
