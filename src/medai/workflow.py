from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from medai.artifacts import load_model, write_json
from medai.computation_providers import get_provider_adapter
from medai.computation_providers import skills_dir as _skills_dir
from medai.config import AutoResearchConfig, RunConfig
from medai.models import (
    ClaimsFile,
    CodegenPlan,
    DatasetPatchFile,
    EvidenceSummary,
    Experiment,
    ExperimentTodo,
    ReplicationCommand,
    ReplicationLog,
    ReplicationPlan,
    SkillCorrectionsFile,
    SmartReplicateLog,
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

MAX_AUDIT_REWRITES = 3


class WorkflowState(TypedDict, total=False):
    config: RunConfig
    paper_markdown: str
    resources_path: str
    claims_path: str
    experiments_path: str
    codebase_dir: str
    audit_verdict: str
    audit_report_path: str
    replicate_plan_path: str
    report_path: str


def skills_dir() -> Path:
    return _skills_dir()


def resolve_replication_output(
    value: str,
    codebase_dir: Path,
    replication_dir: Path,
) -> Path:
    raw_path = Path(value).expanduser()
    if raw_path.is_absolute():
        candidates = [raw_path]
        for marker, destination in (
            (("codegen", "codebase"), codebase_dir),
            (("replication",), replication_dir),
        ):
            for index in range(len(raw_path.parts) - len(marker) + 1):
                if tuple(raw_path.parts[index : index + len(marker)]) == marker:
                    candidates.append(destination.joinpath(*raw_path.parts[index + len(marker) :]))
                    break
    else:
        candidates = [codebase_dir / raw_path, replication_dir / raw_path]
        if raw_path.parts and raw_path.parts[0] == "replication":
            candidates.append(replication_dir.parent / raw_path)

    allowed_roots = [codebase_dir.resolve(), replication_dir.resolve()]
    for candidate in candidates:
        resolved = candidate.resolve()
        if any(resolved.is_relative_to(root) for root in allowed_roots) and (
            resolved.is_file() or resolved.is_dir()
        ):
            return resolved
    raise RuntimeError(
        "Replication output must be a file or directory inside the copied codebase or "
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
            smart_log_path = replication_dir / experiment.experiment_id / "smart_replicate_log.json"
            smart_log = load_model(smart_log_path, SmartReplicateLog)
            validate_smart_replicate_log(
                experiment,
                smart_log,
                {claim_id: claims_by_id[claim_id].paper_result for claim_id in experiment.claims},
            )
            outputs.append(str(smart_log_path))
    return outputs


def _run_replication_command(
    command: str,
    *,
    codebase_dir: Path,
    log_path: Path,
    result_path: Path,
) -> dict[str, Any]:
    """Execute one Codex-requested replication command and retain its combined log."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                ["/bin/bash", "-lc", command],
                cwd=codebase_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
            assert process.stdout is not None
            for line in iter(process.stdout.readline, ""):
                print(line, end="")
                log.write(line)
        exit_code = process.wait()
    except OSError as exc:
        raise RuntimeError(f"Could not execute replication command: {exc}") from exc

    result = {
        "command": command,
        "exit_code": exit_code,
        "duration_seconds": round(time.monotonic() - started, 3),
        "log_path": str(log_path),
        "artifact_validation_error": None,
    }
    write_json(result_path, result)
    return result


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


def read_audit_verdict(report_path: Path) -> str:
    try:
        lines = [
            line.strip()
            for line in report_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except FileNotFoundError as exc:
        raise RuntimeError(f"Audit agent did not write its report: {report_path}") from exc
    verdict_lines = [line for line in lines if line.startswith("Verdict:")]
    if (
        len(verdict_lines) != 1
        or not lines
        or lines[-1]
        not in {
            "Verdict: PASS",
            "Verdict: FAIL",
        }
    ):
        raise RuntimeError(
            "Audit report must contain exactly one verdict and end with "
            f"`Verdict: PASS` or `Verdict: FAIL`: {report_path}"
        )
    return lines[-1].removeprefix("Verdict: ")


def validate_codegen_remote_compute(
    plan: Any,
    state_path: Path,
    *,
    cloud_dataset: str | None = None,
    drive_provider: str | None = None,
    computation_provider: str | None = None,
    require_active: bool = True,
) -> dict[str, Any] | None:
    remote_compute = plan.remote_compute
    if remote_compute is None:
        if cloud_dataset is not None:
            raise RuntimeError("Cloud-drive mode requires a remote-compute plan")
        return
    if Path(remote_compute.state_path).resolve() != state_path.resolve():
        raise RuntimeError(
            "Remote-compute state path does not match the current run: "
            f"{remote_compute.state_path}"
        )
    if cloud_dataset is None:
        return None
    try:
        provider_envelope = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cloud-drive state is missing or invalid: {state_path}") from exc
    provider_state = provider_envelope.get("provider_state")
    cloud_drive = provider_state.get("cloud_drive") if isinstance(provider_state, dict) else None
    provider = provider_envelope.get("provider")
    if not isinstance(provider, str) or not provider or not isinstance(cloud_drive, dict):
        raise RuntimeError("Cloud-drive mode requires completed provider state")
    if computation_provider is not None and provider != computation_provider:
        raise RuntimeError("Cloud-drive state provider does not match the run configuration")
    if require_active and provider_envelope.get("released") is True:
        raise RuntimeError("Cloud-drive instance was already released")
    if (
        cloud_drive.get("completed") is not True
        or cloud_drive.get("drive") != drive_provider
        or cloud_drive.get("dataset") != cloud_dataset
    ):
        raise RuntimeError("Cloud-drive materialization is incomplete or inconsistent")
    target_path = cloud_drive.get("target_path")
    if not isinstance(target_path, str) or not target_path:
        raise RuntimeError("Cloud-drive state is missing its materialized target path")
    if remote_compute.remote_dataset_dir != target_path:
        raise RuntimeError("Remote plan dataset path does not match completed cloud-drive state")
    return cloud_drive


def _load_computation_provider_state(state_path: Path) -> dict[str, Any]:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Remote computation state is missing: {state_path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Remote computation state is unreadable or invalid: {state_path}"
        ) from exc
    if not isinstance(state, dict):
        raise RuntimeError(f"Remote computation state is not a JSON object: {state_path}")
    return state


def _run_computation_provider_action(
    state_path: Path,
    action: str,
    *,
    arguments: list[str] | None = None,
    expected_provider: str | None = None,
) -> str:
    state = _load_computation_provider_state(state_path)
    provider = state.get("provider")
    if not isinstance(provider, str):
        raise RuntimeError("Remote computation state is missing its provider")
    if expected_provider is not None and provider != expected_provider:
        raise RuntimeError("Remote computation state provider does not match the run configuration")
    try:
        adapter = get_provider_adapter(provider)
    except ValueError as exc:
        raise RuntimeError(f"Unsupported computation provider in state: {provider}") from exc
    if action not in adapter.action_timeouts:
        raise RuntimeError(f"Computation provider does not support action: {action}")
    completed = subprocess.run(
        [
            sys.executable,
            str(adapter.script),
            action,
            "--state",
            str(state_path),
            *(arguments or []),
        ],
        capture_output=True,
        text=True,
        timeout=adapter.action_timeouts[action],
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Could not {action} {provider} instance: {detail}")
    return completed.stdout.strip()


def reconcile_run_computation_instance(config: RunConfig) -> dict[str, Any]:
    state_path = config.output / "remote_compute" / "instance.json"
    output = _run_computation_provider_action(
        state_path,
        "reconcile",
        expected_provider=config.computation_provider,
    )
    try:
        result = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Computation-provider reconcile returned invalid JSON") from exc
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("replaced"), bool)
        or result.get("status") != "running"
    ):
        raise RuntimeError("Computation-provider reconcile returned an invalid result")
    return result


def power_off_run_computation_instance(config: RunConfig) -> None:
    state_path = config.output / "remote_compute" / "instance.json"
    if not state_path.is_file():
        return
    state = _load_computation_provider_state(state_path)
    if not state.get("created_by_run") or state.get("released") is True:
        return
    _run_computation_provider_action(
        state_path,
        "power-off",
        expected_provider=config.computation_provider,
    )


def release_run_computation_instance(config: RunConfig | AutoResearchConfig) -> None:
    state_path = config.output / "remote_compute" / "instance.json"
    if not state_path.is_file():
        return
    state = _load_computation_provider_state(state_path)
    if not state.get("created_by_run") or state.get("released") is True:
        return
    _run_computation_provider_action(
        state_path,
        "release",
        expected_provider=config.computation_provider,
    )


def _cloud_pull(config: RunConfig) -> None:
    if not config.clouddrive:
        return
    if config.cloud_dataset is None:
        raise RuntimeError("Cloud-drive mode is missing its dataset name")
    state_path = config.output / "remote_compute" / "instance.json"
    _run_computation_provider_action(
        state_path,
        "cloud-pull",
        arguments=["--dataset", config.cloud_dataset],
        expected_provider=config.computation_provider,
    )


def _run_has_remote_plan(config: RunConfig) -> bool:
    candidates: tuple[tuple[Path, type[CodegenPlan] | type[ReplicationPlan]], ...] = (
        (config.output / "plan" / "replicate_plan.json", ReplicationPlan),
        (config.output / "codegen" / "codebase" / "codegen_plan.json", CodegenPlan),
    )
    for path, model_type in candidates:
        if path.is_file() and load_model(path, model_type).remote_compute is not None:
            return True
    return False


def _validate_recorded_remote_state(state_path: Path, config: RunConfig) -> None:
    state = _load_computation_provider_state(state_path)
    if not state.get("created_by_run"):
        raise RuntimeError("Remote computation state lacks current-run ownership")
    _run_computation_provider_action(
        state_path,
        "validate-state",
        expected_provider=config.computation_provider,
    )


def _replication_attempt_started(pipeline_state: PipelineState) -> bool:
    stages = pipeline_state.state["stages"]
    return "replicate_agent" in stages or "report_agents" in stages


def _archive_replicate_attempt(config: RunConfig, resume_count: int) -> Path:
    output = config.output
    archive_root = output / "resume_history" / f"resume_{resume_count:03d}"
    temporary_root = archive_root.with_name(f".{archive_root.name}.tmp")
    if archive_root.exists() or temporary_root.exists():
        raise RuntimeError(f"Resume archive target already exists: {archive_root}")

    replication_dir = output / "replication"
    report_dir = output / "report"
    codebase_dir = output / "codegen" / "codebase"
    prompt_paths = [output / "prompts" / "replicate.md"]
    prompt_paths.extend(sorted((output / "prompts").glob("replicate_resume_*.md")))
    prompt_paths.extend(sorted((output / "prompts").glob("replicate_command*.json")))
    prompt_paths.extend(sorted((output / "prompts").glob("report_*.md")))
    prompt_paths = [path for path in prompt_paths if path.is_file()]

    mappings: list[dict[str, str]] = []
    unresolved: list[str] = []
    log_reference_error: str | None = None
    replication_log_path = replication_dir / "replication_log.json"
    if replication_log_path.is_file():
        try:
            payload = json.loads(replication_log_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            payload = {}
            log_reference_error = str(exc)
        outcomes = payload.get("step_outcomes") if isinstance(payload, dict) else None
        if not isinstance(outcomes, list):
            outcomes = []
            log_reference_error = log_reference_error or "step_outcomes is not a list"
        logged_outputs: list[str] = []
        for outcome in outcomes:
            output_files = outcome.get("output_files") if isinstance(outcome, dict) else None
            if not isinstance(output_files, list) or not all(
                isinstance(value, str) for value in output_files
            ):
                log_reference_error = (
                    log_reference_error or "one or more output_files fields are invalid"
                )
                continue
            logged_outputs.extend(output_files)
        codebase_root = codebase_dir.resolve()
        copied: dict[Path, Path] = {}
        for logged_path in logged_outputs:
            try:
                resolved = resolve_replication_output(
                    logged_path,
                    codebase_dir,
                    replication_dir,
                )
            except RuntimeError:
                unresolved.append(logged_path)
                continue
            if not resolved.is_relative_to(codebase_root):
                continue
            relative = resolved.relative_to(codebase_root)
            archived_path = archive_root / "referenced_codebase_outputs" / relative
            if resolved not in copied:
                temporary_path = temporary_root / "referenced_codebase_outputs" / relative
                try:
                    temporary_path.parent.mkdir(parents=True, exist_ok=True)
                    if resolved.is_dir():
                        shutil.copytree(resolved, temporary_path, dirs_exist_ok=True)
                    else:
                        shutil.copy2(resolved, temporary_path)
                except Exception:
                    if temporary_root.is_dir():
                        shutil.rmtree(temporary_root)
                    raise
                copied[resolved] = archived_path
            mappings.append(
                {
                    "logged_path": logged_path,
                    "original_path": str(resolved),
                    "archived_path": str(copied[resolved]),
                }
            )

    try:
        for name, source in (("replication", replication_dir), ("report", report_dir)):
            destination = temporary_root / name
            if source.is_symlink():
                raise RuntimeError(f"Refusing to archive symlinked run directory: {source}")
            if source.exists():
                if not source.is_dir():
                    raise RuntimeError(f"Run artifact path is not a directory: {source}")
                shutil.copytree(source, destination)
            else:
                destination.mkdir(parents=True, exist_ok=True)
        for prompt_path in prompt_paths:
            destination = temporary_root / "prompts" / prompt_path.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(prompt_path, destination)
        write_json(
            temporary_root / "path_mapping.json",
            {
                "resume_count": resume_count,
                "referenced_codebase_outputs": mappings,
                "unresolved_log_outputs": unresolved,
                "log_reference_error": log_reference_error,
            },
        )
        archive_root.parent.mkdir(parents=True, exist_ok=True)
        temporary_root.replace(archive_root)
    except Exception:
        if temporary_root.is_dir():
            shutil.rmtree(temporary_root)
        raise

    for directory in (replication_dir, report_dir):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)
    for prompt_path in prompt_paths:
        prompt_path.unlink()
    return archive_root


def prepare_replication_resume(config: RunConfig) -> dict[str, Any]:
    pipeline_state = PipelineState(config.output)
    state_path = config.output / "remote_compute" / "instance.json"
    report_completed = pipeline_state.is_stage_completed("report_agents")
    remote_plan = (
        _run_has_remote_plan(config) if report_completed or not state_path.is_file() else False
    )
    if report_completed:
        if remote_plan:
            _validate_recorded_remote_state(state_path, config)
        return {"reconciled": False, "replaced": False, "rollback": None}

    replicate_started = _replication_attempt_started(pipeline_state)
    resume_count = int(pipeline_state.state.get("resume_count", 0))
    if replicate_started:
        archive_root = config.output / "resume_history" / f"resume_{resume_count:03d}"
        temporary_root = archive_root.with_name(f".{archive_root.name}.tmp")
        if archive_root.exists() or temporary_root.exists():
            raise RuntimeError(f"Resume archive target already exists: {archive_root}")

    reconciliation: dict[str, Any] = {"reconciled": False, "replaced": False}
    if state_path.is_file():
        _validate_recorded_remote_state(state_path, config)
        reconciliation = {
            "reconciled": True,
            **reconcile_run_computation_instance(config),
        }
    elif remote_plan:
        raise RuntimeError(f"Remote computation state is missing: {state_path}")

    if replicate_started:
        if config.clouddrive and reconciliation["replaced"]:
            _cloud_pull(config)
        archive_root = _archive_replicate_attempt(config, resume_count)
        pipeline_state.invalidate_stages(
            ["replicate_agent", "report_agents"],
            f"Explicit resume restarted replication from its first step: {archive_root}",
        )
        return {**reconciliation, "rollback": "replicate", "archive": str(archive_root)}

    if reconciliation["replaced"]:
        codebase_dir = config.output / "codegen" / "codebase"
        checkpoints = {
            "source_prepared": codebase_dir.is_dir(),
            "infrastructure_resume": True,
        }
        pipeline_state.invalidate_stages(
            [
                "codegen_agent",
                "audit_agent",
                "plan_agent",
                "replicate_agent",
                "report_agents",
            ],
            "Remote computation instance was replaced during explicit resume",
            checkpoint_overrides={"codegen_agent": checkpoints},
        )
        return {**reconciliation, "rollback": "codegen"}

    return {**reconciliation, "rollback": None}


def preflight_node(state: WorkflowState) -> dict[str, str]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    resources_path = config.output / "preflight" / "resources.json"
    dataset_patch_path = config.output / "system_maintenance" / "dataset" / "patch.json"
    skill_corrections_path = config.output / "system_maintenance" / "skills" / "corrections.json"
    if config.data is None and not config.clouddrive:
        print("enter preflight stage")
        pipeline_state.start_stage("preflight")
        raise ValueError("Replicate runs require --data for preprocessing audit")
    if pipeline_state.is_stage_completed("preflight"):
        try:
            resources = json.loads(resources_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Completed preflight artifact is invalid: {resources_path}"
            ) from exc
        if not isinstance(resources, dict) or not isinstance(resources.get("gpus"), list):
            raise RuntimeError(f"Completed preflight artifact is invalid: {resources_path}")
        load_model(dataset_patch_path, DatasetPatchFile)
        if not skill_corrections_path.exists():
            write_json(skill_corrections_path, [])
        load_model(skill_corrections_path, SkillCorrectionsFile)
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
        "system_maintenance/skills",
    ):
        (config.output / name).mkdir(parents=True, exist_ok=True)
    write_json(resources_path, detect_resources(config.output))
    write_json(dataset_patch_path, [])
    write_json(skill_corrections_path, [])
    pipeline_state.complete_stage(
        "preflight",
        [str(resources_path), str(dataset_patch_path), str(skill_corrections_path)],
    )
    return {"resources_path": str(resources_path)}


def preprocess_pdf_node(state: WorkflowState) -> dict[str, str]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    paper_markdown = config.output / "preprocessing" / "paper.md"
    artifacts_dir = config.output / "preprocessing" / "artifacts"
    if pipeline_state.is_stage_completed("preprocess_pdf"):
        if not paper_markdown.is_file() or not paper_markdown.read_text(encoding="utf-8").strip():
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
    paper_markdown = Path(state["paper_markdown"])
    claims_path = config.output / "preprocessing" / "claims.json"
    experiments_path = config.output / "preprocessing" / "experiment_todo.json"
    transcript_path = config.output / "preprocessing" / "preprocessing_transcript.jsonl"
    if pipeline_state.is_stage_completed("preprocessing_agent"):
        if not paper_markdown.is_file() or not paper_markdown.read_text(encoding="utf-8").strip():
            raise RuntimeError(
                f"Completed preprocessing paper artifact is missing or empty: {paper_markdown}"
            )
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
        paper_markdown=paper_markdown,
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
    if not paper_markdown.is_file() or not paper_markdown.read_text(encoding="utf-8").strip():
        raise RuntimeError(
            f"Preprocessing agent left paper artifact missing or empty: {paper_markdown}"
        )
    claims = load_model(claims_path, ClaimsFile)
    experiments = load_model(experiments_path, ExperimentTodo)
    validate_experiment_coverage(claims, experiments)
    pipeline_state.complete_stage(
        "preprocessing_agent",
        [
            str(paper_markdown),
            str(claims_path),
            str(experiments_path),
            str(transcript_path),
        ],
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
    codegen_checkpoints = pipeline_state.get_stage_checkpoints("codegen_agent")
    source_prepared = codegen_checkpoints.get("source_prepared", False) or (
        previous_status in {"running", "failed"}
        and "checkpoints" not in previous_stage
        and codebase_dir.is_dir()
        and any(codebase_dir.iterdir())
    )
    codegen_plan_path = codebase_dir / "codegen_plan.json"
    transcript_path = config.output / "codegen" / "codegen_transcript.jsonl"
    computation_provider_state_path = config.output / "remote_compute" / "instance.json"
    dataset_patch_path = config.output / "system_maintenance" / "dataset" / "patch.json"
    skill_corrections_path = config.output / "system_maintenance" / "skills" / "corrections.json"
    audit_stage = pipeline_state.state["stages"].get("audit_agent", {})
    audit_checkpoints = pipeline_state.get_stage_checkpoints("audit_agent")
    codegen_attempt = int(previous_stage.get("attempts", 0))
    audit_revision = (
        previous_status == "completed"
        and audit_stage.get("status") == "completed"
        and audit_checkpoints.get("verdict") == "FAIL"
        and audit_checkpoints.get("audited_codegen_attempt") == codegen_attempt
    )
    if audit_revision:
        audit_feedback_path = Path(str(audit_checkpoints["report_path"]))
    elif previous_status in {"running", "failed"} and codegen_checkpoints.get(
        "audit_feedback_path"
    ):
        audit_feedback_path = Path(str(codegen_checkpoints["audit_feedback_path"]))
    else:
        audit_feedback_path = None
    if audit_feedback_path is not None and read_audit_verdict(audit_feedback_path) != "FAIL":
        raise RuntimeError(f"Codegen audit feedback is not a FAIL report: {audit_feedback_path}")
    completed_run_validation = pipeline_state.is_stage_completed("report_agents")
    infrastructure_resume = bool(codegen_checkpoints.get("infrastructure_resume"))
    if pipeline_state.is_stage_completed("codegen_agent") and not audit_revision:
        if not codebase_dir.is_dir():
            raise RuntimeError(f"Completed codebase directory is missing: {codebase_dir}")
        codegen_plan = load_model(codegen_plan_path, CodegenPlan)
        validate_codegen_remote_compute(
            codegen_plan,
            computation_provider_state_path,
            cloud_dataset=config.cloud_dataset if config.clouddrive else None,
            drive_provider=config.drive_provider,
            computation_provider=config.computation_provider,
            require_active=not completed_run_validation,
        )
        load_model(dataset_patch_path, DatasetPatchFile)
        load_model(skill_corrections_path, SkillCorrectionsFile)
        if not transcript_path.is_file():
            raise RuntimeError(f"Completed codegen transcript is missing: {transcript_path}")
        print("resume codegen_agent stage: skipped (already completed)")
        return {"codebase_dir": str(codebase_dir)}

    print("enter codegen stage")
    if audit_revision:
        pipeline_state.invalidate_stages(
            ["plan_agent", "replicate_agent", "report_agents"],
            f"Codegen revised after failed preprocessing audit: {audit_feedback_path}",
        )
    pipeline_state.start_stage("codegen_agent")
    if audit_feedback_path is not None:
        pipeline_state.update_stage_checkpoints(
            "codegen_agent",
            {"audit_feedback_path": str(audit_feedback_path)},
        )
    if not source_prepared or not codebase_dir.is_dir():
        if previous_status is None and codebase_dir.is_dir() and any(codebase_dir.iterdir()):
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
    prompt_path = render_prompt(
        "codegen/session_instructions.md",
        config.output / "prompts" / "codegen.md",
        codebase_dir=codebase_dir,
        paper_markdown=state["paper_markdown"],
        claims_path=state["claims_path"],
        experiments_path=state["experiments_path"],
        data_dir=config.data,
        cloud_drive_enabled=config.clouddrive,
        cloud_dataset=config.cloud_dataset,
        drive_provider=config.drive_provider,
        cloud_source=config.cloud_source,
        computation_provider_reference=config.computation_provider_reference,
        drive_reference=config.drive_reference,
        infrastructure_resume=infrastructure_resume,
        skills_dir=skills_dir(),
        codegen_plan_path=codegen_plan_path,
        dataset_patch_path=dataset_patch_path,
        skill_corrections_path=skill_corrections_path,
        computation_provider_state_path=computation_provider_state_path,
        gpu_info=resources["gpus"],
        computation_provider=config.computation_provider,
        resuming=previous_status in {"running", "failed", "invalidated"},
        audit_feedback_path=audit_feedback_path,
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
    codegen_plan = load_model(codegen_plan_path, CodegenPlan)
    validate_codegen_remote_compute(
        codegen_plan,
        computation_provider_state_path,
        cloud_dataset=config.cloud_dataset if config.clouddrive else None,
        drive_provider=config.drive_provider,
        computation_provider=config.computation_provider,
    )
    load_model(dataset_patch_path, DatasetPatchFile)
    load_model(skill_corrections_path, SkillCorrectionsFile)
    pipeline_state.complete_stage(
        "codegen_agent",
        [
            str(codebase_dir),
            str(codegen_plan_path),
            str(dataset_patch_path),
            str(skill_corrections_path),
            str(transcript_path),
        ],
    )
    return {"codebase_dir": str(codebase_dir)}


def audit_agent_node(state: WorkflowState) -> dict[str, str]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    codegen_stage = pipeline_state.state["stages"].get("codegen_agent", {})
    codegen_attempt = int(codegen_stage.get("attempts", 0))
    if codegen_stage.get("status") != "completed" or codegen_attempt < 1:
        raise RuntimeError("Preprocessing audit requires a completed codegen attempt")

    checkpoints = pipeline_state.get_stage_checkpoints("audit_agent")
    audited_codegen_attempt = checkpoints.get("audited_codegen_attempt")
    if (
        pipeline_state.is_stage_completed("audit_agent")
        and audited_codegen_attempt == codegen_attempt
    ):
        report_path = Path(str(checkpoints.get("report_path", "")))
        verdict = read_audit_verdict(report_path)
        if verdict != checkpoints.get("verdict"):
            raise RuntimeError(f"Audit report verdict does not match its checkpoint: {report_path}")
        print("resume audit_agent stage: skipped (already completed)")
        return {
            "audit_verdict": verdict,
            "audit_report_path": str(report_path),
        }

    rewrite_rounds_used = int(checkpoints.get("rewrite_rounds_used", 0))
    if (
        pipeline_state.get_stage_status("audit_agent") == "failed"
        and audited_codegen_attempt == codegen_attempt
        and checkpoints.get("verdict") == "FAIL"
        and rewrite_rounds_used >= MAX_AUDIT_REWRITES
    ):
        raise RuntimeError(
            "Preprocessing audit failed after three codegen rewrite rounds; "
            f"latest report: {checkpoints.get('report_path')}"
        )

    print("enter audit agent stage")
    previous_audit_status = pipeline_state.get_stage_status("audit_agent")
    pipeline_state.start_stage("audit_agent")
    scientific_attempt = rewrite_rounds_used + 1
    attempt_dir = config.output / "codegen" / "audit" / f"attempt_{scientific_attempt:03d}"
    scripts_dir = attempt_dir / "scripts"
    results_dir = attempt_dir / "results"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    report_path = attempt_dir / "audit_report.md"
    transcript_path = attempt_dir / "audit_transcript.jsonl"
    codegen_plan = load_model(Path(state["codebase_dir"]) / "codegen_plan.json", CodegenPlan)
    cloud_drive_state = validate_codegen_remote_compute(
        codegen_plan,
        config.output / "remote_compute" / "instance.json",
        cloud_dataset=config.cloud_dataset if config.clouddrive else None,
        drive_provider=config.drive_provider,
        computation_provider=config.computation_provider,
    )
    remote_working_dir = (
        codegen_plan.remote_compute.remote_working_dir
        if config.clouddrive and codegen_plan.remote_compute is not None
        else None
    )
    remote_audit_dir = (
        f"{remote_working_dir.rstrip('/')}/preprocessing_audit/" f"attempt_{scientific_attempt:03d}"
        if remote_working_dir
        else None
    )
    prompt_path = render_prompt(
        "codegen/audit_session_instructions.md",
        config.output / "prompts" / f"audit_attempt_{scientific_attempt:03d}.md",
        paper_markdown=state["paper_markdown"],
        codegen_plan_path=Path(state["codebase_dir"]) / "codegen_plan.json",
        codebase_dir=state["codebase_dir"],
        data_dir=config.data,
        cloud_drive_enabled=config.clouddrive,
        cloud_dataset=config.cloud_dataset,
        drive_provider=config.drive_provider,
        computation_provider_reference=config.computation_provider_reference,
        drive_reference=config.drive_reference,
        remote_dataset_dir=(cloud_drive_state.get("target_path") if cloud_drive_state else None),
        remote_working_dir=remote_working_dir,
        remote_audit_dir=remote_audit_dir,
        resources_path=state["resources_path"],
        skills_dir=skills_dir(),
        audit_dir=attempt_dir,
        scripts_dir=scripts_dir,
        results_dir=results_dir,
        report_path=report_path,
        codegen_attempt=codegen_attempt,
        remote_compute_state_path=config.output / "remote_compute" / "instance.json",
        remote_compute_active=(config.output / "remote_compute" / "instance.json").is_file(),
        resuming=previous_audit_status in {"running", "failed"},
    )
    run_agent(
        provider=config.provider,
        prompt_path=prompt_path,
        working_dir=attempt_dir,
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )
    verdict = read_audit_verdict(report_path)
    checkpoint = {
        "audited_codegen_attempt": codegen_attempt,
        "verdict": verdict,
        "report_path": str(report_path),
        "rewrite_rounds_used": rewrite_rounds_used,
    }
    outputs = [str(attempt_dir), str(report_path), str(transcript_path)]
    if verdict == "FAIL" and rewrite_rounds_used >= MAX_AUDIT_REWRITES:
        pipeline_state.update_stage_checkpoints("audit_agent", checkpoint)
        error = (
            "Preprocessing audit failed after three codegen rewrite rounds; "
            f"latest report: {report_path}"
        )
        pipeline_state.fail(error, outputs)
        raise RuntimeError(error)
    if verdict == "FAIL":
        checkpoint["rewrite_rounds_used"] = rewrite_rounds_used + 1
    pipeline_state.update_stage_checkpoints("audit_agent", checkpoint)
    pipeline_state.complete_stage("audit_agent", outputs)
    return {
        "audit_verdict": verdict,
        "audit_report_path": str(report_path),
    }


def audit_route(state: WorkflowState) -> str:
    verdict = state.get("audit_verdict")
    if verdict not in {"PASS", "FAIL"}:
        raise RuntimeError(f"Invalid preprocessing audit verdict: {verdict!r}")
    return "plan_agent" if verdict == "PASS" else "codegen_agent"


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
        validate_codegen_remote_compute(
            plan,
            config.output / "remote_compute" / "instance.json",
            cloud_dataset=config.cloud_dataset if config.clouddrive else None,
            drive_provider=config.drive_provider,
            computation_provider=config.computation_provider,
            require_active=not pipeline_state.is_stage_completed("report_agents"),
        )
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
        cloud_drive_enabled=config.clouddrive,
        cloud_dataset=config.cloud_dataset,
        drive_provider=config.drive_provider,
        computation_provider=config.computation_provider,
        computation_provider_reference=config.computation_provider_reference,
        drive_reference=config.drive_reference,
        claims_path=state["claims_path"],
        experiments_path=state["experiments_path"],
        skills_dir=skills_dir(),
        computation_provider_state_path=(config.output / "remote_compute" / "instance.json"),
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
    validate_codegen_remote_compute(
        plan,
        config.output / "remote_compute" / "instance.json",
        cloud_dataset=config.cloud_dataset if config.clouddrive else None,
        drive_provider=config.drive_provider,
        computation_provider=config.computation_provider,
        require_active=not pipeline_state.is_stage_completed("report_agents"),
    )
    pipeline_state.complete_stage(
        "plan_agent",
        [str(replicate_plan_path), str(transcript_path)],
    )
    return {"replicate_plan_path": str(replicate_plan_path)}


def replicate_agent_node(state: WorkflowState) -> dict[str, Any]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    transcript_path = config.output / "replication" / "replication_transcript.jsonl"
    plan = load_model(Path(state["replicate_plan_path"]), ReplicationPlan)
    if not pipeline_state.is_stage_completed("replicate_agent"):
        _cloud_pull(config)
    validate_codegen_remote_compute(
        plan,
        config.output / "remote_compute" / "instance.json",
        cloud_dataset=config.cloud_dataset if config.clouddrive else None,
        drive_provider=config.drive_provider,
        computation_provider=config.computation_provider,
        require_active=not pipeline_state.is_stage_completed("report_agents"),
    )
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
        computation_provider_state_path=(config.output / "remote_compute" / "instance.json"),
        cloud_drive_enabled=config.clouddrive,
        cloud_dataset=config.cloud_dataset,
        drive_provider=config.drive_provider,
        computation_provider=config.computation_provider,
        computation_provider_reference=config.computation_provider_reference,
        drive_reference=config.drive_reference,
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
    if config.provider == "codex":
        command_dir = config.output / "replication" / "commands"
        command_dir.mkdir(parents=True, exist_ok=True)
        command_schema_path = config.output / "prompts" / "replicate_command.schema.json"
        write_json(command_schema_path, ReplicationCommand.model_json_schema())
        session_id: str | None = None
        resume_prompt_path: Path | None = None
        command_index = 1
        while True:
            command_request_path = command_dir / f"command_{command_index:03d}.json"
            if session_id is None:
                session_id = run_agent(
                    provider=config.provider,
                    prompt_path=prompt_path,
                    working_dir=Path(state["codebase_dir"]),
                    transcript_path=transcript_path,
                    siliconflow_config_path=config.siliconflow_config,
                    codex_model=config.codex_model,
                    codex_reasoning_effort=config.codex_reasoning_effort,
                    output_schema_path=command_schema_path,
                    output_last_message_path=command_request_path,
                )
                if session_id is None:
                    raise RuntimeError("Codex replication turn did not return a session ID")
            else:
                assert resume_prompt_path is not None
                run_agent(
                    provider=config.provider,
                    prompt_path=resume_prompt_path,
                    working_dir=Path(state["codebase_dir"]),
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
            result = _run_replication_command(
                command,
                codebase_dir=Path(state["codebase_dir"]),
                log_path=log_path,
                result_path=result_path,
            )
            try:
                outputs = validate_replication_artifacts(state)
            except (RuntimeError, ValueError) as exc:
                result["artifact_validation_error"] = str(exc)
                write_json(result_path, result)
                resume_prompt_path = render_prompt(
                    "replication/command_result_instructions.md",
                    config.output / "prompts" / f"replicate_resume_{command_index:03d}.md",
                    command_result_path=result_path,
                    command_log_path=log_path,
                    exit_code=result["exit_code"],
                    duration_seconds=result["duration_seconds"],
                    artifact_validation_error=result["artifact_validation_error"],
                )
                command_index += 1
                continue
            break
    else:
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
    power_off_run_computation_instance(config)
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
        pipeline_state.get_stage_checkpoints("report_agents").get("completed_experiments", [])
    )
    transcript_paths = []
    for experiment in experiments.experiments:
        experiment_payload = experiment.model_dump(mode="json")
        transcript_path = config.output / "report" / f"{experiment.experiment_id}_transcript.jsonl"
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
            replication_log_path=(config.output / "replication" / "replication_log.json"),
            evidence_summary_path=(config.output / "replication" / "evidence_summary.json"),
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
    builder.add_node("audit_agent", audit_agent_node)
    builder.add_node("plan_agent", plan_agent_node)
    builder.add_node("replicate_agent", replicate_agent_node)
    builder.add_node("report_agents", report_agents_node)
    builder.add_edge(START, "preflight")
    builder.add_edge("preflight", "preprocess_pdf")
    builder.add_edge("preprocess_pdf", "preprocessing_agent")
    builder.add_edge("preprocessing_agent", "codegen_agent")
    builder.add_edge("codegen_agent", "audit_agent")
    builder.add_conditional_edges(
        "audit_agent",
        audit_route,
        {"plan_agent": "plan_agent", "codegen_agent": "codegen_agent"},
    )
    builder.add_edge("plan_agent", "replicate_agent")
    builder.add_edge("replicate_agent", "report_agents")
    builder.add_edge("report_agents", END)
    return builder.compile()
