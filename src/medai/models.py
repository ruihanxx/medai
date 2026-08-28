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
    verdict: Literal["FULL", "PARTIAL", "NONE"]
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


class CapacityDecision(StrictModel):
    execution_location: Literal["local", "remote"] | None
    rationale: str = Field(min_length=1)


class PlannedFile(StrictModel):
    path: str
    responsibility: str


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


class ValidationImportance(OpenModel):
    validation_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    weight: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)


class ValidationWeights(OpenModel):
    validations: list[ValidationImportance] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids_and_normalized_positive_weights(self) -> "ValidationWeights":
        validation_ids = [item.validation_id for item in self.validations]
        if len(validation_ids) != len(set(validation_ids)):
            raise ValueError("Validation-weight IDs must be unique")
        positive = [item.weight for item in self.validations if item.weight > 0]
        if not positive:
            raise ValueError("At least one validation must have positive weight")
        if not math.isclose(sum(positive), 1.0, rel_tol=1e-6, abs_tol=1e-9):
            raise ValueError("Positive validation weights must sum to 1")
        return self

    @property
    def positive_ids(self) -> list[str]:
        return [item.validation_id for item in self.validations if item.weight > 0]


class ValidationContract(OpenModel):
    validation_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    baseline_entry_points: list[str] = Field(min_length=1)
    editable_paths: list[str] = Field(min_length=1)
    frozen_contract: Any
    primary_metric: Any
    comparison_rule: Any


class ValidationContracts(OpenModel):
    validations: list[ValidationContract] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_validation_ids(self) -> "ValidationContracts":
        validation_ids = [item.validation_id for item in self.validations]
        if len(validation_ids) != len(set(validation_ids)):
            raise ValueError("Validation-contract IDs must be unique")
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
    source: Literal["paper", "validation", "literature"]
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


class IdeaFileChange(StrictModel):
    file_path: str = Field(min_length=1)
    change: str = Field(min_length=1)


class IdeaImplementationPlan(OpenModel):
    idea_id: str = Field(pattern=r"^R\d{2}-I\d{2}$")
    summary: str = Field(min_length=1)
    method: Any
    refine_file_list: list[IdeaFileChange]
    new_file_list: list[IdeaFileChange]

    @model_validator(mode="after")
    def unique_refinement_fields(self) -> "IdeaImplementationPlan":
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
        return self


class ValidationAuditCheck(OpenModel):
    validation_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    name: str = Field(min_length=1)
    verdict: Literal["pass", "fail"]
    evidence: list[str] = Field(min_length=1)
    issue: str | None = None

    @model_validator(mode="after")
    def failed_check_has_issue(self) -> "ValidationAuditCheck":
        if self.verdict == "fail" and not self.issue:
            raise ValueError("A failed codegen audit check must describe its issue")
        return self


class ValidationCodegenAudit(OpenModel):
    idea_id: str = Field(pattern=r"^R\d{2}-I\d{2}$")
    verdict: Literal["pass", "fail"]
    refinement_only: bool
    scope_evidence: list[str] = Field(min_length=1)
    scope_issue: str | None = None
    checks: list[ValidationAuditCheck] = Field(min_length=1)
    required_fixes: list[str]

    @model_validator(mode="after")
    def verdict_matches_scope_and_checks(self) -> "ValidationCodegenAudit":
        pairs = [(check.validation_id, check.name) for check in self.checks]
        if len(pairs) != len(set(pairs)):
            raise ValueError("Codegen audit validation/check names must be unique")
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


class RefinementValidationPlan(StrictModel):
    validation_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    baseline_validation_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    steps: list[ReplicationStep] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def unique_step_ids(self) -> "RefinementValidationPlan":
        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Refinement validation step IDs must be unique")
        return self


class AutoResearchValidationPlan(StrictModel):
    environment: PlanEnvironment
    validations: list[RefinementValidationPlan] = Field(min_length=1)
    remote_compute: RemoteComputePlan | None = None

    @model_validator(mode="after")
    def unique_validation_ids(self) -> "AutoResearchValidationPlan":
        validation_ids = [item.validation_id for item in self.validations]
        if len(validation_ids) != len(set(validation_ids)):
            raise ValueError("Auto Research validation-plan IDs must be unique")
        return self


class RefinementValidationLog(StrictModel):
    validation_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    step_outcomes: list[ReplicationStepOutcome] = Field(min_length=1)


