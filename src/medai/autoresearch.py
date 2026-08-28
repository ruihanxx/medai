from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from medai.artifacts import load_model, write_json
from medai.autoresearch_visualization import generate_autoresearch_visualizations
from medai.computation_providers import get_provider_adapter
from medai.config import AutoResearchConfig
from medai.data_availability import sha256_file
from medai.models import (
    AutoResearchCommand,
    AutoResearchValidationLog,
    AutoResearchValidationPlan,
    CodegenPlan,
    EligibilityResult,
    EvidenceSummary,
    GraphExecutionScope,
    IdeaAssessment,
    IdeaCandidatePool,
    IdeaGenerationArtifact,
    IdeaImplementationPlan,
    NodeState,
    PaperGraph,
    ReplicationCommand,
    ReplicationLog,
    ReplicationPlan,
    RoundSummary,
    SmartReplicateLog,
    ValidationCodegenAudit,
    ValidationContracts,
    ValidationWeights,
    validate_autoresearch_validation_log,
    validate_autoresearch_validation_plan,
    validate_candidate_pool_for_selection,
    validate_codegen_audit,
    validate_idea_generation_artifact,
    validate_idea_implementation_plan,
    validate_refinement_graph,
    validate_replication_log,
    validate_replication_plan,
    validate_smart_replicate_log,
    validate_validation_contracts,
    validate_validation_weights,
)
from medai.pipeline_state import PipelineState
from medai.prompts import render_prompt
from medai.providers import run_agent
from medai.resources import detect_resources
from medai.study_graph import merge_node_updates, write_empty_node_state
from medai.workflow import (
    _cloud_drive_materialization_completed,
    _next_command_index,
    _provider_cloud_drives,
    _run_agent_command,
    _run_computation_provider_action,
    power_off_run_computation_instance,
    power_on_run_computation_instance,
    resolve_replication_output,
    skills_dir,
    validate_codegen_remote_compute,
)

REQUIRED_BASE_STAGES = (
    "preflight",
    "preprocess_pdf",
    "preprocessing_agent",
    "data_availability_agent",
    "partial_data_gate",
    "codegen_agent",
    "audit_agent",
    "plan_agent",
    "replicate_agent",
    "report_agents",
)
AUTORESEARCH_REPORT_SECTIONS = (
    "## 1. Base problem and research context",
    "## 2. Idea ledger",
    "## 3. Validation comparisons",
    "## 4. Validity and failure assessment",
    "## 5. Visualizations",
)


class AutoResearchState(TypedDict, total=False):
    config: AutoResearchConfig
    eligibility_path: str
    eligible: bool
    report_path: str


class _AutoResearchEnvironmentSetupError(RuntimeError):
    pass


def expected_idea_ids(round_index: int) -> list[str]:
    return [f"R{round_index:02d}-I{idea_index:02d}" for idea_index in range(1, 4)]


def _remove_selected_candidates(path: Path, pool: IdeaCandidatePool) -> None:
    selected = set(pool.selected_candidate_ids)
    remaining = IdeaCandidatePool(
        next_candidate_index=pool.next_candidate_index,
        candidates=[
            candidate
            for candidate in pool.candidates
            if candidate.candidate_id not in selected
        ],
        selected_candidate_ids=[],
    )
    write_json(path, remaining.model_dump(mode="json"))


def validate_autoresearch_report(report_text: str, idea_ids: list[str]) -> None:
    h1_headings = re.findall(r"(?m)^# ([^\r\n]+?)[ \t]*$", report_text)
    if h1_headings != ["Auto Research Report"]:
        raise ValueError("Auto Research report must use title: # Auto Research Report")
    actual_sections = re.findall(r"(?m)^## ([^\r\n]+?)[ \t]*$", report_text)
    expected_sections = [section.removeprefix("## ") for section in AUTORESEARCH_REPORT_SECTIONS]
    if actual_sections != expected_sections:
        raise ValueError(
            "Auto Research report must contain exactly the required sections in order"
        )
    for idea_id in idea_ids:
        if not re.search(
            rf"(?<![A-Za-z0-9_.-]){re.escape(idea_id)}(?![A-Za-z0-9_.-])",
            report_text,
        ):
            raise ValueError(f"Auto Research report is missing idea: {idea_id}")
    for image_name in ("idea_metric_comparison.png", "idea_status_overview.png"):
        if image_name not in report_text:
            raise ValueError(f"Auto Research report is missing visualization: {image_name}")


def _round_dir(config: AutoResearchConfig, round_index: int) -> Path:
    return config.output / "rounds" / f"round_{round_index:03d}"


def _idea_dir(config: AutoResearchConfig, round_index: int, idea_index: int) -> Path:
    return _round_dir(config, round_index) / "ideas" / f"idea_{idea_index:02d}"


def _round_artifact_context(
    config: AutoResearchConfig,
    round_index: int,
) -> dict[str, Any]:
    summary = _load_validated_round_summary(config, round_index)
    idea_artifacts = []
    for idea_index, summary_idea in enumerate(summary.ideas, start=1):
        idea_dir = _idea_dir(config, round_index, idea_index)
        assessment_path = idea_dir / "assessment" / "assessment.json"
        assessment = load_model(assessment_path, IdeaAssessment)
        candidate_paths = {
            "implementation_plan": idea_dir / "codegen" / "implementation_plan.json",
            "refinement_graph": idea_dir / "graph" / "refinement_graph.json",
            "node_state": idea_dir / "graph" / "node_state.json",
            "audit": idea_dir / "audit" / "audit.json",
            "validation_plan": idea_dir / "plan" / "validation_plan.json",
            "validation_log": idea_dir / "validation" / "validation_log.json",
            "evidence_summary": idea_dir / "validation" / "evidence_summary.json",
        }
        idea_artifacts.append(
            {
                "idea_id": summary_idea.idea_id,
                "verdict": summary_idea.verdict,
                "failure_reasons": assessment.failure_reasons,
                "assessment": str(assessment_path),
                **{
                    name: str(path) if path.is_file() else None
                    for name, path in candidate_paths.items()
                },
            }
        )
    return {
        "round": round_index,
        "ideas": str(_round_dir(config, round_index) / "ideas.json"),
        "summary": str(_round_dir(config, round_index) / "round_summary.json"),
        "idea_artifacts": idea_artifacts,
    }


def _stage_name(round_index: int, idea_index: int | None, stage: str) -> str:
    prefix = f"round_{round_index:03d}"
    if idea_index is not None:
        prefix += f".idea_{idea_index:02d}"
    return f"{prefix}.{stage}"


def _relative_code_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise RuntimeError(f"Code artifact path must be repository-relative: {value}")
    return path


def _validate_contract_code_paths(
    contracts: ValidationContracts,
    base_codebase_dir: Path,
) -> None:
    for contract in contracts.validations:
        for value in contract.editable_paths:
            path = _relative_code_path(value)
            if not (base_codebase_dir / path).is_file():
                raise RuntimeError(
                    f"Validation contract references a missing base code file: {value}"
                )


def _codebase_file_hashes(codebase_dir: Path) -> dict[str, str]:
    ignored = {
        ".git",
        ".venv",
        ".cache",
        ".hypothesis",
        ".ipynb_checkpoints",
        ".mypy_cache",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
    }
    files = {}
    for path in sorted(codebase_dir.rglob("*")):
        relative = path.relative_to(codebase_dir)
        if (
            any(part in ignored for part in relative.parts)
            or path.suffix in {".pyc", ".pyo"}
            or not path.is_file()
        ):
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
        files[relative.as_posix()] = digest.hexdigest()
    return files


def _source_code_fingerprint(codebase_dir: Path) -> str:
    source_suffixes = {
        ".bash",
        ".c",
        ".cc",
        ".cpp",
        ".cu",
        ".go",
        ".h",
        ".hpp",
        ".java",
        ".jl",
        ".js",
        ".kt",
        ".m",
        ".ps1",
        ".py",
        ".r",
        ".rs",
        ".scala",
        ".sh",
        ".toml",
        ".ts",
        ".tsx",
        ".yaml",
        ".yml",
    }
    source_names = {
        "DESCRIPTION",
        "Dockerfile",
        "Makefile",
        "environment.yml",
        "requirements.txt",
    }
    digest = hashlib.sha256()
    for path, file_digest in _codebase_file_hashes(codebase_dir).items():
        relative = Path(path)
        if relative.suffix.casefold() not in source_suffixes and relative.name not in source_names:
            continue
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
    return digest.hexdigest()


def _validate_refinement_implementation(
    config: AutoResearchConfig,
    codebase_dir: Path,
    plan: IdeaImplementationPlan,
) -> None:
    base_codebase_dir = config.base_run / "codegen" / "codebase"
    contracts = load_model(
        config.output / "validation_setup" / "validation_contracts.json",
        ValidationContracts,
    )
    validate_idea_implementation_plan(contracts, plan)
    new_files = {
        _relative_code_path(item.file_path).as_posix()
        for item in plan.new_file_list
    }
    refine_files = {
        _relative_code_path(item.file_path).as_posix()
        for item in plan.refine_file_list
    }

    for relative in new_files:
        if (base_codebase_dir / relative).exists():
            raise RuntimeError(f"New file already exists in base code: {relative}")
        if not (codebase_dir / relative).is_file():
            raise RuntimeError(f"Declared new file is missing: {relative}")
    for relative in refine_files:
        if not (base_codebase_dir / relative).is_file():
            raise RuntimeError(f"Refine file is missing from base code: {relative}")
        if not (codebase_dir / relative).is_file():
            raise RuntimeError(f"Refinement deleted a declared refine file: {relative}")

    base_files = _codebase_file_hashes(base_codebase_dir)
    refined_files = _codebase_file_hashes(codebase_dir)
    changed_files = {
        path
        for path in set(base_files) | set(refined_files)
        if base_files.get(path) != refined_files.get(path)
    }
    allowed_files = new_files | refine_files
    undeclared = changed_files - allowed_files
    if undeclared:
        raise RuntimeError(
            f"Refinement changed files outside the declared boundary: {sorted(undeclared)}"
        )
    unchanged_declared = allowed_files - changed_files
    if unchanged_declared:
        raise RuntimeError(
            f"Implementation plan declares unchanged files: {sorted(unchanged_declared)}"
        )


