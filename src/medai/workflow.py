from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from medai.artifacts import load_model, write_json
from medai.config import RunConfig
from medai.models import (
    ClaimsFile,
    CodegenPlan,
    DataInventory,
    DatasetPatchFile,
    EvidenceSummary,
    Experiment,
    ExperimentTodo,
    ReplicationLog,
    ReplicationPlan,
    SmartReplicateLog,
    validate_data_inventory,
    validate_experiment_coverage,
    validate_replication_log,
    validate_replication_plan,
    validate_reproduction_report,
    validate_smart_replicate_log,
)
from medai.pipeline_state import PipelineState
from medai.preprocessing import convert_pdf_to_markdown
from medai.prompts import render_prompt
from medai.providers import run_agent
from medai.resources import detect_resources


class WorkflowState(TypedDict, total=False):
    config: RunConfig
    paper_markdown: str
    resources_path: str
    claims_path: str
    experiments_path: str
    codebase_dir: str
    replicate_plan_path: str
    report_path: str


def skills_dir() -> Path:
    configured = os.environ.get("MEDAI_SKILLS_DIR")
    if configured:
        return Path(configured)
    repository_skills = Path(__file__).resolve().parents[2] / "templates" / "skills"
    if repository_skills.is_dir():
        return repository_skills
    return Path(__file__).parent / "templates" / "skills"


def resolve_replication_output(
    value: str,
    codebase_dir: Path,
    replication_dir: Path,
) -> Path:
    raw_path = Path(value).expanduser()
    if raw_path.is_absolute():
        candidates = [raw_path]
    else:
        candidates = [codebase_dir / raw_path, replication_dir / raw_path]
        if raw_path.parts and raw_path.parts[0] == "replication":
            candidates.append(replication_dir.parent / raw_path)

    allowed_roots = [codebase_dir.resolve(), replication_dir.resolve()]
    for candidate in candidates:
        resolved = candidate.resolve()
        if any(resolved.is_relative_to(root) for root in allowed_roots) and resolved.is_file():
            return resolved
    raise RuntimeError(
        "Replication output must be a regular file inside the copied codebase or "
        f"replication directory: {value}"
    )


def validate_replication_artifacts(state: WorkflowState) -> list[str]:
    config = state["config"]
    replication_dir = config.output / "replication"
    replication_log_path = replication_dir / "replication_log.json"
    evidence_summary_path = replication_dir / "evidence_summary.json"
    plan = load_model(Path(state["replicate_plan_path"]), ReplicationPlan)
    replication_log = load_model(replication_log_path, ReplicationLog)
    validate_replication_log(plan, replication_log)
    load_model(evidence_summary_path, EvidenceSummary)
    managed_artifacts = {
        replication_log_path.resolve(),
        evidence_summary_path.resolve(),
    }
    for outcome in replication_log.step_outcomes:
        for output_file in outcome.output_files:
            resolved = resolve_replication_output(
                output_file,
                Path(state["codebase_dir"]),
                replication_dir,
            )
            if resolved in managed_artifacts:
                raise RuntimeError(
                    f"Replication step {outcome.step_id} cannot cite a managed log "
                    f"as its output: {output_file}"
                )

    outputs = [str(replication_log_path), str(evidence_summary_path)]
    if config.smart_replicate:
        experiments = load_model(Path(state["experiments_path"]), ExperimentTodo)
        claims = load_model(Path(state["claims_path"]), ClaimsFile)
        claims_by_id = {claim.claim_id: claim for claim in claims.claims}
        for experiment in experiments.experiments:
            smart_log_path = (
                replication_dir / experiment.experiment_id / "smart_replicate_log.json"
            )
            smart_log = load_model(smart_log_path, SmartReplicateLog)
            validate_smart_replicate_log(
                experiment,
                smart_log,
                {
                    claim_id: claims_by_id[claim_id].paper_result
                    for claim_id in experiment.claims
                },
            )
            outputs.append(str(smart_log_path))
    return outputs


def validate_report_experiment(
    report_text: str,
    claims: ClaimsFile,
    experiment: Experiment,
    codegen_plan: CodegenPlan,
) -> None:
    claim_ids = set(experiment.claims)
    validate_reproduction_report(
        report_text,
        ClaimsFile(claims=[claim for claim in claims.claims if claim.claim_id in claim_ids]),
        ExperimentTodo(experiments=[experiment]),
        codegen_plan,
    )


