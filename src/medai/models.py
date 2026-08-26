from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenModel(BaseModel):
    """Small validated envelope whose scientific payload remains extensible."""

    model_config = ConfigDict(extra="allow")


class GraphNode(OpenModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    inputs: list[str]
    method: Any
    paper_result: Any = None
    provenance: list[dict[str, Any]]

    @model_validator(mode="after")
    def unique_inputs(self) -> "GraphNode":
        if len(self.inputs) != len(set(self.inputs)):
            raise ValueError(f"Graph node {self.id} contains duplicate inputs")
        if self.id in self.inputs:
            raise ValueError(f"Graph node {self.id} cannot depend on itself")
        return self


class PaperGraph(OpenModel):
    version: Literal[1] = 1
    datasets: list[GraphNode]
    preprocessing: list[GraphNode]
    training: list[GraphNode]
    models: list[GraphNode]
    validations: list[GraphNode]
    claims: list[GraphNode] = Field(min_length=1)

    @property
    def collections(self) -> tuple[tuple[str, list[GraphNode]], ...]:
        return (
            ("datasets", self.datasets),
            ("preprocessing", self.preprocessing),
            ("training", self.training),
            ("models", self.models),
            ("validations", self.validations),
            ("claims", self.claims),
        )

    @property
    def nodes(self) -> list[GraphNode]:
        return [node for _, collection in self.collections for node in collection]

    @property
    def node_map(self) -> dict[str, GraphNode]:
        return {node.id: node for node in self.nodes}

    @property
    def category_map(self) -> dict[str, str]:
        return {
            node.id: category
            for category, collection in self.collections
            for node in collection
        }

    @model_validator(mode="after")
    def validate_graph(self) -> "PaperGraph":
        nodes = self.nodes
        node_ids = [node.id for node in nodes]
        if len(node_ids) != len(set(node_ids)):
            duplicates = sorted({node_id for node_id in node_ids if node_ids.count(node_id) > 1})
            raise ValueError(f"Paper graph node IDs must be globally unique: {duplicates}")
        known = set(node_ids)
        unknown = sorted(
            {input_id for node in nodes for input_id in node.inputs if input_id not in known}
        )
        if unknown:
            raise ValueError(f"Paper graph inputs reference unknown node IDs: {unknown}")
        for claim in self.claims:
            if not claim.inputs:
                raise ValueError(f"Claim node {claim.id} must have at least one input")

        visiting: set[str] = set()
        visited: set[str] = set()
        node_map = self.node_map

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError(f"Paper graph contains a cycle at {node_id}")
            if node_id in visited:
                return
            visiting.add(node_id)
            for input_id in node_map[node_id].inputs:
                visit(input_id)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in node_ids:
            visit(node_id)

        consumers: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
        for node in nodes:
            for input_id in node.inputs:
                consumers[input_id].append(node.id)
        claim_ids = {claim.id for claim in self.claims}
        reaches_claim: dict[str, bool] = {}

        def reaches(node_id: str) -> bool:
            if node_id in reaches_claim:
                return reaches_claim[node_id]
            value = node_id in claim_ids or any(reaches(child) for child in consumers[node_id])
            reaches_claim[node_id] = value
            return value

        orphaned = [node_id for node_id in node_ids if not reaches(node_id)]
        if orphaned:
            raise ValueError(f"Every paper graph node must reach a claim: {orphaned}")
        return self


class NodeIssue(OpenModel):
    description: str = Field(min_length=1)

    @field_validator("description")
    @classmethod
    def nonblank_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Issue description must not be blank")
        return value


class NodeUpdate(OpenModel):
    source: str = Field(min_length=1)
    node_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    issues: list[NodeIssue] = Field(default_factory=list)


class PendingNodeUpdate(OpenModel):
    """Agent-authored update before the orchestrator assigns its source."""

    node_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    issues: list[NodeIssue] = Field(default_factory=list)


class NodeState(OpenModel):
    paper_graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    updates: list[NodeUpdate]

    @model_validator(mode="after")
    def unique_source_node_pairs(self) -> "NodeState":
        pairs = [(update.source, update.node_id) for update in self.updates]
        if len(pairs) != len(set(pairs)):
            raise ValueError("Node-state updates must be unique by (source, node_id)")
        return self


class GraphDataRequirementAvailability(StrictModel):
    preprocessing_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    dataset_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    source_kind: Literal["local", "cloud"] | None
    source_name: str | None
    required_content: str = Field(min_length=1)
    status: Literal["available", "source_blocked", "unknown"]
    evidence: str = Field(min_length=1)

    @model_validator(mode="after")
    def source_fields_match(self) -> "GraphDataRequirementAvailability":
        if (self.source_kind is None) != (self.source_name is None):
            raise ValueError("source_kind and source_name must both be set or both be null")
        if self.source_name is not None and not self.source_name.strip():
            raise ValueError("source_name must not be blank")
        return self


class GraphDataAvailabilityReport(StrictModel):
    capacity_decision: "CapacityDecision"
    requirements: list[GraphDataRequirementAvailability]


class BlockedNode(StrictModel):
    node_id: str
    status: Literal["source_blocked", "unknown"]
    direct_data_blockers: list[str]
    dependency_paths: list[list[str]]


class GraphExecutionScope(StrictModel):
    paper_graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    availability_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: Literal["FULL", "PARTIAL", "NONE", "UNKNOWN"]
    runnable_node_ids: list[str]
    blocked_nodes: list[BlockedNode]
    active_sources: list[str]
    execution_location: Literal["local", "remote"] | None


class GraphScopeRevisionIssue(StrictModel):
    node_ids: list[str] = Field(min_length=1)
    dataset_ids: list[str] = Field(min_length=1)
    required_content: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class GraphScopeRevisionIssues(StrictModel):
    scope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    issues: list[GraphScopeRevisionIssue] = Field(min_length=1)


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


class ExperimentDataset(StrictModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    usage: str = Field(min_length=1)

    @field_validator("name", "role", "usage")
    @classmethod
    def nonblank_dataset_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Experiment dataset fields must not be blank")
        return normalized


class Experiment(StrictModel):
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    description: str
    computational_demand: str = Field(min_length=1)
    datasets: list[ExperimentDataset] = Field(min_length=1)
    claims: list[str] = Field(min_length=1)
    artifacts: list[str]

    @model_validator(mode="after")
    def unique_mappings(self) -> "Experiment":
        if len(self.claims) != len(set(self.claims)):
            raise ValueError("Experiment claim IDs must be unique")
        if len(self.artifacts) != len(set(self.artifacts)):
            raise ValueError("Experiment artifact labels must be unique")
        dataset_names = [dataset.name.casefold() for dataset in self.datasets]
        if len(dataset_names) != len(set(dataset_names)):
            raise ValueError("Experiment dataset names must be unique")
        return self


class ExperimentTodo(StrictModel):
    experiments: list[Experiment] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_experiment_ids(self) -> "ExperimentTodo":
        experiment_ids = [experiment.experiment_id for experiment in self.experiments]
        if len(experiment_ids) != len(set(experiment_ids)):
            raise ValueError("experiment_id values must be unique")
        return self


class DataRequirementAvailability(StrictModel):
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    dataset: str = Field(min_length=1)
    source_kind: Literal["local", "cloud"] | None
    source_name: str | None
    required_content: str = Field(min_length=1)
    status: Literal["available", "source_blocked", "unknown"]
    evidence: str = Field(min_length=1)

    @model_validator(mode="after")
    def source_fields_match(self) -> "DataRequirementAvailability":
        if (self.source_kind is None) != (self.source_name is None):
            raise ValueError("source_kind and source_name must both be set or both be null")
        if self.source_name is not None and not self.source_name.strip():
            raise ValueError("source_name must not be blank")
        return self


class ExperimentDependency(StrictModel):
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    depends_on: list[str]
    evidence: str = Field(min_length=1)

    @model_validator(mode="after")
    def unique_dependencies(self) -> "ExperimentDependency":
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("depends_on IDs must be unique")
        if self.experiment_id in self.depends_on:
            raise ValueError("an experiment cannot depend on itself")
        return self


class CapacityDecision(StrictModel):
    execution_location: Literal["local", "remote"] | None
    rationale: str = Field(min_length=1)


class DataAvailabilityReport(StrictModel):
    capacity_decision: CapacityDecision
    requirements: list[DataRequirementAvailability]
    dependencies: list[ExperimentDependency]


class ScopeRevisionIssue(StrictModel):
    experiment_ids: list[str] = Field(min_length=1)
    datasets: list[str] = Field(min_length=1)
    required_content: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class ScopeRevisionIssues(StrictModel):
    scope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    issues: list[ScopeRevisionIssue] = Field(min_length=1)


class BlockedExperiment(StrictModel):
    experiment_id: str
    status: Literal["source_blocked", "unknown"]
    direct_data_blockers: list[str]
    dependency_paths: list[list[str]]


class ExecutionScope(StrictModel):
    availability_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: Literal["FULL", "PARTIAL", "NONE", "UNKNOWN"]
    runnable_experiment_ids: list[str]
    blocked_experiments: list[BlockedExperiment]
    active_sources: list[str]
    execution_location: Literal["local", "remote"] | None


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


class SkillCorrection(StrictModel):
    skill: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    reference_path: str = Field(min_length=1)
    discrepancy: str = Field(min_length=1)
    resolved_procedure: str = Field(min_length=1)
    documentation_urls: list[str]


class SkillCorrectionsFile(RootModel[list[SkillCorrection]]):
    pass


class RemoteComputePlan(BaseModel):
    model_config = ConfigDict(extra="allow")

    state_path: str = Field(min_length=1)
    remote_working_dir: str = Field(min_length=1)
    remote_dataset_dir: str = Field(min_length=1)


class CodegenPlan(StrictModel):
    files: list[PlannedFile] = Field(min_length=1)
    dependency_order: list[str] = Field(min_length=1)
    entry_points: list[str] = Field(min_length=1)
    shared_state: str
    node_updates: list[PendingNodeUpdate]
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
    node_updates: list[PendingNodeUpdate] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_step_ids(self) -> "ReplicationLog":
        step_ids = [outcome.step_id for outcome in self.step_outcomes]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Replication-log step IDs must be unique")
        return self


class AgentStageResult(StrictModel):
    status: Literal["completed", "blocked", "failed"]
    error: str | None

    @model_validator(mode="after")
    def status_matches_error(self) -> "AgentStageResult":
        if self.status == "completed":
            if self.error is not None:
                raise ValueError("completed agent stage result must have error=null")
        elif self.error is None or not self.error.strip():
            raise ValueError(f"{self.status} agent stage result requires a non-empty error")
        return self


class CodegenCloudPullRequest(StrictModel):
    status: Literal["command", "blocked", "failed"]
    command: str | None
    error: str | None

    @model_validator(mode="after")
    def status_matches_payload(self) -> "CodegenCloudPullRequest":
        if self.status == "command":
            if self.command is None or not self.command.strip():
                raise ValueError("cloud-pull command result requires a non-empty command")
            if self.error is not None:
                raise ValueError("cloud-pull command result must have error=null")
        else:
            if self.command is not None:
                raise ValueError(f"{self.status} cloud-pull result must have command=null")
            if self.error is None or not self.error.strip():
                raise ValueError(f"{self.status} cloud-pull result requires a non-empty error")
        return self


class ReplicationCommand(StrictModel):
    command: str = Field(min_length=1)

    @field_validator("command")
    @classmethod
    def nonempty_command(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("command must not be blank")
        return value


class AutoResearchCommand(StrictModel):
    operation: Literal["remote_exec", "download"]
    command: str | None
    remote: str | None
    destination: str | None

    @model_validator(mode="after")
    def fields_match_operation(self) -> "AutoResearchCommand":
        if self.operation == "remote_exec":
            if not isinstance(self.command, str) or not self.command.strip():
                raise ValueError("remote_exec requires a non-empty command")
            if self.remote is not None or self.destination is not None:
                raise ValueError("remote_exec accepts only its command")
        elif (
            self.command is not None
            or not isinstance(self.remote, str)
            or not self.remote.strip()
            or not isinstance(self.destination, str)
            or not self.destination.strip()
        ):
            raise ValueError("download requires non-empty remote and destination paths")
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
    claim_id: str
    baseline_result: Any
    paper_result: Any
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


class IdeaProvenance(StrictModel):
    reference: str = Field(min_length=1)
    support: str = Field(min_length=1)


class GeneratedIdea(StrictModel):
    idea_id: str = Field(pattern=r"^R\d{2,}-I\d{2}$")
    description: str = Field(min_length=1)
    motivation: str = Field(min_length=1)
    provenance: list[IdeaProvenance] = Field(min_length=1)


class IdeaGenerationArtifact(StrictModel):
    round_index: int = Field(ge=1)
    ideas: list[GeneratedIdea] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def exact_round_idea_ids(self) -> "IdeaGenerationArtifact":
        expected_ids = [f"R{self.round_index:02d}-I{idea_index:02d}" for idea_index in range(1, 4)]
        actual_ids = [idea.idea_id for idea in self.ideas]
        if actual_ids != expected_ids:
            raise ValueError(f"Ideas must use exactly these IDs in order: {expected_ids}")
        return self


class IdeaCandidateEvidence(StrictModel):
    source: Literal["paper", "experiment", "literature"]
    reference: str = Field(min_length=1)
    support: str = Field(min_length=1)


class IdeaCandidate(StrictModel):
    candidate_id: str = Field(pattern=r"^C\d{4}$")
    problem: str = Field(min_length=1)
    methods: list[str] = Field(min_length=1)
    motivation: str = Field(min_length=1)
    evidence: list[IdeaCandidateEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_methods(self) -> "IdeaCandidate":
        if len(self.methods) != len(set(self.methods)):
            raise ValueError("Candidate methods must be unique")
        return self


class IdeaCandidatePool(StrictModel):
    next_candidate_index: int = Field(ge=1)
    candidates: list[IdeaCandidate] = Field(max_length=6)
    selected_candidate_ids: list[str] = Field(max_length=3)

    @model_validator(mode="after")
    def valid_candidate_ids(self) -> "IdeaCandidatePool":
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("Candidate IDs must be unique")
        if any(
            re.fullmatch(r"C\d{4}", candidate_id) is None
            for candidate_id in self.selected_candidate_ids
        ):
            raise ValueError("Selected candidate IDs must use the C0001 format")
        if len(self.selected_candidate_ids) != len(set(self.selected_candidate_ids)):
            raise ValueError("Selected candidate IDs must be unique")
        if not set(self.selected_candidate_ids).issubset(candidate_ids):
            raise ValueError("Selected candidate IDs must exist in the candidate pool")
        used_indexes = [int(candidate_id[1:]) for candidate_id in candidate_ids]
        if used_indexes and self.next_candidate_index <= max(used_indexes):
            raise ValueError("next_candidate_index must exceed every candidate ID")
        return self


class ExperimentContract(StrictModel):
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    baseline_entry_points: list[str] = Field(min_length=1)
    model_implementation_paths: list[str] = Field(min_length=1)
    input_representation_paths: list[str] = Field(min_length=1)
    training_paths: list[str] = Field(min_length=1)
    integration_paths: list[str] = Field(min_length=1)
    data_contract: str = Field(min_length=1)
    prediction_target_contract: str = Field(min_length=1)
    input_representation_contract: str = Field(min_length=1)
    output_contract: str = Field(min_length=1)
    training_target_contract: str = Field(min_length=1)
    loss_contract: str = Field(min_length=1)
    training_contract: str = Field(min_length=1)
    evaluation_contract: str = Field(min_length=1)
    metrics: str = Field(min_length=1)
    primary_metric: str = Field(min_length=1)
    metric_direction: Literal["higher", "lower"]


class ExperimentContracts(StrictModel):
    experiments: list[ExperimentContract] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_experiment_ids(self) -> "ExperimentContracts":
        experiment_ids = [experiment.experiment_id for experiment in self.experiments]
        if len(experiment_ids) != len(set(experiment_ids)):
            raise ValueError("Experiment-contract IDs must be unique")
        return self


class IdeaFileChange(StrictModel):
    file_path: str = Field(min_length=1)
    change: str = Field(min_length=1)


RefinementType = Literal["input_representation", "model", "training_strategy"]


class IdeaImplementationPlan(StrictModel):
    idea_id: str = Field(pattern=r"^R\d{2}-I\d{2}$")
    summary: str = Field(min_length=1)
    refinement_types: list[RefinementType] = Field(min_length=1)
    refinement_description: str = Field(min_length=1)
    refine_file_list: list[IdeaFileChange]
    new_file_list: list[IdeaFileChange]

    @model_validator(mode="after")
    def unique_refinement_fields(self) -> "IdeaImplementationPlan":
        if len(self.refinement_types) != len(set(self.refinement_types)):
            raise ValueError("refinement_types must be unique")
        refine_paths = [item.file_path for item in self.refine_file_list]
        new_paths = [item.file_path for item in self.new_file_list]
        if len(refine_paths) != len(set(refine_paths)):
            raise ValueError("refine_file_list paths must be unique")
        if len(new_paths) != len(set(new_paths)):
            raise ValueError("new_file_list paths must be unique")
        overlap = set(refine_paths) & set(new_paths)
        if overlap:
            raise ValueError(
                f"Files cannot appear in both refine_file_list and new_file_list: {sorted(overlap)}"
            )
        if not refine_paths and not new_paths:
            raise ValueError("An implementation plan must declare at least one file change")
        if "model" in self.refinement_types and not new_paths:
            raise ValueError("A model refinement must declare a new file")
        return self


ContractAspect = Literal[
    "data",
    "prediction_target",
    "input_representation",
    "output",
    "training",
    "evaluation",
]


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
    refinement_only: bool
    scope_evidence: list[str] = Field(min_length=1)
    scope_issue: str | None = None
    checks: list[CodegenAuditCheck] = Field(min_length=1)
    required_fixes: list[str]

    @model_validator(mode="after")
    def verdict_matches_scope_and_checks(self) -> "CodegenAudit":
        pairs = [(check.experiment_id, check.aspect) for check in self.checks]
        if len(pairs) != len(set(pairs)):
            raise ValueError("Codegen audit experiment/aspect checks must be unique")
        if not self.refinement_only and not self.scope_issue:
            raise ValueError("An out-of-scope refinement audit must describe the scope issue")
        if self.refinement_only and self.scope_issue:
            raise ValueError("An in-scope refinement audit cannot report a scope issue")
        expected_verdict = (
            "pass"
            if self.refinement_only and all(check.verdict == "pass" for check in self.checks)
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
    score: int | None = Field(ge=-5, le=5)
    score_rationale: str = Field(min_length=1)
    weighted_score: float | None = Field(ge=-5, le=5)
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
            if self.score is None:
                raise ValueError("A complete comparison must define an assessment score")
            expected_weighted = self.score * self.weight
            if self.weighted_score is None or not math.isclose(
                self.weighted_score,
                expected_weighted,
                rel_tol=1e-6,
                abs_tol=1e-9,
            ):
                raise ValueError(
                    "weighted_score is inconsistent with the assessment score and weight"
                )
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
            raise ValueError("A failed audit or inconsistent protocol requires an invalid verdict")
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


def validate_replication_plan(
    graph: PaperGraph,
    scope: GraphExecutionScope,
    plan: ReplicationPlan,
) -> None:
    expected = set(scope.runnable_node_ids)
    unknown_scope = expected - set(graph.node_map)
    if unknown_scope:
        raise ValueError(f"Execution scope contains unknown graph nodes: {sorted(unknown_scope)}")
    actual = {reference for step in plan.steps for reference in step.verifies}
    unknown = actual - expected
    missing = expected - actual
    if unknown:
        raise ValueError(f"Replication plan verifies inactive node IDs: {sorted(unknown)}")
    if missing:
        raise ValueError(f"Replication plan does not cover runnable node IDs: {sorted(missing)}")


def validate_replication_log(plan: ReplicationPlan, log: ReplicationLog) -> None:
    planned_ids = [step.id for step in plan.steps]
    outcome_ids = [outcome.step_id for outcome in log.step_outcomes]
    if outcome_ids != planned_ids:
        raise ValueError("Replication log must cover plan steps in order")
    outcomes_by_id = {outcome.step_id: outcome for outcome in log.step_outcomes}
    missing_outputs = [
        step.id for step in plan.steps if step.verifies and not outcomes_by_id[step.id].output_files
    ]
    if missing_outputs:
        raise ValueError(
            f"Result-producing replication steps have no output files: {missing_outputs}"
        )


def validate_experiment_weights(
    todo: ExperimentTodo,
    weights: ExperimentWeights,
) -> None:
    available = [experiment.experiment_id for experiment in todo.experiments]
    actual = [experiment.experiment_id for experiment in weights.experiments]
    expected = [experiment_id for experiment_id in available if experiment_id in actual]
    if actual != expected:
        raise ValueError(
            "Experiment weights must select known prediction experiments in input order"
        )


def validate_experiment_contracts(
    weights: ExperimentWeights,
    contracts: ExperimentContracts,
) -> None:
    expected = [experiment.experiment_id for experiment in weights.experiments]
    actual = [experiment.experiment_id for experiment in contracts.experiments]
    if actual != expected:
        raise ValueError("Experiment contracts must cover every weighted prediction experiment")


def validate_candidate_pool_for_selection(pool: IdeaCandidatePool) -> None:
    if len(pool.candidates) != 6:
        raise ValueError("Idea generation must review exactly six candidates")
    if len(pool.selected_candidate_ids) != 3:
        raise ValueError("Idea generation must select exactly three candidates")
    for candidate in pool.candidates:
        sources = {evidence.source for evidence in candidate.evidence}
        if not sources.intersection({"paper", "experiment"}):
            raise ValueError(
                f"Candidate {candidate.candidate_id} lacks paper or experiment evidence"
            )
        if "literature" not in sources:
            raise ValueError(f"Candidate {candidate.candidate_id} lacks literature evidence")


def validate_idea_generation_artifact(
    artifact: IdeaGenerationArtifact,
    round_index: int,
) -> None:
    if artifact.round_index != round_index:
        raise ValueError(
            f"Idea artifact round {artifact.round_index} does not match round {round_index}"
        )


def validate_idea_implementation_plan(
    contracts: ExperimentContracts,
    plan: IdeaImplementationPlan,
) -> None:
    permitted_paths = {
        path
        for contract in contracts.experiments
        for path in (
            *contract.input_representation_paths,
            *contract.training_paths,
            *contract.integration_paths,
        )
    }
    invalid_paths = {item.file_path for item in plan.refine_file_list} - permitted_paths
    if invalid_paths:
        raise ValueError(
            "Implementation plan refines paths outside the frozen boundary: "
            f"{sorted(invalid_paths)}"
        )


def validate_codegen_audit(
    contracts: ExperimentContracts,
    audit: CodegenAudit,
) -> None:
    aspects = [
        "data",
        "prediction_target",
        "input_representation",
        "output",
        "training",
        "evaluation",
    ]
    expected = [
        (experiment.experiment_id, aspect)
        for experiment in contracts.experiments
        for aspect in aspects
    ]
    actual = [(check.experiment_id, check.aspect) for check in audit.checks]
    if actual != expected:
        raise ValueError("Codegen audit must check every experiment contract aspect in order")


def validate_autoresearch_experiment_plan(
    contracts: ExperimentContracts,
    plan: AutoResearchExperimentPlan,
) -> None:
    expected = [experiment.experiment_id for experiment in contracts.experiments]
    actual = [experiment.experiment_id for experiment in plan.experiments]
    if actual != expected:
        raise ValueError("Auto Research experiment plan must cover every experiment in order")
    contracts_by_id = {contract.experiment_id: contract for contract in contracts.experiments}
    for experiment in plan.experiments:
        commands = {step.command_hint.strip() for step in experiment.steps}
        baseline_commands = {
            command.strip()
            for command in contracts_by_id[experiment.experiment_id].baseline_entry_points
        }
        if commands & baseline_commands:
            raise ValueError(f"Auto Research plan reruns a baseline: {experiment.experiment_id}")


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
        outcomes_by_id = {outcome.step_id: outcome for outcome in logged_experiment.step_outcomes}
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


def validate_smart_replicate_log(claim: GraphNode, log: SmartReplicateLog) -> None:
    if log.claim_id != claim.id:
        raise ValueError(f"Smart-replicate log ID {log.claim_id} does not match {claim.id}")
    if claim.paper_result is None:
        raise ValueError(f"Claim {claim.id} has no paper result for Smart Replicate")
    if log.paper_result != claim.paper_result:
        raise ValueError(f"Smart-replicate paper result does not match claim {claim.id}")


def validate_reproduction_report(
    report_text: str,
    graph: PaperGraph,
) -> None:
    if report_text.count("# Reproduction Report") != 1:
        raise ValueError("Report must contain exactly one `# Reproduction Report` heading")
    markers = [f"## Claim {claim.id}" for claim in graph.claims]
    missing = [marker for marker in markers if report_text.count(marker) != 1]
    if missing:
        raise ValueError(f"Report must contain each claim exactly once: {missing}")
    positions = [report_text.index(marker) for marker in markers]
    if positions != sorted(positions):
        raise ValueError("Report claim sections are not in paper-graph order")
    for claim in graph.claims:
        start = report_text.index(f"## Claim {claim.id}")
        later = [position for position in positions if position > start]
        end = min(later) if later else len(report_text)
        validate_claim_report(report_text[start:end], claim.id, heading_level=2)


def validate_claim_report(
    report_text: str,
    claim_id: str,
    *,
    heading_level: int = 1,
) -> None:
    heading = f"{'#' * heading_level} Claim {claim_id}"
    if report_text.count(heading) != 1:
        raise ValueError(f"Claim report must contain exactly one {heading!r} heading")
    required_labels = [
        "Paper result:",
        "Reproduced result:",
        "Upstream node results:",
        "Direct comparison:",
        "Scope blockers:",
        "Lineage issues:",
        "Assessment:",
    ]
    missing = [label for label in required_labels if label not in report_text]
    if missing:
        raise ValueError(f"Claim report {claim_id} is missing fields: {missing}")
    verdicts = re.findall(
        r"Assessment:\s*(close|not close|not assessable)(?![A-Za-z-])",
        report_text,
    )
    if len(verdicts) != 1:
        raise ValueError(
            f"Claim report {claim_id} must contain one explicit close/not close/not assessable "
            "assessment"
        )