def _validate_idea_graph(config: AutoResearchConfig, refinement_graph_path: Path) -> PaperGraph:
    base_graph = load_model(
        config.base_run / "preprocessing" / "paper_graph.json",
        PaperGraph,
    )
    refinement_graph = load_model(refinement_graph_path, PaperGraph)
    weights = load_model(
        config.output / "validation_setup" / "validation_weights.json",
        ValidationWeights,
    )
    validate_refinement_graph(base_graph, refinement_graph, weights)
    return refinement_graph


def _validate_base_run(config: AutoResearchConfig) -> None:
    base_state = PipelineState(config.base_run)
    if base_state.state.get("status") == "completed_partial":
        raise RuntimeError("A partial replication cannot be used as an Auto Research base run")
    if base_state.state.get("status") != "completed":
        raise RuntimeError(f"Base replicate run is not completed: {config.base_run}")
    incomplete = [
        stage for stage in REQUIRED_BASE_STAGES if not base_state.is_stage_completed(stage)
    ]
    if incomplete:
        raise RuntimeError(f"Base replicate run has incomplete stages: {incomplete}")

    resources_path = config.base_run / "preflight" / "resources.json"
    try:
        resources = json.loads(resources_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Base resource artifact is invalid: {resources_path}") from exc
    if not isinstance(resources, dict) or not isinstance(resources.get("gpus"), list):
        raise RuntimeError(f"Base resource artifact is invalid: {resources_path}")
    paper_artifacts = config.base_run / "preprocessing" / "artifacts"
    if not paper_artifacts.is_dir():
        raise RuntimeError(f"Base paper artifacts directory is missing: {paper_artifacts}")

    graph = load_model(
        config.base_run / "preprocessing" / "paper_graph.json",
        PaperGraph,
    )
    scope = load_model(
        config.base_run / "preprocessing" / "execution_scope.json",
        GraphExecutionScope,
    )
    load_model(config.base_run / "graph" / "node_state.json", NodeState)
    load_model(
        config.base_run / "codegen" / "codebase" / "codegen_plan.json",
        CodegenPlan,
    )
    replicate_plan = load_model(
        config.base_run / "plan" / "replicate_plan.json",
        ReplicationPlan,
    )
    validate_replication_plan(graph, scope, replicate_plan)
    replication_log = load_model(
        config.base_run / "replication" / "replication_log.json",
        ReplicationLog,
    )
    validate_replication_log(replicate_plan, replication_log)
    codebase_dir = config.base_run / "codegen" / "codebase"
    replication_dir = config.base_run / "replication"
    for outcome in replication_log.step_outcomes:
        for output_file in outcome.output_files:
            resolve_replication_output(output_file, codebase_dir, replication_dir)
    load_model(
        config.base_run / "replication" / "evidence_summary.json",
        EvidenceSummary,
    )
    report_path = config.base_run / "report" / "reproduction_report.md"
    try:
        report_text = report_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"Base reproduction report is missing: {report_path}") from exc
    if not report_text.strip():
        raise RuntimeError(f"Base reproduction report is empty: {report_path}")

    if base_state.state["inputs"].get("smart_replicate"):
        runnable = set(scope.runnable_node_ids)
        for claim in graph.claims:
            if claim.id not in runnable or claim.paper_result is None:
                continue
            smart_log = load_model(
                config.base_run
                / "replication"
                / "claims"
                / claim.id
                / "smart_replicate_log.json",
                SmartReplicateLog,
            )
            validate_smart_replicate_log(claim, smart_log)
    if config.clouddrive:
        _load_base_cloud_state(config)


def _load_base_cloud_state(config: AutoResearchConfig) -> dict[str, Any]:
    state_path = config.base_run / "remote_compute" / "instance.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Base remote-compute state is invalid: {state_path}") from exc
    provider_state = state.get("provider_state") if isinstance(state, dict) else None
    clouds = _provider_cloud_drives(provider_state) if isinstance(provider_state, dict) else {}
    if (
        state.get("provider") != config.computation_provider
        or state.get("created_by_run") is not True
        or state.get("released") is not True
        or set(clouds) != set(config.selected_cloud_datasets)
    ):
        raise RuntimeError(
            "Cloud-backed Auto Research requires a released base instance with "
            "completed state for the inherited drive and dataset"
        )
    for dataset, cloud in clouds.items():
        if (
            cloud.get("completed") is not True
            or cloud.get("drive") != config.drive_provider
            or cloud.get("dataset") != dataset
            or not isinstance(cloud.get("target_path"), str)
        ):
            raise RuntimeError("Base cloud-drive dataset state is invalid")
        inventory_name = _cloud_inventory_name(cloud)
        inventory_path = config.base_run / "remote_compute" / inventory_name
        try:
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Base cloud inventory is invalid: {inventory_path}") from exc
        if (
            not isinstance(inventory, dict)
            or inventory.get("dataset") != dataset
            or not isinstance(inventory.get("files"), list)
            or not inventory["files"]
        ):
            raise RuntimeError(f"Base cloud inventory is invalid: {inventory_path}")
    return state


def _copy_base_cloud_inventory(config: AutoResearchConfig) -> None:
    if not config.clouddrive:
        return
    state = _load_base_cloud_state(config)
    clouds = _provider_cloud_drives(state["provider_state"])
    for cloud in clouds.values():
        name = _cloud_inventory_name(cloud)
        source = config.base_run / "remote_compute" / name
        destination = config.output / "remote_compute" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file():
            if destination.read_bytes() != source.read_bytes():
                raise RuntimeError(
                    "Auto Research cloud inventory differs from its base replicate run"
                )
            continue
        shutil.copy2(source, destination)


def _cloud_inventory_name(cloud: dict[str, Any]) -> str:
    name = cloud.get("inventory_path", "cloud-inventory.v1.json")
    if (
        not isinstance(name, str)
        or Path(name).name != name
        or not name.startswith("cloud-inventory")
        or not name.endswith(".v1.json")
    ):
        raise RuntimeError("Base cloud-drive inventory path is invalid")
    return name


def _autoresearch_cloud_pull_handoff_enabled(config: AutoResearchConfig) -> bool:
    if (
        config.provider != "codex"
        or not config.clouddrive
        or config.computation_provider is None
        or config.drive_provider is None
    ):
        return False
    return get_provider_adapter(config.computation_provider).drive(
        config.drive_provider
    ).cloud_pull_handoff


def autoresearch_preflight_node(state: AutoResearchState) -> dict[str, Any]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    resources_path = config.output / "preflight" / "resources.json"
    if pipeline_state.is_stage_completed("preflight"):
        _validate_base_run(config)
        try:
            resources = json.loads(resources_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Completed Auto Research preflight artifact is invalid: {resources_path}"
            ) from exc
        if not isinstance(resources, dict) or not isinstance(resources.get("gpus"), list):
            raise RuntimeError(
                f"Completed Auto Research preflight artifact is invalid: {resources_path}"
            )
        print("resume autoresearch preflight stage: skipped (already completed)")
        return {}

    print("enter autoresearch preflight stage")
    pipeline_state.start_stage("preflight")
    config.validate()
    _validate_base_run(config)
    for name in (
        "preflight",
        "eligibility",
        "validation_setup",
        "rounds",
        "report",
        "prompts",
        "remote_compute",
    ):
        (config.output / name).mkdir(parents=True, exist_ok=True)
    write_json(resources_path, detect_resources(config.output))
    pipeline_state.complete_stage("preflight", [str(resources_path)])
    return {}


def autoresearch_eligibility_node(state: AutoResearchState) -> dict[str, Any]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    eligibility_path = config.output / "eligibility" / "eligibility.json"
    transcript_path = config.output / "eligibility" / "eligibility_transcript.jsonl"
    if pipeline_state.is_stage_completed("eligibility_agent"):
        eligibility = load_model(eligibility_path, EligibilityResult)
        if not transcript_path.is_file():
            raise RuntimeError(
                f"Completed eligibility transcript is missing: {transcript_path}"
            )
        if not eligibility.eligible:
            pipeline_state.mark_ineligible(eligibility.reason)
        print("resume autoresearch eligibility stage: skipped (already completed)")
        return {
            "eligibility_path": str(eligibility_path),
            "eligible": eligibility.eligible,
        }

    print("enter autoresearch eligibility stage")
    pipeline_state.start_stage("eligibility_agent")
    prompt_path = render_prompt(
        "autoresearch/eligibility/session_instructions.md",
        config.output / "prompts" / "eligibility.md",
        paper_markdown=config.base_run / "preprocessing" / "paper.md",
        eligibility_path=eligibility_path,
    )
    run_agent(
        provider=config.provider,
        prompt_path=prompt_path,
        working_dir=config.output / "eligibility",
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )
    eligibility = load_model(eligibility_path, EligibilityResult)
    pipeline_state.complete_stage(
        "eligibility_agent",
        [str(eligibility_path), str(transcript_path)],
    )
    if not eligibility.eligible:
        pipeline_state.mark_ineligible(eligibility.reason)
    return {
        "eligibility_path": str(eligibility_path),
        "eligible": eligibility.eligible,
    }


