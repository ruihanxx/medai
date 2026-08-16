from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from medai.artifacts import load_model, write_json
from medai.autoresearch_visualization import generate_autoresearch_visualizations
from medai.config import AutoResearchConfig
from medai.models import (
    AutoResearchExperimentLog,
    AutoResearchExperimentPlan,
    ClaimsFile,
    CodegenAudit,
    CodegenPlan,
    EligibilityResult,
    EvidenceSummary,
    ExperimentContracts,
    ExperimentTodo,
    ExperimentWeights,
    IdeaAssessment,
    IdeaCandidatePool,
    IdeaImplementationPlan,
    ReplicationLog,
    ReplicationPlan,
    RoundSummary,
    SmartReplicateLog,
    validate_autoresearch_experiment_log,
    validate_autoresearch_experiment_plan,
    validate_candidate_pool_for_selection,
    validate_codegen_audit,
    validate_experiment_contracts,
    validate_experiment_coverage,
    validate_experiment_weights,
    validate_idea_implementation_plan,
    validate_replication_log,
    validate_replication_plan,
    validate_reproduction_report,
    validate_smart_replicate_log,
)
from medai.pipeline_state import PipelineState
from medai.prompts import render_prompt
from medai.providers import run_agent
from medai.resources import detect_resources
from medai.workflow import resolve_replication_output, skills_dir

REQUIRED_BASE_STAGES = (
    "preflight",
    "preprocess_pdf",
    "preprocessing_agent",
    "codegen_agent",
    "audit_agent",
    "plan_agent",
    "replicate_agent",
    "report_agents",
)
AUTORESEARCH_REPORT_SECTIONS = (
    "## 1. Base problem and research context",
    "## 2. Idea ledger",
    "## 3. Experiment comparisons",
    "## 4. Validity and failure assessment",
    "## 5. Visualizations",
)


class AutoResearchState(TypedDict, total=False):
    config: AutoResearchConfig
    eligibility_path: str
    eligible: bool
    report_path: str


def expected_idea_ids(round_index: int) -> list[str]:
    return [f"R{round_index:02d}-I{idea_index:02d}" for idea_index in range(1, 4)]


