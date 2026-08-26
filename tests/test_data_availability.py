from __future__ import annotations

import hashlib
import json

import pytest

from medai.data_availability import derive_graph_execution_scope
from medai.models import GraphDataAvailabilityReport, PaperGraph


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


def test_independent_preprocessing_variants_produce_maximal_claim_subgraph() -> None:
    scope = _derive(_report("source_blocked", "available"))
    assert scope.verdict == "PARTIAL"
    assert scope.runnable_node_ids == ["D1", "P_stats", "V_stats", "C_stats"]
    blocked_claim = next(item for item in scope.blocked_nodes if item.node_id == "C_pred")
    assert blocked_claim.dependency_paths == [
        ["C_pred", "V_pred", "M1", "T1", "P_train"]
    ]


def test_unknown_on_one_claim_keeps_verdict_unknown() -> None:
    scope = _derive(_report("unknown", "available"))
    assert scope.verdict == "UNKNOWN"
    assert "C_stats" in scope.runnable_node_ids


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
