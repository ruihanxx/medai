from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from medai.artifacts import load_model, write_json
from medai.autoresearch_visualization import generate_autoresearch_visualizations
from medai.config import AutoResearchConfig
from medai.models import (
    ClaimsFile,
    CodegenAudit,
    CodegenPlan,
    EligibilityResult,
    EvidenceSummary,
    ExperimentTodo,
    IdeaAssessment,
    IdeaImplementationPlan,
    ReplicationLog,
    ReplicationPlan,
    RoundSummary,
    SmartReplicateLog,
    validate_experiment_coverage,
    validate_replication_log,
    validate_replication_plan,
    validate_reproduction_report,
    validate_smart_replicate_log,
)
from medai.pipeline_state import PipelineState
from medai.prompts import render_prompt
from medai.providers import run_agent
from medai.resources import detect_resources
from medai.workflow import skills_dir

REQUIRED_BASE_STAGES = (
    "preflight",
    "preprocess_pdf",
    "preprocessing_agent",
    "codegen_agent",
    "plan_agent",
    "replicate_agent",
    "report_agents",
)
AUTORESEARCH_REPORT_SECTIONS = (
    "## 1. Base problem and anchors",
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
    matches = list(re.finditer(r"(?m)^## (R\d{2}-I\d{2})\s*$", text))
    actual_ids = [match.group(1) for match in matches]
    expected_ids = expected_idea_ids(round_index)
    if actual_ids != expected_ids:
        raise ValueError(
            f"Idea document must contain exactly these ideas in order: {expected_ids}"
        )
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[match.end() : end]
        for heading in ("Description", "Motivation", "Provenance"):
            heading_matches = list(
                re.finditer(rf"(?m)^### {re.escape(heading)}\s*$", section)
            )
            if len(heading_matches) != 1:
                raise ValueError(f"{match.group(1)} must contain exactly one {heading} section")
            body_start = heading_matches[0].end()
            next_heading = re.search(r"(?m)^### ", section[body_start:])
            body_end = body_start + next_heading.start() if next_heading else len(section)
            if not section[body_start:body_end].strip():
                raise ValueError(f"{match.group(1)} has an empty {heading} section")


def validate_autoresearch_report(report_text: str, idea_ids: list[str]) -> None:
    invalid_sections = [
        section for section in AUTORESEARCH_REPORT_SECTIONS if report_text.count(section) != 1
    ]
    if invalid_sections:
        raise ValueError(
            "Auto Research report must contain exactly one of every required section: "
            f"{invalid_sections}"
        )
    positions = [report_text.index(section) for section in AUTORESEARCH_REPORT_SECTIONS]
    if positions != sorted(positions):
        raise ValueError("Auto Research report sections are out of order")
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


def _stage_name(round_index: int, idea_index: int | None, stage: str) -> str:
    prefix = f"round_{round_index:03d}"
    if idea_index is not None:
        prefix += f".idea_{idea_index:02d}"
    return f"{prefix}.{stage}"


def _validate_base_run(config: AutoResearchConfig) -> None:
    base_state = PipelineState(config.base_run)
    if base_state.state.get("status") != "completed":
        raise RuntimeError(f"Base replicate run is not completed: {config.base_run}")
    incomplete = [
        stage for stage in REQUIRED_BASE_STAGES if not base_state.is_stage_completed(stage)
    ]
    if incomplete:
        raise RuntimeError(f"Base replicate run has incomplete stages: {incomplete}")

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
        base_manifest=config.base_run / "manifest.json",
        paper_markdown=config.base_run / "preprocessing" / "paper.md",
        claims_path=config.base_run / "preprocessing" / "claims.json",
        experiments_path=config.base_run / "preprocessing" / "experiment_todo.json",
        codegen_plan_path=config.base_run / "codegen" / "codebase" / "codegen_plan.json",
        codebase_dir=config.base_run / "codegen" / "codebase",
        replicate_plan_path=config.base_run / "plan" / "replicate_plan.json",
        replication_log_path=config.base_run / "replication" / "replication_log.json",
        evidence_summary_path=config.base_run / "replication" / "evidence_summary.json",
        reproduction_report_path=config.base_run / "report" / "reproduction_report.md",
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


def _run_idea_generation(config: AutoResearchConfig, round_index: int) -> Path:
    pipeline_state = PipelineState(config.output)
    stage_name = _stage_name(round_index, None, "idea_generation")
    round_dir = _round_dir(config, round_index)
    ideas_path = round_dir / "ideas.md"
    transcript_path = round_dir / "idea_generation_transcript.jsonl"
    if pipeline_state.is_stage_completed(stage_name):
        try:
            validate_ideas_document(ideas_path.read_text(encoding="utf-8"), round_index)
        except FileNotFoundError as exc:
            raise RuntimeError(f"Completed idea document is missing: {ideas_path}") from exc
        if not transcript_path.is_file():
            raise RuntimeError(
                f"Completed idea-generation transcript is missing: {transcript_path}"
            )
        print(f"resume {stage_name} stage: skipped (already completed)")
        return ideas_path

    print(f"enter {stage_name} stage")
    pipeline_state.start_stage(stage_name)
    round_dir.mkdir(parents=True, exist_ok=True)
    prior_rounds = [
        {
            "ideas": str(_round_dir(config, prior) / "ideas.md"),
            "summary": str(_round_dir(config, prior) / "round_summary.json"),
        }
        for prior in range(1, round_index)
    ]
    prompt_path = render_prompt(
        "autoresearch/idea_generation/session_instructions.md",
        config.output / "prompts" / f"round_{round_index:03d}" / "idea_generation.md",
        paper_markdown=config.base_run / "preprocessing" / "paper.md",
        eligibility_path=config.output / "eligibility" / "eligibility.json",
        reproduction_report_path=config.base_run / "report" / "reproduction_report.md",
        codebase_dir=config.base_run / "codegen" / "codebase",
        idea_generation_skill=skills_dir() / "idea-generation" / "SKILL.md",
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
    pipeline_state.complete_stage(stage_name, [str(ideas_path), str(transcript_path)])
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
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
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
        ideas_path=ideas_path,
        eligibility_path=config.output / "eligibility" / "eligibility.json",
        base_codebase_dir=config.base_run / "codegen" / "codebase",
        codebase_dir=codebase_dir,
        data_dir=config.data,
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
    pipeline_state.complete_stage(
        stage_name,
        [str(codebase_dir), str(implementation_plan_path), str(transcript_path)],
    )
    return codebase_dir, implementation_plan_path


def _codebase_fingerprint(codebase_dir: Path) -> str:
    digest = hashlib.sha256()
    ignored = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
    for path in sorted(codebase_dir.rglob("*")):
        relative = path.relative_to(codebase_dir)
        if any(part in ignored for part in relative.parts) or not path.is_file():
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
    if pipeline_state.is_stage_completed(stage_name):
        audit = load_model(attempt_path, CodegenAudit)
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
        eligibility_path=config.output / "eligibility" / "eligibility.json",
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
    ideas_path: Path,
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
    if pipeline_state.is_stage_completed(stage_name):
        load_model(plan_path, ReplicationPlan)
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
        ideas_path=ideas_path,
        eligibility_path=config.output / "eligibility" / "eligibility.json",
        implementation_plan_path=implementation_plan_path,
        audit_path=audit_path,
        codebase_dir=codebase_dir,
        base_replication_log=config.base_run / "replication" / "replication_log.json",
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
    load_model(plan_path, ReplicationPlan)
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
    log_path: Path,
    evidence_path: Path,
    codebase_dir: Path,
    experiment_dir: Path,
) -> list[str]:
    plan = load_model(plan_path, ReplicationPlan)
    log = load_model(log_path, ReplicationLog)
    validate_replication_log(plan, log)
    load_model(evidence_path, EvidenceSummary)
    managed = {log_path.resolve(), evidence_path.resolve()}
    outputs = [str(log_path), str(evidence_path)]
    for outcome in log.step_outcomes:
        for output_file in outcome.output_files:
            resolved = _resolve_experiment_output(output_file, codebase_dir, experiment_dir)
            if resolved in managed:
                raise RuntimeError(
                    f"Experiment step {outcome.step_id} cannot cite a managed log as output"
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
    if pipeline_state.is_stage_completed(stage_name):
        _validate_experiment_artifacts(
            plan_path,
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
    experiment_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = render_prompt(
        "autoresearch/experiment/session_instructions.md",
        config.output
        / "prompts"
        / f"round_{round_index:03d}"
        / f"idea_{idea_index:02d}"
        / "experiment.md",
        idea_id=idea_id,
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
    outputs = _validate_experiment_artifacts(
        plan_path,
        log_path,
        evidence_path,
        codebase_dir,
        experiment_dir,
    )
    pipeline_state.complete_stage(stage_name, [*outputs, str(transcript_path)])
    return log_path, evidence_path


def _run_assessment(
    config: AutoResearchConfig,
    round_index: int,
    idea_index: int,
    ideas_path: Path,
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
        ideas_path=ideas_path,
        eligibility_path=config.output / "eligibility" / "eligibility.json",
        implementation_plan_path=implementation_plan_path,
        audit_path=audit_path,
        experiment_plan_path=plan_path,
        experiment_log_path=log_path,
        evidence_summary_path=evidence_path,
        base_replication_log=config.base_run / "replication" / "replication_log.json",
        base_evidence_summary=config.base_run / "replication" / "evidence_summary.json",
        base_reproduction_report=config.base_run / "report" / "reproduction_report.md",
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
        primary_metric=None,
        secondary_metrics=[],
        evidence_paths=[],
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
        ideas_path,
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
        ideas_path,
        implementation_plan_path,
        audit_path,
        plan_path,
        log_path,
        evidence_path,
    )


def _write_round_summary(
    config: AutoResearchConfig,
    round_index: int,
    assessment_paths: list[Path],
) -> RoundSummary:
    pipeline_state = PipelineState(config.output)
    stage_name = _stage_name(round_index, None, "summary")
    summary_path = _round_dir(config, round_index) / "round_summary.json"
    if pipeline_state.is_stage_completed(stage_name):
        summary = load_model(summary_path, RoundSummary)
        for idea in summary.ideas:
            load_model(Path(idea.assessment_path), IdeaAssessment)
        print(f"resume {stage_name} stage: skipped (already completed)")
        return summary

    print(f"enter {stage_name} stage")
    pipeline_state.start_stage(stage_name)
    assessments = [load_model(path, IdeaAssessment) for path in assessment_paths]
    summary = RoundSummary(
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
        summaries.append(load_model(path, RoundSummary))
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
        base_reproduction_report=config.base_run / "report" / "reproduction_report.md",
        rounds_json=json.dumps(
            [
                {
                    "ideas": str(_round_dir(config, summary.round) / "ideas.md"),
                    "summary": str(
                        _round_dir(config, summary.round) / "round_summary.json"
                    ),
                }
                for summary in summaries
            ],
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
    return "research" if state.get("eligible") else "ineligible"


def create_autoresearch_workflow():
    builder = StateGraph(AutoResearchState)
    builder.add_node("preflight", autoresearch_preflight_node)
    builder.add_node("eligibility", autoresearch_eligibility_node)
    builder.add_node("research", autoresearch_loop_node)
    builder.add_node("report", autoresearch_report_node)
    builder.add_edge(START, "preflight")
    builder.add_edge("preflight", "eligibility")
    builder.add_conditional_edges(
        "eligibility",
        _eligibility_route,
        {"research": "research", "ineligible": END},
    )
    builder.add_edge("research", "report")
    builder.add_edge("report", END)
    return builder.compile()