def preflight_node(state: WorkflowState) -> dict[str, str]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    resources_path = config.output / "preflight" / "resources.json"
    dataset_patch_path = config.output / "system_maintenance" / "dataset" / "patch.json"
    if pipeline_state.is_stage_completed("preflight"):
        try:
            resources = json.loads(resources_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Completed preflight artifact is invalid: {resources_path}") from exc
        if not isinstance(resources, dict) or not isinstance(resources.get("gpus"), list):
            raise RuntimeError(f"Completed preflight artifact is invalid: {resources_path}")
        load_model(dataset_patch_path, DatasetPatchFile)
        print("resume preflight stage: skipped (already completed)")
        return {"resources_path": str(resources_path)}

    print("enter preflight stage")
    config.validate()
    pipeline_state.start_stage("preflight")
    for name in (
        "preflight",
        "preprocessing",
        "codegen",
        "plan",
        "replication",
        "report",
        "prompts",
        "remote_compute",
        "system_maintenance/dataset",
    ):
        (config.output / name).mkdir(parents=True, exist_ok=True)
    write_json(resources_path, detect_resources(config.output))
    write_json(dataset_patch_path, [])
    pipeline_state.complete_stage(
        "preflight",
        [str(resources_path), str(dataset_patch_path)],
    )
    return {"resources_path": str(resources_path)}


def preprocess_pdf_node(state: WorkflowState) -> dict[str, str]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    paper_markdown = config.output / "preprocessing" / "paper.md"
    artifacts_dir = config.output / "preprocessing" / "artifacts"
    if pipeline_state.is_stage_completed("preprocess_pdf"):
        if not paper_markdown.is_file() or not paper_markdown.read_text(
            encoding="utf-8"
        ).strip():
            raise RuntimeError(f"Completed PDF artifact is missing or empty: {paper_markdown}")
        if not artifacts_dir.is_dir():
            raise RuntimeError(f"Completed PDF artifact directory is missing: {artifacts_dir}")
        print("resume preprocess_pdf stage: skipped (already completed)")
        return {"paper_markdown": str(paper_markdown)}

    print("enter preprocessing stage")
    pipeline_state.start_stage("preprocess_pdf")
    paper_markdown = convert_pdf_to_markdown(
        config.paper,
        config.output / "preprocessing",
    )
    pipeline_state.complete_stage(
        "preprocess_pdf",
        [
            str(paper_markdown),
            str(artifacts_dir),
        ],
    )
    return {"paper_markdown": str(paper_markdown)}


def preprocessing_agent_node(state: WorkflowState) -> dict[str, str]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    claims_path = config.output / "preprocessing" / "claims.json"
    experiments_path = config.output / "preprocessing" / "experiment_todo.json"
    transcript_path = (
        config.output / "preprocessing" / "preprocessing_transcript.jsonl"
    )
    if pipeline_state.is_stage_completed("preprocessing_agent"):
        claims = load_model(claims_path, ClaimsFile)
        experiments = load_model(experiments_path, ExperimentTodo)
        validate_experiment_coverage(claims, experiments)
        if not transcript_path.is_file():
            raise RuntimeError(f"Completed preprocessing transcript is missing: {transcript_path}")
        print("resume preprocessing_agent stage: skipped (already completed)")
        return {
            "claims_path": str(claims_path),
            "experiments_path": str(experiments_path),
        }

    print("enter preprocessing agent stage")
    pipeline_state.start_stage("preprocessing_agent")
    prompt_path = render_prompt(
        "preprocessing/session_instructions.md",
        config.output / "prompts" / "preprocessing.md",
        paper_markdown=state["paper_markdown"],
        artifacts_dir=config.output / "preprocessing" / "artifacts",
        skills_dir=skills_dir(),
        claims_path=claims_path,
        experiments_path=experiments_path,
    )
    run_agent(
        provider=config.provider,
        prompt_path=prompt_path,
        working_dir=config.output / "preprocessing",
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )
    claims = load_model(claims_path, ClaimsFile)
    experiments = load_model(experiments_path, ExperimentTodo)
    validate_experiment_coverage(claims, experiments)
    pipeline_state.complete_stage(
        "preprocessing_agent",
        [str(claims_path), str(experiments_path), str(transcript_path)],
    )
    return {
        "claims_path": str(claims_path),
        "experiments_path": str(experiments_path),
    }


def codegen_agent_node(state: WorkflowState) -> dict[str, str]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    previous_status = pipeline_state.get_stage_status("codegen_agent")
    codebase_dir = config.output / "codegen" / "codebase"
    previous_stage = pipeline_state.state["stages"].get("codegen_agent", {})
    source_prepared = pipeline_state.get_stage_checkpoints("codegen_agent").get(
        "source_prepared", False
    ) or (
        previous_status in {"running", "failed"}
        and "checkpoints" not in previous_stage
        and codebase_dir.is_dir()
        and any(codebase_dir.iterdir())
    )
    codegen_plan_path = codebase_dir / "codegen_plan.json"
    data_inventory_path = codebase_dir / "data_inventory.json"
    transcript_path = config.output / "codegen" / "codegen_transcript.jsonl"
    computation_provider_state_path = config.output / "remote_compute" / "instance.json"
    dataset_patch_path = (
        config.output / "system_maintenance" / "dataset" / "patch.json"
    )
    if pipeline_state.is_stage_completed("codegen_agent"):
        if not codebase_dir.is_dir():
            raise RuntimeError(f"Completed codebase directory is missing: {codebase_dir}")
        inventory = load_model(data_inventory_path, DataInventory)
        validate_data_inventory(config.data, inventory)
        load_model(codegen_plan_path, CodegenPlan)
        load_model(dataset_patch_path, DatasetPatchFile)
        if not transcript_path.is_file():
            raise RuntimeError(f"Completed codegen transcript is missing: {transcript_path}")
        print("resume codegen_agent stage: skipped (already completed)")
        return {"codebase_dir": str(codebase_dir)}

    print("enter codegen stage")
    pipeline_state.start_stage("codegen_agent")
    if not source_prepared or not codebase_dir.is_dir():
        if (
            previous_status is None
            and codebase_dir.is_dir()
            and any(codebase_dir.iterdir())
        ):
            raise RuntimeError(f"Codebase output is not empty: {codebase_dir}")
        if config.repo is not None:
            shutil.copytree(
                config.repo,
                codebase_dir,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".venv",
                    "__pycache__",
                    ".pytest_cache",
                    ".ruff_cache",
                    "runs",
                    "replicate",
                ),
            )
        else:
            codebase_dir.mkdir(parents=True, exist_ok=True)
        pipeline_state.update_stage_checkpoints(
            "codegen_agent",
            {"source_prepared": True},
        )

    resources = json.loads(Path(state["resources_path"]).read_text(encoding="utf-8"))
    computation_provider = (
        "AutoDL"
        if os.environ.get("AUTODL_TOKEN") and os.environ.get("AUTODL_IMAGE_UUID")
        else None
    )
    prompt_path = render_prompt(
        "codegen/session_instructions.md",
        config.output / "prompts" / "codegen.md",
        codebase_dir=codebase_dir,
        paper_markdown=state["paper_markdown"],
        claims_path=state["claims_path"],
        experiments_path=state["experiments_path"],
        data_dir=config.data,
        skills_dir=skills_dir(),
        data_inventory_path=data_inventory_path,
        codegen_plan_path=codegen_plan_path,
        dataset_patch_path=dataset_patch_path,
        computation_provider_state_path=computation_provider_state_path,
        gpu_info=resources["gpus"],
        computation_provider=computation_provider,
        resuming=previous_status in {"running", "failed"},
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
    inventory = load_model(data_inventory_path, DataInventory)
    validate_data_inventory(config.data, inventory)
    load_model(codegen_plan_path, CodegenPlan)
    load_model(dataset_patch_path, DatasetPatchFile)
    pipeline_state.complete_stage(
        "codegen_agent",
        [
            str(codebase_dir),
            str(data_inventory_path),
            str(codegen_plan_path),
            str(dataset_patch_path),
            str(transcript_path),
        ],
    )
    return {"codebase_dir": str(codebase_dir)}


def plan_agent_node(state: WorkflowState) -> dict[str, str]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    replicate_plan_path = config.output / "plan" / "replicate_plan.json"
    transcript_path = config.output / "plan" / "plan_transcript.jsonl"
    claims = load_model(Path(state["claims_path"]), ClaimsFile)
    experiments = load_model(Path(state["experiments_path"]), ExperimentTodo)
    if pipeline_state.is_stage_completed("plan_agent"):
        plan = load_model(replicate_plan_path, ReplicationPlan)
        validate_replication_plan(experiments, plan)
        if not transcript_path.is_file():
            raise RuntimeError(f"Completed plan transcript is missing: {transcript_path}")
        print("resume plan_agent stage: skipped (already completed)")
        return {"replicate_plan_path": str(replicate_plan_path)}

    print("enter plan stage")
    pipeline_state.start_stage("plan_agent")
    resources = json.loads(Path(state["resources_path"]).read_text(encoding="utf-8"))
    prompt_path = render_prompt(
        "plan/session_instructions.md",
        config.output / "prompts" / "plan.md",
        codebase_dir=state["codebase_dir"],
        paper_markdown=state["paper_markdown"],
        data_dir=config.data,
        claims_path=state["claims_path"],
        experiments_path=state["experiments_path"],
        skills_dir=skills_dir(),
        computation_provider_state_path=(
            config.output / "remote_compute" / "instance.json"
        ),
        replicate_plan_path=replicate_plan_path,
        claims=claims.model_dump(mode="json"),
        experiments=experiments.model_dump(mode="json"),
        gpu_info=resources["gpus"],
    )
    run_agent(
        provider=config.provider,
        prompt_path=prompt_path,
        working_dir=Path(state["codebase_dir"]),
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )
    plan = load_model(replicate_plan_path, ReplicationPlan)
    validate_replication_plan(experiments, plan)
    pipeline_state.complete_stage(
        "plan_agent",
        [str(replicate_plan_path), str(transcript_path)],
    )
    return {"replicate_plan_path": str(replicate_plan_path)}


def replicate_agent_node(state: WorkflowState) -> dict[str, Any]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    transcript_path = config.output / "replication" / "replication_transcript.jsonl"
    if pipeline_state.is_stage_completed("replicate_agent"):
        validate_replication_artifacts(state)
        if not transcript_path.is_file():
            raise RuntimeError(f"Completed replication transcript is missing: {transcript_path}")
        print("resume replicate_agent stage: skipped (already completed)")
        return {}

    print("enter replicate stage")
    pipeline_state.start_stage("replicate_agent")
    experiments = load_model(Path(state["experiments_path"]), ExperimentTodo)
    claims = load_model(Path(state["claims_path"]), ClaimsFile)
    claims_by_id = {claim.claim_id: claim for claim in claims.claims}
    prompt_path = render_prompt(
        "replication/session_instructions.md",
        config.output / "prompts" / "replicate.md",
        replicate_plan_path=state["replicate_plan_path"],
        codebase_dir=state["codebase_dir"],
        replication_dir=config.output / "replication",
        skills_dir=skills_dir(),
        computation_provider_state_path=(
            config.output / "remote_compute" / "instance.json"
        ),
        smart=config.smart_replicate,
        smart_anchors=json.dumps(
            [
                {
                    "claim_id": claim_id,
                    "statement": claims_by_id[claim_id].statement,
                    "anchor": claims_by_id[claim_id].paper_result,
                    "provenance": claims_by_id[claim_id].provenance.model_dump(),
                }
                for experiment in experiments.experiments
                for claim_id in experiment.claims
            ],
            ensure_ascii=False,
            indent=2,
        ),
    )
    run_agent(
        provider=config.provider,
        prompt_path=prompt_path,
        working_dir=Path(state["codebase_dir"]),
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )

    outputs = validate_replication_artifacts(state)
    pipeline_state.complete_stage(
        "replicate_agent",
        [*outputs, str(transcript_path)],
    )
    return {}


def report_agents_node(state: WorkflowState) -> dict[str, str]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    experiments = load_model(Path(state["experiments_path"]), ExperimentTodo)
    claims = load_model(Path(state["claims_path"]), ClaimsFile)
    codegen_plan_path = Path(state["codebase_dir"]) / "codegen_plan.json"
    codegen_plan = load_model(codegen_plan_path, CodegenPlan)
    report_path = config.output / "report" / "reproduction_report.md"
    if pipeline_state.is_stage_completed("report_agents"):
        if not report_path.is_file():
            raise RuntimeError(f"Completed reproduction report is missing: {report_path}")
        validate_reproduction_report(
            report_path.read_text(encoding="utf-8"),
            claims,
            experiments,
            codegen_plan,
        )
        for experiment in experiments.experiments:
            transcript_path = (
                config.output / "report" / f"{experiment.experiment_id}_transcript.jsonl"
            )
            if not transcript_path.is_file():
                raise RuntimeError(f"Completed report transcript is missing: {transcript_path}")
        pipeline_state.mark_completed()
        print("resume report_agents stage: skipped (already completed)")
        return {"report_path": str(report_path)}

    print("enter report stage")
    pipeline_state.start_stage("report_agents")
    completed_experiments = set(
        pipeline_state.get_stage_checkpoints("report_agents").get(
            "completed_experiments", []
        )
    )
    transcript_paths = []
    for experiment in experiments.experiments:
        experiment_payload = experiment.model_dump(mode="json")
        transcript_path = (
            config.output
            / "report"
            / f"{experiment.experiment_id}_transcript.jsonl"
        )
        transcript_paths.append(str(transcript_path))
        if experiment.experiment_id in completed_experiments:
            try:
                if not transcript_path.is_file():
                    raise RuntimeError(
                        f"Checkpointed report transcript is missing: {transcript_path}"
                    )
                validate_report_experiment(
                    report_path.read_text(encoding="utf-8"),
                    claims,
                    experiment,
                    codegen_plan,
                )
            except (OSError, RuntimeError, ValueError):
                completed_experiments.remove(experiment.experiment_id)
                pipeline_state.update_stage_checkpoints(
                    "report_agents",
                    {
                        "completed_experiments": [
                            item.experiment_id
                            for item in experiments.experiments
                            if item.experiment_id in completed_experiments
                        ]
                    },
                )
                print(
                    f"resume report experiment {experiment.experiment_id}: "
                    "checkpoint invalid; rerunning"
                )
            else:
                print(
                    f"resume report experiment {experiment.experiment_id}: "
                    "skipped (already completed)"
                )
                continue
        prompt_path = render_prompt(
            "report/session_instructions.md",
            config.output / "prompts" / f"report_{experiment.experiment_id}.md",
            report_path=report_path,
            experiment_id=experiment.experiment_id,
            claims_path=state["claims_path"],
            paper_markdown=state["paper_markdown"],
            paper_artifacts=config.output / "preprocessing" / "artifacts",
            experiments_path=state["experiments_path"],
            replicate_plan_path=state["replicate_plan_path"],
            codebase_dir=state["codebase_dir"],
            replication_dir=config.output / "replication",
            replication_log_path=(
                config.output / "replication" / "replication_log.json"
            ),
            evidence_summary_path=(
                config.output / "replication" / "evidence_summary.json"
            ),
            experiment_json=json.dumps(experiment_payload, ensure_ascii=False, indent=2),
            codegen_plan_path=codegen_plan_path,
            ambiguities_json=json.dumps(
                [ambiguity.model_dump(mode="json") for ambiguity in codegen_plan.ambiguities],
                ensure_ascii=False,
                indent=2,
            ),
        )
        run_agent(
            provider=config.provider,
            prompt_path=prompt_path,
            working_dir=config.output,
            transcript_path=transcript_path,
            siliconflow_config_path=config.siliconflow_config,
            codex_model=config.codex_model,
            codex_reasoning_effort=config.codex_reasoning_effort,
        )
        if not report_path.is_file() or not report_path.read_text(encoding="utf-8").strip():
            raise RuntimeError(f"Report agent did not write the shared report: {report_path}")
        validate_report_experiment(
            report_path.read_text(encoding="utf-8"),
            claims,
            experiment,
            codegen_plan,
        )
        completed_experiments.add(experiment.experiment_id)
        pipeline_state.update_stage_checkpoints(
            "report_agents",
            {
                "completed_experiments": [
                    item.experiment_id
                    for item in experiments.experiments
                    if item.experiment_id in completed_experiments
                ]
            },
        )
    report_text = report_path.read_text(encoding="utf-8")
    validate_reproduction_report(report_text, claims, experiments, codegen_plan)
    pipeline_state.complete_stage(
        "report_agents",
        [str(report_path), *transcript_paths],
    )
    pipeline_state.mark_completed()
    return {"report_path": str(report_path)}


def create_workflow():
    builder = StateGraph(WorkflowState)
    builder.add_node("preflight", preflight_node)
    builder.add_node("preprocess_pdf", preprocess_pdf_node)
    builder.add_node("preprocessing_agent", preprocessing_agent_node)
    builder.add_node("codegen_agent", codegen_agent_node)
    builder.add_node("plan_agent", plan_agent_node)
    builder.add_node("replicate_agent", replicate_agent_node)
    builder.add_node("report_agents", report_agents_node)
    builder.add_edge(START, "preflight")
    builder.add_edge("preflight", "preprocess_pdf")
    builder.add_edge("preprocess_pdf", "preprocessing_agent")
    builder.add_edge("preprocessing_agent", "codegen_agent")
    builder.add_edge("codegen_agent", "plan_agent")
    builder.add_edge("plan_agent", "replicate_agent")
    builder.add_edge("replicate_agent", "report_agents")
    builder.add_edge("report_agents", END)
    return builder.compile()


def release_run_computation_instance(config: RunConfig) -> None:
    state_path = config.output / "remote_compute" / "instance.json"
    if not state_path.is_file():
        return
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not state.get("created_by_run") or state.get("released"):
        return
    provider = state.get("provider")
    if provider != "autodl":
        raise RuntimeError(f"Unsupported computation provider in state: {provider}")
    script = skills_dir() / "computation_provider" / "scripts" / f"{provider}.py"
    completed = subprocess.run(
        [sys.executable, str(script), "release", "--state", str(state_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Could not release {provider} instance: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