def validate_ideas_document(text: str, round_index: int) -> None:
    expected_ids = expected_idea_ids(round_index)
    h1_headings = re.findall(r"(?m)^# ([^\r\n]+?)[ \t]*$", text)
    expected_title = f"Idea Generation Round {round_index}"
    if h1_headings != [expected_title]:
        raise ValueError(f"Idea document must use title: # {expected_title}")
    level_two_headings = re.findall(r"(?m)^## ([^\r\n]+?)[ \t]*$", text)
    if level_two_headings != expected_ids:
        raise ValueError(
            f"Idea document must contain exactly these ideas in order: {expected_ids}"
        )
    matches = list(re.finditer(r"(?m)^## (R\d{2}-I\d{2})[ \t]*$", text))
    expected_sections = ["Description", "Motivation", "Provenance"]
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[match.end() : end]
        section_matches = list(re.finditer(r"(?m)^### ([^\r\n]+?)[ \t]*$", section))
        actual_sections = [heading.group(1) for heading in section_matches]
        if actual_sections != expected_sections:
            raise ValueError(
                f"{match.group(1)} must contain exactly Description, Motivation, "
                "and Provenance in order"
            )
        for heading_index, heading_match in enumerate(section_matches):
            body_start = heading_match.end()
            body_end = (
                section_matches[heading_index + 1].start()
                if heading_index + 1 < len(section_matches)
                else len(section)
            )
            if not section[body_start:body_end].strip():
                raise ValueError(
                    f"{match.group(1)} has an empty {heading_match.group(1)} section"
                )


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
            "audit": idea_dir / "audit" / "audit.json",
            "experiment_plan": idea_dir / "plan" / "experiment_plan.json",
            "experiment_log": idea_dir / "experiment" / "experiment_log.json",
            "evidence_summary": idea_dir / "experiment" / "evidence_summary.json",
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
        "ideas": str(_round_dir(config, round_index) / "ideas.md"),
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
    contracts: ExperimentContracts,
    base_codebase_dir: Path,
) -> None:
    for contract in contracts.experiments:
        for value in (
            *contract.model_implementation_paths,
            *contract.input_representation_paths,
            *contract.training_paths,
            *contract.integration_paths,
        ):
            path = _relative_code_path(value)
            if not (base_codebase_dir / path).is_file():
                raise RuntimeError(
                    f"Experiment contract references a missing base code file: {value}"
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
        config.output / "experiment_setup" / "experiment_contracts.json",
        ExperimentContracts,
    )
    validate_idea_implementation_plan(contracts, plan)
    contracts_by_id = {
        contract.experiment_id: contract for contract in contracts.experiments
    }

    new_refinement_files = {
        _relative_code_path(value).as_posix() for value in plan.new_refinement_files
    }
    existing_refinement_files = set()
    for integration in plan.experiment_integrations:
        contract = contracts_by_id[integration.experiment_id]
        if integration.baseline_entry_points != contract.baseline_entry_points:
            raise RuntimeError(
                f"Implementation changed baseline entry points for "
                f"{integration.experiment_id}"
            )
        contract_paths_by_aspect = {
            "input_representation": {
                _relative_code_path(value).as_posix()
                for value in contract.input_representation_paths
            },
            "training_strategy": {
                _relative_code_path(value).as_posix()
                for value in contract.training_paths
            },
            "integration": {
                _relative_code_path(value).as_posix()
                for value in contract.integration_paths
            },
        }
        for change in integration.refinement_changes:
            path = _relative_code_path(change.path).as_posix()
            if path not in contract_paths_by_aspect[change.aspect]:
                raise RuntimeError(
                    f"Implementation changes undeclared {change.aspect} path for "
                    f"{integration.experiment_id}: {path}"
                )
            existing_refinement_files.add(path)

    for relative in new_refinement_files:
        if (base_codebase_dir / relative).exists():
            raise RuntimeError(f"Refinement file already exists in base code: {relative}")
        if not (codebase_dir / relative).is_file():
            raise RuntimeError(f"Declared refinement file is missing: {relative}")
    for relative in existing_refinement_files:
        if not (base_codebase_dir / relative).is_file():
            raise RuntimeError(f"Declared change file is missing from base code: {relative}")
        if not (codebase_dir / relative).is_file():
            raise RuntimeError(f"Refinement deleted a declared change file: {relative}")

    base_files = _codebase_file_hashes(base_codebase_dir)
    refined_files = _codebase_file_hashes(codebase_dir)
    changed_files = {
        path
        for path in set(base_files) | set(refined_files)
        if base_files.get(path) != refined_files.get(path)
    }
    allowed_files = new_refinement_files | existing_refinement_files
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


def _validate_base_run(config: AutoResearchConfig) -> None:
    base_state = PipelineState(config.base_run)
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

    claims = load_model(config.base_run / "preprocessing" / "claims.json", ClaimsFile)
    experiments = load_model(
        config.base_run / "preprocessing" / "experiment_todo.json",
        ExperimentTodo,
    )
    validate_experiment_coverage(claims, experiments)
    codegen_plan = load_model(
        config.base_run / "codegen" / "codebase" / "codegen_plan.json",
        CodegenPlan,
    )
    replicate_plan = load_model(
        config.base_run / "plan" / "replicate_plan.json",
        ReplicationPlan,
    )
    validate_replication_plan(experiments, replicate_plan)
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
    validate_reproduction_report(report_text, claims, experiments, codegen_plan)

    if base_state.state["inputs"].get("smart_replicate"):
        claims_by_id = {claim.claim_id: claim for claim in claims.claims}
        for experiment in experiments.experiments:
            smart_log = load_model(
                config.base_run
                / "replication"
                / experiment.experiment_id
                / "smart_replicate_log.json",
                SmartReplicateLog,
            )
            validate_smart_replicate_log(
                experiment,
                smart_log,
                {
                    claim_id: claims_by_id[claim_id].paper_result
                    for claim_id in experiment.claims
                },
            )


