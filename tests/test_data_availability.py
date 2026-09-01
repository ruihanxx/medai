from __future__ import annotations

import hashlib
import json

import pytest

from medai.artifacts import write_json
from medai.config import RunConfig
from medai.data_availability import derive_graph_execution_scope
from medai.models import GraphDataAvailabilityReport, PaperGraph
from medai.pipeline_state import PipelineState, build_run_inputs
from medai.workflow import data_availability_agent_node


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
