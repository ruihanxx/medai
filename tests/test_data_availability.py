from __future__ import annotations

from medai.data_availability import derive_execution_scope
from medai.models import DataAvailabilityReport, ExperimentTodo


def _experiments(*datasets: tuple[str, list[str]]) -> ExperimentTodo:
    return ExperimentTodo.model_validate(
        {
            "experiments": [
                {
                    "experiment_id": experiment_id,
                    "description": experiment_id,
                    "computational_demand": "eight CPU cores",
                    "datasets": [
                        {"name": dataset, "role": "analysis", "usage": "analyze"}
                        for dataset in names
                    ],
                    "claims": [f"C{index}"],
                    "artifacts": [],
                }
                for index, (experiment_id, names) in enumerate(datasets, 1)
            ]
        }
    )


def _report(
    experiments: ExperimentTodo,
    statuses: dict[tuple[str, str], str],
    dependencies: dict[str, list[str]] | None = None,
) -> DataAvailabilityReport:
    dependencies = dependencies or {}
    return DataAvailabilityReport.model_validate(
        {
            "capacity_decision": {
                "execution_location": "local",
                "rationale": "representative probe fits local resources",
            },
            "requirements": [
                {
                    "experiment_id": experiment.experiment_id,
                    "dataset": dataset.name,
                    "source_kind": "local",
                    "source_name": dataset.name,
                    "required_content": "required table",
                    "status": statuses.get(
                        (experiment.experiment_id, dataset.name), "available"
                    ),
                    "evidence": "paper and file inventory evidence",
                }
                for experiment in experiments.experiments
                for dataset in experiment.datasets
            ],
            "dependencies": [
                {
                    "experiment_id": experiment.experiment_id,
                    "depends_on": dependencies.get(experiment.experiment_id, []),
                    "evidence": "paper dependency evidence",
                }
                for experiment in experiments.experiments
            ],
        }
    )


def test_partial_scope_keeps_independent_available_experiment() -> None:
    experiments = _experiments(("E1", ["A"]), ("E2", ["B"]))
    report = _report(experiments, {("E2", "B"): "source_blocked"})

    scope = derive_execution_scope(experiments, report, "a" * 64)

    assert scope.verdict == "PARTIAL"
    assert scope.runnable_experiment_ids == ["E1"]
    assert [item.experiment_id for item in scope.blocked_experiments] == ["E2"]


def test_one_missing_dataset_blocks_multi_dataset_experiment() -> None:
    experiments = _experiments(("E1", ["A", "B"]))
    report = _report(experiments, {("E1", "B"): "source_blocked"})

    scope = derive_execution_scope(experiments, report, "b" * 64)

    assert scope.verdict == "NONE"
    assert scope.runnable_experiment_ids == []


def test_dependency_closure_propagates_block_and_unknown() -> None:
    experiments = _experiments(("E1", ["A", "B"]), ("E2", ["C"]))
    dependencies = {"E2": ["E1"]}
    blocked = derive_execution_scope(
        experiments,
        _report(experiments, {("E1", "B"): "source_blocked"}, dependencies),
        "c" * 64,
    )
    unknown = derive_execution_scope(
        experiments,
        _report(experiments, {("E1", "B"): "unknown"}, dependencies),
        "d" * 64,
    )

    assert blocked.verdict == "NONE"
    assert blocked.blocked_experiments[1].dependency_paths == [["E2", "E1"]]
    assert unknown.verdict == "UNKNOWN"
    assert all(item.status == "unknown" for item in unknown.blocked_experiments)


def test_missing_content_does_not_block_other_content_in_same_dataset() -> None:
    experiments = _experiments(("E1", ["B"]), ("E2", ["B"]))
    scope = derive_execution_scope(
        experiments,
        _report(experiments, {("E1", "B"): "source_blocked"}),
        "e" * 64,
    )

    assert scope.verdict == "PARTIAL"
    assert scope.runnable_experiment_ids == ["E2"]


def test_dependency_validation_rejects_cycle_and_unknown_id() -> None:
    experiments = _experiments(("E1", ["A"]), ("E2", ["B"]))
    for dependencies, message in [
        ({"E1": ["E2"], "E2": ["E1"]}, "cycle"),
        ({"E1": ["E9"]}, "unknown IDs"),
    ]:
        try:
            derive_execution_scope(
                experiments,
                _report(experiments, {}, dependencies),
                "f" * 64,
            )
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("invalid dependency graph was accepted")


def test_scope_hash_changes_with_scope() -> None:
    experiments = _experiments(("E1", ["A"]), ("E2", ["B"]))
    full = derive_execution_scope(experiments, _report(experiments, {}), "1" * 64)
    partial = derive_execution_scope(
        experiments,
        _report(experiments, {("E2", "B"): "source_blocked"}),
        "1" * 64,
    )

    assert full.scope_sha256 != partial.scope_sha256