def autoresearch_validation_setup_node(state: AutoResearchState) -> dict[str, Any]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    setup_dir = config.output / "validation_setup"
    paper_graph_path = config.base_run / "preprocessing" / "paper_graph.json"
    graph = load_model(paper_graph_path, PaperGraph)
    weights_path = setup_dir / "validation_weights.json"
    weights_transcript_path = setup_dir / "validation_weighting_transcript.jsonl"

    if pipeline_state.is_stage_completed("validation_weighting"):
        weights = load_model(weights_path, ValidationWeights)
        validate_validation_weights(graph, weights)
        if not weights_transcript_path.is_file():
            raise RuntimeError(
                f"Completed validation-weighting transcript is missing: "
                f"{weights_transcript_path}"
            )
        print("resume validation_weighting stage: skipped (already completed)")
    else:
        print("enter validation_weighting stage")
        pipeline_state.start_stage("validation_weighting")
        setup_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = render_prompt(
            "autoresearch/validation_weighting/session_instructions.md",
            config.output / "prompts" / "validation_setup" / "weighting.md",
            paper_markdown=config.base_run / "preprocessing" / "paper.md",
            paper_graph_path=paper_graph_path,
            weights_path=weights_path,
        )
        run_agent(
            provider=config.provider,
            prompt_path=prompt_path,
            working_dir=setup_dir,
            transcript_path=weights_transcript_path,
            siliconflow_config_path=config.siliconflow_config,
            codex_model=config.codex_model,
            codex_reasoning_effort=config.codex_reasoning_effort,
        )
        weights = load_model(weights_path, ValidationWeights)
        validate_validation_weights(graph, weights)
        pipeline_state.complete_stage(
            "validation_weighting",
            [str(weights_path), str(weights_transcript_path)],
        )

    contracts_path = setup_dir / "validation_contracts.json"
    contracts_transcript_path = setup_dir / "validation_contracts_transcript.jsonl"
    if pipeline_state.is_stage_completed("validation_contracts"):
        contracts = load_model(contracts_path, ValidationContracts)
        validate_validation_contracts(weights, contracts)
        _validate_contract_code_paths(
            contracts,
            config.base_run / "codegen" / "codebase",
        )
        if not contracts_transcript_path.is_file():
            raise RuntimeError(
                f"Completed validation-contract transcript is missing: "
                f"{contracts_transcript_path}"
            )
        print("resume validation_contracts stage: skipped (already completed)")
        return {}

    print("enter validation_contracts stage")
    pipeline_state.start_stage("validation_contracts")
    base_codebase_dir = config.base_run / "codegen" / "codebase"
    before = _codebase_fingerprint(base_codebase_dir)
    prompt_path = render_prompt(
        "autoresearch/validation_contracts/session_instructions.md",
        config.output / "prompts" / "validation_setup" / "contracts.md",
        paper_graph_path=paper_graph_path,
        weights_path=weights_path,
        codegen_plan_path=base_codebase_dir / "codegen_plan.json",
        replicate_plan_path=config.base_run / "plan" / "replicate_plan.json",
        base_codebase_dir=base_codebase_dir,
        contracts_path=contracts_path,
    )
    run_agent(
        provider=config.provider,
        prompt_path=prompt_path,
        working_dir=setup_dir,
        transcript_path=contracts_transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )
    if _codebase_fingerprint(base_codebase_dir) != before:
        raise RuntimeError("Validation-contract agent modified the base codebase")
    contracts = load_model(contracts_path, ValidationContracts)
    validate_validation_contracts(weights, contracts)
    _validate_contract_code_paths(contracts, base_codebase_dir)
    pipeline_state.complete_stage(
        "validation_contracts",
        [str(contracts_path), str(contracts_transcript_path)],
    )
    return {}


def _run_idea_generation(config: AutoResearchConfig, round_index: int) -> Path:
    pipeline_state = PipelineState(config.output)
    stage_name = _stage_name(round_index, None, "idea_generation")
    round_dir = _round_dir(config, round_index)
    ideas_path = round_dir / "ideas.json"
    transcript_path = round_dir / "idea_generation_transcript.jsonl"
    candidates_path = config.output / "idea_generation" / "candidates.json"
    if pipeline_state.is_stage_completed(stage_name):
        artifact = load_model(ideas_path, IdeaGenerationArtifact)
        validate_idea_generation_artifact(artifact, round_index)
        if not transcript_path.is_file():
            raise RuntimeError(
                f"Completed idea-generation transcript is missing: {transcript_path}"
            )
        load_model(candidates_path, IdeaCandidatePool)
        print(f"resume {stage_name} stage: skipped (already completed)")
        return ideas_path

    print(f"enter {stage_name} stage")
    pipeline_state.start_stage(stage_name)
    round_dir.mkdir(parents=True, exist_ok=True)
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    prior_rounds = [
        _round_artifact_context(config, prior) for prior in range(1, round_index)
    ]
    prompt_path = render_prompt(
        "autoresearch/idea_generation/session_instructions.md",
        config.output / "prompts" / f"round_{round_index:03d}" / "idea_generation.md",
        paper_markdown=config.base_run / "preprocessing" / "paper.md",
        eligibility_path=config.output / "eligibility" / "eligibility.json",
        weights_path=config.output / "validation_setup" / "validation_weights.json",
        contracts_path=(
            config.output / "validation_setup" / "validation_contracts.json"
        ),
        reproduction_report_path=config.base_run / "report" / "reproduction_report.md",
        codebase_dir=config.base_run / "codegen" / "codebase",
        candidates_path=candidates_path,
        prior_rounds_json=json.dumps(prior_rounds, ensure_ascii=False, indent=2),
        round_index=round_index,
        idea_ids=expected_idea_ids(round_index),
        ideas_path=ideas_path,
    )
    run_agent(
        provider=config.provider,
        prompt_path=prompt_path,
        working_dir=round_dir,
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )
    artifact = load_model(ideas_path, IdeaGenerationArtifact)
    validate_idea_generation_artifact(artifact, round_index)
    candidate_pool = load_model(candidates_path, IdeaCandidatePool)
    validate_candidate_pool_for_selection(candidate_pool)
    _remove_selected_candidates(candidates_path, candidate_pool)
    pipeline_state.complete_stage(
        stage_name,
        [str(ideas_path), str(candidates_path), str(transcript_path)],
    )
    return ideas_path


def _copy_base_codebase(base_codebase: Path, idea_codebase: Path) -> None:
    if idea_codebase.is_dir() and any(idea_codebase.iterdir()):
        raise RuntimeError(f"Idea codebase output is not empty: {idea_codebase}")
    shutil.copytree(
        base_codebase,
        idea_codebase,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            ".cache",
            ".hypothesis",
            ".ipynb_checkpoints",
            ".mypy_cache",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            "*.pyc",
            "*.pyo",
            "runs",
            "autoresearch",
        ),
    )


def _run_codegen(
    config: AutoResearchConfig,
    round_index: int,
    idea_index: int,
    ideas_path: Path,
    repair_audit_path: Path | None = None,
) -> tuple[Path, Path]:
    pipeline_state = PipelineState(config.output)
    stage_suffix = "codegen_repair" if repair_audit_path else "codegen"
    stage_name = _stage_name(round_index, idea_index, stage_suffix)
    idea_id = expected_idea_ids(round_index)[idea_index - 1]
    idea_dir = _idea_dir(config, round_index, idea_index)
    codegen_dir = idea_dir / "codegen"
    codebase_dir = codegen_dir / "codebase"
    implementation_plan_path = codegen_dir / "implementation_plan.json"
    graph_dir = idea_dir / "graph"
    refinement_graph_path = graph_dir / "refinement_graph.json"
    node_state_path = graph_dir / "node_state.json"
    transcript_path = codegen_dir / f"{stage_suffix}_transcript.jsonl"
    previous_status = pipeline_state.get_stage_status(stage_name)
    source_prepared = pipeline_state.get_stage_checkpoints(stage_name).get(
        "source_prepared", False
    )
    if pipeline_state.is_stage_completed(stage_name):
        plan = load_model(implementation_plan_path, IdeaImplementationPlan)
        if plan.idea_id != idea_id:
            raise RuntimeError(
                f"Implementation plan ID {plan.idea_id} does not match {idea_id}"
            )
        if not codebase_dir.is_dir() or not transcript_path.is_file():
            raise RuntimeError(f"Completed {stage_suffix} artifacts are missing for {idea_id}")
        _validate_refinement_implementation(config, codebase_dir, plan)
        _validate_idea_graph(config, refinement_graph_path)
        if not node_state_path.is_file():
            write_empty_node_state(node_state_path, sha256_file(refinement_graph_path))
        print(f"resume {stage_name} stage: skipped (already completed)")
        return codebase_dir, implementation_plan_path

    print(f"enter {stage_name} stage")
    pipeline_state.start_stage(stage_name)
    codegen_dir.mkdir(parents=True, exist_ok=True)
    graph_dir.mkdir(parents=True, exist_ok=True)
    if not repair_audit_path and not source_prepared:
        if previous_status in {"running", "failed"} and codebase_dir.is_dir() and any(
            codebase_dir.iterdir()
        ):
            source_prepared = True
        else:
            _copy_base_codebase(config.base_run / "codegen" / "codebase", codebase_dir)
        pipeline_state.update_stage_checkpoints(stage_name, {"source_prepared": True})
    if repair_audit_path and not codebase_dir.is_dir():
        raise RuntimeError(f"Cannot repair missing idea codebase: {codebase_dir}")

    prompt_name = "codegen_repair.md" if repair_audit_path else "codegen.md"
    prompt_path = render_prompt(
        "autoresearch/codegen/session_instructions.md",
        config.output
        / "prompts"
        / f"round_{round_index:03d}"
        / f"idea_{idea_index:02d}"
        / prompt_name,
        idea_id=idea_id,
        paper_markdown=config.base_run / "preprocessing" / "paper.md",
        ideas_path=ideas_path,
        eligibility_path=config.output / "eligibility" / "eligibility.json",
        contracts_path=(
            config.output / "validation_setup" / "validation_contracts.json"
        ),
        paper_graph_path=config.base_run / "preprocessing" / "paper_graph.json",
        refinement_graph_path=refinement_graph_path,
        base_codegen_plan_path=(
            config.base_run / "codegen" / "codebase" / "codegen_plan.json"
        ),
        base_replicate_plan_path=config.base_run / "plan" / "replicate_plan.json",
        base_codebase_dir=config.base_run / "codegen" / "codebase",
        codebase_dir=codebase_dir,
        implementation_plan_path=implementation_plan_path,
        repair_audit_path=repair_audit_path,
    )
    run_agent(
        provider=config.provider,
        prompt_path=prompt_path,
        working_dir=codebase_dir,
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )
    plan = load_model(implementation_plan_path, IdeaImplementationPlan)
    if plan.idea_id != idea_id:
        raise RuntimeError(f"Implementation plan ID {plan.idea_id} does not match {idea_id}")
    _validate_refinement_implementation(config, codebase_dir, plan)
    _validate_idea_graph(config, refinement_graph_path)
    write_empty_node_state(node_state_path, sha256_file(refinement_graph_path))
    pipeline_state.complete_stage(
        stage_name,
        [
            str(codebase_dir),
            str(implementation_plan_path),
            str(refinement_graph_path),
            str(node_state_path),
            str(transcript_path),
        ],
    )
    return codebase_dir, implementation_plan_path