class AutoResearchValidationLog(StrictModel):
    validations: list[RefinementValidationLog] = Field(min_length=1)
    node_updates: list[PendingNodeUpdate] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_validation_ids(self) -> "AutoResearchValidationLog":
        validation_ids = [item.validation_id for item in self.validations]
        if len(validation_ids) != len(set(validation_ids)):
            raise ValueError("Auto Research validation-log IDs must be unique")
        return self


class ValidationMetricComparison(OpenModel):
    validation_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    refined_validation_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    primary_metric: Any
    comparison_rule: Any
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
    def validate_comparison(self) -> "ValidationMetricComparison":
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
    validations: list[ValidationMetricComparison]
    weighted_score: float | None
    threshold: float = Field(ge=0)
    failure_reasons: list[str]

    @model_validator(mode="after")
    def verdict_matches_weighted_score(self) -> "IdeaAssessment":
        validation_ids = [item.validation_id for item in self.validations]
        if len(validation_ids) != len(set(validation_ids)):
            raise ValueError("Assessment validation IDs must be unique")
        expected_score = None
        if self.validations and all(
            item.weighted_score is not None for item in self.validations
        ):
            expected_score = sum(
                item.weighted_score
                for item in self.validations
                if item.weighted_score is not None
            )
        if expected_score is None:
            if self.weighted_score is not None:
                raise ValueError("Incomplete validation comparisons require a null weighted score")
        elif self.weighted_score is None or not math.isclose(
            self.weighted_score,
            expected_score,
            rel_tol=1e-6,
            abs_tol=1e-9,
        ):
            raise ValueError("Assessment weighted score does not match validation scores")

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


def validate_validation_weights(graph: PaperGraph, weights: ValidationWeights) -> None:
    available = [node.id for node in graph.validations]
    actual = [item.validation_id for item in weights.validations]
    expected = [validation_id for validation_id in available if validation_id in actual]
    if actual != expected:
        raise ValueError(
            "Validation weights must select known prediction V nodes in graph order"
        )


def validate_validation_contracts(
    weights: ValidationWeights,
    contracts: ValidationContracts,
) -> None:
    expected = weights.positive_ids
    actual = [item.validation_id for item in contracts.validations]
    if actual != expected:
        raise ValueError("Validation contracts must cover only positive-weight V nodes")


def validate_candidate_pool_for_selection(pool: IdeaCandidatePool) -> None:
    if len(pool.candidates) != 6:
        raise ValueError("Idea generation must review exactly six candidates")
    if len(pool.selected_candidate_ids) != 3:
        raise ValueError("Idea generation must select exactly three candidates")
    for candidate in pool.candidates:
        sources = {evidence.source for evidence in candidate.evidence}
        if not sources.intersection({"paper", "validation"}):
            raise ValueError(
                f"Candidate {candidate.candidate_id} lacks paper or validation evidence"
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
    contracts: ValidationContracts,
    plan: IdeaImplementationPlan,
) -> None:
    permitted_paths = {
        path
        for contract in contracts.validations
        for path in contract.editable_paths
    }
    invalid_paths = {item.file_path for item in plan.refine_file_list} - permitted_paths
    if invalid_paths:
        raise ValueError(
            "Implementation plan refines paths outside the frozen boundary: "
            f"{sorted(invalid_paths)}"
        )


def validate_refinement_graph(
    base_graph: PaperGraph,
    refinement_graph: PaperGraph,
    weights: ValidationWeights,
) -> None:
    base_nodes = base_graph.node_map
    refined_nodes = refinement_graph.node_map
    missing_base = sorted(set(base_nodes) - set(refined_nodes))
    if missing_base:
        raise ValueError(f"Refinement graph omits base node IDs: {missing_base}")
    changed_base = sorted(
        node_id
        for node_id, node in base_nodes.items()
        if refined_nodes[node_id].model_dump(mode="json") != node.model_dump(mode="json")
    )
    if changed_base:
        raise ValueError(f"Refinement graph modifies base nodes in place: {changed_base}")
    base_categories = base_graph.category_map
    refined_categories = refinement_graph.category_map
    recategorized = sorted(
        node_id
        for node_id in base_nodes
        if base_categories[node_id] != refined_categories[node_id]
    )
    if recategorized:
        raise ValueError(f"Refinement graph recategorizes base nodes: {recategorized}")
    new_datasets = sorted(
        node_id
        for node_id in set(refined_nodes) - set(base_nodes)
        if refined_categories[node_id] == "datasets"
    )
    if new_datasets:
        raise ValueError(
            f"Refinement graph may not add datasets: {new_datasets}"
        )
    new_validations = [
        node
        for node in refinement_graph.validations
        if node.id not in base_nodes
    ]
    baseline_ids = [getattr(node, "baseline_validation_id", None) for node in new_validations]
    if baseline_ids != weights.positive_ids:
        raise ValueError(
            "Refinement graph must add one V node for each positive-weight baseline V in order"
        )
    base_claim_ids = {node.id for node in base_graph.claims}
    invalid_new_claims = sorted(
        node.id
        for node in refinement_graph.claims
        if node.id not in base_nodes
        and getattr(node, "baseline_claim_id", None) not in base_claim_ids
    )
    if invalid_new_claims:
        raise ValueError(
            "New refinement claims must map to a base claim with baseline_claim_id: "
            f"{invalid_new_claims}"
        )


