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
    ExperimentResult,
    ExperimentTodo,
    ReplicationPlan,
    validate_data_inventory,
    validate_experiment_coverage,
    validate_experiment_result,
    validate_replication_plan,
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


def preflight_node(state: WorkflowState) -> dict[str, str]:
    print("enter preflight stage")
    config = state["config"]
    config.validate()
    record_stage(config.output, "preflight", "running")
    for name in (
        "preflight",
        "preprocessing",
        "codegen",
        "audit",
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
    autodl_state_path = config.output / "remote_compute" / "autodl_instance.json"
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
        resources_path=state["resources_path"],
        data_inventory_path=data_inventory_path,
        codegen_plan_path=codegen_plan_path,
        dataset_patch_path=dataset_patch_path,
        autodl_state_path=autodl_state_path,
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


def audit_agent_node(state: WorkflowState) -> dict[str, str]:
    print("enter codegen audit stage")
    config = state["config"]
    record_stage(config.output, "audit_agent", "running")
    replicate_plan_path = config.output / "audit" / "replicate_plan.json"
    transcript_path = config.output / "audit" / "audit_transcript.jsonl"
    prompt_path = render_prompt(
        "audit/session_instructions.md",
        config.output / "prompts" / "audit.md",
        codebase_dir=state["codebase_dir"],
        claims_path=state["claims_path"],
        experiments_path=state["experiments_path"],
        resources_path=state["resources_path"],
        skills_dir=skills_dir(),
        autodl_state_path=config.output / "remote_compute" / "autodl_instance.json",
        replicate_plan_path=replicate_plan_path,
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
    experiments = load_model(Path(state["experiments_path"]), ExperimentTodo)
    plan = load_model(replicate_plan_path, ReplicationPlan)
    validate_replication_plan(experiments, plan)
    record_stage(
        config.output,
        "audit_agent",
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
    mappings = [
        {
            "experiment_id": experiment.experiment_id,
            "description": experiment.description,
            "claims": experiment.claims,
            "artifacts": experiment.artifacts,
        }
        for experiment in experiments.experiments
    ]
    prompt_path = render_prompt(
        "replication/session_instructions.md",
        config.output / "prompts" / "replicate.md",
        replicate_plan_path=state["replicate_plan_path"],
        codebase_dir=state["codebase_dir"],
        replication_dir=config.output / "replication",
        experiment_mappings=json.dumps(mappings, ensure_ascii=False, indent=2),
        skills_dir=skills_dir(),
        autodl_state_path=config.output / "remote_compute" / "autodl_instance.json",
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

    result_paths = []
    for experiment in experiments.experiments:
        result_path = (
            config.output
            / "replication"
            / experiment.experiment_id
            / "result.json"
        )
        result = load_model(result_path, ExperimentResult)
        validate_experiment_result(experiment, result)
        for claim in result.claims:
            for evidence in claim.evidence:
                candidates = [
                    Path(evidence),
                    Path(state["codebase_dir"]) / evidence,
                    config.output / evidence,
                ]
                if not any(candidate.exists() for candidate in candidates):
                    raise RuntimeError(
                        f"Claim evidence does not exist for {claim.claim_id}: {evidence}"
                    )
        for artifact in result.artifacts:
            candidates = [
                Path(artifact.path),
                Path(state["codebase_dir"]) / artifact.path,
                config.output / artifact.path,
            ]
            if not any(candidate.exists() for candidate in candidates):
                raise RuntimeError(
                    f"Artifact evidence does not exist for {artifact.artifact_id}: {artifact.path}"
                )
        result_paths.append(str(result_path))

    record_stage(
        config.output,
        "replicate_agent",
        "completed",
        outputs=[*result_paths, str(transcript_path)],
    )
    return {}


def report_agents_node(state: WorkflowState) -> dict[str, str]:
    print("enter report stage")
    config = state["config"]
    record_stage(config.output, "report_agents", "running")
    experiments = load_model(Path(state["experiments_path"]), ExperimentTodo)
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
            experiment_json=json.dumps(experiment_payload, ensure_ascii=False, indent=2),
            result_path=(
                config.output
                / "replication"
                / experiment.experiment_id
                / "result.json"
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
    missing_experiments = [
        experiment.experiment_id
        for experiment in experiments.experiments
        if experiment.experiment_id not in report_text
    ]
    if missing_experiments:
        raise RuntimeError(
            f"Shared report is missing experiments: {missing_experiments}"
        )
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
    builder.add_node("audit_agent", audit_agent_node)
    builder.add_node("replicate_agent", replicate_agent_node)
    builder.add_node("report_agents", report_agents_node)
    builder.add_edge(START, "preflight")
    builder.add_edge("preflight", "preprocess_pdf")
    builder.add_edge("preprocess_pdf", "preprocessing_agent")
    builder.add_edge("preprocessing_agent", "codegen_agent")
    builder.add_edge("codegen_agent", "audit_agent")
    builder.add_edge("audit_agent", "replicate_agent")
    builder.add_edge("replicate_agent", "report_agents")
    builder.add_edge("report_agents", END)
    return builder.compile()


def release_run_autodl_instance(config: RunConfig) -> None:
    state_path = config.output / "remote_compute" / "autodl_instance.json"
    if not state_path.is_file():
        return
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not state.get("created_by_run") or state.get("released"):
        return
    script = skills_dir() / "computation_provider" / "scripts" / "autodl.py"
    completed = subprocess.run(
        [sys.executable, str(script), "release", "--state", str(state_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Could not release AutoDL instance: {(completed.stderr or completed.stdout).strip()}"
        )
