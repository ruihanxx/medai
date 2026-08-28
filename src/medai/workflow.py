from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from medai.artifacts import load_model, write_json
from medai.computation_providers import get_provider_adapter
from medai.computation_providers import skills_dir as _skills_dir
from medai.config import AutoResearchConfig, RunConfig
from medai.data_availability import derive_graph_execution_scope, sha256_file
from medai.models import (
    AgentStageResult,
    CodegenCloudPullRequest,
    CodegenPlan,
    DatasetPatchFile,
    EvidenceSummary,
    GraphDataAvailabilityReport,
    GraphExecutionScope,
    GraphScopeRevisionIssues,
    PaperGraph,
    PendingNodeUpdate,
    ReplicationLog,
    ReplicationPlan,
    SkillCorrectionsFile,
    SmartReplicateLog,
    replication_topological_layers,
    validate_claim_report,
    validate_replication_log,
    validate_replication_plan,
    validate_smart_replicate_log,
)
from medai.pipeline_state import PipelineState
from medai.preprocessing import convert_pdf_to_markdown
from medai.prompts import render_prompt
from medai.providers import run_agent
from medai.resources import detect_resources
from medai.study_graph import (
    collect_lineage_issues,
    graph_ancestors,
    load_node_state,
    merge_node_updates,
    write_empty_node_state,
)

MAX_COHORT_REFINE_ROUNDS = 3
MAX_AGENT_ARTIFACT_REPAIR_TURNS = 2


class WorkflowState(TypedDict, total=False):
    config: RunConfig
    paper_markdown: str
    resources_path: str
    paper_graph_path: str
    node_state_path: str
    execution_scope_path: str
    codebase_dir: str
    audit_verdict: str
    audit_report_path: str
    audit_issue_kinds: list[str]
    audit_refinement_exhausted: bool
    replicate_plan_path: str
    report_path: str
    scope_revision_requested: bool


class PartialDataAwaitingConfirmation(RuntimeError):
    """The current partial scope needs an explicit user decision."""


class PartialDataStopped(RuntimeError):
    """The user declined the current partial scope."""


class NoRunnableClaims(RuntimeError):
    """No paper claim can run with the confirmed source data."""


def skills_dir() -> Path:
    return _skills_dir()


def _require_agent_stage_completion(result_path: Path, stage_name: str) -> None:
    result = load_model(result_path, AgentStageResult)
    if result.status != "completed":
        raise RuntimeError(f"{stage_name} reported {result.status}: {result.error}")


def _paper_graph(state: WorkflowState) -> PaperGraph:
    return load_model(Path(state["paper_graph_path"]), PaperGraph)


