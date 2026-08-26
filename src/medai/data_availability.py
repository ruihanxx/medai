"""Validation and orchestration-owned derivation of replication execution scope."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from medai.models import (
    BlockedExperiment,
    DataAvailabilityReport,
    ExecutionScope,
    ExperimentTodo,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def derive_execution_scope(
    experiments: ExperimentTodo,
    report: DataAvailabilityReport,
    report_sha256: str,
) -> ExecutionScope:
    """Validate complete agent coverage and derive dependency-closed scope."""
    experiment_ids = [item.experiment_id for item in experiments.experiments]
    known_ids = set(experiment_ids)
    expected_pairs = {
        (experiment.experiment_id, dataset.name.casefold())
        for experiment in experiments.experiments
        for dataset in experiment.datasets
    }
    actual_pairs = [
        (item.experiment_id, item.dataset.casefold()) for item in report.requirements
    ]
    if len(actual_pairs) != len(set(actual_pairs)):
        raise ValueError("data availability requirements contain duplicate experiment/dataset pairs")
    if set(actual_pairs) != expected_pairs:
        missing = sorted(expected_pairs - set(actual_pairs))
        extra = sorted(set(actual_pairs) - expected_pairs)
        raise ValueError(
            f"data availability coverage mismatch; missing={missing!r}, extra={extra!r}"
        )

    dependency_ids = [item.experiment_id for item in report.dependencies]
    if len(dependency_ids) != len(set(dependency_ids)):
        raise ValueError("data availability dependencies contain duplicate experiment IDs")
    if set(dependency_ids) != known_ids:
        raise ValueError("data availability dependencies must cover every experiment exactly once")
    dependencies = {item.experiment_id: item.depends_on for item in report.dependencies}
    unknown_dependencies = sorted(
        {dependency for values in dependencies.values() for dependency in values} - known_ids
    )
    if unknown_dependencies:
        raise ValueError(f"data availability dependencies reference unknown IDs: {unknown_dependencies}")
    _assert_acyclic(dependencies, experiment_ids)

    direct_status: dict[str, str] = {experiment_id: "available" for experiment_id in experiment_ids}
    direct_blockers: dict[str, list[str]] = {experiment_id: [] for experiment_id in experiment_ids}
    for requirement in report.requirements:
        if requirement.status == "unknown":
            direct_status[requirement.experiment_id] = "unknown"
        elif (
            requirement.status == "source_blocked"
            and direct_status[requirement.experiment_id] != "unknown"
        ):
            direct_status[requirement.experiment_id] = "source_blocked"
        if requirement.status != "available":
            direct_blockers[requirement.experiment_id].append(
                f"{requirement.dataset}: {requirement.required_content} — {requirement.evidence}"
            )

    resolved: dict[str, str] = {}

    def resolve(experiment_id: str) -> str:
        if experiment_id in resolved:
            return resolved[experiment_id]
        inherited = [resolve(parent) for parent in dependencies[experiment_id]]
        if direct_status[experiment_id] == "unknown" or "unknown" in inherited:
            status = "unknown"
        elif direct_status[experiment_id] == "source_blocked" or "source_blocked" in inherited:
            status = "source_blocked"
        else:
            status = "available"
        resolved[experiment_id] = status
        return status

    for experiment_id in experiment_ids:
        resolve(experiment_id)

    runnable = [experiment_id for experiment_id in experiment_ids if resolved[experiment_id] == "available"]
    active_sources: list[str] = []
    for requirement in report.requirements:
        if (
            requirement.experiment_id in runnable
            and requirement.source_name
            and requirement.source_name not in active_sources
        ):
            active_sources.append(requirement.source_name)
    blocked = [
        BlockedExperiment(
            experiment_id=experiment_id,
            status=resolved[experiment_id],
            direct_data_blockers=direct_blockers[experiment_id],
            dependency_paths=_blocking_paths(
                experiment_id,
                dependencies,
                direct_status,
            ),
        )
        for experiment_id in experiment_ids
        if resolved[experiment_id] != "available"
    ]
    if any(item.status == "unknown" for item in blocked):
        verdict = "UNKNOWN"
    elif not runnable:
        verdict = "NONE"
    elif blocked:
        verdict = "PARTIAL"
    else:
        verdict = "FULL"

    unsigned = {
        "availability_report_sha256": report_sha256,
        "verdict": verdict,
        "runnable_experiment_ids": runnable,
        "blocked_experiments": [item.model_dump(mode="json") for item in blocked],
        "active_sources": active_sources,
        "execution_location": report.capacity_decision.execution_location,
    }
    scope_hash = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ExecutionScope(scope_sha256=scope_hash, **unsigned)


def _assert_acyclic(dependencies: dict[str, list[str]], ordered_ids: list[str]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(experiment_id: str) -> None:
        if experiment_id in visiting:
            raise ValueError(f"experiment dependency graph contains a cycle at {experiment_id}")
        if experiment_id in visited:
            return
        visiting.add(experiment_id)
        for dependency in dependencies[experiment_id]:
            visit(dependency)
        visiting.remove(experiment_id)
        visited.add(experiment_id)

    for experiment_id in ordered_ids:
        visit(experiment_id)


def _blocking_paths(
    experiment_id: str,
    dependencies: dict[str, list[str]],
    direct_status: dict[str, str],
) -> list[list[str]]:
    paths: list[list[str]] = []

    def walk(current: str, path: list[str]) -> None:
        if direct_status[current] != "available":
            paths.append(path)
            return
        for dependency in dependencies[current]:
            walk(dependency, [*path, dependency])

    walk(experiment_id, [experiment_id])
    return paths
