from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from medai.data_availability import derive_graph_execution_scope
from medai.models import (
    CapacityDecision,
    GraphDataAvailabilityReport,
    GraphDataRequirementAvailability,
    NodeState,
    PaperGraph,
)
from medai.study_graph import (
    collect_lineage_issues,
    merge_node_updates,
    remove_node_updates,
)

GRAPH_SHA = "1" * 64
REPORT_SHA = "2" * 64


def _node(node_id: str, inputs: list[str], **extra: object) -> dict[str, object]:
    return {
        "id": node_id,
        "inputs": inputs,
        "method": extra.pop("method", {"free": ["form", 1]}),
        "paper_result": extra.pop("paper_result", None),
        "provenance": extra.pop("provenance", [{"page": 1, "locator": "table"}]),
        **extra,
    }


def _graph() -> PaperGraph:
    return PaperGraph.model_validate(
        {
            "version": 1,
            "datasets": [_node("D1", [], license_note="open")],
            "preprocessing": [
                _node("P1", ["D1"], method=["split=a", {"label": "x"}]),
                _node("P2", ["D1"], method="split=b"),
            ],
            "training": [_node("T1", ["P1"])],
            "models": [_node("M1", ["T1"], paper_result={"artifact": "checkpoint"})],
            "validations": [
                _node(
                    "V1",
                    ["M1", "P1"],
                    method={
                        "models": ["M1"],
                        "data": ["P1"],
                        "metrics": ["auroc", "sensitivity"],
                        "combination": "cartesian",
                    },
                ),
                _node("V2", ["P2"], method={"statistic": "prevalence"}),
            ],
            "claims": [
                _node("C1", ["V1"], method={"comparison": "greater-than"}),
                _node("C2", ["V2"], method="describe prevalence"),
            ],
            "paper_specific": {"allowed": True},
        }
    )


def _availability(p1: str = "available", p2: str = "available") -> GraphDataAvailabilityReport:
    return GraphDataAvailabilityReport(
        capacity_decision=CapacityDecision(
            execution_location="local", rationale="small test"
        ),
        requirements=[
            GraphDataRequirementAvailability(
                preprocessing_id=preprocessing_id,
                dataset_id="D1",
                source_kind="local" if status == "available" else None,
                source_name="data.csv" if status == "available" else None,
                required_content=f"content for {preprocessing_id}",
                status=status,
                evidence=f"evidence for {preprocessing_id}",
            )
            for preprocessing_id, status in (("P1", p1), ("P2", p2))
        ],
    )


def test_paper_graph_accepts_open_payloads_and_statistical_paths() -> None:
    graph = _graph()

    assert graph.node_map["D1"].license_note == "open"
    assert graph.model_dump()["paper_specific"] == {"allowed": True}
    assert graph.node_map["V2"].inputs == ["P2"]
    assert graph.node_map["V1"].method["combination"] == "cartesian"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda graph: graph["claims"][0].update(id="V2"), "globally unique"),
        (lambda graph: graph["claims"][0].update(inputs=["missing"]), "unknown node"),
        (lambda graph: graph["claims"][0].update(inputs=["V1", "V1"]), "duplicate"),
        (lambda graph: graph["datasets"][0].update(inputs=["C1"]), "cycle"),
        (lambda graph: graph["claims"].pop(), "reach a claim"),
    ],
)
def test_paper_graph_rejects_invalid_structure(mutation, message: str) -> None:
    payload = _graph().model_dump(mode="python")
    mutation(payload)

    with pytest.raises(ValidationError, match=message):
        PaperGraph.model_validate(payload)


def test_availability_blocks_preprocessing_variants_independently() -> None:
    scope = derive_graph_execution_scope(
        _graph(),
        _availability(p1="source_blocked", p2="available"),
        paper_graph_sha256=GRAPH_SHA,
        report_sha256=REPORT_SHA,
    )

    assert scope.verdict == "PARTIAL"
    assert scope.runnable_node_ids == ["D1", "P2", "V2", "C2"]
    assert {item.node_id for item in scope.blocked_nodes} == {
        "P1",
        "T1",
        "M1",
        "V1",
        "C1",
    }
    claim_block = next(item for item in scope.blocked_nodes if item.node_id == "C1")
    assert claim_block.dependency_paths == [
        ["C1", "V1", "M1", "T1", "P1"],
        ["C1", "V1", "P1"],
    ]


def test_unknown_requirement_keeps_scope_unknown() -> None:
    scope = derive_graph_execution_scope(
        _graph(),
        _availability(p1="unknown", p2="available"),
        paper_graph_sha256=GRAPH_SHA,
        report_sha256=REPORT_SHA,
    )

    assert scope.verdict == "UNKNOWN"
    assert "C2" in scope.runnable_node_ids


def test_overlay_merge_is_idempotent_and_lineage_is_precise(tmp_path) -> None:
    graph = _graph()
    state_path = tmp_path / "graph" / "node_state.json"
    update = {
        "node_id": "P1",
        "result": {"rows": 10},
        "evidence": ["outputs/p1.json"],
        "issues": [{"description": "split unclear", "required_fix": "verify seed"}],
    }
    merge_node_updates(state_path, graph, GRAPH_SHA, "codegen", [update])
    merge_node_updates(state_path, graph, GRAPH_SHA, "codegen", [update])
    merge_node_updates(
        state_path,
        graph,
        GRAPH_SHA,
        "audit:1",
        [
            {
                "node_id": "P1",
                "issues": [{"description": "split unclear", "required_fix": "verify seed"}],
            },
            {"node_id": "V2", "issues": [{"description": "unrelated issue"}]},
        ],
    )
    state = NodeState.model_validate_json(state_path.read_text(encoding="utf-8"))

    assert len(state.updates) == 3
    issues = collect_lineage_issues(graph, state, "C1")
    assert len(issues) == 1
    assert issues[0]["origin_node_id"] == "P1"
    assert issues[0]["sources"] == ["audit:1", "codegen"]
    assert issues[0]["paths"] == [
        ["P1", "T1", "M1", "V1", "C1"],
        ["P1", "V1", "C1"],
    ]
    assert collect_lineage_issues(graph, state, "M1")[0]["paths"] == [
        ["P1", "T1", "M1"]
    ]
    assert collect_lineage_issues(graph, state, "C2")[0]["origin_node_id"] == "V2"

    remove_node_updates(state_path, source_prefixes=["audit:"])
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert [(item["source"], item["node_id"]) for item in payload["updates"]] == [
        ("codegen", "P1")
    ]


def test_availability_requires_every_preprocessing_dataset_pair() -> None:
    report = _availability()
    report.requirements.pop()

    with pytest.raises(ValueError, match="coverage mismatch"):
        derive_graph_execution_scope(
            _graph(),
            report,
            paper_graph_sha256=GRAPH_SHA,
            report_sha256=REPORT_SHA,
        )
