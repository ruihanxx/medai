from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from medai.artifacts import write_json
from medai.config import RunConfig
from medai.data_availability import derive_graph_execution_scope
from medai.models import GraphDataAvailabilityReport, PaperGraph
from medai.pipeline_state import PipelineState, build_run_inputs
from medai.workflow import data_availability_agent_node


def test_availability_prompt_requires_metadata_adapter_for_provider_readiness() -> None:
    prompt = (
        Path(__file__).parents[1]
        / "templates"
        / "data_availability"
        / "session_instructions.md"
    ).read_text(encoding="utf-8")

    assert "already validated the selected provider and drive configuration" in prompt
    assert "shell variable tests" in prompt
    assert "guess or reconstruct" in prompt
    assert "any provider environment variable name" in prompt
    assert "provider readiness only by invoking the adapter" in prompt
    assert "selected in\nprovider metadata" in prompt
    assert "Only an actual adapter failure" in prompt
    assert "foreground provider-command handoff" in prompt
    assert "Do not invoke `create`, `cloud-pull`" in prompt
    assert '"status":"completed"' in prompt


def test_availability_hands_provider_commands_to_host_and_resumes(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "output"
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    provider_reference = tmp_path / "provider.md"
    drive_reference = tmp_path / "drive.md"
    provider_reference.write_text("provider\n", encoding="utf-8")
    drive_reference.write_text("drive\n", encoding="utf-8")
    config = RunConfig(
        paper=paper,
        output=output,
        provider="codex",
        clouddrive=True,
        computation_provider="fake",
        computation_provider_config={"provider": "fake"},
        computation_provider_reference=provider_reference,
        drive_provider="fake-drive",
        drive_reference=drive_reference,
        cloud_dataset="dataset-a",
        cloud_source="datasets/dataset-a",
        cloud_datasets=("dataset-a",),
        cloud_sources=("datasets/dataset-a",),
    )
    PipelineState.create(output, build_run_inputs(config))
    graph_path = output / "preprocessing" / "paper_graph.json"
    resources_path = output / "preflight" / "resources.json"
    write_json(graph_path, _graph().model_dump(mode="json"))
    write_json(resources_path, {"gpus": [], "cpu": {}, "memory": {}, "disk": {}})

    agent_calls = []
    events = []

    def fake_agent(**kwargs):
        agent_calls.append(kwargs)
        call_index = len(agent_calls)
        request_path = kwargs["output_last_message_path"]
        if call_index == 1:
            payload = {"status": "command", "command": "create-instance", "error": None}
        elif call_index == 2:
            payload = {"status": "command", "command": "cloud-pull", "error": None}
        else:
            report = _report("available", "available")
            report.capacity_decision.execution_location = "remote"
            for requirement in report.requirements:
                requirement.source_kind = "cloud"
                requirement.source_name = "datasets/dataset-a"
            write_json(
                output
                / "preprocessing"
                / "data_availability"
                / "attempt_001"
                / "data_availability.json",
                report.model_dump(mode="json"),
            )
            payload = {"status": "completed", "command": None, "error": None}
        write_json(request_path, payload)
        mode = "a" if kwargs.get("resume_session_id") else "w"
        with kwargs["transcript_path"].open(mode, encoding="utf-8") as transcript:
            transcript.write('{"type":"turn.completed"}\n')
        events.append(f"agent-{call_index}")
        return "thread-123"

    def fake_command(command, *, codebase_dir, log_path, result_path):
        events.append(f"local-{command}")
        log_path.write_text(f"{command}: complete\n", encoding="utf-8")
        result = {
            "command": command,
            "exit_code": 0,
            "duration_seconds": 1.0,
            "log_path": str(log_path),
            "artifact_validation_error": None,
        }
        write_json(result_path, result)
        return result

    monkeypatch.setattr("medai.workflow.run_agent", fake_agent)
    monkeypatch.setattr("medai.workflow._run_agent_command", fake_command)
    monkeypatch.setattr(
        "medai.workflow._cloud_pull_handoff_enabled",
        lambda _config, **_kwargs: True,
    )
    monkeypatch.setattr(
        "medai.workflow._cloud_drive_materialization_completed",
        lambda *_args, **_kwargs: True,
    )

    result = data_availability_agent_node(
        {
            "config": config,
            "paper_markdown": str(output / "preprocessing" / "paper.md"),
            "paper_graph_path": str(graph_path),
            "resources_path": str(resources_path),
        }
    )

    assert events == [
        "agent-1",
        "local-create-instance",
        "agent-2",
        "local-cloud-pull",
        "agent-3",
    ]
    assert agent_calls[0]["resume_session_id"] is None
    assert agent_calls[1]["resume_session_id"] == "thread-123"
    assert agent_calls[2]["resume_session_id"] == "thread-123"
    assert result["execution_scope_path"].endswith("preprocessing/execution_scope.json")
    handoff_dir = (
        output / "preprocessing" / "data_availability" / "attempt_001" / "provider_handoff"
    )
    assert json.loads((handoff_dir / "turn_001.json").read_text())["command"] == (
        "create-instance"
    )
    assert json.loads((handoff_dir / "turn_002.json").read_text())["command"] == (
        "cloud-pull"
    )
    assert json.loads((handoff_dir / "turn_003.json").read_text())["status"] == (
        "completed"
    )


def _node(node_id: str, inputs: list[str]) -> dict[str, object]:
    return {
        "id": node_id,
        "inputs": inputs,
        "method": node_id,
        "paper_result": None,
        "provenance": [],
    }


def _graph() -> PaperGraph:
    return PaperGraph.model_validate(
        {
            "version": 1,
            "datasets": [_node("D1", [])],
            "preprocessing": [_node("P_train", ["D1"]), _node("P_stats", ["D1"])],
            "training": [_node("T1", ["P_train"])],
            "models": [_node("M1", ["T1"])],
            "validations": [_node("V_pred", ["M1"]), _node("V_stats", ["P_stats"])],
            "claims": [_node("C_pred", ["V_pred"]), _node("C_stats", ["V_stats"])],
        }
    )


def _report(train: str, stats: str) -> GraphDataAvailabilityReport:
    return GraphDataAvailabilityReport.model_validate(
        {
            "capacity_decision": {"execution_location": "local", "rationale": "test"},
            "requirements": [
                {
                    "preprocessing_id": preprocessing_id,
                    "dataset_id": "D1",
                    "source_kind": "local" if status == "available" else None,
                    "source_name": "data.csv" if status == "available" else None,
                    "required_content": preprocessing_id,
                    "status": status,
                    "evidence": f"{preprocessing_id}: {status}",
                }
                for preprocessing_id, status in (("P_train", train), ("P_stats", stats))
            ],
        }
    )


def _derive(report: GraphDataAvailabilityReport):
    payload = report.model_dump(mode="json")
    report_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return derive_graph_execution_scope(
        _graph(), report, paper_graph_sha256="1" * 64, report_sha256=report_hash
    )


def test_force_remote_rejects_a_completed_local_scope(tmp_path) -> None:
    output = tmp_path / "output"
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF")
    data = tmp_path / "data"
    data.mkdir()
    config = RunConfig(
        paper=paper,
        output=output,
        provider="codex",
        data=data,
        datasets=("data",),
        local_data_paths=(data,),
        force_remote=True,
        computation_provider="fake",
        computation_provider_config={"provider": "fake"},
        computation_provider_reference=tmp_path / "provider.md",
    )
    graph_path = output / "preprocessing" / "paper_graph.json"
    write_json(graph_path, _graph().model_dump(mode="json"))
    report = _report("available", "available")
    for requirement in report.requirements:
        requirement.source_name = str(data)
    report_path = output / "availability.json"
    write_json(report_path, report.model_dump(mode="json"))
    pipeline_state = PipelineState.create(output, build_run_inputs(config))
    pipeline_state.start_stage("data_availability_agent")
    pipeline_state.update_stage_checkpoints(
        "data_availability_agent",
        {"report_path": str(report_path), "scope_sha256": "0" * 64, "verdict": "FULL"},
    )
    pipeline_state.complete_stage("data_availability_agent", [str(report_path)])

    with pytest.raises(ValueError, match="--force-remote scope must use remote"):
        data_availability_agent_node(
            {"config": config, "paper_graph_path": str(graph_path)}  # type: ignore[arg-type]
        )


def test_independent_preprocessing_variants_produce_maximal_claim_subgraph() -> None:
    scope = _derive(_report("source_blocked", "available"))
    assert scope.verdict == "PARTIAL"
    assert scope.runnable_node_ids == ["D1", "P_stats", "V_stats", "C_stats"]
    blocked_claim = next(item for item in scope.blocked_nodes if item.node_id == "C_pred")
    assert blocked_claim.dependency_paths == [
        ["C_pred", "V_pred", "M1", "T1", "P_train"]
    ]


def test_unknown_on_one_claim_produces_partial_scope() -> None:
    scope = _derive(_report("unknown", "available"))
    assert scope.verdict == "PARTIAL"
    assert "C_stats" in scope.runnable_node_ids


@pytest.mark.parametrize("status", ["source_blocked", "unknown"])
def test_scope_is_none_only_when_all_claims_are_blocked(status: str) -> None:
    scope = _derive(_report(status, status))
    assert scope.verdict == "NONE"
    assert scope.runnable_node_ids == []


def test_scope_is_bound_to_availability_content() -> None:
    available = _derive(_report("available", "available"))
    partial = _derive(_report("source_blocked", "available"))
    assert available.scope_sha256 != partial.scope_sha256
    assert available.verdict == "FULL"


def test_availability_rejects_missing_p_by_d_requirement() -> None:
    report = _report("available", "available")
    report.requirements.pop()
    with pytest.raises(ValueError, match="coverage mismatch"):
        _derive(report)


def test_shared_preprocessing_prefix_has_one_direct_source_requirement() -> None:
    graph = PaperGraph.model_validate(
        {
            "version": 1,
            "datasets": [_node("D1", [])],
            "preprocessing": [
                _node("P_common", ["D1"]),
                _node("P_random", ["P_common"]),
                _node("P_temporal", ["P_common"]),
            ],
            "training": [],
            "models": [],
            "validations": [
                _node("V_random", ["P_random"]),
                _node("V_temporal", ["P_temporal"]),
            ],
            "claims": [
                _node("C_random", ["V_random"]),
                _node("C_temporal", ["V_temporal"]),
            ],
        }
    )
    report = GraphDataAvailabilityReport.model_validate(
        {
            "capacity_decision": {"execution_location": "local", "rationale": "test"},
            "requirements": [
                {
                    "preprocessing_id": "P_common",
                    "dataset_id": "D1",
                    "source_kind": "local",
                    "source_name": "data.csv",
                    "required_content": "shared cohort source fields",
                    "status": "available",
                    "evidence": "columns inspected",
                }
            ],
        }
    )

    scope = derive_graph_execution_scope(
        graph,
        report,
        paper_graph_sha256="1" * 64,
        report_sha256="2" * 64,
    )

    assert scope.verdict == "FULL"
    assert scope.runnable_node_ids == [node.id for node in graph.nodes]

    blocked = report.model_copy(deep=True)
    blocked.requirements[0] = blocked.requirements[0].model_copy(
        update={
            "source_kind": None,
            "source_name": None,
            "status": "source_blocked",
            "evidence": "required source fields absent",
        }
    )
    blocked_scope = derive_graph_execution_scope(
        graph,
        blocked,
        paper_graph_sha256="1" * 64,
        report_sha256="3" * 64,
    )
    assert blocked_scope.verdict == "NONE"
    assert {item.node_id for item in blocked_scope.blocked_nodes} == {
        "P_common",
        "P_random",
        "P_temporal",
        "V_random",
        "V_temporal",
        "C_random",
        "C_temporal",
    }

    extra = report.model_copy(deep=True)
    extra.requirements.append(
        extra.requirements[0].model_copy(update={"preprocessing_id": "P_random"})
    )
    with pytest.raises(ValueError, match="coverage mismatch"):
        derive_graph_execution_scope(
            graph,
            extra,
            paper_graph_sha256="1" * 64,
            report_sha256="2" * 64,
        )