def validate_codegen_audit(
    contracts: ValidationContracts,
    audit: ValidationCodegenAudit,
) -> None:
    expected = [item.validation_id for item in contracts.validations]
    actual = [check.validation_id for check in audit.checks]
    unknown = sorted(set(actual) - set(expected))
    missing = [validation_id for validation_id in expected if validation_id not in actual]
    if unknown or missing:
        raise ValueError(
            f"Codegen audit validation coverage mismatch; missing={missing}, unknown={unknown}"
        )


def validate_autoresearch_validation_plan(
    contracts: ValidationContracts,
    refinement_graph: PaperGraph,
    plan: AutoResearchValidationPlan,
) -> None:
    expected_baselines = [item.validation_id for item in contracts.validations]
    expected_refined = [
        node.id
        for node in refinement_graph.validations
        if getattr(node, "baseline_validation_id", None) in expected_baselines
    ]
    actual = [item.validation_id for item in plan.validations]
    if actual != expected_refined:
        raise ValueError("Auto Research validation plan must cover every refined V in order")
    baselines = [item.baseline_validation_id for item in plan.validations]
    if baselines != expected_baselines:
        raise ValueError("Auto Research validation plan baseline mappings are invalid")
    contracts_by_id = {item.validation_id: item for item in contracts.validations}
    for item in plan.validations:
        commands = {step.command_hint.strip() for step in item.steps}
        baseline_commands = {
            command.strip()
            for command in contracts_by_id[item.baseline_validation_id].baseline_entry_points
        }
        if commands & baseline_commands:
            raise ValueError(
                f"Auto Research validation plan reruns baseline {item.baseline_validation_id}"
            )


def validate_autoresearch_validation_log(
    base_graph: PaperGraph,
    refinement_graph: PaperGraph,
    plan: AutoResearchValidationPlan,
    log: AutoResearchValidationLog,
) -> None:
    expected = [item.validation_id for item in plan.validations]
    actual = [item.validation_id for item in log.validations]
    if actual != expected:
        raise ValueError("Auto Research validation log must cover every refined V in order")
    for planned, logged in zip(
        plan.validations,
        log.validations,
        strict=True,
    ):
        planned_ids = [step.id for step in planned.steps]
        outcome_ids = [outcome.step_id for outcome in logged.step_outcomes]
        if outcome_ids != planned_ids:
            raise ValueError(f"Validation log must cover steps in order: {planned.validation_id}")
        outcomes_by_id = {outcome.step_id: outcome for outcome in logged.step_outcomes}
        missing_outputs = [
            step.id
            for step in planned.steps
            if step.verifies and not outcomes_by_id[step.id].output_files
        ]
        if missing_outputs:
            raise ValueError(
                "Result-producing Auto Research steps have no output files for "
                f"{planned.validation_id}: {missing_outputs}"
            )
    new_ids = set(refinement_graph.node_map) - set(base_graph.node_map)
    update_ids = [update.node_id for update in log.node_updates]
    if len(update_ids) != len(set(update_ids)) or set(update_ids) != new_ids:
        raise ValueError("Validation log node updates must cover every refinement node exactly")


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
    report_headings = list(
        re.finditer(r"^# Reproduction Report\r?$", report_text, re.MULTILINE)
    )
    if len(report_headings) != 1:
        raise ValueError("Report must contain exactly one `# Reproduction Report` heading")
    markers = [f"## Claim {claim.id}" for claim in graph.claims]
    matches = {
        marker: list(
            re.finditer(rf"^{re.escape(marker)}\r?$", report_text, re.MULTILINE)
        )
        for marker in markers
    }
    missing = [marker for marker in markers if len(matches[marker]) != 1]
    if missing:
        raise ValueError(f"Report must contain each claim exactly once: {missing}")
    positions = [matches[marker][0].start() for marker in markers]
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
    heading_matches = list(
        re.finditer(rf"^{re.escape(heading)}\r?$", report_text, re.MULTILINE)
    )
    if len(heading_matches) != 1:
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