def _execution_scope(state: WorkflowState) -> GraphExecutionScope:
    cached = state.get("_execution_scope")
    if isinstance(cached, GraphExecutionScope):
        return cached
    scope_value = state.get("execution_scope_path")
    if scope_value is not None:
        scope = load_model(Path(scope_value), GraphExecutionScope)
        current_graph_hash = sha256_file(Path(state["paper_graph_path"]))
        if scope.paper_graph_sha256 != current_graph_hash:
            raise RuntimeError("Execution scope does not match the immutable paper graph")
        node_state = load_node_state(Path(state["node_state_path"]))
        if node_state.paper_graph_sha256 != current_graph_hash:
            raise RuntimeError("Node state does not match the immutable paper graph")
        state["_execution_scope"] = scope  # type: ignore[typeddict-unknown-key]
        return scope
    graph = _paper_graph(state)
    runnable = [node.id for node in graph.nodes]
    payload = {
        "paper_graph_sha256": sha256_file(Path(state["paper_graph_path"])),
        "availability_report_sha256": "0" * 64,
        "verdict": "FULL",
        "runnable_node_ids": runnable,
        "blocked_nodes": [],
        "active_sources": [],
        "execution_location": "local",
    }
    payload["scope_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    scope = GraphExecutionScope.model_validate(payload)
    scope_path = state["config"].output / "preprocessing" / "execution_scope.json"
    write_json(scope_path, scope.model_dump(mode="json"))
    state["execution_scope_path"] = str(scope_path)
    state["_execution_scope"] = scope  # type: ignore[typeddict-unknown-key]
    return scope


def _active_node_ids(state: WorkflowState) -> set[str]:
    return set(_execution_scope(state).runnable_node_ids)


def _active_cloud_datasets(state: WorkflowState) -> tuple[str, ...]:
    config = state["config"]
    scope = _execution_scope(state)
    if scope.availability_report_sha256 == "0" * 64:
        return config.selected_cloud_datasets
    active_sources = set(scope.active_sources)
    cloud_sources = config.selected_cloud_sources or config.selected_cloud_datasets
    return tuple(
        dataset
        for dataset, source in zip(
            config.selected_cloud_datasets,
            cloud_sources,
            strict=True,
        )
        if dataset in active_sources or source in active_sources
    )


_SCOPED_STAGES = [
    "codegen_agent",
    "audit_agent",
    "cohort_refine_agent",
    "plan_agent",
    "replicate_agent",
    "report_agents",
]


def _ensure_stage_scope(pipeline_state: PipelineState, stage_name: str, scope_hash: str) -> None:
    if pipeline_state.state.get("legacy_full_scope") is True:
        return
    if not pipeline_state.is_stage_completed(stage_name):
        return
    if pipeline_state.get_stage_checkpoints(stage_name).get("scope_sha256") == scope_hash:
        return
    index = _SCOPED_STAGES.index(stage_name)
    pipeline_state.invalidate_stages(
        _SCOPED_STAGES[index:],
        f"Execution scope changed to {scope_hash}",
    )


def _checkpoint_stage_scope(
    pipeline_state: PipelineState, stage_name: str, scope_hash: str
) -> None:
    pipeline_state.update_stage_checkpoints(stage_name, {"scope_sha256": scope_hash})


def _validate_agent_artifacts_with_resume(
    *,
    config: RunConfig,
    stage_name: str,
    session_id: str | None,
    working_dir: Path,
    transcript_path: Path,
    artifact_paths: list[Path],
    validate: Callable[[], object],
    result_schema_path: Path | None = None,
    result_path: Path | None = None,
) -> None:
    """Resume a direct Codex stage when its owned artifacts fail validation."""
    repair_turns = 0
    prompt_index = 1
    while True:
        try:
            validate()
            return
        except (OSError, RuntimeError, ValueError) as exc:
            if config.provider != "codex":
                raise
            if session_id is None:
                raise RuntimeError(
                    f"Codex {stage_name} artifacts failed validation without a session ID"
                ) from exc
            if repair_turns >= MAX_AGENT_ARTIFACT_REPAIR_TURNS:
                raise RuntimeError(
                    f"{stage_name} artifacts still failed validation after "
                    f"{MAX_AGENT_ARTIFACT_REPAIR_TURNS} resumed repair turns: {exc}"
                ) from exc

            resume_prompt_path = (
                config.output / "prompts" / f"{stage_name}_validation_resume_{prompt_index:03d}.md"
            )
            while resume_prompt_path.exists():
                prompt_index += 1
                resume_prompt_path = (
                    config.output
                    / "prompts"
                    / f"{stage_name}_validation_resume_{prompt_index:03d}.md"
                )
            render_prompt(
                "replication/artifact_validation_resume.md",
                resume_prompt_path,
                stage_name=stage_name,
                artifact_paths=artifact_paths,
                artifact_validation_error=str(exc),
                structured_stage_result=result_schema_path is not None,
            )
            run_agent(
                provider=config.provider,
                prompt_path=resume_prompt_path,
                working_dir=working_dir,
                transcript_path=transcript_path,
                siliconflow_config_path=config.siliconflow_config,
                codex_model=config.codex_model,
                codex_reasoning_effort=config.codex_reasoning_effort,
                output_schema_path=result_schema_path,
                output_last_message_path=result_path,
                resume_session_id=session_id,
            )
            if result_path is not None:
                _require_agent_stage_completion(result_path, stage_name)
            repair_turns += 1
            prompt_index += 1


def _replication_output_candidates(
    value: str,
    codebase_dir: Path,
    replication_dir: Path,
) -> list[Path]:
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
    return candidates


def resolve_replication_output(
    value: str,
    codebase_dir: Path,
    replication_dir: Path,
) -> Path:
    candidates = _replication_output_candidates(value, codebase_dir, replication_dir)

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


def _replication_artifact_error(path: Path) -> str | None:
    try:
        if path.is_dir():
            if not any(path.iterdir()):
                return f"artifact directory is empty: {path}"
            return None
        if not path.is_file():
            return f"artifact is missing: {path}"
        if path.stat().st_size == 0:
            return f"artifact file is empty: {path}"
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
        elif path.suffix == ".gz":
            with gzip.open(path, "rb") as stream:
                for _ in iter(lambda: stream.read(1024 * 1024), b""):
                    pass
    except (EOFError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return f"artifact integrity check failed for {path}: {exc}"
    return None


def _canonical_replication_output(
    value: str,
    codebase_dir: Path,
    replication_dir: Path,
) -> Path | None:
    allowed_roots = [codebase_dir.resolve(), replication_dir.resolve()]
    for candidate in _replication_output_candidates(value, codebase_dir, replication_dir):
        resolved = candidate.resolve()
        if any(resolved.is_relative_to(root) for root in allowed_roots):
            return resolved
    return None


def _archived_replication_output(archive_root: Path, value: str) -> Path | None:
    raw_path = Path(value)
    candidates: list[Path] = []
    for marker, destination in (
        (("codegen", "codebase"), archive_root / "referenced_codebase_outputs"),
        (("replication",), archive_root / "replication"),
    ):
        for index in range(len(raw_path.parts) - len(marker) + 1):
            if tuple(raw_path.parts[index : index + len(marker)]) == marker:
                candidates.append(destination.joinpath(*raw_path.parts[index + len(marker) :]))
                break
    if not raw_path.is_absolute():
        candidates.extend(
            [
                archive_root / "referenced_codebase_outputs" / raw_path,
                archive_root / "replication" / raw_path,
            ]
        )
    archive_resolved = archive_root.resolve()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_relative_to(archive_resolved) and (
            resolved.is_file() or resolved.is_dir()
        ):
            return resolved
    return None


def _load_replication_updates(log_path: Path) -> list[PendingNodeUpdate]:
    try:
        payload = json.loads(log_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    raw_updates = payload.get("node_updates") if isinstance(payload, dict) else None
    if not isinstance(raw_updates, list):
        return []
    updates: list[PendingNodeUpdate] = []
    for raw_update in raw_updates:
        try:
            updates.append(PendingNodeUpdate.model_validate(raw_update))
        except ValueError:
            continue
    return updates


def _inspect_completed_replication_nodes(state: WorkflowState) -> dict[str, Any]:
    graph = _paper_graph(state)
    scope = _execution_scope(state)
    codebase_dir = Path(state["codebase_dir"])
    replication_dir = state["config"].output / "replication"
    updates = _load_replication_updates(replication_dir / "replication_log.json")
    update_counts: dict[str, int] = {}
    for update in updates:
        update_counts[update.node_id] = update_counts.get(update.node_id, 0) + 1
    updates_by_id = {
        update.node_id: update for update in updates if update_counts[update.node_id] == 1
    }
    artifact_errors: dict[Path, str | None] = {}
    reusable: set[str] = set()
    pending_reasons: dict[str, str] = {}
    runnable = set(scope.runnable_node_ids)

    for layer in replication_topological_layers(graph, scope):
        for node_id in layer:
            node = graph.node_map[node_id]
            missing_predecessors = [input_id for input_id in node.inputs if input_id not in reusable]
            if missing_predecessors:
                pending_reasons[node_id] = (
                    "incomplete direct predecessors: " + ", ".join(missing_predecessors)
                )
                continue
            if update_counts.get(node_id, 0) > 1:
                pending_reasons[node_id] = "duplicate node updates"
                continue
            update = updates_by_id.get(node_id)
            if update is None:
                pending_reasons[node_id] = "missing node update"
                continue
            completion_status = getattr(update, "completion_status", None)
            result = getattr(update, "result", None)
            if completion_status is not None and completion_status != "completed":
                pending_reasons[node_id] = (
                    f"node update has non-completed status: {completion_status}"
                )
                continue
            if completion_status is None and isinstance(result, str):
                pending_reasons[node_id] = (
                    "legacy textual result has no explicit completed status"
                )
                continue
            if result is None or result == "" or result == [] or result == {}:
                pending_reasons[node_id] = "node update has no result"
                continue
            evidence = getattr(update, "evidence", None)
            if (
                not isinstance(evidence, list)
                or not evidence
                or not all(isinstance(value, str) and value.strip() for value in evidence)
            ):
                pending_reasons[node_id] = "node update has no evidence paths"
                continue
            evidence_error = None
            for value in evidence:
                try:
                    path = resolve_replication_output(value, codebase_dir, replication_dir)
                except RuntimeError as exc:
                    evidence_error = str(exc)
                    break
                if path not in artifact_errors:
                    artifact_errors[path] = _replication_artifact_error(path)
                if artifact_errors[path] is not None:
                    evidence_error = artifact_errors[path]
                    break
            if evidence_error is not None:
                pending_reasons[node_id] = evidence_error
                continue
            reusable.add(node_id)

    ordered_ids = [node.id for node in graph.nodes if node.id in runnable]
    return {
        "completed_node_ids": [node_id for node_id in ordered_ids if node_id in reusable],
        "pending_node_ids": [node_id for node_id in ordered_ids if node_id not in reusable],
        "pending_reasons": {
            node_id: pending_reasons[node_id]
            for node_id in ordered_ids
            if node_id in pending_reasons
        },
    }


def validate_replication_artifacts(state: WorkflowState) -> list[str]:
    config = state["config"]
    replication_dir = config.output / "replication"
    replication_log_path = replication_dir / "replication_log.json"
    evidence_summary_path = replication_dir / "evidence_summary.json"
    plan = load_model(Path(state["replicate_plan_path"]), ReplicationPlan)
    replication_log = load_model(replication_log_path, ReplicationLog)
    validate_replication_log(plan, replication_log)
    load_model(evidence_summary_path, EvidenceSummary)
    graph = _paper_graph(state)
    scope = _execution_scope(state)
    managed_artifacts = {
        replication_log_path.resolve(),
        evidence_summary_path.resolve(),
    }
    artifact_errors: dict[Path, str | None] = {}
    for outcome in replication_log.step_outcomes:
        for output_file in outcome.output_files:
            resolved = resolve_replication_output(
                output_file,
                Path(state["codebase_dir"]),
                replication_dir,
            )
            if resolved not in artifact_errors:
                artifact_errors[resolved] = _replication_artifact_error(resolved)
            if artifact_errors[resolved] is not None:
                raise RuntimeError(artifact_errors[resolved])
            if resolved in managed_artifacts:
                raise RuntimeError(
                    f"Replication step {outcome.step_id} cannot cite a managed log "
                    f"as its output: {output_file}"
                )

    update_ids = [update.node_id for update in replication_log.node_updates]
    if len(update_ids) != len(set(update_ids)):
        raise RuntimeError("Replication log contains duplicate node updates")
    expected_ids = set(scope.runnable_node_ids)
    if set(update_ids) != expected_ids:
        raise RuntimeError(
            "Replication node updates must cover every runnable node exactly once; "
            f"missing={sorted(expected_ids - set(update_ids))!r}, "
            f"extra={sorted(set(update_ids) - expected_ids)!r}"
        )
    for update in replication_log.node_updates:
        completion_status = getattr(update, "completion_status", None)
        if completion_status is not None and completion_status != "completed":
            raise RuntimeError(
                f"Runnable node {update.node_id} has non-completed status: "
                f"{completion_status}"
            )
        result = getattr(update, "result", None)
        if result is None or result == "" or result == [] or result == {}:
            raise RuntimeError(f"Runnable node {update.node_id} has no actual replication result")
        evidence = getattr(update, "evidence", None)
        if (
            not isinstance(evidence, list)
            or not evidence
            or not all(isinstance(value, str) and value.strip() for value in evidence)
        ):
            raise RuntimeError(f"Runnable node {update.node_id} has no actual evidence paths")
        for evidence_path in evidence:
            resolved = resolve_replication_output(
                evidence_path,
                Path(state["codebase_dir"]),
                replication_dir,
            )
            if resolved not in artifact_errors:
                artifact_errors[resolved] = _replication_artifact_error(resolved)
            if artifact_errors[resolved] is not None:
                raise RuntimeError(artifact_errors[resolved])
            if resolved in managed_artifacts:
                raise RuntimeError(
                    f"Runnable node {update.node_id} cites a managed log as evidence: "
                    f"{evidence_path}"
                )

    merge_node_updates(
        Path(state["node_state_path"]),
        graph,
        scope.paper_graph_sha256,
        "replicate_agent",
        replication_log.node_updates,
    )

    outputs = [str(replication_log_path), str(evidence_summary_path)]
    if config.smart_replicate:
        runnable = set(scope.runnable_node_ids)
        for claim in graph.claims:
            if claim.id not in runnable or claim.paper_result is None:
                continue
            smart_log_path = (
                replication_dir / "claims" / claim.id / "smart_replicate_log.json"
            )
            smart_log = load_model(smart_log_path, SmartReplicateLog)
            validate_smart_replicate_log(claim, smart_log)
            outputs.append(str(smart_log_path))
    return outputs


def _run_agent_command(
    command: str,
    *,
    codebase_dir: Path,
    log_path: Path,
    result_path: Path,
) -> dict[str, Any]:
    """Execute one Codex-requested foreground command and retain its combined log."""
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
        raise RuntimeError(f"Could not execute Codex command: {exc}") from exc

    result = {
        "command": command,
        "exit_code": exit_code,
        "duration_seconds": round(time.monotonic() - started, 3),
        "log_path": str(log_path),
        "artifact_validation_error": None,
    }
    write_json(result_path, result)
    return result


def read_audit_verdict(report_path: Path) -> str:
    return str(read_audit_report(report_path)["verdict"])


def read_audit_report(report_path: Path) -> dict[str, Any]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Audit agent did not write its report: {report_path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Audit report is not valid JSON: {report_path}") from exc
    if not isinstance(report, dict) or set(report) != {"verdict", "issues"}:
        raise RuntimeError(
            f"Audit report must contain exactly `verdict` and `issues`: {report_path}"
        )
    verdict = report["verdict"]
    issues = report["issues"]
    if verdict not in {"PASS", "FAIL"} or not isinstance(issues, list):
        raise RuntimeError(f"Audit report has an invalid verdict or issues: {report_path}")
    for issue in issues:
        if (
            not isinstance(issue, dict)
            or not isinstance(issue.get("node_id"), str)
            or not issue["node_id"].strip()
            or not isinstance(issue.get("description"), str)
            or not issue["description"].strip()
            or issue.get("route", "preprocessing_fix")
            not in {"preprocessing_fix", "source_unavailable"}
        ):
            raise RuntimeError(f"Audit report contains an invalid issue: {report_path}")
    if (verdict == "PASS" and issues) or (verdict == "FAIL" and not issues):
        raise RuntimeError(
            "Audit report PASS requires no issues and FAIL requires at least one issue: "
            f"{report_path}"
        )
    return report


def _merge_audit_node_updates(
    state: WorkflowState,
    source: str,
    audit_report: dict[str, Any],
) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for issue in audit_report["issues"]:
        payload = dict(issue)
        node_id = str(payload.pop("node_id"))
        grouped.setdefault(node_id, []).append(payload)
    merge_node_updates(
        Path(state["node_state_path"]),
        _paper_graph(state),
        _execution_scope(state).paper_graph_sha256,
        source,
        [
            {"node_id": node_id, "issues": issues}
            for node_id, issues in grouped.items()
        ],
    )


def validate_codegen_remote_compute(
    plan: Any,
    state_path: Path,
    *,
    cloud_dataset: str | None = None,
    cloud_datasets: Sequence[str] | None = None,
    drive_provider: str | None = None,
    computation_provider: str | None = None,
    require_active: bool = True,
) -> dict[str, Any] | None:
    expected_datasets = tuple(cloud_datasets or ((cloud_dataset,) if cloud_dataset else ()))
    remote_compute = plan.remote_compute
    if remote_compute is None:
        if expected_datasets:
            raise RuntimeError("Cloud-drive mode requires a remote-compute plan")
        return
    if Path(remote_compute.state_path).resolve() != state_path.resolve():
        raise RuntimeError(
            f"Remote-compute state path does not match the current run: {remote_compute.state_path}"
        )
    if not expected_datasets:
        return None
    try:
        provider_envelope = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cloud-drive state is missing or invalid: {state_path}") from exc
    provider_state = provider_envelope.get("provider_state")
    provider = provider_envelope.get("provider")
    if not isinstance(provider, str) or not provider or not isinstance(provider_state, dict):
        raise RuntimeError("Cloud-drive mode requires completed provider state")
    if computation_provider is not None and provider != computation_provider:
        raise RuntimeError("Cloud-drive state provider does not match the run configuration")
    if require_active and provider_envelope.get("released") is True:
        raise RuntimeError("Cloud-drive instance was already released")
    cloud_drives = _provider_cloud_drives(provider_state)
    selected: dict[str, dict[str, Any]] = {}
    for dataset in expected_datasets:
        cloud_drive = cloud_drives.get(dataset)
        if not isinstance(cloud_drive, dict) or (
            cloud_drive.get("completed") is not True
            or cloud_drive.get("drive") != drive_provider
            or cloud_drive.get("dataset") != dataset
        ):
            raise RuntimeError("Cloud-drive materialization is incomplete or inconsistent")
        target_path = cloud_drive.get("target_path")
        if not isinstance(target_path, str) or not target_path:
            raise RuntimeError("Cloud-drive state is missing its materialized target path")
        selected[dataset] = cloud_drive
    target_path = _cloud_dataset_root(selected)
    if remote_compute.remote_dataset_dir != target_path:
        raise RuntimeError("Remote plan dataset path does not match completed cloud-drive state")
    if len(selected) == 1:
        return next(iter(selected.values()))
    return {"completed": True, "target_path": target_path, "datasets": selected}


def _provider_cloud_drives(provider_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    plural = provider_state.get("cloud_drives")
    if isinstance(plural, dict):
        return {
            name: value
            for name, value in plural.items()
            if isinstance(name, str) and isinstance(value, dict)
        }
    legacy = provider_state.get("cloud_drive")
    if isinstance(legacy, dict) and isinstance(legacy.get("dataset"), str):
        return {legacy["dataset"]: legacy}
    return {}


def _cloud_dataset_root(cloud_drives: dict[str, dict[str, Any]]) -> str:
    targets = {
        dataset: str(cloud["target_path"])
        for dataset, cloud in cloud_drives.items()
    }
    if len(targets) == 1:
        return next(iter(targets.values()))
    parents = {str(PurePosixPath(target).parent) for target in targets.values()}
    if len(parents) != 1 or any(
        PurePosixPath(target).name != dataset for dataset, target in targets.items()
    ):
        raise RuntimeError("Cloud datasets do not share the provider-defined dataset root")
    return parents.pop()


def _uses_cloud_data(
    config: RunConfig | AutoResearchConfig,
    plan: CodegenPlan | ReplicationPlan,
) -> bool:
    return config.clouddrive and (config.data is None or plan.remote_compute is not None)


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


def reconcile_run_computation_instance(
    config: RunConfig | AutoResearchConfig,
) -> dict[str, Any]:
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


def power_on_run_computation_instance(
    config: RunConfig | AutoResearchConfig,
) -> dict[str, Any]:
    state_path = config.output / "remote_compute" / "instance.json"
    if not state_path.is_file():
        return {"created": False, "materialization_required": False}
    state = _load_computation_provider_state(state_path)
    if not state.get("created_by_run") or state.get("released") is True:
        return {"created": False, "materialization_required": False}
    output = _run_computation_provider_action(
        state_path,
        "power-on",
        expected_provider=config.computation_provider,
    )
    try:
        result = json.loads(output)
    except json.JSONDecodeError:
        result = None
    if isinstance(result, dict):
        created = result.get("created")
        materialization_required = result.get("materialization_required")
        if isinstance(created, bool) and isinstance(materialization_required, bool):
            return result
    return {"created": False, "materialization_required": False}


def power_off_run_computation_instance(
    config: RunConfig | AutoResearchConfig,
) -> None:
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


def _cloud_pull(
    config: RunConfig,
    *,
    use_cloud: bool,
    datasets: Sequence[str] | None = None,
) -> None:
    if not use_cloud:
        return
    if not config.selected_cloud_datasets:
        raise RuntimeError("Cloud-drive mode is missing its dataset name")
    state_path = config.output / "remote_compute" / "instance.json"
    for dataset in datasets or config.selected_cloud_datasets:
        _run_computation_provider_action(
            state_path,
            "cloud-pull",
            arguments=["--dataset", dataset],
            expected_provider=config.computation_provider,
        )


def _cloud_pull_handoff_enabled(config: RunConfig) -> bool:
    if (
        config.provider != "codex"
        or not config.clouddrive
        or config.data is not None
        or config.computation_provider is None
        or config.drive_provider is None
    ):
        return False
    return (
        get_provider_adapter(config.computation_provider)
        .drive(config.drive_provider)
        .cloud_pull_handoff
    )


def _cloud_drive_materialization_completed(
    config: RunConfig | AutoResearchConfig,
    datasets: Sequence[str] | None = None,
) -> bool:
    if not config.clouddrive or not config.selected_cloud_datasets:
        return False
    state_path = config.output / "remote_compute" / "instance.json"
    if not state_path.is_file():
        return False
    state = _load_computation_provider_state(state_path)
    if state.get("provider") != config.computation_provider:
        raise RuntimeError("Cloud-drive state provider does not match the run configuration")
    if state.get("released") is True:
        raise RuntimeError("Cloud-drive instance was already released")
    provider_state = state.get("provider_state")
    if not isinstance(provider_state, dict):
        raise RuntimeError("Cloud-drive state is invalid")
    cloud_drives = _provider_cloud_drives(provider_state)
    if not cloud_drives:
        return False
    for dataset in datasets or config.selected_cloud_datasets:
        cloud_drive = cloud_drives.get(dataset)
        if not isinstance(cloud_drive, dict):
            return False
        if (
            cloud_drive.get("drive") != config.drive_provider
            or cloud_drive.get("dataset") != dataset
        ):
            raise RuntimeError("Cloud-drive state does not match the run configuration")
        if cloud_drive.get("completed") is not True:
            return False
        target_path = cloud_drive.get("target_path")
        if not isinstance(target_path, str) or not target_path:
            raise RuntimeError("Cloud-drive state is missing its materialized target path")
    return True


def _next_command_index(command_dir: Path) -> int:
    index = 1
    while (command_dir / f"command_{index:03d}.json").exists():
        index += 1
    return index


def _run_codegen_cloud_pull_handoff(
    *,
    config: RunConfig,
    codebase_dir: Path,
    prompt_path: Path,
    transcript_path: Path,
    stage_result_schema_path: Path,
    stage_result_path: Path,
) -> str:
    """Pause one Codex session while local orchestration monitors cloud materialization."""
    command_dir = config.output / "codegen" / "cloud_pull" / "commands"
    command_dir.mkdir(parents=True, exist_ok=True)
    command_schema_path = config.output / "prompts" / "codegen_cloud_pull_command.schema.json"
    write_json(command_schema_path, CodegenCloudPullRequest.model_json_schema())
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
                raise RuntimeError("Codex cloud-pull preparation turn did not return a session ID")
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

        request = load_model(command_request_path, CodegenCloudPullRequest)
        if request.status != "command":
            raise RuntimeError(
                "codegen_agent reported "
                f"{request.status} during cloud-pull preparation: {request.error}"
            )
        assert request.command is not None
        command = request.command
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
            "codegen/cloud_pull_result_instructions.md",
            config.output / "prompts" / f"codegen_cloud_pull_resume_{command_index:03d}.md",
            command_result_path=result_path,
            command_log_path=log_path,
            exit_code=result["exit_code"],
            duration_seconds=result["duration_seconds"],
            artifact_validation_error=result["artifact_validation_error"],
            computation_provider_state_path=config.output / "remote_compute" / "instance.json",
        )
        command_index += 1

    completion_prompt_path = render_prompt(
        "codegen/cloud_pull_complete_instructions.md",
        config.output / "prompts" / "codegen_cloud_pull_complete.md",
        computation_provider_state_path=config.output / "remote_compute" / "instance.json",
    )
    run_agent(
        provider=config.provider,
        prompt_path=completion_prompt_path,
        working_dir=codebase_dir,
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
        output_schema_path=stage_result_schema_path,
        output_last_message_path=stage_result_path,
        resume_session_id=session_id,
    )
    return session_id


def _run_has_remote_plan(config: RunConfig) -> bool:
    candidates: tuple[tuple[Path, type[CodegenPlan] | type[ReplicationPlan]], ...] = (
        (config.output / "plan" / "replicate_plan.json", ReplicationPlan),
        (config.output / "codegen" / "codebase" / "codegen_plan.json", CodegenPlan),
    )
    for path, model_type in candidates:
        if path.is_file() and load_model(path, model_type).remote_compute is not None:
            return True
    return False


def _validate_recorded_remote_state(
    state_path: Path,
    config: RunConfig | AutoResearchConfig,
) -> None:
    state = _load_computation_provider_state(state_path)
    if not state.get("created_by_run"):
        raise RuntimeError("Remote computation state lacks current-run ownership")
    _run_computation_provider_action(
        state_path,
        "validate-state",
        expected_provider=config.computation_provider,
    )


def _restore_archived_replication_output(source: Path, target: Path) -> None:
    if source.resolve() == target.resolve():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.resume-restore.tmp")
    if temporary.exists():
        raise RuntimeError(f"Replication restore target already exists: {temporary}")
    if source.is_file():
        shutil.copy2(source, temporary)
        temporary.replace(target)
        return
    if source.is_dir() and not target.exists():
        shutil.copytree(source, temporary)
        temporary.replace(target)
        return
    if not target.is_dir() or _replication_artifact_error(target) is not None:
        raise RuntimeError(f"Cannot safely restore archived directory over: {target}")


def _recover_archived_replication_nodes(config: RunConfig) -> list[str]:
    graph_path = config.output / "preprocessing" / "paper_graph.json"
    scope_path = config.output / "preprocessing" / "execution_scope.json"
    node_state_path = config.output / "graph" / "node_state.json"
    plan_path = config.output / "plan" / "replicate_plan.json"
    if not all(path.is_file() for path in (graph_path, scope_path, node_state_path, plan_path)):
        return []

    graph = load_model(graph_path, PaperGraph)
    scope = load_model(scope_path, GraphExecutionScope)
    codebase_dir = config.output / "codegen" / "codebase"
    replication_dir = config.output / "replication"
    log_path = replication_dir / "replication_log.json"
    sources: list[tuple[Path | None, list[PendingNodeUpdate]]] = [
        (None, _load_replication_updates(log_path))
    ]
    history_root = config.output / "resume_history"
    if history_root.is_dir():
        for archive_root in sorted(history_root.glob("resume_[0-9][0-9][0-9]"), reverse=True):
            sources.append(
                (
                    archive_root,
                    _load_replication_updates(
                        archive_root / "replication" / "replication_log.json"
                    ),
                )
            )

    candidates: dict[str, list[tuple[PendingNodeUpdate, list[tuple[Path, Path]]]]] = {}
    integrity_cache: dict[Path, str | None] = {}
    runnable = set(scope.runnable_node_ids)
    for archive_root, updates in sources:
        counts: dict[str, int] = {}
        for update in updates:
            counts[update.node_id] = counts.get(update.node_id, 0) + 1
        for update in updates:
            if update.node_id not in runnable or counts[update.node_id] != 1:
                continue
            completion_status = getattr(update, "completion_status", None)
            result = getattr(update, "result", None)
            if completion_status is not None and completion_status != "completed":
                continue
            if completion_status is None and isinstance(result, str):
                continue
            if result is None or result == "" or result == [] or result == {}:
                continue
            evidence = getattr(update, "evidence", None)
            if (
                not isinstance(evidence, list)
                or not evidence
                or not all(isinstance(value, str) and value.strip() for value in evidence)
            ):
                continue
            resolved_evidence: list[tuple[Path, Path]] = []
            for value in evidence:
                target = _canonical_replication_output(value, codebase_dir, replication_dir)
                if target is None:
                    break
                source = (
                    _archived_replication_output(archive_root, value)
                    if archive_root is not None
                    else None
                )
                if source is None:
                    try:
                        source = resolve_replication_output(value, codebase_dir, replication_dir)
                    except RuntimeError:
                        break
                if source not in integrity_cache:
                    integrity_cache[source] = _replication_artifact_error(source)
                if integrity_cache[source] is not None:
                    break
                resolved_evidence.append((source, target))
            else:
                candidates.setdefault(update.node_id, []).append(
                    (update, resolved_evidence)
                )

    selected: dict[str, tuple[PendingNodeUpdate, list[tuple[Path, Path]]]] = {}
    for layer in replication_topological_layers(graph, scope):
        for node_id in layer:
            node = graph.node_map[node_id]
            if all(input_id in selected for input_id in node.inputs):
                node_candidates = candidates.get(node_id, [])
                if node_candidates:
                    selected[node_id] = node_candidates[0]

    for update, evidence_paths in selected.values():
        for source, target in evidence_paths:
            _restore_archived_replication_output(source, target)

    try:
        payload = json.loads(log_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if not isinstance(payload.get("step_outcomes"), list):
        payload["step_outcomes"] = []
    current_by_id = {update.node_id: update for update in _load_replication_updates(log_path)}
    recovered_updates: list[dict[str, Any]] = []
    for node in graph.nodes:
        if node.id not in runnable:
            continue
        if node.id in selected:
            recovered = selected[node.id][0].model_dump(mode="json")
            recovered["completion_status"] = "completed"
            recovered_updates.append(recovered)
        elif node.id in current_by_id:
            recovered_updates.append(current_by_id[node.id].model_dump(mode="json"))
    payload["node_updates"] = recovered_updates
    write_json(log_path, payload)
    return [node.id for node in graph.nodes if node.id in selected]


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
    prompt_paths.extend(sorted((output / "prompts").glob("replicate_agent_validation_resume_*.md")))
    prompt_paths.extend(sorted((output / "prompts").glob("replicate_command*.json")))
    prompt_paths.extend(sorted((output / "prompts").glob("report_*.md")))
    prompt_paths = [path for path in prompt_paths if path.is_file()]

    mappings: list[dict[str, str]] = []
    unresolved: list[str] = []
    log_reference_error: str | None = None
    result_step_ids: set[int] | None = None
    replicate_plan_path = output / "plan" / "replicate_plan.json"
    if replicate_plan_path.is_file():
        try:
            archived_plan = load_model(replicate_plan_path, ReplicationPlan)
        except (OSError, RuntimeError, ValueError):
            pass
        else:
            result_step_ids = {step.id for step in archived_plan.steps if step.verifies}
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
            step_id = outcome.get("step_id") if isinstance(outcome, dict) else None
            if result_step_ids is not None and step_id not in result_step_ids:
                continue
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

    plan_needs_rebuild = False
    if pipeline_state.is_stage_completed("plan_agent"):
        try:
            graph = load_model(
                config.output / "preprocessing" / "paper_graph.json",
                PaperGraph,
            )
            scope = load_model(
                config.output / "preprocessing" / "execution_scope.json",
                GraphExecutionScope,
            )
            plan = load_model(
                config.output / "plan" / "replicate_plan.json",
                ReplicationPlan,
            )
            validate_replication_plan(graph, scope, plan)
        except (OSError, RuntimeError, ValueError):
            plan_needs_rebuild = True

    if replicate_started:
        if config.clouddrive and reconciliation["replaced"]:
            _cloud_pull(config, use_cloud=True)
        archive_root = _archive_replicate_attempt(config, resume_count)
        recovered_node_ids = _recover_archived_replication_nodes(config)

        if pipeline_state.is_stage_completed("replicate_agent") and not plan_needs_rebuild:
            return {
                **reconciliation,
                "rollback": None,
                "archive": str(archive_root),
                "recovered_node_ids": recovered_node_ids,
            }

        invalidated_stages = ["replicate_agent", "report_agents"]
        reason = (
            "Explicit resume will inspect and reuse completed replication nodes: "
            f"{archive_root}"
        )
        rollback = "replicate"
        if plan_needs_rebuild:
            invalidated_stages.insert(0, "plan_agent")
            reason = (
                "Explicit resume must rebuild the replication plan as exact DAG "
                f"topological layers; completed node artifacts remain reusable: {archive_root}"
            )
            rollback = "plan"
        pipeline_state.invalidate_stages(
            invalidated_stages,
            reason,
        )
        return {
            **reconciliation,
            "rollback": rollback,
            "archive": str(archive_root),
            "recovered_node_ids": recovered_node_ids,
        }

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
                "cohort_refine_agent",
                "plan_agent",
                "replicate_agent",
                "report_agents",
            ],
            "Remote computation instance was replaced during explicit resume",
            checkpoint_overrides={"codegen_agent": checkpoints},
        )
        return {**reconciliation, "rollback": "codegen"}

    if plan_needs_rebuild:
        pipeline_state.invalidate_stages(
            ["plan_agent", "replicate_agent", "report_agents"],
            "Explicit resume must rebuild the replication plan as exact DAG "
            "topological layers",
        )
        return {**reconciliation, "rollback": "plan"}

    return {**reconciliation, "rollback": None}


def prepare_autoresearch_resume(config: AutoResearchConfig) -> dict[str, Any]:
    pipeline_state = PipelineState(config.output)
    state_path = config.output / "remote_compute" / "instance.json"
    if pipeline_state.is_stage_completed("final_report") or not state_path.is_file():
        return {"reconciled": False, "replaced": False}

    _validate_recorded_remote_state(state_path, config)
    reconciliation = {
        "reconciled": True,
        **reconcile_run_computation_instance(config),
    }
    try:
        if config.clouddrive and (
            reconciliation["replaced"] or reconciliation.get("materialization_required") is True
        ):
            if not config.selected_cloud_datasets:
                raise RuntimeError("Cloud-backed Auto Research is missing its dataset name")
            for dataset in config.selected_cloud_datasets:
                _run_computation_provider_action(
                    state_path,
                    "cloud-pull",
                    arguments=["--dataset", dataset, "--prepare"],
                    expected_provider=config.computation_provider,
                )
                _run_computation_provider_action(
                    state_path,
                    "cloud-pull",
                    arguments=["--dataset", dataset, "--monitor"],
                    expected_provider=config.computation_provider,
                )
            if not _cloud_drive_materialization_completed(config):
                raise RuntimeError("Replacement Auto Research instance has incomplete cloud data")
    finally:
        power_off_run_computation_instance(config)
    return reconciliation


def preflight_node(state: WorkflowState) -> dict[str, str]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    resources_path = config.output / "preflight" / "resources.json"
    dataset_patch_path = config.output / "system_maintenance" / "dataset" / "patch.json"
    skill_corrections_path = config.output / "system_maintenance" / "skills" / "corrections.json"
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
        "graph",
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
    paper_graph_path = config.output / "preprocessing" / "paper_graph.json"
    node_state_path = config.output / "graph" / "node_state.json"
    transcript_path = config.output / "preprocessing" / "preprocessing_transcript.jsonl"

    def validate_graph_output() -> None:
        if not paper_markdown.is_file() or not paper_markdown.read_text(encoding="utf-8").strip():
            raise RuntimeError(
                f"Preprocessing agent left paper artifact missing or empty: {paper_markdown}"
            )
        load_model(paper_graph_path, PaperGraph)

    def validate_outputs() -> None:
        validate_graph_output()
        node_state = load_node_state(node_state_path)
        if node_state.paper_graph_sha256 != sha256_file(paper_graph_path):
            raise RuntimeError("Node state does not match the immutable paper graph")

    if pipeline_state.is_stage_completed("preprocessing_agent"):
        validate_outputs()
        if not transcript_path.is_file():
            raise RuntimeError(f"Completed preprocessing transcript is missing: {transcript_path}")
        print("resume preprocessing_agent stage: skipped (already completed)")
        return {
            "paper_graph_path": str(paper_graph_path),
            "node_state_path": str(node_state_path),
        }

    print("enter preprocessing agent stage")
    pipeline_state.start_stage("preprocessing_agent")
    prompt_path = render_prompt(
        "preprocessing/session_instructions.md",
        config.output / "prompts" / "preprocessing.md",
        paper_markdown=paper_markdown,
        artifacts_dir=config.output / "preprocessing" / "artifacts",
        skills_dir=skills_dir(),
        paper_graph_path=paper_graph_path,
    )
    session_id = run_agent(
        provider=config.provider,
        prompt_path=prompt_path,
        working_dir=config.output / "preprocessing",
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )
    _validate_agent_artifacts_with_resume(
        config=config,
        stage_name="preprocessing_agent",
        session_id=session_id,
        working_dir=config.output / "preprocessing",
        transcript_path=transcript_path,
        artifact_paths=[paper_markdown, paper_graph_path],
        validate=validate_graph_output,
    )
    write_empty_node_state(node_state_path, sha256_file(paper_graph_path))
    validate_outputs()
    pipeline_state.complete_stage(
        "preprocessing_agent",
        [
            str(paper_markdown),
            str(paper_graph_path),
            str(node_state_path),
            str(transcript_path),
        ],
    )
    return {
        "paper_graph_path": str(paper_graph_path),
        "node_state_path": str(node_state_path),
    }


def data_availability_agent_node(state: WorkflowState) -> dict[str, str]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    graph = _paper_graph(state)
    graph_sha256 = sha256_file(Path(state["paper_graph_path"]))
    scope_path = config.output / "preprocessing" / "execution_scope.json"
    stage = pipeline_state.state["stages"].get("data_availability_agent", {})

    def load_and_validate(report_path: Path) -> GraphExecutionScope:
        report = load_model(report_path, GraphDataAvailabilityReport)
        local_sources = {str(path) for path in config.dataset_paths}
        cloud_sources = set(config.selected_cloud_sources) | set(
            config.selected_cloud_datasets
        )
        for requirement in report.requirements:
            if requirement.status == "available" and requirement.source_name is None:
                raise ValueError("An available requirement must map to a concrete source")
            if (
                requirement.source_kind == "local"
                and requirement.source_name not in local_sources
            ):
                raise ValueError(
                    f"Availability report maps an unknown local source: "
                    f"{requirement.source_name}"
                )
            if (
                requirement.source_kind == "cloud"
                and requirement.source_name not in cloud_sources
            ):
                raise ValueError(
                    f"Availability report maps an unknown cloud source: "
                    f"{requirement.source_name}"
                )
        scope = derive_graph_execution_scope(
            graph,
            report,
            paper_graph_sha256=graph_sha256,
            report_sha256=sha256_file(report_path),
        )
        if scope.verdict in {"FULL", "PARTIAL"} and scope.execution_location is None:
            raise ValueError("A runnable execution scope requires an execution location")
        active_sources = set(scope.active_sources)
        active_cloud = tuple(
            dataset
            for dataset, source in zip(
                config.selected_cloud_datasets,
                config.selected_cloud_sources,
                strict=True,
            )
            if dataset in active_sources or source in active_sources
        )
        if (
            (config.data is None or scope.execution_location == "remote")
            and active_cloud
            and not _cloud_drive_materialization_completed(config, active_cloud)
        ):
            raise RuntimeError(
                "Cloud-only data availability requires every active cloud dataset "
                "to be materialized and audited"
            )
        write_json(scope_path, scope.model_dump(mode="json"))
        state["_execution_scope"] = scope  # type: ignore[typeddict-unknown-key]
        return scope

    if pipeline_state.is_stage_completed("data_availability_agent"):
        report_path = Path(str(stage.get("checkpoints", {}).get("report_path", "")))
        scope = load_and_validate(report_path)
        recorded_hash = stage.get("checkpoints", {}).get("scope_sha256")
        if recorded_hash != scope.scope_sha256:
            legacy_scope = scope.model_dump(mode="json", exclude={"scope_sha256"})
            legacy_scope["verdict"] = "UNKNOWN"
            legacy_hash = hashlib.sha256(
                json.dumps(legacy_scope, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest()
            if (
                stage.get("checkpoints", {}).get("verdict") != "UNKNOWN"
                or recorded_hash != legacy_hash
            ):
                raise RuntimeError(
                    "Completed data-availability scope does not match its checkpoint"
                )
            pipeline_state.migrate_completed_stage_checkpoints(
                "data_availability_agent",
                {"scope_sha256": scope.scope_sha256, "verdict": scope.verdict},
            )
            print("migrated legacy UNKNOWN data-availability scope")
        print("resume data_availability_agent stage: skipped (already completed)")
        return {"execution_scope_path": str(scope_path)}

    print("enter data availability agent stage")
    previous_attempts = int(stage.get("attempts", 0))
    pipeline_state.start_stage("data_availability_agent")
    attempt = previous_attempts + 1
    attempt_dir = (
        config.output / "preprocessing" / "data_availability" / f"attempt_{attempt:03d}"
    )
    results_dir = attempt_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    report_path = attempt_dir / "data_availability.json"
    transcript_path = attempt_dir / "data_availability_transcript.jsonl"
    resources_path = Path(state["resources_path"])
    local_datasets = list(zip(config.dataset_names, config.dataset_paths, strict=True))
    cloud_datasets = [
        (dataset, source)
        for dataset, source in zip(
            config.selected_cloud_datasets,
            config.selected_cloud_sources,
            strict=True,
        )
    ]
    scope_revision_reports = sorted(
        config.output.glob("codegen/audit/attempt_*/audit_report.json")
    )
    scope_revision_reports.extend(sorted(config.output.glob("codegen/scope_revision_*.json")))
    prompt_path = render_prompt(
        "data_availability/session_instructions.md",
        config.output / "prompts" / f"data_availability_attempt_{attempt:03d}.md",
        paper_markdown=state["paper_markdown"],
        paper_graph_path=state["paper_graph_path"],
        resources_path=resources_path,
        local_datasets=local_datasets,
        cloud_datasets=cloud_datasets,
        scope_revision_reports=scope_revision_reports,
        cloud_only=config.data is None and bool(config.selected_cloud_datasets),
        dual_source=config.data is not None and bool(config.selected_cloud_datasets),
        computation_provider_reference=config.computation_provider_reference,
        drive_reference=config.drive_reference,
        computation_provider_state_path=config.output / "remote_compute" / "instance.json",
        report_path=report_path,
        results_dir=results_dir,
    )
    session_id = run_agent(
        provider=config.provider,
        prompt_path=prompt_path,
        working_dir=attempt_dir,
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )
    scope: GraphExecutionScope | None = None

    def validate_outputs() -> None:
        nonlocal scope
        scope = load_and_validate(report_path)

    _validate_agent_artifacts_with_resume(
        config=config,
        stage_name="data_availability_agent",
        session_id=session_id,
        working_dir=attempt_dir,
        transcript_path=transcript_path,
        artifact_paths=[report_path, results_dir],
        validate=validate_outputs,
    )
    assert scope is not None
    pipeline_state.update_stage_checkpoints(
        "data_availability_agent",
        {
            "report_path": str(report_path),
            "scope_sha256": scope.scope_sha256,
            "verdict": scope.verdict,
        },
    )
    pipeline_state.complete_stage(
        "data_availability_agent",
        [str(report_path), str(results_dir), str(transcript_path), str(scope_path)],
    )
    return {"execution_scope_path": str(scope_path)}


def _partial_data_message(scope: GraphExecutionScope, graph: PaperGraph) -> str:
    runnable = set(scope.runnable_node_ids)
    claim_ids = {claim.id for claim in graph.claims}
    lines = ["Partial data availability detected.", "", "Reproducible claims:"]
    lines.extend(f"- {claim.id}" for claim in graph.claims if claim.id in runnable)
    lines.extend(["", "Claims that will not be reproduced:"])
    for blocked in scope.blocked_nodes:
        if blocked.node_id not in claim_ids:
            continue
        details = list(blocked.direct_data_blockers)
        details.extend(" -> ".join(path) for path in blocked.dependency_paths if len(path) > 1)
        lines.append(f"- {blocked.node_id}: {'; '.join(details)}")
    lines.extend(
        [
            "",
            "Continuing will produce a partial replication. It will not represent a complete",
            "replication of the paper and cannot be used as an Auto Research base run.",
            "",
            "Only the reproducible claim subgraph will be executed.",
        ]
    )
    return "\n".join(lines)


def _record_partial_decision(
    config: RunConfig,
    scope: GraphExecutionScope,
    *,
    decision: str,
    source: str,
) -> Path:
    path = config.output / "preprocessing" / "partial_replication_decisions.json"
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Partial-data decision log is invalid: {path}") from exc
    else:
        payload = {"decisions": []}
    decisions = payload.get("decisions") if isinstance(payload, dict) else None
    if not isinstance(decisions, list):
        raise RuntimeError(f"Partial-data decision log is invalid: {path}")
    decisions.append(
        {
            "availability_report_sha256": scope.availability_report_sha256,
            "scope_sha256": scope.scope_sha256,
            "runnable_node_ids": scope.runnable_node_ids,
            "blocked_node_ids": [item.node_id for item in scope.blocked_nodes],
            "decision": decision,
            "source": source,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    write_json(path, payload)
    return path


def partial_data_gate_node(state: WorkflowState) -> dict[str, str]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    scope_path = Path(state["execution_scope_path"])
    scope = load_model(scope_path, GraphExecutionScope)
    checkpoints = pipeline_state.get_stage_checkpoints("partial_data_gate")
    if (
        pipeline_state.is_stage_completed("partial_data_gate")
        and checkpoints.get("scope_sha256") == scope.scope_sha256
    ):
        print("resume partial_data_gate stage: skipped (already completed)")
        return {"execution_scope_path": str(scope_path)}

    pipeline_state.start_stage("partial_data_gate")
    if scope.verdict == "NONE":
        power_off_run_computation_instance(config)
        release_run_computation_instance(config)
        raise NoRunnableClaims(
            "No claims are runnable with the available source data."
        )

    decision_path: Path | None = None
    if scope.verdict == "PARTIAL":
        message = _partial_data_message(scope, _paper_graph(state))
        print(message)
        if config.on_partial_data == "continue":
            accepted, source = True, "cli_policy_continue"
        elif config.on_partial_data == "stop":
            accepted, source = False, "cli_policy_stop"
        elif not sys.stdin.isatty():
            power_off_run_computation_instance(config)
            pipeline_state.mark_awaiting_confirmation(scope.scope_sha256)
            raise PartialDataAwaitingConfirmation(
                "Confirmation is required in non-interactive mode. Resume this output with "
                "--on-partial-data continue or --on-partial-data stop."
            )
        else:
            accepted = (
                input("Continue with the reproducible claim subgraph? [y/N] ")
                .strip()
                .casefold()
                in {"y", "yes"}
            )
            source = "interactive"
        decision_path = _record_partial_decision(
            config,
            scope,
            decision="continue" if accepted else "stop",
            source=source,
        )
        if not accepted:
            power_off_run_computation_instance(config)
            release_run_computation_instance(config)
            pipeline_state.mark_stopped_by_user(scope.scope_sha256)
            raise PartialDataStopped("Partial replication was stopped by the user.")
        if source == "interactive":
            power_on_run_computation_instance(config)

    outputs = [str(scope_path)]
    if decision_path is not None:
        outputs.append(str(decision_path))
    pipeline_state.update_stage_checkpoints(
        "partial_data_gate",
        {"scope_sha256": scope.scope_sha256, "verdict": scope.verdict},
    )
    pipeline_state.complete_stage("partial_data_gate", outputs)
    return {"execution_scope_path": str(scope_path)}


def codegen_agent_node(state: WorkflowState) -> dict[str, Any]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    scope = _execution_scope(state)
    _ensure_stage_scope(pipeline_state, "codegen_agent", scope.scope_sha256)
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
    scope_revision_path = (
        config.output / "codegen" / f"scope_revision_{scope.scope_sha256}.json"
    )
    completed_run_validation = pipeline_state.is_stage_completed("report_agents")
    infrastructure_resume = bool(codegen_checkpoints.get("infrastructure_resume"))
    graph = _paper_graph(state)
    active_node_ids = _active_node_ids(state)

    def validate_outputs(*, require_active: bool = True) -> None:
        if not codebase_dir.is_dir():
            raise RuntimeError(f"Completed codebase directory is missing: {codebase_dir}")
        codegen_plan = load_model(codegen_plan_path, CodegenPlan)
        update_ids = [update.node_id for update in codegen_plan.node_updates]
        if len(update_ids) != len(set(update_ids)):
            raise ValueError("Codegen plan contains duplicate node updates")
        unknown_update_ids = set(update_ids) - active_node_ids
        if unknown_update_ids:
            raise ValueError(
                f"Codegen plan updates inactive graph nodes: {sorted(unknown_update_ids)}"
            )
        cloud_data = _uses_cloud_data(config, codegen_plan)
        validate_codegen_remote_compute(
            codegen_plan,
            computation_provider_state_path,
            cloud_datasets=_active_cloud_datasets(state) if cloud_data else (),
            drive_provider=config.drive_provider,
            computation_provider=config.computation_provider,
            require_active=require_active,
        )
        load_model(dataset_patch_path, DatasetPatchFile)
        load_model(skill_corrections_path, SkillCorrectionsFile)

    if pipeline_state.is_stage_completed("codegen_agent"):
        validate_outputs(require_active=not completed_run_validation)
        codegen_plan = load_model(codegen_plan_path, CodegenPlan)
        attempt = int(pipeline_state.state["stages"]["codegen_agent"].get("attempts", 1))
        merge_node_updates(
            Path(state["node_state_path"]),
            graph,
            scope.paper_graph_sha256,
            f"codegen:{attempt:03d}",
            codegen_plan.node_updates,
        )
        if not transcript_path.is_file():
            raise RuntimeError(f"Completed codegen transcript is missing: {transcript_path}")
        print("resume codegen_agent stage: skipped (already completed)")
        return {"codebase_dir": str(codebase_dir), "scope_revision_requested": False}

    print("enter codegen stage")
    pipeline_state.start_stage("codegen_agent")
    _checkpoint_stage_scope(pipeline_state, "codegen_agent", scope.scope_sha256)
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
    cloud_pull_handoff = _cloud_pull_handoff_enabled(config)
    result_schema_path: Path | None = None
    result_path: Path | None = None
    if config.provider == "codex":
        result_schema_path = config.output / "prompts" / "codegen_agent_result.schema.json"
        result_path = config.output / "codegen" / "codegen_agent_result.json"
        write_json(result_schema_path, AgentStageResult.model_json_schema())
    prompt_path = render_prompt(
        "codegen/session_instructions.md",
        config.output / "prompts" / "codegen.md",
        codebase_dir=codebase_dir,
        paper_markdown=state["paper_markdown"],
        paper_graph_path=state["paper_graph_path"],
        execution_scope_path=state["execution_scope_path"],
        resources_path=state["resources_path"],
        data_dir=config.data,
        datasets=config.dataset_names,
        data_paths=config.dataset_paths,
        cloud_drive_enabled=config.clouddrive,
        cloud_dataset=", ".join(config.selected_cloud_datasets),
        cloud_datasets=_active_cloud_datasets(state),
        drive_provider=config.drive_provider,
        cloud_source=", ".join(config.selected_cloud_sources),
        cloud_sources=config.selected_cloud_sources,
        cloud_pull_handoff=cloud_pull_handoff,
        computation_provider_reference=config.computation_provider_reference,
        drive_reference=config.drive_reference,
        infrastructure_resume=infrastructure_resume,
        skills_dir=skills_dir(),
        codegen_plan_path=codegen_plan_path,
        dataset_patch_path=dataset_patch_path,
        skill_corrections_path=skill_corrections_path,
        scope_revision_path=scope_revision_path,
        computation_provider_state_path=computation_provider_state_path,
        local_resources=resources,
        gpu_info=resources["gpus"],
        computation_provider=config.computation_provider,
        structured_stage_result=result_schema_path is not None,
        resuming=previous_status in {"running", "failed", "invalidated"},
    )
    if cloud_pull_handoff and not _cloud_drive_materialization_completed(config):
        assert result_schema_path is not None
        assert result_path is not None
        session_id = _run_codegen_cloud_pull_handoff(
            config=config,
            codebase_dir=codebase_dir,
            prompt_path=prompt_path,
            transcript_path=transcript_path,
            stage_result_schema_path=result_schema_path,
            stage_result_path=result_path,
        )
    else:
        session_id = run_agent(
            provider=config.provider,
            prompt_path=prompt_path,
            working_dir=codebase_dir,
            transcript_path=transcript_path,
            siliconflow_config_path=config.siliconflow_config,
            codex_model=config.codex_model,
            codex_reasoning_effort=config.codex_reasoning_effort,
            output_schema_path=result_schema_path,
            output_last_message_path=result_path,
        )
    if result_path is not None:
        stage_result = load_model(result_path, AgentStageResult)
        if stage_result.status != "completed" and scope_revision_path.is_file():
            revision = load_model(scope_revision_path, GraphScopeRevisionIssues)
            if revision.scope_sha256 != scope.scope_sha256:
                raise RuntimeError("Codegen scope revision is bound to a different scope")
            active_ids = set(scope.runnable_node_ids)
            unknown_ids = {
                node_id
                for issue in revision.issues
                for node_id in issue.node_ids
                if node_id not in active_ids
            }
            if unknown_ids:
                raise RuntimeError(
                    f"Codegen scope revision references inactive nodes: {sorted(unknown_ids)}"
                )
            pipeline_state.invalidate_stages(
                [
                    "data_availability_agent",
                    "partial_data_gate",
                    "codegen_agent",
                    "audit_agent",
                    "cohort_refine_agent",
                    "plan_agent",
                    "replicate_agent",
                    "report_agents",
                ],
                f"Codegen discovered unavailable source data: {scope_revision_path}",
            )
            return {
                "codebase_dir": str(codebase_dir),
                "scope_revision_requested": True,
            }
        _require_agent_stage_completion(result_path, "codegen_agent")
    _validate_agent_artifacts_with_resume(
        config=config,
        stage_name="codegen_agent",
        session_id=session_id,
        working_dir=codebase_dir,
        transcript_path=transcript_path,
        artifact_paths=[
            codebase_dir,
            codegen_plan_path,
            dataset_patch_path,
            skill_corrections_path,
        ],
        validate=validate_outputs,
        result_schema_path=result_schema_path,
        result_path=result_path,
    )
    codegen_plan = load_model(codegen_plan_path, CodegenPlan)
    attempt = int(pipeline_state.state["stages"]["codegen_agent"].get("attempts", 1))
    merge_node_updates(
        Path(state["node_state_path"]),
        graph,
        scope.paper_graph_sha256,
        f"codegen:{attempt:03d}",
        codegen_plan.node_updates,
    )
    outputs = [
        str(codebase_dir),
        str(codegen_plan_path),
        str(dataset_patch_path),
        str(skill_corrections_path),
        str(transcript_path),
    ]
    if result_path is not None:
        outputs.append(str(result_path))
    pipeline_state.complete_stage(
        "codegen_agent",
        outputs,
    )
    return {"codebase_dir": str(codebase_dir), "scope_revision_requested": False}


def codegen_route(state: WorkflowState) -> str:
    if state.get("scope_revision_requested", False):
        return "data_availability_agent"
    return "audit_agent"


def audit_agent_node(state: WorkflowState) -> dict[str, str | bool]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    scope = _execution_scope(state)
    _ensure_stage_scope(pipeline_state, "audit_agent", scope.scope_sha256)
    codegen_stage = pipeline_state.state["stages"].get("codegen_agent", {})
    codegen_attempt = int(codegen_stage.get("attempts", 0))
    if codegen_stage.get("status") != "completed" or codegen_attempt < 1:
        raise RuntimeError("Preprocessing audit requires a completed codegen attempt")

    checkpoints = pipeline_state.get_stage_checkpoints("audit_agent")
    cohort_refine_checkpoints = pipeline_state.get_stage_checkpoints("cohort_refine_agent")
    completed_refine_round = int(cohort_refine_checkpoints.get("completed_round", 0))
    audited_codegen_attempt = checkpoints.get("audited_codegen_attempt")
    audited_refine_round = int(checkpoints.get("audited_refine_round", 0))
    if (
        pipeline_state.is_stage_completed("audit_agent")
        and audited_codegen_attempt == codegen_attempt
        and audited_refine_round == completed_refine_round
    ):
        report_path = Path(str(checkpoints.get("report_path", "")))
        audit_report = read_audit_report(report_path)
        verdict = str(audit_report["verdict"])
        if verdict != checkpoints.get("verdict"):
            raise RuntimeError(f"Audit report verdict does not match its checkpoint: {report_path}")
        _merge_audit_node_updates(
            state,
            f"audit:{int(checkpoints.get('scientific_attempt', 1)):03d}",
            audit_report,
        )
        print("resume audit_agent stage: skipped (already completed)")
        return {
            "audit_verdict": verdict,
            "audit_report_path": str(report_path),
            "audit_refinement_exhausted": bool(checkpoints.get("refinement_exhausted", False)),
            "audit_issue_kinds": list(checkpoints.get("issue_kinds", [])),
        }

    refine_rounds_used = int(checkpoints.get("refine_rounds_used", 0))

    print("enter audit agent stage")
    previous_audit_status = pipeline_state.get_stage_status("audit_agent")
    pipeline_state.start_stage("audit_agent")
    _checkpoint_stage_scope(pipeline_state, "audit_agent", scope.scope_sha256)
    scientific_attempt = refine_rounds_used + 1
    attempt_dir = config.output / "codegen" / "audit" / f"attempt_{scientific_attempt:03d}"
    scripts_dir = attempt_dir / "scripts"
    results_dir = attempt_dir / "results"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    report_path = attempt_dir / "audit_report.json"
    transcript_path = attempt_dir / "audit_transcript.jsonl"
    codegen_plan = load_model(Path(state["codebase_dir"]) / "codegen_plan.json", CodegenPlan)
    cloud_data = _uses_cloud_data(config, codegen_plan)
    cloud_drive_state = validate_codegen_remote_compute(
        codegen_plan,
        config.output / "remote_compute" / "instance.json",
        cloud_datasets=_active_cloud_datasets(state) if cloud_data else (),
        drive_provider=config.drive_provider,
        computation_provider=config.computation_provider,
    )
    remote_working_dir = (
        codegen_plan.remote_compute.remote_working_dir
        if cloud_data and codegen_plan.remote_compute is not None
        else None
    )
    remote_audit_dir = (
        f"{remote_working_dir.rstrip('/')}/preprocessing_audit/attempt_{scientific_attempt:03d}"
        if remote_working_dir
        else None
    )
    prompt_path = render_prompt(
        "cohort_refine/audit_session_instructions.md",
        config.output / "prompts" / f"audit_attempt_{scientific_attempt:03d}.md",
        paper_markdown=state["paper_markdown"],
        paper_graph_path=state["paper_graph_path"],
        execution_scope_path=state["execution_scope_path"],
        codegen_plan_path=Path(state["codebase_dir"]) / "codegen_plan.json",
        codebase_dir=state["codebase_dir"],
        data_dir=config.data,
        datasets=config.dataset_names,
        data_paths=config.dataset_paths,
        cloud_drive_enabled=cloud_data,
        cloud_dataset=", ".join(config.selected_cloud_datasets),
        cloud_datasets=_active_cloud_datasets(state),
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
    session_id = run_agent(
        provider=config.provider,
        prompt_path=prompt_path,
        working_dir=attempt_dir,
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )
    resume_index = 1
    while True:
        try:
            audit_report = read_audit_report(report_path)
            verdict = str(audit_report["verdict"])
            active_ids = set(scope.runnable_node_ids)
            for issue in audit_report["issues"]:
                if issue["node_id"] not in active_ids:
                    raise RuntimeError(
                        "Audit issue references a node outside the execution scope: "
                        f"{issue['node_id']}"
                    )
            break
        except RuntimeError as exc:
            if config.provider != "codex":
                raise
            if session_id is None:
                raise RuntimeError(
                    "Codex audit turn returned without a valid report or session ID"
                ) from exc
            resume_prompt_path = (
                config.output
                / "prompts"
                / f"audit_attempt_{scientific_attempt:03d}_resume_{resume_index:03d}.md"
            )
            while resume_prompt_path.exists():
                resume_index += 1
                resume_prompt_path = (
                    config.output
                    / "prompts"
                    / f"audit_attempt_{scientific_attempt:03d}_resume_{resume_index:03d}.md"
                )
            render_prompt(
                "cohort_refine/audit_resume_instructions.md",
                resume_prompt_path,
                artifact_validation_error=str(exc),
                report_path=report_path,
                results_dir=results_dir,
                remote_audit_dir=remote_audit_dir,
                remote_compute_state_path=(config.output / "remote_compute" / "instance.json"),
            )
            run_agent(
                provider=config.provider,
                prompt_path=resume_prompt_path,
                working_dir=attempt_dir,
                transcript_path=transcript_path,
                siliconflow_config_path=config.siliconflow_config,
                codex_model=config.codex_model,
                codex_reasoning_effort=config.codex_reasoning_effort,
                resume_session_id=session_id,
            )
            resume_index += 1
    issue_kinds = sorted(
        {issue.get("route", "preprocessing_fix") for issue in audit_report["issues"]}
    )
    source_revision = "source_unavailable" in issue_kinds
    checkpoint = {
        "audited_codegen_attempt": codegen_attempt,
        "audited_refine_round": completed_refine_round,
        "verdict": verdict,
        "report_path": str(report_path),
        "refine_rounds_used": refine_rounds_used,
        "issue_kinds": issue_kinds,
        "refinement_exhausted": (
            verdict == "FAIL" and refine_rounds_used >= MAX_COHORT_REFINE_ROUNDS
        ),
        "scientific_attempt": scientific_attempt,
    }
    outputs = [str(attempt_dir), str(report_path), str(transcript_path)]
    if (
        verdict == "FAIL"
        and not source_revision
        and not checkpoint["refinement_exhausted"]
    ):
        checkpoint["refine_rounds_used"] = refine_rounds_used + 1
    _merge_audit_node_updates(state, f"audit:{scientific_attempt:03d}", audit_report)
    pipeline_state.update_stage_checkpoints("audit_agent", checkpoint)
    pipeline_state.complete_stage("audit_agent", outputs)
    if source_revision:
        pipeline_state.invalidate_stages(
            [
                "data_availability_agent",
                "partial_data_gate",
                "codegen_agent",
                "audit_agent",
                "cohort_refine_agent",
                "plan_agent",
                "replicate_agent",
                "report_agents",
            ],
            f"Audit discovered unavailable source data: {report_path}",
        )
    return {
        "audit_verdict": verdict,
        "audit_report_path": str(report_path),
        "audit_refinement_exhausted": checkpoint["refinement_exhausted"],
        "audit_issue_kinds": issue_kinds,
    }


def audit_route(state: WorkflowState) -> str:
    verdict = state.get("audit_verdict")
    if verdict not in {"PASS", "FAIL"}:
        raise RuntimeError(f"Invalid preprocessing audit verdict: {verdict!r}")
    if "source_unavailable" in state.get("audit_issue_kinds", []):
        return "data_availability_agent"
    if verdict == "PASS" or state.get("audit_refinement_exhausted", False):
        return "plan_agent"
    return "cohort_refine_agent"


def cohort_refine_agent_node(state: WorkflowState) -> dict[str, str]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    scope = _execution_scope(state)
    _ensure_stage_scope(pipeline_state, "cohort_refine_agent", scope.scope_sha256)
    audit_checkpoints = pipeline_state.get_stage_checkpoints("audit_agent")
    audit_report_path = Path(str(audit_checkpoints.get("report_path", "")))
    if (
        not pipeline_state.is_stage_completed("audit_agent")
        or audit_checkpoints.get("verdict") != "FAIL"
        or audit_checkpoints.get("refinement_exhausted", False)
        or read_audit_verdict(audit_report_path) != "FAIL"
    ):
        raise RuntimeError("Cohort refinement requires a non-exhausted failed audit")

    refine_round = int(audit_checkpoints.get("refine_rounds_used", 0))
    if not 1 <= refine_round <= MAX_COHORT_REFINE_ROUNDS:
        raise RuntimeError(f"Invalid cohort refinement round: {refine_round}")
    checkpoints = pipeline_state.get_stage_checkpoints("cohort_refine_agent")
    if (
        pipeline_state.is_stage_completed("cohort_refine_agent")
        and checkpoints.get("completed_round") == refine_round
        and checkpoints.get("audit_report_path") == str(audit_report_path)
    ):
        refined_plan = load_model(
            Path(state["codebase_dir"]) / "codegen_plan.json",
            CodegenPlan,
        )
        merge_node_updates(
            Path(state["node_state_path"]),
            _paper_graph(state),
            scope.paper_graph_sha256,
            f"cohort_refine:{refine_round:03d}",
            refined_plan.node_updates,
        )
        print("resume cohort_refine_agent stage: skipped (already completed)")
        return {"codebase_dir": state["codebase_dir"]}

    print("enter cohort refine agent stage")
    previous_status = pipeline_state.get_stage_status("cohort_refine_agent")
    pipeline_state.invalidate_stages(
        ["plan_agent", "replicate_agent", "report_agents"],
        f"Cohort preprocessing refined after failed audit: {audit_report_path}",
    )
    pipeline_state.start_stage("cohort_refine_agent")
    _checkpoint_stage_scope(pipeline_state, "cohort_refine_agent", scope.scope_sha256)
    attempt_dir = config.output / "codegen" / "cohort_refine" / f"attempt_{refine_round:03d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = attempt_dir / "cohort_refine_transcript.jsonl"
    codebase_dir = Path(state["codebase_dir"])
    codegen_plan_path = codebase_dir / "codegen_plan.json"
    codegen_plan = load_model(codegen_plan_path, CodegenPlan)
    cloud_data = _uses_cloud_data(config, codegen_plan)
    cloud_drive_state = validate_codegen_remote_compute(
        codegen_plan,
        config.output / "remote_compute" / "instance.json",
        cloud_datasets=_active_cloud_datasets(state) if cloud_data else (),
        drive_provider=config.drive_provider,
        computation_provider=config.computation_provider,
    )
    remote_working_dir = (
        codegen_plan.remote_compute.remote_working_dir
        if cloud_data and codegen_plan.remote_compute is not None
        else None
    )
    prompt_path = render_prompt(
        "cohort_refine/session_instructions.md",
        config.output / "prompts" / f"cohort_refine_attempt_{refine_round:03d}.md",
        paper_markdown=state["paper_markdown"],
        paper_graph_path=state["paper_graph_path"],
        execution_scope_path=state["execution_scope_path"],
        codebase_dir=codebase_dir,
        codegen_plan_path=codegen_plan_path,
        audit_report_path=audit_report_path,
        data_dir=config.data,
        datasets=config.dataset_names,
        data_paths=config.dataset_paths,
        cloud_drive_enabled=cloud_data,
        cloud_dataset=", ".join(config.selected_cloud_datasets),
        cloud_datasets=_active_cloud_datasets(state),
        drive_provider=config.drive_provider,
        computation_provider_reference=config.computation_provider_reference,
        drive_reference=config.drive_reference,
        remote_compute_state_path=config.output / "remote_compute" / "instance.json",
        remote_dataset_dir=(cloud_drive_state.get("target_path") if cloud_drive_state else None),
        remote_working_dir=remote_working_dir,
        skills_dir=skills_dir(),
        refine_round=refine_round,
        resuming=previous_status in {"running", "failed"},
    )
    session_id = run_agent(
        provider=config.provider,
        prompt_path=prompt_path,
        working_dir=codebase_dir,
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )
    _validate_agent_artifacts_with_resume(
        config=config,
        stage_name=f"cohort_refine_attempt_{refine_round:03d}",
        session_id=session_id,
        working_dir=codebase_dir,
        transcript_path=transcript_path,
        artifact_paths=[codegen_plan_path],
        validate=lambda: load_model(codegen_plan_path, CodegenPlan),
    )
    refined_plan = load_model(codegen_plan_path, CodegenPlan)
    unknown_update_ids = {
        update.node_id for update in refined_plan.node_updates
    } - set(scope.runnable_node_ids)
    if unknown_update_ids:
        raise ValueError(
            f"Cohort refinement updates inactive graph nodes: {sorted(unknown_update_ids)}"
        )
    merge_node_updates(
        Path(state["node_state_path"]),
        _paper_graph(state),
        scope.paper_graph_sha256,
        f"cohort_refine:{refine_round:03d}",
        refined_plan.node_updates,
    )
    pipeline_state.update_stage_checkpoints(
        "cohort_refine_agent",
        {
            "completed_round": refine_round,
            "audit_report_path": str(audit_report_path),
        },
    )
    pipeline_state.complete_stage(
        "cohort_refine_agent",
        [str(codebase_dir), str(attempt_dir), str(transcript_path)],
    )
    return {"codebase_dir": str(codebase_dir)}


def plan_agent_node(state: WorkflowState) -> dict[str, str]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    scope = _execution_scope(state)
    _ensure_stage_scope(pipeline_state, "plan_agent", scope.scope_sha256)
    replicate_plan_path = config.output / "plan" / "replicate_plan.json"
    transcript_path = config.output / "plan" / "plan_transcript.jsonl"
    graph = _paper_graph(state)

    def validate_outputs() -> None:
        plan = load_model(replicate_plan_path, ReplicationPlan)
        validate_replication_plan(graph, scope, plan)
        cloud_data = _uses_cloud_data(config, plan)
        validate_codegen_remote_compute(
            plan,
            config.output / "remote_compute" / "instance.json",
            cloud_datasets=_active_cloud_datasets(state) if cloud_data else (),
            drive_provider=config.drive_provider,
            computation_provider=config.computation_provider,
            require_active=not pipeline_state.is_stage_completed("report_agents"),
        )

    if pipeline_state.is_stage_completed("plan_agent"):
        validate_outputs()
        if not transcript_path.is_file():
            raise RuntimeError(f"Completed plan transcript is missing: {transcript_path}")
        print("resume plan_agent stage: skipped (already completed)")
        return {"replicate_plan_path": str(replicate_plan_path)}

    print("enter plan stage")
    pipeline_state.start_stage("plan_agent")
    _checkpoint_stage_scope(pipeline_state, "plan_agent", scope.scope_sha256)
    resources = json.loads(Path(state["resources_path"]).read_text(encoding="utf-8"))
    cloud_data = config.clouddrive
    if config.clouddrive and config.data is not None:
        codegen_plan = load_model(Path(state["codebase_dir"]) / "codegen_plan.json", CodegenPlan)
        cloud_data = _uses_cloud_data(config, codegen_plan)
    prompt_path = render_prompt(
        "plan/session_instructions.md",
        config.output / "prompts" / "plan.md",
        codebase_dir=state["codebase_dir"],
        paper_markdown=state["paper_markdown"],
        data_dir=config.data,
        datasets=config.dataset_names,
        data_paths=config.dataset_paths,
        cloud_drive_enabled=cloud_data,
        cloud_dataset=", ".join(config.selected_cloud_datasets),
        cloud_datasets=_active_cloud_datasets(state),
        drive_provider=config.drive_provider,
        computation_provider=config.computation_provider,
        computation_provider_reference=config.computation_provider_reference,
        drive_reference=config.drive_reference,
        paper_graph_path=state["paper_graph_path"],
        execution_scope_path=state["execution_scope_path"],
        skills_dir=skills_dir(),
        computation_provider_state_path=(config.output / "remote_compute" / "instance.json"),
        replicate_plan_path=replicate_plan_path,
        paper_graph=graph.model_dump(mode="json"),
        runnable_node_ids=scope.runnable_node_ids,
        topological_layers=replication_topological_layers(graph, scope),
        gpu_info=resources["gpus"],
    )
    session_id = run_agent(
        provider=config.provider,
        prompt_path=prompt_path,
        working_dir=Path(state["codebase_dir"]),
        transcript_path=transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )
    _validate_agent_artifacts_with_resume(
        config=config,
        stage_name="plan_agent",
        session_id=session_id,
        working_dir=Path(state["codebase_dir"]),
        transcript_path=transcript_path,
        artifact_paths=[replicate_plan_path],
        validate=validate_outputs,
    )
    pipeline_state.complete_stage(
        "plan_agent",
        [str(replicate_plan_path), str(transcript_path)],
    )
    return {"replicate_plan_path": str(replicate_plan_path)}


def replicate_agent_node(state: WorkflowState) -> dict[str, Any]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    scope = _execution_scope(state)
    _ensure_stage_scope(pipeline_state, "replicate_agent", scope.scope_sha256)
    transcript_path = config.output / "replication" / "replication_transcript.jsonl"
    plan = load_model(Path(state["replicate_plan_path"]), ReplicationPlan)
    graph = _paper_graph(state)
    validate_replication_plan(graph, scope, plan)
    cloud_data = _uses_cloud_data(config, plan)
    if pipeline_state.is_stage_completed("replicate_agent"):
        validate_codegen_remote_compute(
            plan,
            config.output / "remote_compute" / "instance.json",
            cloud_datasets=_active_cloud_datasets(state) if cloud_data else (),
            drive_provider=config.drive_provider,
            computation_provider=config.computation_provider,
            require_active=not pipeline_state.is_stage_completed("report_agents"),
        )
        try:
            validate_replication_artifacts(state)
            if not transcript_path.is_file():
                raise RuntimeError(
                    f"Completed replication transcript is missing: {transcript_path}"
                )
        except (OSError, RuntimeError, ValueError) as exc:
            pipeline_state.invalidate_stages(
                ["replicate_agent", "report_agents"],
                f"Completed replication artifacts failed resume validation: {exc}",
            )
        else:
            print("resume replicate_agent stage: skipped (already completed)")
            return {}

    if not pipeline_state.is_stage_completed("replicate_agent"):
        _cloud_pull(
            config,
            use_cloud=cloud_data,
            datasets=_active_cloud_datasets(state),
        )
    validate_codegen_remote_compute(
        plan,
        config.output / "remote_compute" / "instance.json",
        cloud_datasets=_active_cloud_datasets(state) if cloud_data else (),
        drive_provider=config.drive_provider,
        computation_provider=config.computation_provider,
        require_active=not pipeline_state.is_stage_completed("report_agents"),
    )

    resume_state = _inspect_completed_replication_nodes(state)
    print(
        "replication node inspection: "
        f"completed={resume_state['completed_node_ids']}, "
        f"pending={resume_state['pending_node_ids']}"
    )
    print("enter replicate stage")
    pipeline_state.start_stage("replicate_agent")
    _checkpoint_stage_scope(pipeline_state, "replicate_agent", scope.scope_sha256)
    pipeline_state.update_stage_checkpoints(
        "replicate_agent",
        {"completed_node_ids": resume_state["completed_node_ids"]},
    )
    runnable = set(scope.runnable_node_ids)
    prompt_path = render_prompt(
        "replication/session_instructions.md",
        config.output / "prompts" / "replicate.md",
        replicate_plan_path=state["replicate_plan_path"],
        paper_markdown=state["paper_markdown"],
        codebase_dir=state["codebase_dir"],
        replication_dir=config.output / "replication",
        skills_dir=skills_dir(),
        computation_provider_state_path=(config.output / "remote_compute" / "instance.json"),
        cloud_drive_enabled=cloud_data,
        cloud_dataset=", ".join(config.selected_cloud_datasets),
        cloud_datasets=_active_cloud_datasets(state),
        drive_provider=config.drive_provider,
        computation_provider=config.computation_provider,
        computation_provider_reference=config.computation_provider_reference,
        drive_reference=config.drive_reference,
        smart=config.smart_replicate,
        execution_scope_path=state["execution_scope_path"],
        paper_graph_path=state["paper_graph_path"],
        node_state_path=state["node_state_path"],
        resume_state_json=json.dumps(resume_state, ensure_ascii=False, indent=2),
        smart_anchors=json.dumps(
            [
                {
                    "claim_id": claim.id,
                    "method": claim.method,
                    "paper_result": claim.paper_result,
                    "provenance": claim.provenance,
                }
                for claim in graph.claims
                if claim.id in runnable and claim.paper_result is not None
            ],
            ensure_ascii=False,
            indent=2,
        ),
    )
    outputs: list[str] = []

    def validate_outputs() -> None:
        outputs[:] = validate_replication_artifacts(state)

    try:
        session_id = run_agent(
            provider=config.provider,
            prompt_path=prompt_path,
            working_dir=Path(state["codebase_dir"]),
            transcript_path=transcript_path,
            siliconflow_config_path=config.siliconflow_config,
            codex_model=config.codex_model,
            codex_reasoning_effort=config.codex_reasoning_effort,
        )
        if config.provider == "codex" and session_id is None:
            raise RuntimeError("Codex replication turn did not return a session ID")
        _validate_agent_artifacts_with_resume(
            config=config,
            stage_name="replicate_agent",
            session_id=session_id,
            working_dir=Path(state["codebase_dir"]),
            transcript_path=transcript_path,
            artifact_paths=[
                config.output / "replication" / "replication_log.json",
                config.output / "replication" / "evidence_summary.json",
            ],
            validate=validate_outputs,
        )
    finally:
        power_off_run_computation_instance(config)
    pipeline_state.complete_stage(
        "replicate_agent",
        [*outputs, str(transcript_path)],
    )
    return {}


def report_agents_node(state: WorkflowState) -> dict[str, str]:
    config = state["config"]
    pipeline_state = PipelineState(config.output)
    scope = _execution_scope(state)
    _ensure_stage_scope(pipeline_state, "report_agents", scope.scope_sha256)
    graph = _paper_graph(state)
    node_state = load_node_state(Path(state["node_state_path"]))
    report_path = config.output / "report" / "reproduction_report.md"
    claims_dir = config.output / "report" / "claims"
    final_transcript_path = config.output / "report" / "report_transcript.jsonl"
    claims_dir.mkdir(parents=True, exist_ok=True)
    if pipeline_state.is_stage_completed("report_agents"):
        if not report_path.is_file() or not report_path.read_text(encoding="utf-8").strip():
            raise RuntimeError(f"Completed reproduction report is missing: {report_path}")
        for claim in graph.claims:
            fragment_path = claims_dir / f"{claim.id}.md"
            validate_claim_report(fragment_path.read_text(encoding="utf-8"), claim.id)
            transcript_path = claims_dir / f"{claim.id}_transcript.jsonl"
            if not transcript_path.is_file():
                raise RuntimeError(f"Completed report transcript is missing: {transcript_path}")
        if final_transcript_path.is_file():
            pipeline_state.mark_completed(partial=scope.verdict == "PARTIAL")
            print("resume report_agents stage: skipped (already completed)")
            return {"report_path": str(report_path)}
        print("resume report_agents stage: reindexing legacy final report")

    print("enter report stage")
    pipeline_state.start_stage("report_agents")
    _checkpoint_stage_scope(pipeline_state, "report_agents", scope.scope_sha256)
    completed_claims = set(
        pipeline_state.get_stage_checkpoints("report_agents").get("completed_claims", [])
    )
    transcript_paths: list[str] = []
    blocked_by_id = {item.node_id: item for item in scope.blocked_nodes}
    for claim in graph.claims:
        fragment_path = claims_dir / f"{claim.id}.md"
        transcript_path = claims_dir / f"{claim.id}_transcript.jsonl"
        transcript_paths.append(str(transcript_path))
        if claim.id in completed_claims:
            try:
                if not transcript_path.is_file():
                    raise RuntimeError(
                        f"Checkpointed report transcript is missing: {transcript_path}"
                    )
                validate_claim_report(fragment_path.read_text(encoding="utf-8"), claim.id)
            except (OSError, RuntimeError, ValueError):
                completed_claims.remove(claim.id)
                pipeline_state.update_stage_checkpoints(
                    "report_agents",
                    {
                        "completed_claims": [
                            item.id for item in graph.claims if item.id in completed_claims
                        ]
                    },
                )
                print(f"resume report claim {claim.id}: checkpoint invalid; rerunning")
            else:
                print(f"resume report claim {claim.id}: skipped (already completed)")
                continue
        ancestor_ids = graph_ancestors(graph, claim.id)
        upstream_updates = [
            update.model_dump(mode="json")
            for update in node_state.updates
            if update.node_id in ancestor_ids
        ]
        blockers = [
            item.model_dump(mode="json")
            for node_id, item in blocked_by_id.items()
            if node_id in ancestor_ids
        ]
        prompt_path = render_prompt(
            "report/session_instructions.md",
            config.output / "prompts" / f"report_{claim.id}.md",
            claim_report_path=fragment_path,
            claim_id=claim.id,
            paper_markdown=state["paper_markdown"],
            paper_artifacts=config.output / "preprocessing" / "artifacts",
            paper_graph_path=state["paper_graph_path"],
            node_state_path=state["node_state_path"],
            execution_scope_path=state["execution_scope_path"],
            replicate_plan_path=state["replicate_plan_path"],
            codebase_dir=state["codebase_dir"],
            replication_dir=config.output / "replication",
            replication_log_path=(config.output / "replication" / "replication_log.json"),
            evidence_summary_path=(config.output / "replication" / "evidence_summary.json"),
            claim_json=json.dumps(claim.model_dump(mode="json"), ensure_ascii=False, indent=2),
            ancestor_node_ids=sorted(ancestor_ids),
            upstream_updates_json=json.dumps(
                upstream_updates,
                ensure_ascii=False,
                indent=2,
            ),
            scope_blockers_json=json.dumps(blockers, ensure_ascii=False, indent=2),
            lineage_issues_json=json.dumps(
                collect_lineage_issues(graph, node_state, claim.id),
                ensure_ascii=False,
                indent=2,
            ),
        )

        def validate_outputs() -> None:
            if not fragment_path.is_file() or not fragment_path.read_text(encoding="utf-8").strip():
                raise RuntimeError(f"Report agent did not write claim fragment: {fragment_path}")
            validate_claim_report(fragment_path.read_text(encoding="utf-8"), claim.id)

        session_id = run_agent(
            provider=config.provider,
            prompt_path=prompt_path,
            working_dir=config.output,
            transcript_path=transcript_path,
            siliconflow_config_path=config.siliconflow_config,
            codex_model=config.codex_model,
            codex_reasoning_effort=config.codex_reasoning_effort,
        )
        _validate_agent_artifacts_with_resume(
            config=config,
            stage_name=f"report_{claim.id}",
            session_id=session_id,
            working_dir=config.output,
            transcript_path=transcript_path,
            artifact_paths=[fragment_path],
            validate=validate_outputs,
        )
        completed_claims.add(claim.id)
        pipeline_state.update_stage_checkpoints(
            "report_agents",
            {
                "completed_claims": [item.id for item in graph.claims if item.id in completed_claims]
            },
        )

    claim_index = [
        {
            "claim_id": claim.id,
            "type": claim.model_dump(mode="json").get("role"),
            "paper_result": claim.paper_result,
            "claim_report_path": str(Path("report") / "claims" / f"{claim.id}.md"),
        }
        for claim in graph.claims
    ]
    node_issue_index = []
    for node in graph.nodes:
        issues = []
        for update in node_state.updates:
            if update.node_id != node.id:
                continue
            issues.extend(
                {
                    "source": update.source,
                    "description": issue.description,
                }
                for issue in update.issues
            )
        node_issue_index.append({"node_id": node.id, "issues": issues})

    final_prompt_path = render_prompt(
        "report/final_session_instructions.md",
        config.output / "prompts" / "report_final.md",
        report_path=report_path,
        run_dir=config.output,
        paper_markdown=state["paper_markdown"],
        paper_artifacts=config.output / "preprocessing" / "artifacts",
        paper_graph_path=state["paper_graph_path"],
        node_state_path=state["node_state_path"],
        execution_scope_path=state["execution_scope_path"],
        replication_log_path=config.output / "replication" / "replication_log.json",
        claims_dir=claims_dir,
        claim_index_json=json.dumps(claim_index, ensure_ascii=False, indent=2),
        node_issue_index_json=json.dumps(
            node_issue_index,
            ensure_ascii=False,
            indent=2,
        ),
    )

    def validate_final_report_output() -> None:
        if not report_path.is_file() or not report_path.read_text(encoding="utf-8").strip():
            raise RuntimeError(f"Final report agent did not write report: {report_path}")

    session_id = run_agent(
        provider=config.provider,
        prompt_path=final_prompt_path,
        working_dir=config.output,
        transcript_path=final_transcript_path,
        siliconflow_config_path=config.siliconflow_config,
        codex_model=config.codex_model,
        codex_reasoning_effort=config.codex_reasoning_effort,
    )
    _validate_agent_artifacts_with_resume(
        config=config,
        stage_name="report_final",
        session_id=session_id,
        working_dir=config.output,
        transcript_path=final_transcript_path,
        artifact_paths=[report_path],
        validate=validate_final_report_output,
    )
    pipeline_state.complete_stage(
        "report_agents",
        [
            str(report_path),
            *(str(claims_dir / f"{claim.id}.md") for claim in graph.claims),
            *transcript_paths,
            str(final_transcript_path),
        ],
    )
    scope_path = Path(state["execution_scope_path"])
    partial = (
        scope_path.is_file()
        and load_model(scope_path, GraphExecutionScope).verdict == "PARTIAL"
    )
    pipeline_state.mark_completed(partial=partial)
    return {"report_path": str(report_path)}


def create_workflow():
    builder = StateGraph(WorkflowState)
    builder.add_node("preflight", preflight_node)
    builder.add_node("preprocess_pdf", preprocess_pdf_node)
    builder.add_node("preprocessing_agent", preprocessing_agent_node)
    builder.add_node("data_availability_agent", data_availability_agent_node)
    builder.add_node("partial_data_gate", partial_data_gate_node)
    builder.add_node("codegen_agent", codegen_agent_node)
    builder.add_node("audit_agent", audit_agent_node)
    builder.add_node("cohort_refine_agent", cohort_refine_agent_node)
    builder.add_node("plan_agent", plan_agent_node)
    builder.add_node("replicate_agent", replicate_agent_node)
    builder.add_node("report_agents", report_agents_node)
    builder.add_edge(START, "preflight")
    builder.add_edge("preflight", "preprocess_pdf")
    builder.add_edge("preprocess_pdf", "preprocessing_agent")
    builder.add_edge("preprocessing_agent", "data_availability_agent")
    builder.add_edge("data_availability_agent", "partial_data_gate")
    builder.add_edge("partial_data_gate", "codegen_agent")
    builder.add_conditional_edges(
        "codegen_agent",
        codegen_route,
        {
            "audit_agent": "audit_agent",
            "data_availability_agent": "data_availability_agent",
        },
    )
    builder.add_conditional_edges(
        "audit_agent",
        audit_route,
        {
            "plan_agent": "plan_agent",
            "cohort_refine_agent": "cohort_refine_agent",
            "data_availability_agent": "data_availability_agent",
        },
    )
    builder.add_edge("cohort_refine_agent", "audit_agent")
    builder.add_edge("plan_agent", "replicate_agent")
    builder.add_edge("replicate_agent", "report_agents")
    builder.add_edge("report_agents", END)
    return builder.compile()
