from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from medai.artifacts import (
    complete_manifest,
    load_model,
    record_stage,
    write_json,
)
from medai.config import RunConfig
from medai.models import (
    ClaimsFile,
    CodegenPlan,
    DataInventory,
    DatasetPatchFile,
    EvidenceSummary,
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


def preflight_node(state: WorkflowState) -> dict[str, str]:
    print("enter preflight stage")
    config = state["config"]
    config.validate()
    record_stage(config.output, "preflight", "running")
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
    resources_path = config.output / "preflight" / "resources.json"
    dataset_patch_path = (
        config.output / "system_maintenance" / "dataset" / "patch.json"
    )
    write_json(resources_path, detect_resources(config.output))
    write_json(dataset_patch_path, [])
    record_stage(config.output, "preflight", "completed", outputs=[str(resources_path)])
    return {"resources_path": str(resources_path)}


def preprocess_pdf_node(state: WorkflowState) -> dict[str, str]:
    print("enter preprocessing stage")
    config = state["config"]
    record_stage(config.output, "preprocess_pdf", "running")
    paper_markdown = convert_pdf_to_markdown(
        config.paper,
        config.output / "preprocessing",
    )
    record_stage(
        config.output,
        "preprocess_pdf",
        "completed",
        outputs=[
            str(paper_markdown),
            str(config.output / "preprocessing" / "artifacts"),
        ],
    )
    return {"paper_markdown": str(paper_markdown)}


def preprocessing_agent_node(state: WorkflowState) -> dict[str, str]:
    print("enter preprocessing agent stage")
    config = state["config"]
    record_stage(config.output, "preprocessing_agent", "running")
    claims_path = config.output / "preprocessing" / "claims.json"
    experiments_path = config.output / "preprocessing" / "experiment_todo.json"
    transcript_path = (
        config.output / "preprocessing" / "preprocessing_transcript.jsonl"
    )
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
    record_stage(
        config.output,
        "preprocessing_agent",
        "completed",
        outputs=[str(claims_path), str(experiments_path), str(transcript_path)],
    )
    return {
        "claims_path": str(claims_path),
        "experiments_path": str(experiments_path),
    }


def codegen_agent_node(state: WorkflowState) -> dict[str, str]:
    print("enter codegen stage")
    config = state["config"]
    record_stage(config.output, "codegen_agent", "running")
    codebase_dir = config.output / "codegen" / "codebase"
    if codebase_dir.exists() and any(codebase_dir.iterdir()):
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

    codegen_plan_path = codebase_dir / "codegen_plan.json"
    data_inventory_path = codebase_dir / "data_inventory.json"
    transcript_path = config.output / "codegen" / "codegen_transcript.jsonl"
    computation_provider_state_path = config.output / "remote_compute" / "instance.json"
    dataset_patch_path = (
        config.output / "system_maintenance" / "dataset" / "patch.json"
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
    record_stage(
        config.output,
        "codegen_agent",
        "completed",
        outputs=[
            str(codebase_dir),
            str(data_inventory_path),
            str(codegen_plan_path),
            str(dataset_patch_path),
            str(transcript_path),
        ],
    )
    return {"codebase_dir": str(codebase_dir)}


def plan_agent_node(state: WorkflowState) -> dict[str, str]:
    print("enter plan stage")
    config = state["config"]
    record_stage(config.output, "plan_agent", "running")
    replicate_plan_path = config.output / "plan" / "replicate_plan.json"
    transcript_path = config.output / "plan" / "plan_transcript.jsonl"
    claims = load_model(Path(state["claims_path"]), ClaimsFile)
    experiments = load_model(Path(state["experiments_path"]), ExperimentTodo)
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
    record_stage(
        config.output,
        "plan_agent",
        "completed",
        outputs=[str(replicate_plan_path), str(transcript_path)],
    )
    return {"replicate_plan_path": str(replicate_plan_path)}


def replicate_agent_node(state: WorkflowState) -> dict[str, Any]:
    print("enter replicate stage")
    config = state["config"]
    record_stage(config.output, "replicate_agent", "running")
    transcript_path = config.output / "replication" / "replication_transcript.jsonl"
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

    smart_log_paths = []
    if config.smart_replicate:
        for experiment in experiments.experiments:
            smart_log_path = (
                replication_dir
                / experiment.experiment_id
                / "smart_replicate_log.json"
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
            smart_log_paths.append(str(smart_log_path))

    record_stage(
        config.output,
        "replicate_agent",
        "completed",
        outputs=[
            str(replication_log_path),
            str(evidence_summary_path),
            *smart_log_paths,
            str(transcript_path),
        ],
    )
    return {}


def report_agents_node(state: WorkflowState) -> dict[str, str]:
    print("enter report stage")
    config = state["config"]
    record_stage(config.output, "report_agents", "running")
    experiments = load_model(Path(state["experiments_path"]), ExperimentTodo)
    claims = load_model(Path(state["claims_path"]), ClaimsFile)
    codegen_plan_path = Path(state["codebase_dir"]) / "codegen_plan.json"
    codegen_plan = load_model(codegen_plan_path, CodegenPlan)
    report_path = config.output / "report" / "reproduction_report.md"
    transcript_paths = []
    for experiment in experiments.experiments:
        experiment_payload = experiment.model_dump(mode="json")
        transcript_path = (
            config.output
            / "report"
            / f"{experiment.experiment_id}_transcript.jsonl"
        )
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
        transcript_paths.append(str(transcript_path))
    report_text = report_path.read_text(encoding="utf-8")
    validate_reproduction_report(report_text, claims, experiments, codegen_plan)
    record_stage(
        config.output,
        "report_agents",
        "completed",
        outputs=[str(report_path), *transcript_paths],
    )
    complete_manifest(config.output)
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