def _codebase_fingerprint(codebase_dir: Path) -> str:
    digest = hashlib.sha256()
    ignored = {
        ".git",
        ".venv",
        ".cache",
        ".hypothesis",
        ".ipynb_checkpoints",
        ".mypy_cache",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
    }
    for path in sorted(codebase_dir.rglob("*")):
        relative = path.relative_to(codebase_dir)
        if (
            any(part in ignored for part in relative.parts)
            or path.suffix in {".pyc", ".pyo"}
            or not path.is_file()
        ):
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _run_codegen_audit(
    config: AutoResearchConfig,
    round_index: int,
    idea_index: int,
    attempt: int,
    codebase_dir: Path,
    implementation_plan_path: Path,
) -> tuple[ValidationCodegenAudit, Path]:
    pipeline_state = PipelineState(config.output)
    stage_name = _stage_name(round_index, idea_index, f"audit_{attempt}")
    idea_id = expected_idea_ids(round_index)[idea_index - 1]
    audit_dir = _idea_dir(config, round_index, idea_index) / "audit"
    attempt_path = audit_dir / f"audit_{attempt}.json"
    canonical_path = audit_dir / "audit.json"
    transcript_path = audit_dir / f"audit_{attempt}_transcript.jsonl"
    contracts_path = config.output / "validation_setup" / "validation_contracts.json"
    contracts = load_model(contracts_path, ValidationContracts)
    refinement_graph_path = (
        _idea_dir(config, round_index, idea_index) / "graph" / "refinement_graph.json"
    )
    if pipeline_state.is_stage_completed(stage_name):
        audit = load_model(attempt_path, ValidationCodegenAudit)
        validate_codegen_audit(contracts, audit)
        _validate_idea_graph(config, refinement_graph_path)
        if audit.idea_id != idea_id or not transcript_path.is_file():
            raise RuntimeError(f"Completed audit artifacts are invalid for {idea_id}")
        shutil.copy2(attempt_path, canonical_path)
        print(f"resume {stage_name} stage: skipped (already completed)")
        return audit, canonical_path

    print(f"enter {stage_name} stage")
    pipeline_state.start_stage(stage_name)
    audit_dir.mkdir(parents=True, exist_ok=True)
    before = _codebase_fingerprint(codebase_dir)
    prompt_path = render_prompt(
        "autoresearch/audit/session_instructions.md",
        config.output
        / "prompts"
        / f"round_{round_index:03d}"
        / f"idea_{idea_index:02d}"
        / f"audit_{attempt}.md",
        idea_id=idea_id,
        contracts_path=contracts_path,
        base_codebase_dir=config.base_run / "codegen" / "codebase",
        codebase_dir=codebase_dir,
        implementation_plan_path=implementation_plan_path,
        refinement_graph_path=refinement_graph_path,
        base_graph_path=config.base_run / "preprocessing" / "paper_graph.json",
        audit_path=attempt_path,
    )
    run_agent(
        provider=config.provider,
        prompt_path=prompt_path,
        working_dir=audit_dir,
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )
    after = _codebase_fingerprint(codebase_dir)
    if after != before:
        raise RuntimeError(f"Codegen audit agent modified the idea codebase: {idea_id}")
    audit = load_model(attempt_path, ValidationCodegenAudit)
    if audit.idea_id != idea_id:
        raise RuntimeError(f"Codegen audit ID {audit.idea_id} does not match {idea_id}")
    validate_codegen_audit(contracts, audit)
    _validate_idea_graph(config, refinement_graph_path)
    shutil.copy2(attempt_path, canonical_path)
    pipeline_state.complete_stage(
        stage_name,
        [str(attempt_path), str(canonical_path), str(transcript_path)],
    )
    return audit, canonical_path


def _run_plan_cloud_pull_handoff(
    *,
    config: AutoResearchConfig,
    round_index: int,
    idea_index: int,
    codebase_dir: Path,
    prompt_path: Path,
    transcript_path: Path,
) -> None:
    plan_dir = _idea_dir(config, round_index, idea_index) / "plan"
    command_dir = plan_dir / "cloud_pull" / "commands"
    command_dir.mkdir(parents=True, exist_ok=True)
    prompt_dir = (
        config.output
        / "prompts"
        / f"round_{round_index:03d}"
        / f"idea_{idea_index:02d}"
    )
    command_schema_path = prompt_dir / "plan_cloud_pull_command.schema.json"
    write_json(command_schema_path, ReplicationCommand.model_json_schema())
    session_id: str | None = None
    resume_prompt_path: Path | None = None
    command_index = _next_command_index(command_dir)
    while True:
        command_request_path = command_dir / f"command_{command_index:03d}.json"
        if session_id is None:
            session_id = run_agent(
                provider=config.provider,
                prompt_path=prompt_path,
                working_dir=codebase_dir,
                transcript_path=transcript_path,
                siliconflow_config_path=config.siliconflow_config,
                codex_model=config.codex_model,
                codex_reasoning_effort=config.codex_reasoning_effort,
                output_schema_path=command_schema_path,
                output_last_message_path=command_request_path,
            )
            if session_id is None:
                raise RuntimeError(
                    "Codex Auto Research cloud-pull preparation did not return a session ID"
                )
        else:
            assert resume_prompt_path is not None
            run_agent(
                provider=config.provider,
                prompt_path=resume_prompt_path,
                working_dir=codebase_dir,
                transcript_path=transcript_path,
                siliconflow_config_path=config.siliconflow_config,
                codex_model=config.codex_model,
                codex_reasoning_effort=config.codex_reasoning_effort,
                output_schema_path=command_schema_path,
                output_last_message_path=command_request_path,
                resume_session_id=session_id,
            )

        command = load_model(command_request_path, ReplicationCommand).command
        log_path = command_dir / f"command_{command_index:03d}.log"
        result_path = command_dir / f"command_{command_index:03d}_result.json"
        result = _run_agent_command(
            command,
            codebase_dir=codebase_dir,
            log_path=log_path,
            result_path=result_path,
        )
        try:
            materialized = _cloud_drive_materialization_completed(config)
            validation_error = "Cloud-drive materialization is incomplete"
        except RuntimeError as exc:
            materialized = False
            validation_error = str(exc)
        if materialized:
            break
        result["artifact_validation_error"] = validation_error
        write_json(result_path, result)
        resume_prompt_path = render_prompt(
            "autoresearch/plan/cloud_pull_result_instructions.md",
            prompt_dir / f"plan_cloud_pull_resume_{command_index:03d}.md",
            command_result_path=result_path,
            command_log_path=log_path,
            exit_code=result["exit_code"],
            duration_seconds=result["duration_seconds"],
            artifact_validation_error=validation_error,
            computation_provider_state_path=(
                config.output / "remote_compute" / "instance.json"
            ),
        )
        command_index += 1

    power_off_run_computation_instance(config)
    completion_prompt_path = render_prompt(
        "autoresearch/plan/cloud_pull_complete_instructions.md",
        prompt_dir / "plan_cloud_pull_complete.md",
        computation_provider_state_path=(
            config.output / "remote_compute" / "instance.json"
        ),
    )
    run_agent(
        provider=config.provider,
        prompt_path=completion_prompt_path,
        working_dir=codebase_dir,
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
        resume_session_id=session_id,
    )


def _run_validation_plan(
    config: AutoResearchConfig,
    round_index: int,
    idea_index: int,
    codebase_dir: Path,
    implementation_plan_path: Path,
    audit_path: Path,
) -> Path:
    pipeline_state = PipelineState(config.output)
    stage_name = _stage_name(round_index, idea_index, "plan")
    idea_id = expected_idea_ids(round_index)[idea_index - 1]
    plan_dir = _idea_dir(config, round_index, idea_index) / "plan"
    plan_path = plan_dir / "validation_plan.json"
    transcript_path = plan_dir / "plan_transcript.jsonl"
    contracts_path = config.output / "validation_setup" / "validation_contracts.json"
    weights_path = config.output / "validation_setup" / "validation_weights.json"
    validation_dir = _idea_dir(config, round_index, idea_index) / "validation"
    refinement_graph_path = (
        _idea_dir(config, round_index, idea_index) / "graph" / "refinement_graph.json"
    )
    refinement_graph = _validate_idea_graph(config, refinement_graph_path)
    contracts = load_model(contracts_path, ValidationContracts)
    weights = load_model(weights_path, ValidationWeights)
    if pipeline_state.is_stage_completed(stage_name):
        plan = load_model(plan_path, AutoResearchValidationPlan)
        validate_autoresearch_validation_plan(contracts, refinement_graph, plan)
        validate_codegen_remote_compute(
            plan,
            config.output / "remote_compute" / "instance.json",
            cloud_datasets=config.selected_cloud_datasets if config.clouddrive else (),
            drive_provider=config.drive_provider,
            computation_provider=config.computation_provider,
            require_active=not pipeline_state.is_stage_completed("final_report"),
        )
        if not transcript_path.is_file():
            raise RuntimeError(f"Completed validation-plan transcript is missing: {transcript_path}")
        print(f"resume {stage_name} stage: skipped (already completed)")
        return plan_path

    print(f"enter {stage_name} stage")
    pipeline_state.start_stage(stage_name)
    plan_dir.mkdir(parents=True, exist_ok=True)
    _copy_base_cloud_inventory(config)
    cloud_pull_handoff = _autoresearch_cloud_pull_handoff_enabled(config)
    cloud_materialized = (
        _cloud_drive_materialization_completed(config) if config.clouddrive else False
    )
    prompt_path = render_prompt(
        "autoresearch/plan/session_instructions.md",
        config.output
        / "prompts"
        / f"round_{round_index:03d}"
        / f"idea_{idea_index:02d}"
        / "plan.md",
        idea_id=idea_id,
        contracts_path=contracts_path,
        weights_path=weights_path,
        implementation_plan_path=implementation_plan_path,
        refinement_graph_path=refinement_graph_path,
        audit_path=audit_path,
        codebase_dir=codebase_dir,
        data_dir=config.data,
        datasets=config.dataset_names,
        data_paths=config.dataset_paths,
        cloud_drive_enabled=config.clouddrive,
        cloud_dataset=", ".join(config.selected_cloud_datasets),
        cloud_datasets=config.selected_cloud_datasets,
        drive_provider=config.drive_provider,
        computation_provider=config.computation_provider,
        computation_provider_reference=config.computation_provider_reference,
        drive_reference=config.drive_reference,
        cloud_pull_handoff=cloud_pull_handoff,
        cloud_materialization_required=config.clouddrive and not cloud_materialized,
        base_computation_provider_state_path=(
            config.base_run / "remote_compute" / "instance.json"
        ),
        skills_dir=skills_dir(),
        validation_dir=validation_dir,
        validation_plan_path=plan_path,
        computation_provider_state_path=config.output / "remote_compute" / "instance.json",
        contracts=contracts.model_dump(mode="json"),
        weights=weights.model_dump(mode="json"),
        gpu_info=json.loads(
            (config.output / "preflight" / "resources.json").read_text(encoding="utf-8")
        )["gpus"],
    )
    try:
        if cloud_pull_handoff and not cloud_materialized:
            _run_plan_cloud_pull_handoff(
                config=config,
                round_index=round_index,
                idea_index=idea_index,
                codebase_dir=codebase_dir,
                prompt_path=prompt_path,
                transcript_path=transcript_path,
            )
        else:
            run_agent(
                provider=config.provider,
                prompt_path=prompt_path,
                working_dir=codebase_dir,
                transcript_path=transcript_path,
                siliconflow_config_path=config.siliconflow_config,
                codex_model=config.codex_model,
                codex_reasoning_effort=config.codex_reasoning_effort,
            )
        plan = load_model(plan_path, AutoResearchValidationPlan)
        validate_autoresearch_validation_plan(contracts, refinement_graph, plan)
        validate_codegen_remote_compute(
            plan,
            config.output / "remote_compute" / "instance.json",
            cloud_datasets=config.selected_cloud_datasets if config.clouddrive else (),
            drive_provider=config.drive_provider,
            computation_provider=config.computation_provider,
        )
        pipeline_state.complete_stage(
            stage_name,
            [str(plan_path), str(transcript_path)],
        )
        return plan_path
    finally:
        if config.clouddrive:
            power_off_run_computation_instance(config)