def autoresearch_preflight_node(state: AutoResearchState) -> dict[str, Any]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    resources_path = config.output / "preflight" / "resources.json"
    idea_skill = skills_dir() / "idea-generation" / "SKILL.md"
    if pipeline_state.is_stage_completed("preflight"):
        _validate_base_run(config)
        if not idea_skill.is_file():
            raise RuntimeError(f"Required idea-generation skill is missing: {idea_skill}")
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
    if not idea_skill.is_file():
        raise RuntimeError(f"Required idea-generation skill is missing: {idea_skill}")
    for name in (
        "preflight",
        "eligibility",
        "experiment_setup",
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


def autoresearch_experiment_setup_node(state: AutoResearchState) -> dict[str, Any]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    setup_dir = config.output / "experiment_setup"
    experiments_path = config.base_run / "preprocessing" / "experiment_todo.json"
    experiments = load_model(experiments_path, ExperimentTodo)
    weights_path = setup_dir / "experiment_weights.json"
    weights_transcript_path = setup_dir / "experiment_weighting_transcript.jsonl"

    if pipeline_state.is_stage_completed("experiment_weighting"):
        weights = load_model(weights_path, ExperimentWeights)
        validate_experiment_weights(experiments, weights)
        if not weights_transcript_path.is_file():
            raise RuntimeError(
                f"Completed experiment-weighting transcript is missing: "
                f"{weights_transcript_path}"
            )
        print("resume experiment_weighting stage: skipped (already completed)")
    else:
        print("enter experiment_weighting stage")
        pipeline_state.start_stage("experiment_weighting")
        setup_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = render_prompt(
            "autoresearch/experiment_weighting/session_instructions.md",
            config.output / "prompts" / "experiment_setup" / "weighting.md",
            paper_markdown=config.base_run / "preprocessing" / "paper.md",
            experiments_path=experiments_path,
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
        weights = load_model(weights_path, ExperimentWeights)
        validate_experiment_weights(experiments, weights)
        pipeline_state.complete_stage(
            "experiment_weighting",
            [str(weights_path), str(weights_transcript_path)],
        )

    contracts_path = setup_dir / "experiment_contracts.json"
    contracts_transcript_path = setup_dir / "experiment_contracts_transcript.jsonl"
    if pipeline_state.is_stage_completed("experiment_contracts"):
        contracts = load_model(contracts_path, ExperimentContracts)
        validate_experiment_contracts(experiments, contracts)
        _validate_contract_code_paths(
            contracts,
            config.base_run / "codegen" / "codebase",
        )
        if not contracts_transcript_path.is_file():
            raise RuntimeError(
                f"Completed experiment-contract transcript is missing: "
                f"{contracts_transcript_path}"
            )
        print("resume experiment_contracts stage: skipped (already completed)")
        return {}

    print("enter experiment_contracts stage")
    pipeline_state.start_stage("experiment_contracts")
    base_codebase_dir = config.base_run / "codegen" / "codebase"
    before = _codebase_fingerprint(base_codebase_dir)
    prompt_path = render_prompt(
        "autoresearch/experiment_contracts/session_instructions.md",
        config.output / "prompts" / "experiment_setup" / "contracts.md",
        experiments_path=experiments_path,
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
        raise RuntimeError("Experiment-contract agent modified the base codebase")
    contracts = load_model(contracts_path, ExperimentContracts)
    validate_experiment_contracts(experiments, contracts)
    _validate_contract_code_paths(contracts, base_codebase_dir)
    pipeline_state.complete_stage(
        "experiment_contracts",
        [str(contracts_path), str(contracts_transcript_path)],
    )
    return {}


def _run_idea_generation(config: AutoResearchConfig, round_index: int) -> Path:
    pipeline_state = PipelineState(config.output)
    stage_name = _stage_name(round_index, None, "idea_generation")
    round_dir = _round_dir(config, round_index)
    ideas_path = round_dir / "ideas.md"
    transcript_path = round_dir / "idea_generation_transcript.jsonl"
    candidates_path = config.output / "idea_generation" / "candidates.json"
    if pipeline_state.is_stage_completed(stage_name):
        try:
            validate_ideas_document(ideas_path.read_text(encoding="utf-8"), round_index)
        except FileNotFoundError as exc:
            raise RuntimeError(f"Completed idea document is missing: {ideas_path}") from exc
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
        reproduction_report_path=config.base_run / "report" / "reproduction_report.md",
        codebase_dir=config.base_run / "codegen" / "codebase",
        idea_generation_skill=skills_dir() / "idea-generation" / "SKILL.md",
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
    try:
        validate_ideas_document(ideas_path.read_text(encoding="utf-8"), round_index)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Idea-generation agent did not write: {ideas_path}") from exc
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
        print(f"resume {stage_name} stage: skipped (already completed)")
        return codebase_dir, implementation_plan_path

    print(f"enter {stage_name} stage")
    pipeline_state.start_stage(stage_name)
    codegen_dir.mkdir(parents=True, exist_ok=True)
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
            config.output / "experiment_setup" / "experiment_contracts.json"
        ),
        experiments_path=(
            config.base_run / "preprocessing" / "experiment_todo.json"
        ),
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
    pipeline_state.complete_stage(
        stage_name,
        [str(codebase_dir), str(implementation_plan_path), str(transcript_path)],
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
) -> tuple[CodegenAudit, Path]:
    pipeline_state = PipelineState(config.output)
    stage_name = _stage_name(round_index, idea_index, f"audit_{attempt}")
    idea_id = expected_idea_ids(round_index)[idea_index - 1]
    audit_dir = _idea_dir(config, round_index, idea_index) / "audit"
    attempt_path = audit_dir / f"audit_{attempt}.json"
    canonical_path = audit_dir / "audit.json"
    transcript_path = audit_dir / f"audit_{attempt}_transcript.jsonl"
    contracts_path = config.output / "experiment_setup" / "experiment_contracts.json"
    contracts = load_model(contracts_path, ExperimentContracts)
    if pipeline_state.is_stage_completed(stage_name):
        audit = load_model(attempt_path, CodegenAudit)
        validate_codegen_audit(contracts, audit)
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
    audit = load_model(attempt_path, CodegenAudit)
    if audit.idea_id != idea_id:
        raise RuntimeError(f"Codegen audit ID {audit.idea_id} does not match {idea_id}")
    validate_codegen_audit(contracts, audit)
    shutil.copy2(attempt_path, canonical_path)
    pipeline_state.complete_stage(
        stage_name,
        [str(attempt_path), str(canonical_path), str(transcript_path)],
    )
    return audit, canonical_path


def _run_experiment_plan(
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
    plan_path = plan_dir / "experiment_plan.json"
    transcript_path = plan_dir / "plan_transcript.jsonl"
    contracts_path = config.output / "experiment_setup" / "experiment_contracts.json"
    contracts = load_model(contracts_path, ExperimentContracts)
    implementation = load_model(implementation_plan_path, IdeaImplementationPlan)
    if pipeline_state.is_stage_completed(stage_name):
        plan = load_model(plan_path, AutoResearchExperimentPlan)
        validate_autoresearch_experiment_plan(contracts, implementation, plan)
        if not transcript_path.is_file():
            raise RuntimeError(f"Completed experiment-plan transcript is missing: {transcript_path}")
        print(f"resume {stage_name} stage: skipped (already completed)")
        return plan_path

    print(f"enter {stage_name} stage")
    pipeline_state.start_stage(stage_name)
    plan_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = render_prompt(
        "autoresearch/plan/session_instructions.md",
        config.output
        / "prompts"
        / f"round_{round_index:03d}"
        / f"idea_{idea_index:02d}"
        / "plan.md",
        idea_id=idea_id,
        contracts_path=contracts_path,
        weights_path=config.output / "experiment_setup" / "experiment_weights.json",
        implementation_plan_path=implementation_plan_path,
        audit_path=audit_path,
        codebase_dir=codebase_dir,
        experiment_plan_path=plan_path,
        computation_provider_state_path=config.output / "remote_compute" / "instance.json",
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
    plan = load_model(plan_path, AutoResearchExperimentPlan)
    validate_autoresearch_experiment_plan(contracts, implementation, plan)
    pipeline_state.complete_stage(stage_name, [str(plan_path), str(transcript_path)])
    return plan_path


def _resolve_experiment_output(value: str, codebase_dir: Path, experiment_dir: Path) -> Path:
    raw = Path(value).expanduser()
    candidates = [raw] if raw.is_absolute() else [codebase_dir / raw, experiment_dir / raw]
    allowed_roots = [codebase_dir.resolve(), experiment_dir.resolve()]
    for candidate in candidates:
        resolved = candidate.resolve()
        if any(resolved.is_relative_to(root) for root in allowed_roots) and resolved.is_file():
            return resolved
    raise RuntimeError(
        "Auto Research experiment output must be a regular file inside the idea "
        f"codebase or experiment directory: {value}"
    )


def _validate_experiment_artifacts(
    plan_path: Path,
    implementation_plan_path: Path,
    log_path: Path,
    evidence_path: Path,
    codebase_dir: Path,
    experiment_dir: Path,
) -> list[str]:
    plan = load_model(plan_path, AutoResearchExperimentPlan)
    implementation = load_model(implementation_plan_path, IdeaImplementationPlan)
    log = load_model(log_path, AutoResearchExperimentLog)
    validate_autoresearch_experiment_log(plan, log)
    load_model(evidence_path, EvidenceSummary)
    managed = {log_path.resolve(), evidence_path.resolve()}
    outputs = [str(log_path), str(evidence_path)]
    integrations = {
        integration.experiment_id: integration
        for integration in implementation.experiment_integrations
    }
    for experiment in log.experiments:
        baseline_commands = {
            command.strip()
            for command in integrations[experiment.experiment_id].baseline_entry_points
        }
        for outcome in experiment.step_outcomes:
            if outcome.command_executed.strip() in baseline_commands:
                raise RuntimeError(
                    f"Auto Research experiment reran a baseline: "
                    f"{experiment.experiment_id} step {outcome.step_id}"
                )
            if outcome.code_modified or outcome.fixes_applied:
                raise RuntimeError(
                    f"Auto Research experiment modified audited code: "
                    f"{experiment.experiment_id} step {outcome.step_id}"
                )
            for output_file in outcome.output_files:
                resolved = _resolve_experiment_output(
                    output_file,
                    codebase_dir,
                    experiment_dir,
                )
                if resolved in managed:
                    raise RuntimeError(
                        f"Experiment step {outcome.step_id} cannot cite a managed log "
                        "as output"
                    )
                outputs.append(str(resolved))
    return outputs


def _run_experiment(
    config: AutoResearchConfig,
    round_index: int,
    idea_index: int,
    codebase_dir: Path,
    plan_path: Path,
    implementation_plan_path: Path,
    audit_path: Path,
) -> tuple[Path, Path]:
    pipeline_state = PipelineState(config.output)
    stage_name = _stage_name(round_index, idea_index, "experiment")
    idea_id = expected_idea_ids(round_index)[idea_index - 1]
    experiment_dir = _idea_dir(config, round_index, idea_index) / "experiment"
    log_path = experiment_dir / "experiment_log.json"
    evidence_path = experiment_dir / "evidence_summary.json"
    transcript_path = experiment_dir / "experiment_transcript.jsonl"
    codebase_fingerprint = _source_code_fingerprint(codebase_dir)
    checkpoints = pipeline_state.get_stage_checkpoints(stage_name)
    audited_fingerprint = checkpoints.get("audited_source_fingerprint")
    if audited_fingerprint and audited_fingerprint != codebase_fingerprint:
        raise RuntimeError(f"Audited idea code changed before experiment: {idea_id}")
    if pipeline_state.is_stage_completed(stage_name):
        _validate_experiment_artifacts(
            plan_path,
            implementation_plan_path,
            log_path,
            evidence_path,
            codebase_dir,
            experiment_dir,
        )
        if not transcript_path.is_file():
            raise RuntimeError(f"Completed experiment transcript is missing: {transcript_path}")
        print(f"resume {stage_name} stage: skipped (already completed)")
        return log_path, evidence_path

    print(f"enter {stage_name} stage")
    pipeline_state.start_stage(stage_name)
    if not audited_fingerprint:
        pipeline_state.update_stage_checkpoints(
            stage_name,
            {"audited_source_fingerprint": codebase_fingerprint},
        )
    experiment_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = render_prompt(
        "autoresearch/experiment/session_instructions.md",
        config.output
        / "prompts"
        / f"round_{round_index:03d}"
        / f"idea_{idea_index:02d}"
        / "experiment.md",
        idea_id=idea_id,
        contracts_path=(
            config.output / "experiment_setup" / "experiment_contracts.json"
        ),
        experiment_plan_path=plan_path,
        implementation_plan_path=implementation_plan_path,
        audit_path=audit_path,
        codebase_dir=codebase_dir,
        data_dir=config.data,
        base_replication_log=config.base_run / "replication" / "replication_log.json",
        base_evidence_summary=config.base_run / "replication" / "evidence_summary.json",
        experiment_dir=experiment_dir,
        experiment_log_path=log_path,
        evidence_summary_path=evidence_path,
        computation_provider_state_path=config.output / "remote_compute" / "instance.json",
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
    if _source_code_fingerprint(codebase_dir) != codebase_fingerprint:
        raise RuntimeError(f"Experiment agent modified audited idea code: {idea_id}")
    outputs = _validate_experiment_artifacts(
        plan_path,
        implementation_plan_path,
        log_path,
        evidence_path,
        codebase_dir,
        experiment_dir,
    )
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
        idea_dir / "experiment",
        config.base_run,
        config.base_run / "codegen" / "codebase",
        config.base_run / "replication",
    ]
    for experiment in assessment.experiments:
        for value in experiment.evidence_paths:
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
        config.output / "experiment_setup" / "experiment_weights.json",
        ExperimentWeights,
    )
    contracts = load_model(
        config.output / "experiment_setup" / "experiment_contracts.json",
        ExperimentContracts,
    )
    expected_ids = [experiment.experiment_id for experiment in weights.experiments]
    actual_ids = [experiment.experiment_id for experiment in assessment.experiments]
    if actual_ids != expected_ids:
        raise RuntimeError(
            f"Assessment must cover every weighted experiment in order: {assessment.idea_id}"
        )
    for importance, contract, comparison in zip(
        weights.experiments,
        contracts.experiments,
        assessment.experiments,
        strict=True,
    ):
        if (
            comparison.metric_name != contract.primary_metric
            or comparison.direction != contract.metric_direction
            or not math.isclose(
                comparison.weight,
                importance.weight,
                rel_tol=1e-6,
                abs_tol=1e-9,
            )
        ):
            raise RuntimeError(
                f"Assessment changed frozen weight or metric for "
                f"{comparison.experiment_id}"
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
            config.output / "experiment_setup" / "experiment_contracts.json"
        ),
        weights_path=config.output / "experiment_setup" / "experiment_weights.json",
        implementation_plan_path=implementation_plan_path,
        audit_path=audit_path,
        experiment_plan_path=plan_path,
        experiment_log_path=log_path,
        evidence_summary_path=evidence_path,
        base_replication_log=config.base_run / "replication" / "replication_log.json",
        base_evidence_summary=config.base_run / "replication" / "evidence_summary.json",
        base_reproduction_report=config.base_run / "report" / "reproduction_report.md",
        base_codebase_dir=config.base_run / "codegen" / "codebase",
        base_replication_dir=config.base_run / "replication",
        codebase_dir=_idea_dir(config, round_index, idea_index)
        / "codegen"
        / "codebase",
        experiment_dir=_idea_dir(config, round_index, idea_index) / "experiment",
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
    audit = load_model(audit_path, CodegenAudit)
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
    audit: CodegenAudit,
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
        summary="Codegen audit failed after one repair; experiment was not run.",
        audit_passed=False,
        protocol_consistent=False,
        experiments=[],
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

    plan_path = _run_experiment_plan(
        config,
        round_index,
        idea_index,
        codebase_dir,
        implementation_plan_path,
        audit_path,
    )
    log_path, evidence_path = _run_experiment(
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
        weights_path=config.output / "experiment_setup" / "experiment_weights.json",
        contracts_path=(
            config.output / "experiment_setup" / "experiment_contracts.json"
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
    return "experiment_setup" if state.get("eligible") else "ineligible"


def create_autoresearch_workflow():
    builder = StateGraph(AutoResearchState)
    builder.add_node("preflight", autoresearch_preflight_node)
    builder.add_node("eligibility", autoresearch_eligibility_node)
    builder.add_node("experiment_setup", autoresearch_experiment_setup_node)
    builder.add_node("research", autoresearch_loop_node)
    builder.add_node("report", autoresearch_report_node)
    builder.add_edge(START, "preflight")
    builder.add_edge("preflight", "eligibility")
    builder.add_conditional_edges(
        "eligibility",
        _eligibility_route,
        {"experiment_setup": "experiment_setup", "ineligible": END},
    )
    builder.add_edge("experiment_setup", "research")
    builder.add_edge("research", "report")
    builder.add_edge("report", END)
    return builder.compile()
