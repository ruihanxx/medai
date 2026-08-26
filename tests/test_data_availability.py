from __future__ import annotations

import json
from pathlib import Path

import pytest

from medai.config import RunConfig
from medai.data_availability import derive_execution_scope
from medai.models import DataAvailabilityReport, ExperimentTodo
from medai.pipeline_state import PipelineState
from medai.prompts import render_prompt
from medai.workflow import (
    PartialDataAwaitingConfirmation,
    PartialDataStopped,
    partial_data_gate_node,
)


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


def test_prompt_pins_dependency_examples_and_capacity_rules(tmp_path: Path) -> None:
    prompt_path = render_prompt(
        "data_availability/session_instructions.md",
        tmp_path / "availability.md",
        paper_markdown=tmp_path / "paper.md",
        experiments_path=tmp_path / "experiments.json",
        resources_path=tmp_path / "resources.json",
        local_datasets=[("A", tmp_path / "A")],
        cloud_datasets=[],
        scope_revision_reports=[],
        cloud_only=False,
        dual_source=False,
        computation_provider_reference=None,
        drive_reference=None,
        computation_provider_state_path=tmp_path / "instance.json",
        report_path=tmp_path / "report.json",
        results_dir=tmp_path / "results",
    ).read_text(encoding="utf-8")

    assert "E1 needs complete A and E2 needs B" in prompt_path
    assert "E1 needs both A and B" in prompt_path
    assert "requires E1's trained model" in prompt_path
    assert "B lacks table X used only by E1" in prompt_path
    assert "eight physical cores" in prompt_path
    assert "20% headroom" in prompt_path
    assert "D + max(D, 10 GiB)" in prompt_path
    assert "unresolved uncertainty is `unknown`" in prompt_path


def _partial_gate_state(tmp_path: Path, policy: str) -> tuple[dict[str, object], Path]:
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    data = tmp_path / "data"
    data.mkdir()
    output = tmp_path / "output"
    config = RunConfig.create(
        paper=paper,
        output=output,
        provider="codex",
        repo=None,
        data=data,
        siliconflow_config=None,
        on_partial_data=policy,
    )
    PipelineState.create(output, {"provider": "codex"})
    scope_path = output / "preprocessing" / "execution_scope.json"
    scope_path.parent.mkdir(parents=True)
    scope_path.write_text(
        json.dumps(
            {
                "availability_report_sha256": "a" * 64,
                "scope_sha256": "b" * 64,
                "verdict": "PARTIAL",
                "runnable_experiment_ids": ["E1"],
                "blocked_experiments": [
                    {
                        "experiment_id": "E2",
                        "status": "source_blocked",
                        "direct_data_blockers": ["B: table X — file is absent"],
                        "dependency_paths": [["E2"]],
                    }
                ],
                "active_sources": [str(data)],
                "execution_location": "local",
            }
        ),
        encoding="utf-8",
    )
    return {"config": config, "execution_scope_path": str(scope_path)}, output


def test_noninteractive_ask_waits_for_confirmation(tmp_path: Path, monkeypatch) -> None:
    state, output = _partial_gate_state(tmp_path, "ask")
    monkeypatch.setattr("medai.workflow.sys.stdin.isatty", lambda: False)

    with pytest.raises(PartialDataAwaitingConfirmation, match="--on-partial-data continue"):
        partial_data_gate_node(state)

    manifest = PipelineState(output).state
    assert manifest["status"] == "awaiting_confirmation"
    assert manifest["awaiting_scope_sha256"] == "b" * 64


def test_continue_records_scope_bound_decision(tmp_path: Path) -> None:
    state, output = _partial_gate_state(tmp_path, "continue")

    partial_data_gate_node(state)

    decisions = json.loads(
        (output / "preprocessing" / "partial_replication_decisions.json").read_text(
            encoding="utf-8"
        )
    )["decisions"]
    assert decisions[0]["decision"] == "continue"
    assert decisions[0]["scope_sha256"] == "b" * 64
    assert PipelineState(output).is_stage_completed("partial_data_gate")


def test_stop_records_rejection_and_closes_run(tmp_path: Path, monkeypatch) -> None:
    state, output = _partial_gate_state(tmp_path, "stop")
    events: list[str] = []
    monkeypatch.setattr(
        "medai.workflow.power_off_run_computation_instance",
        lambda _config: events.append("power-off"),
    )
    monkeypatch.setattr(
        "medai.workflow.release_run_computation_instance",
        lambda _config: events.append("release"),
    )

    with pytest.raises(PartialDataStopped):
        partial_data_gate_node(state)

    assert events == ["power-off", "release"]
    assert PipelineState(output).state["status"] == "stopped_by_user"


def test_interactive_empty_answer_defaults_to_no(tmp_path: Path, monkeypatch) -> None:
    state, output = _partial_gate_state(tmp_path, "ask")

    class InteractiveInput:
        @staticmethod
        def isatty() -> bool:
            return True

    monkeypatch.setattr("medai.workflow.sys.stdin", InteractiveInput())
    monkeypatch.setattr("builtins.input", lambda: "")
    monkeypatch.setattr("medai.workflow.power_off_run_computation_instance", lambda _c: None)
    monkeypatch.setattr("medai.workflow.release_run_computation_instance", lambda _c: None)

    with pytest.raises(PartialDataStopped):
        partial_data_gate_node(state)

    assert PipelineState(output).state["status"] == "stopped_by_user"