def _resolve_validation_output(value: str, codebase_dir: Path, validation_dir: Path) -> Path:
    raw = Path(value).expanduser()
    candidates = [raw] if raw.is_absolute() else [codebase_dir / raw, validation_dir / raw]
    allowed_roots = [codebase_dir.resolve(), validation_dir.resolve()]
    for candidate in candidates:
        resolved = candidate.resolve()
        if any(resolved.is_relative_to(root) for root in allowed_roots) and resolved.is_file():
            return resolved
    raise RuntimeError(
        "Auto Research validation output must be a regular file inside the idea "
        f"codebase or validation directory: {value}"
    )


def _validate_validation_artifacts(
    config: AutoResearchConfig,
    plan_path: Path,
    contracts_path: Path,
    log_path: Path,
    evidence_path: Path,
    codebase_dir: Path,
    validation_dir: Path,
) -> list[str]:
    plan = load_model(plan_path, AutoResearchValidationPlan)
    contracts = load_model(contracts_path, ValidationContracts)
    log = load_model(log_path, AutoResearchValidationLog)
    base_graph = load_model(
        config.base_run / "preprocessing" / "paper_graph.json",
        PaperGraph,
    )
    refinement_graph_path = validation_dir.parent / "graph" / "refinement_graph.json"
    refinement_graph = load_model(refinement_graph_path, PaperGraph)
    validate_autoresearch_validation_log(base_graph, refinement_graph, plan, log)
    load_model(evidence_path, EvidenceSummary)
    managed = {log_path.resolve(), evidence_path.resolve()}
    outputs = [str(log_path), str(evidence_path)]
    contracts_by_id = {
        contract.validation_id: contract for contract in contracts.validations
    }
    plans_by_id = {item.validation_id: item for item in plan.validations}
    for validation in log.validations:
        baseline_id = plans_by_id[validation.validation_id].baseline_validation_id
        baseline_commands = {
            command.strip()
            for command in contracts_by_id[baseline_id].baseline_entry_points
        }
        for outcome in validation.step_outcomes:
            if outcome.command_executed.strip() in baseline_commands:
                raise RuntimeError(
                    f"Auto Research validation reran baseline {baseline_id}: "
                    f"{validation.validation_id} step {outcome.step_id}"
                )
            if outcome.code_modified or outcome.fixes_applied:
                raise RuntimeError(
                    f"Auto Research validation modified audited code: "
                    f"{validation.validation_id} step {outcome.step_id}"
                )
            for output_file in outcome.output_files:
                resolved = _resolve_validation_output(
                    output_file,
                    codebase_dir,
                    validation_dir,
                )
                if resolved in managed:
                    raise RuntimeError(
                        f"Validation step {outcome.step_id} cannot cite a managed log "
                        "as output"
                    )
                outputs.append(str(resolved))
    for update in log.node_updates:
        result = getattr(update, "result", None)
        evidence = getattr(update, "evidence", None)
        if result is None or result == "" or result == [] or result == {}:
            raise RuntimeError(f"Refinement node {update.node_id} has no actual result")
        if not isinstance(evidence, list) or not evidence:
            raise RuntimeError(f"Refinement node {update.node_id} has no evidence")
        for value in evidence:
            _resolve_validation_output(value, codebase_dir, validation_dir)
    merge_node_updates(
        validation_dir.parent / "graph" / "node_state.json",
        refinement_graph,
        sha256_file(refinement_graph_path),
        "validation_agent",
        log.node_updates,
    )
    return list(dict.fromkeys(outputs))


def _mother_environment_validation(validation_dir: Path) -> dict[str, int | str] | None:
    environment_dir = validation_dir / "environment"
    try:
        setup = (environment_dir / "setup.sh").read_bytes()
        manifest = (environment_dir / "environment.json").read_bytes()
    except OSError:
        return None
    return {
        "schema_version": 1,
        "setup_sha256": hashlib.sha256(setup).hexdigest(),
        "environment_sha256": hashlib.sha256(manifest).hexdigest(),
    }


def _mother_environment_validated(validation_dir: Path) -> bool:
    expected = _mother_environment_validation(validation_dir)
    if expected is None:
        return False
    environment_dir = validation_dir / "environment"
    validation_path = environment_dir / "validation.json"
    if validation_path.is_file():
        try:
            return json.loads(validation_path.read_text(encoding="utf-8")) == expected
        except (OSError, json.JSONDecodeError):
            return False
    definition_paths = (
        environment_dir / "setup.sh",
        environment_dir / "environment.json",
    )
    try:
        validated_at = (environment_dir / "setup.log").stat().st_mtime_ns
        return all(path.stat().st_mtime_ns <= validated_at for path in definition_paths)
    except OSError:
        return False


def _run_autoresearch_provider_operation(
    operation: AutoResearchCommand,
    *,
    state_path: Path,
    remote_working_dir: str,
    remote_artifact_dir: str,
    artifact_dir: Path,
    log_path: Path,
    result_path: Path,
    expected_provider: str | None,
) -> dict[str, Any]:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Remote computation state is invalid: {state_path}") from exc
    provider = state.get("provider")
    if not isinstance(provider, str):
        raise RuntimeError("Remote computation state is missing its provider")
    if expected_provider is not None and provider != expected_provider:
        raise RuntimeError("Remote computation state provider does not match the run configuration")
    adapter = get_provider_adapter(provider)

    remote_root = PurePosixPath(remote_working_dir)
    remote_artifact_root = PurePosixPath(remote_artifact_dir)
    if (
        not remote_root.is_absolute()
        or not remote_artifact_root.is_absolute()
        or remote_artifact_root == remote_root
        or not remote_artifact_root.is_relative_to(remote_root)
        or ".." in remote_artifact_root.parts
    ):
        raise RuntimeError("Auto Research remote artifact directory is invalid")
    if operation.operation == "remote_exec":
        assert operation.command is not None
        action = "exec"
        arguments = [
            "--",
            "bash",
            "-lc",
            f"mkdir -p -- {shlex.quote(str(remote_artifact_root))} && "
            f"cd {shlex.quote(str(remote_root / 'codebase'))} && "
            f"export MEDAI_AUTORESEARCH_ARTIFACT_DIR="
            f"{shlex.quote(str(remote_artifact_root))} && {operation.command}",
        ]
        destination: str | None = None
    else:
        assert operation.remote is not None
        assert operation.destination is not None
        action = "download"
        requested_remote = PurePosixPath(operation.remote)
        remote_path = (
            requested_remote
            if requested_remote.is_absolute()
            else remote_artifact_root / requested_remote
        )
        if (
            not remote_path.is_absolute()
            or remote_path == remote_artifact_root
            or not remote_path.is_relative_to(remote_artifact_root)
            or ".." in remote_path.parts
        ):
            raise RuntimeError(
                "Auto Research downloads must remain inside the remote artifact directory"
            )
        local_root = artifact_dir.resolve()
        requested_destination = Path(operation.destination).expanduser()
        local_path = (
            requested_destination.resolve()
            if requested_destination.is_absolute()
            else (artifact_dir / requested_destination).resolve()
        )
        if local_path == local_root or not local_path.is_relative_to(local_root):
            raise RuntimeError(
                "Auto Research downloads must remain inside the validation artifact directory"
            )
        local_path.parent.mkdir(parents=True, exist_ok=True)
        arguments = [
            "--remote",
            str(remote_path),
            "--destination",
            str(local_path),
        ]
        destination = str(local_path)

    timeout_seconds = adapter.action_timeouts.get(action)
    if timeout_seconds is None:
        raise RuntimeError(f"Computation provider does not support action: {action}")
    command = [
        sys.executable,
        str(adapter.script),
        action,
        "--state",
        str(state_path),
        *arguments,
    ]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    timed_out = threading.Event()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
            start_new_session=True,
        )

        def terminate_on_timeout() -> None:
            if process.poll() is None:
                timed_out.set()
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        timer = threading.Timer(timeout_seconds, terminate_on_timeout)
        timer.daemon = True
        timer.start()
        try:
            assert process.stdout is not None
            for line in iter(process.stdout.readline, ""):
                print(line, end="")
                log.write(line)
            exit_code = process.wait()
        finally:
            timer.cancel()
        if timed_out.is_set():
            message = f"Computation-provider {action} timed out after {timeout_seconds} seconds\n"
            print(message, end="")
            log.write(message)
            exit_code = 124

    result = {
        "operation": operation.operation,
        "command": operation.command,
        "remote": operation.remote,
        "destination": destination,
        "exit_code": exit_code,
        "duration_seconds": round(time.monotonic() - started, 3),
        "log_path": str(log_path),
        "artifact_validation_error": None,
    }
    write_json(result_path, result)
    return result


def _prepare_autoresearch_command_instance(
    config: AutoResearchConfig,
    codebase_dir: Path,
    validation_dir: Path,
) -> dict[str, Any]:
    acquisition = power_on_run_computation_instance(config)
    state_path = config.output / "remote_compute" / "instance.json"
    if config.clouddrive and acquisition.get("materialization_required") is True:
        if not config.selected_cloud_datasets:
            raise RuntimeError("Cloud-backed Auto Research is missing its dataset name")
        for dataset in config.selected_cloud_datasets:
            _run_computation_provider_action(
                state_path,
                "cloud-pull",
                arguments=["--dataset", dataset],
                expected_provider=config.computation_provider,
            )
        if not _cloud_drive_materialization_completed(config):
            raise RuntimeError("Selected campaign instance has incomplete cloud data")

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Remote computation state is invalid: {state_path}") from exc
    provider_state = state.get("provider_state")
    remote_working_dir = (
        provider_state.get("remote_working_dir")
        if isinstance(provider_state, dict)
        else None
    )
    remote_root = (
        PurePosixPath(remote_working_dir)
        if isinstance(remote_working_dir, str)
        else None
    )
    if (
        remote_root is None
        or not remote_root.is_absolute()
        or len(remote_root.parts) < 4
        or ".." in remote_root.parts
    ):
        raise RuntimeError("Remote computation state is missing its working directory")
    remote_working_dir = str(remote_root)

    environment_dir = validation_dir / "environment"
    setup_path = environment_dir / "setup.sh"
    manifest_path = environment_dir / "environment.json"
    if not setup_path.is_file() or not setup_path.read_text(encoding="utf-8").strip():
        raise RuntimeError("Validation agent did not write its local environment/setup.sh")
    try:
        environment_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Validation agent did not write a valid local environment/environment.json"
        ) from exc
    if not isinstance(environment_manifest, dict) or not environment_manifest:
        raise RuntimeError("Validation environment manifest must be a non-empty JSON object")

    remote_code = f"{remote_working_dir}/codebase"
    remote_environment_spec = f"{remote_working_dir}/environment-spec"
    remote_environment = f"{remote_working_dir}/environment"
    next_code = f"{remote_working_dir}/.codebase.next"
    next_environment_spec = f"{remote_working_dir}/.environment-spec.next"
    quoted_next_code = shlex.quote(next_code)
    quoted_next_environment_spec = shlex.quote(next_environment_spec)
    quoted_working_dir = shlex.quote(remote_working_dir)
    _run_computation_provider_action(
        state_path,
        "exec",
        arguments=[
            "--",
            "bash",
            "-lc",
            f"rm -rf -- {quoted_next_code} {quoted_next_environment_spec}; "
            f"mkdir -p -- {quoted_working_dir}",
        ],
        expected_provider=config.computation_provider,
    )
    _run_computation_provider_action(
        state_path,
        "upload",
        arguments=["--source", str(codebase_dir), "--remote", next_code],
        expected_provider=config.computation_provider,
    )
    _run_computation_provider_action(
        state_path,
        "upload",
        arguments=["--source", str(environment_dir), "--remote", next_environment_spec],
        expected_provider=config.computation_provider,
    )
    replace_command = (
        f"rm -rf -- {shlex.quote(remote_code)} {shlex.quote(remote_environment_spec)}; "
        f"mv -- {shlex.quote(next_code)} {shlex.quote(remote_code)}; "
        f"mv -- {shlex.quote(next_environment_spec)} "
        f"{shlex.quote(remote_environment_spec)}; "
        f"bash {shlex.quote(remote_environment_spec + '/setup.sh')} "
        f"{shlex.quote(remote_environment)} {shlex.quote(remote_code)}"
    )
    try:
        setup_output = _run_computation_provider_action(
            state_path,
            "exec",
            arguments=["--", "bash", "-lc", replace_command],
            expected_provider=config.computation_provider,
        )
    except RuntimeError as exc:
        raise _AutoResearchEnvironmentSetupError(str(exc)) from exc
    (environment_dir / "setup.log").write_text(
        setup_output + ("\n" if setup_output else ""),
        encoding="utf-8",
    )
    validation = _mother_environment_validation(validation_dir)
    if validation is None:
        raise RuntimeError("Validation mother environment disappeared after remote setup")
    validation_path = environment_dir / "validation.json"
    try:
        current_validation = json.loads(validation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        current_validation = None
    if current_validation != validation:
        write_json(validation_path, validation)
    return {**acquisition, "remote_working_dir": remote_working_dir}


def _run_validation_command_handoff(
    *,
    config: AutoResearchConfig,
    round_index: int,
    idea_index: int,
    codebase_dir: Path,
    validation_dir: Path,
    prompt_path: Path,
    transcript_path: Path,
    plan_path: Path,
    log_path: Path,
    evidence_path: Path,
) -> list[str]:
    command_dir = validation_dir / "commands"
    command_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = validation_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    prompt_dir = (
        config.output
        / "prompts"
        / f"round_{round_index:03d}"
        / f"idea_{idea_index:02d}"
    )
    idea_id = expected_idea_ids(round_index)[idea_index - 1]
    command_schema_path = prompt_dir / "validation_command.schema.json"
    write_json(command_schema_path, AutoResearchCommand.model_json_schema())
    session_id: str | None = None
    resume_prompt_path: Path | None = None
    command_index = _next_command_index(command_dir)
    while True:
        command_request_path = command_dir / f"command_{command_index:03d}.json"
        if session_id is None:
            session_id = run_agent(
                provider=config.provider,
                prompt_path=prompt_path,
                working_dir=codebase_dir,
                transcript_path=transcript_path,
                siliconflow_config_path=config.siliconflow_config,
                codex_model=config.codex_model,
                codex_reasoning_effort=config.codex_reasoning_effort,
                output_schema_path=command_schema_path,
                output_last_message_path=command_request_path,
            )
            if session_id is None:
                raise RuntimeError(
                    "Codex Auto Research validation turn did not return a session ID"
                )
        else:
            assert resume_prompt_path is not None
            run_agent(
                provider=config.provider,
                prompt_path=resume_prompt_path,
                working_dir=codebase_dir,
                transcript_path=transcript_path,
                siliconflow_config_path=config.siliconflow_config,
                codex_model=config.codex_model,
                codex_reasoning_effort=config.codex_reasoning_effort,
                output_schema_path=command_schema_path,
                output_last_message_path=command_request_path,
                resume_session_id=session_id,
            )

        operation = load_model(command_request_path, AutoResearchCommand)
        command_log_path = command_dir / f"command_{command_index:03d}.log"
        result_path = command_dir / f"command_{command_index:03d}_result.json"
        setup_failed = False
        started = time.monotonic()
        try:
            acquisition = _prepare_autoresearch_command_instance(
                config,
                codebase_dir,
                validation_dir,
            )
            result = _run_autoresearch_provider_operation(
                operation,
                state_path=config.output / "remote_compute" / "instance.json",
                remote_working_dir=acquisition["remote_working_dir"],
                remote_artifact_dir=(
                    f"{acquisition['remote_working_dir']}/artifacts/{idea_id}"
                ),
                artifact_dir=artifact_dir,
                log_path=command_log_path,
                result_path=result_path,
                expected_provider=config.computation_provider,
            )
        except _AutoResearchEnvironmentSetupError as exc:
            setup_failed = True
            validation_error = (
                "Mother-environment setup failed before the requested operation "
                f"ran: {exc}"
            )
            command_log_path.write_text(validation_error + "\n", encoding="utf-8")
            result = {
                "operation": operation.operation,
                "command": operation.command,
                "remote": operation.remote,
                "destination": operation.destination,
                "exit_code": 1,
                "duration_seconds": round(time.monotonic() - started, 3),
                "log_path": str(command_log_path),
                "artifact_validation_error": validation_error,
            }
            write_json(result_path, result)
        finally:
            power_off_run_computation_instance(config)
        if not setup_failed:
            try:
                return _validate_validation_artifacts(
                    config,
                    plan_path,
                    config.output / "validation_setup" / "validation_contracts.json",
                    log_path,
                    evidence_path,
                    codebase_dir,
                    validation_dir,
                )
            except (RuntimeError, ValueError) as exc:
                result["artifact_validation_error"] = str(exc)
                write_json(result_path, result)
        resume_prompt_path = render_prompt(
            "autoresearch/validation/command_result_instructions.md",
            prompt_dir / f"validation_resume_{command_index:03d}.md",
            command_result_path=result_path,
            command_log_path=command_log_path,
            exit_code=result["exit_code"],
            duration_seconds=result["duration_seconds"],
            artifact_validation_error=result["artifact_validation_error"],
        )
        command_index += 1


def _run_validation(
    config: AutoResearchConfig,
    round_index: int,
    idea_index: int,
    codebase_dir: Path,
    plan_path: Path,
    implementation_plan_path: Path,
    audit_path: Path,
) -> tuple[Path, Path]:
    pipeline_state = PipelineState(config.output)
    stage_name = _stage_name(round_index, idea_index, "validation")
    idea_id = expected_idea_ids(round_index)[idea_index - 1]
    validation_dir = _idea_dir(config, round_index, idea_index) / "validation"
    log_path = validation_dir / "validation_log.json"
    evidence_path = validation_dir / "evidence_summary.json"
    transcript_path = validation_dir / "validation_transcript.jsonl"
    plan = load_model(plan_path, AutoResearchValidationPlan)
    validate_codegen_remote_compute(
        plan,
        config.output / "remote_compute" / "instance.json",
        cloud_datasets=config.selected_cloud_datasets if config.clouddrive else (),
        drive_provider=config.drive_provider,
        computation_provider=config.computation_provider,
        require_active=not pipeline_state.is_stage_completed("final_report"),
    )
    command_handoff = config.provider == "codex" and plan.remote_compute is not None
    codebase_fingerprint = _source_code_fingerprint(codebase_dir)
    checkpoints = pipeline_state.get_stage_checkpoints(stage_name)
    audited_fingerprint = checkpoints.get("audited_source_fingerprint")
    if audited_fingerprint and audited_fingerprint != codebase_fingerprint:
        raise RuntimeError(f"Audited idea code changed before validation: {idea_id}")
    if pipeline_state.is_stage_completed(stage_name):
        _validate_validation_artifacts(
            config,
            plan_path,
            config.output / "validation_setup" / "validation_contracts.json",
            log_path,
            evidence_path,
            codebase_dir,
            validation_dir,
        )
        if not transcript_path.is_file():
            raise RuntimeError(f"Completed validation transcript is missing: {transcript_path}")
        print(f"resume {stage_name} stage: skipped (already completed)")
        return log_path, evidence_path

    print(f"enter {stage_name} stage")
    pipeline_state.start_stage(stage_name)
    if not audited_fingerprint:
        pipeline_state.update_stage_checkpoints(
            stage_name,
            {"audited_source_fingerprint": codebase_fingerprint},
        )
    validation_dir.mkdir(parents=True, exist_ok=True)
    mother_environment_validated = _mother_environment_validated(validation_dir)
    prompt_path = render_prompt(
        "autoresearch/validation/session_instructions.md",
        config.output
        / "prompts"
        / f"round_{round_index:03d}"
        / f"idea_{idea_index:02d}"
        / "validation.md",
        idea_id=idea_id,
        contracts_path=(
            config.output / "validation_setup" / "validation_contracts.json"
        ),
        validation_plan_path=plan_path,
        refinement_graph_path=(
            _idea_dir(config, round_index, idea_index)
            / "graph"
            / "refinement_graph.json"
        ),
        node_state_path=(
            _idea_dir(config, round_index, idea_index) / "graph" / "node_state.json"
        ),
        implementation_plan_path=implementation_plan_path,
        audit_path=audit_path,
        codebase_dir=codebase_dir,
        data_dir=config.data,
        datasets=config.dataset_names,
        data_paths=config.dataset_paths,
        cloud_drive_enabled=config.clouddrive,
        cloud_dataset=", ".join(config.selected_cloud_datasets),
        cloud_datasets=config.selected_cloud_datasets,
        drive_provider=config.drive_provider,
        computation_provider=config.computation_provider,
        computation_provider_reference=config.computation_provider_reference,
        drive_reference=config.drive_reference,
        skills_dir=skills_dir(),
        command_handoff=command_handoff,
        base_replication_log=config.base_run / "replication" / "replication_log.json",
        base_evidence_summary=config.base_run / "replication" / "evidence_summary.json",
        base_node_state=config.base_run / "graph" / "node_state.json",
        refinement_node_state=(
            _idea_dir(config, round_index, idea_index) / "graph" / "node_state.json"
        ),
        validation_dir=validation_dir,
        validation_log_path=log_path,
        evidence_summary_path=evidence_path,
        local_environment_dir=validation_dir / "environment",
        mother_environment_validated=mother_environment_validated,
        local_artifact_dir=validation_dir / "artifacts",
        remote_artifact_dir=(
            f"{plan.remote_compute.remote_working_dir}/artifacts/{idea_id}"
            if plan.remote_compute is not None
            else None
        ),
        remote_environment_dir=(
            f"{plan.remote_compute.remote_working_dir}/environment"
            if plan.remote_compute is not None
            else None
        ),
        computation_provider_state_path=config.output / "remote_compute" / "instance.json",
    )
    if command_handoff:
        outputs = _run_validation_command_handoff(
            config=config,
            round_index=round_index,
            idea_index=idea_index,
            codebase_dir=codebase_dir,
            validation_dir=validation_dir,
            prompt_path=prompt_path,
            transcript_path=transcript_path,
            plan_path=plan_path,
            log_path=log_path,
            evidence_path=evidence_path,
        )
    else:
        if plan.remote_compute is not None:
            power_on_run_computation_instance(config)
        try:
            run_agent(
                provider=config.provider,
                prompt_path=prompt_path,
                working_dir=codebase_dir,
                transcript_path=transcript_path,
                siliconflow_config_path=config.siliconflow_config,
                codex_model=config.codex_model,
                codex_reasoning_effort=config.codex_reasoning_effort,
            )
        finally:
            if plan.remote_compute is not None:
                power_off_run_computation_instance(config)
        outputs = _validate_validation_artifacts(
            config,
            plan_path,
            config.output / "validation_setup" / "validation_contracts.json",
            log_path,
            evidence_path,
            codebase_dir,
            validation_dir,
        )
    if _source_code_fingerprint(codebase_dir) != codebase_fingerprint:
        raise RuntimeError(f"Validation agent modified audited idea code during validation: {idea_id}")
    pipeline_state.complete_stage(stage_name, [*outputs, str(transcript_path)])
    return log_path, evidence_path


def _validate_assessment_evidence(
    assessment: IdeaAssessment,
    config: AutoResearchConfig,
    round_index: int,
    idea_index: int,
) -> None:
    idea_dir = _idea_dir(config, round_index, idea_index)
    roots = [config.base_run.resolve(), idea_dir.resolve()]
    relative_roots = [
        idea_dir,
        idea_dir / "codegen" / "codebase",
        idea_dir / "validation",
        config.base_run,
        config.base_run / "codegen" / "codebase",
        config.base_run / "replication",
    ]
    for validation in assessment.validations:
        for value in validation.evidence_paths:
            raw = Path(value).expanduser()
            candidates = (
                [raw]
                if raw.is_absolute()
                else [root / raw for root in relative_roots]
            )
            if raw.is_absolute():
                for marker, destination in (
                    (("codegen", "codebase"), config.base_run / "codegen" / "codebase"),
                    (("replication",), config.base_run / "replication"),
                ):
                    parts = raw.parts
                    for index in range(len(parts) - len(marker) + 1):
                        if tuple(parts[index : index + len(marker)]) == marker:
                            candidates.append(
                                destination.joinpath(*parts[index + len(marker) :])
                            )
                            break
            if not any(
                candidate.resolve().is_file()
                and any(candidate.resolve().is_relative_to(root) for root in roots)
                for candidate in candidates
            ):
                raise RuntimeError(
                    "Assessment evidence must be an existing file inside the base run or "
                    f"idea artifacts: {value}"
                )


def _validate_assessment_contract(
    assessment: IdeaAssessment,
    config: AutoResearchConfig,
) -> None:
    if not math.isclose(
        assessment.threshold,
        config.assessment_threshold,
        rel_tol=0,
        abs_tol=1e-12,
    ):
        raise RuntimeError(
            f"Assessment threshold does not match campaign configuration: "
            f"{assessment.idea_id}"
        )
    weights = load_model(
        config.output / "validation_setup" / "validation_weights.json",
        ValidationWeights,
    )
    contracts = load_model(
        config.output / "validation_setup" / "validation_contracts.json",
        ValidationContracts,
    )
    positive = [item for item in weights.validations if item.weight > 0]
    expected_ids = [item.validation_id for item in positive]
    actual_ids = [item.validation_id for item in assessment.validations]
    if actual_ids != expected_ids:
        raise RuntimeError(
            f"Assessment must cover every positive-weight V in order: {assessment.idea_id}"
        )
    match = re.fullmatch(r"R(\d+)-I(\d+)", assessment.idea_id)
    if match is None:
        raise RuntimeError(f"Invalid assessment idea ID: {assessment.idea_id}")
    plan = load_model(
        _idea_dir(config, int(match.group(1)), int(match.group(2)))
        / "plan"
        / "validation_plan.json",
        AutoResearchValidationPlan,
    )
    refined_by_baseline = {
        item.baseline_validation_id: item.validation_id for item in plan.validations
    }
    for importance, contract, comparison in zip(
        positive,
        contracts.validations,
        assessment.validations,
        strict=True,
    ):
        if (
            comparison.primary_metric != contract.primary_metric
            or comparison.comparison_rule != contract.comparison_rule
            or comparison.refined_validation_id
            != refined_by_baseline[contract.validation_id]
            or not math.isclose(
                comparison.weight,
                importance.weight,
                rel_tol=1e-6,
                abs_tol=1e-9,
            )
        ):
            raise RuntimeError(
                f"Assessment changed frozen weight, metric, rule, or V mapping for "
                f"{comparison.validation_id}"
            )


def _run_assessment(
    config: AutoResearchConfig,
    round_index: int,
    idea_index: int,
    implementation_plan_path: Path,
    audit_path: Path,
    plan_path: Path,
    log_path: Path,
    evidence_path: Path,
) -> Path:
    pipeline_state = PipelineState(config.output)
    stage_name = _stage_name(round_index, idea_index, "assessment")
    idea_id = expected_idea_ids(round_index)[idea_index - 1]
    assessment_dir = _idea_dir(config, round_index, idea_index) / "assessment"
    assessment_path = assessment_dir / "assessment.json"
    transcript_path = assessment_dir / "assessment_transcript.jsonl"
    if pipeline_state.is_stage_completed(stage_name):
        assessment = load_model(assessment_path, IdeaAssessment)
        if assessment.idea_id != idea_id or not transcript_path.is_file():
            raise RuntimeError(f"Completed assessment artifacts are invalid for {idea_id}")
        _validate_assessment_contract(assessment, config)
        _validate_assessment_evidence(
            assessment,
            config,
            round_index,
            idea_index,
        )
        print(f"resume {stage_name} stage: skipped (already completed)")
        return assessment_path

    print(f"enter {stage_name} stage")
    pipeline_state.start_stage(stage_name)
    assessment_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = render_prompt(
        "autoresearch/assessment/session_instructions.md",
        config.output
        / "prompts"
        / f"round_{round_index:03d}"
        / f"idea_{idea_index:02d}"
        / "assessment.md",
        idea_id=idea_id,
        contracts_path=(
            config.output / "validation_setup" / "validation_contracts.json"
        ),
        weights_path=config.output / "validation_setup" / "validation_weights.json",
        implementation_plan_path=implementation_plan_path,
        audit_path=audit_path,
        validation_plan_path=plan_path,
        validation_log_path=log_path,
        evidence_summary_path=evidence_path,
        base_replication_log=config.base_run / "replication" / "replication_log.json",
        base_evidence_summary=config.base_run / "replication" / "evidence_summary.json",
        base_reproduction_report=config.base_run / "report" / "reproduction_report.md",
        base_codebase_dir=config.base_run / "codegen" / "codebase",
        base_replication_dir=config.base_run / "replication",
        codebase_dir=_idea_dir(config, round_index, idea_index)
        / "codegen"
        / "codebase",
        validation_dir=_idea_dir(config, round_index, idea_index) / "validation",
        assessment_threshold=config.assessment_threshold,
        assessment_path=assessment_path,
    )
    run_agent(
        provider=config.provider,
        prompt_path=prompt_path,
        working_dir=assessment_dir,
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )
    assessment = load_model(assessment_path, IdeaAssessment)
    if assessment.idea_id != idea_id:
        raise RuntimeError(f"Assessment ID {assessment.idea_id} does not match {idea_id}")
    audit = load_model(audit_path, ValidationCodegenAudit)
    if assessment.audit_passed != (audit.verdict == "pass"):
        raise RuntimeError(f"Assessment audit status does not match codegen audit: {idea_id}")
    _validate_assessment_contract(assessment, config)
    _validate_assessment_evidence(
        assessment,
        config,
        round_index,
        idea_index,
    )
    pipeline_state.complete_stage(
        stage_name,
        [str(assessment_path), str(transcript_path)],
    )
    return assessment_path


def _write_audit_failure_assessment(
    config: AutoResearchConfig,
    round_index: int,
    idea_index: int,
    audit: ValidationCodegenAudit,
) -> Path:
    pipeline_state = PipelineState(config.output)
    stage_name = _stage_name(round_index, idea_index, "assessment")
    idea_id = expected_idea_ids(round_index)[idea_index - 1]
    assessment_path = (
        _idea_dir(config, round_index, idea_index) / "assessment" / "assessment.json"
    )
    if pipeline_state.is_stage_completed(stage_name):
        assessment = load_model(assessment_path, IdeaAssessment)
        if assessment.idea_id != idea_id:
            raise RuntimeError(f"Completed assessment ID does not match {idea_id}")
        return assessment_path

    print(f"enter {stage_name} stage")
    pipeline_state.start_stage(stage_name)
    failure_reasons = [
        check.issue for check in audit.checks if check.verdict == "fail" and check.issue
    ]
    assessment = IdeaAssessment(
        idea_id=idea_id,
        verdict="invalid",
        summary="Codegen audit failed after one repair; validation was not run.",
        audit_passed=False,
        protocol_consistent=False,
        validations=[],
        weighted_score=None,
        threshold=config.assessment_threshold,
        failure_reasons=failure_reasons or audit.required_fixes,
    )
    write_json(assessment_path, assessment.model_dump(mode="json"))
    pipeline_state.complete_stage(stage_name, [str(assessment_path)])
    return assessment_path


def _run_idea(
    config: AutoResearchConfig,
    round_index: int,
    idea_index: int,
    ideas_path: Path,
) -> Path:
    codebase_dir, implementation_plan_path = _run_codegen(
        config,
        round_index,
        idea_index,
        ideas_path,
    )
    audit, audit_path = _run_codegen_audit(
        config,
        round_index,
        idea_index,
        1,
        codebase_dir,
        implementation_plan_path,
    )
    if audit.verdict == "fail":
        codebase_dir, implementation_plan_path = _run_codegen(
            config,
            round_index,
            idea_index,
            ideas_path,
            repair_audit_path=audit_path,
        )
        audit, audit_path = _run_codegen_audit(
            config,
            round_index,
            idea_index,
            2,
            codebase_dir,
            implementation_plan_path,
        )
    if audit.verdict == "fail":
        return _write_audit_failure_assessment(
            config,
            round_index,
            idea_index,
            audit,
        )

    plan_path = _run_validation_plan(
        config,
        round_index,
        idea_index,
        codebase_dir,
        implementation_plan_path,
        audit_path,
    )
    log_path, evidence_path = _run_validation(
        config,
        round_index,
        idea_index,
        codebase_dir,
        plan_path,
        implementation_plan_path,
        audit_path,
    )
    return _run_assessment(
        config,
        round_index,
        idea_index,
        implementation_plan_path,
        audit_path,
        plan_path,
        log_path,
        evidence_path,
    )


def _canonical_assessment_paths(
    config: AutoResearchConfig,
    round_index: int,
) -> list[Path]:
    return [
        _idea_dir(config, round_index, idea_index)
        / "assessment"
        / "assessment.json"
        for idea_index in range(1, 4)
    ]


def _build_round_summary(
    round_index: int,
    assessment_paths: list[Path],
) -> RoundSummary:
    assessments = [load_model(path, IdeaAssessment) for path in assessment_paths]
    return RoundSummary(
        round=round_index,
        ideas=[
            {
                "idea_id": assessment.idea_id,
                "verdict": assessment.verdict,
                "reason": assessment.summary,
                "assessment_path": str(path),
            }
            for assessment, path in zip(assessments, assessment_paths, strict=True)
        ],
        has_valid_refinement=any(
            assessment.verdict == "valid" for assessment in assessments
        ),
    )


def _load_validated_round_summary(
    config: AutoResearchConfig,
    round_index: int,
) -> RoundSummary:
    summary_path = _round_dir(config, round_index) / "round_summary.json"
    summary = load_model(summary_path, RoundSummary)
    expected = _build_round_summary(
        round_index,
        _canonical_assessment_paths(config, round_index),
    )
    if summary.model_dump(mode="json") != expected.model_dump(mode="json"):
        raise RuntimeError(
            f"Round summary does not match its canonical assessments: {summary_path}"
        )
    return summary


def _write_round_summary(
    config: AutoResearchConfig,
    round_index: int,
    assessment_paths: list[Path],
) -> RoundSummary:
    pipeline_state = PipelineState(config.output)
    stage_name = _stage_name(round_index, None, "summary")
    summary_path = _round_dir(config, round_index) / "round_summary.json"
    canonical_paths = _canonical_assessment_paths(config, round_index)
    if assessment_paths != canonical_paths:
        raise RuntimeError("Round summary received non-canonical assessment paths")
    if pipeline_state.is_stage_completed(stage_name):
        summary = _load_validated_round_summary(config, round_index)
        print(f"resume {stage_name} stage: skipped (already completed)")
        return summary

    print(f"enter {stage_name} stage")
    pipeline_state.start_stage(stage_name)
    summary = _build_round_summary(round_index, canonical_paths)
    write_json(summary_path, summary.model_dump(mode="json"))
    pipeline_state.complete_stage(
        stage_name,
        [str(summary_path), *(str(path) for path in assessment_paths)],
    )
    return summary


def autoresearch_loop_node(state: AutoResearchState) -> dict[str, Any]:
    config = state["config"]
    for round_index in range(1, config.max_iter + 1):
        ideas_path = _run_idea_generation(config, round_index)
        assessment_paths = [
            _run_idea(config, round_index, idea_index, ideas_path)
            for idea_index in range(1, 4)
        ]
        summary = _write_round_summary(config, round_index, assessment_paths)
        if summary.has_valid_refinement:
            break
    return {}


def _completed_rounds(config: AutoResearchConfig) -> list[RoundSummary]:
    summaries = []
    for round_index in range(1, config.max_iter + 1):
        path = _round_dir(config, round_index) / "round_summary.json"
        if not path.is_file():
            break
        summaries.append(_load_validated_round_summary(config, round_index))
        if summaries[-1].has_valid_refinement:
            break
    if not summaries:
        raise RuntimeError("Auto Research report requires at least one completed round")
    return summaries


def autoresearch_report_node(state: AutoResearchState) -> dict[str, str]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    report_dir = config.output / "report"
    report_path = report_dir / "auto_research_report.md"
    metric_path = report_dir / "idea_metric_comparison.png"
    status_path = report_dir / "idea_status_overview.png"
    summaries = _completed_rounds(config)
    assessments = [
        load_model(Path(idea.assessment_path), IdeaAssessment)
        for summary in summaries
        for idea in summary.ideas
    ]
    idea_ids = [assessment.idea_id for assessment in assessments]
    if pipeline_state.is_stage_completed("final_report"):
        try:
            report_text = report_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise RuntimeError(f"Completed Auto Research report is missing: {report_path}") from exc
        validate_autoresearch_report(report_text, idea_ids)
        if not metric_path.is_file() or not status_path.is_file():
            raise RuntimeError("Completed Auto Research visualizations are missing")
        transcript_path = report_dir / "report_transcript.jsonl"
        if not transcript_path.is_file():
            raise RuntimeError(f"Completed report transcript is missing: {transcript_path}")
        pipeline_state.mark_completed()
        print("resume autoresearch final_report stage: skipped (already completed)")
        return {"report_path": str(report_path)}

    print("enter autoresearch final_report stage")
    pipeline_state.start_stage("final_report")
    report_dir.mkdir(parents=True, exist_ok=True)
    generate_autoresearch_visualizations(
        assessments,
        summaries,
        metric_path,
        status_path,
    )
    transcript_path = report_dir / "report_transcript.jsonl"
    prompt_path = render_prompt(
        "autoresearch/report/session_instructions.md",
        config.output / "prompts" / "final_report.md",
        eligibility_path=config.output / "eligibility" / "eligibility.json",
        weights_path=config.output / "validation_setup" / "validation_weights.json",
        contracts_path=(
            config.output / "validation_setup" / "validation_contracts.json"
        ),
        base_reproduction_report=config.base_run / "report" / "reproduction_report.md",
        rounds_json=json.dumps(
            [_round_artifact_context(config, summary.round) for summary in summaries],
            ensure_ascii=False,
            indent=2,
        ),
        report_path=report_path,
        metric_visualization_path=metric_path,
        status_visualization_path=status_path,
    )
    run_agent(
        provider=config.provider,
        prompt_path=prompt_path,
        working_dir=report_dir,
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )
    try:
        report_text = report_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"Report agent did not write: {report_path}") from exc
    validate_autoresearch_report(report_text, idea_ids)
    pipeline_state.complete_stage(
        "final_report",
        [
            str(report_path),
            str(metric_path),
            str(status_path),
            str(transcript_path),
        ],
    )
    pipeline_state.mark_completed()
    return {"report_path": str(report_path)}


def _eligibility_route(state: AutoResearchState) -> str:
    return "validation_setup" if state.get("eligible") else "ineligible"


def create_autoresearch_workflow():
    builder = StateGraph(AutoResearchState)
    builder.add_node("preflight", autoresearch_preflight_node)
    builder.add_node("eligibility", autoresearch_eligibility_node)
    builder.add_node("validation_setup", autoresearch_validation_setup_node)
    builder.add_node("research", autoresearch_loop_node)
    builder.add_node("report", autoresearch_report_node)
    builder.add_edge(START, "preflight")
    builder.add_edge("preflight", "eligibility")
    builder.add_conditional_edges(
        "eligibility",
        _eligibility_route,
        {"validation_setup": "validation_setup", "ineligible": END},
    )
    builder.add_edge("validation_setup", "research")
    builder.add_edge("research", "report")
    builder.add_edge("report", END)
    return builder.compile()
