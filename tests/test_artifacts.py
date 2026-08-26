from __future__ import annotations

import pytest
from pydantic import ValidationError

from medai.models import (
    AgentStageResult,
    CodegenPlan,
    EvidenceSummary,
    PaperGraph,
    validate_reproduction_report,
)


def _node(node_id: str, inputs: list[str], **extra: object) -> dict[str, object]:
    return {
        "id": node_id,
        "inputs": inputs,
        "method": extra.pop("method", node_id),
        "paper_result": extra.pop("paper_result", None),
        "provenance": extra.pop("provenance", [{"locator": "table 1"}]),
        **extra,
    }


def test_codegen_node_updates_are_open_but_plan_shape_is_small() -> None:
    plan = CodegenPlan.model_validate(
        {
            "files": [{"path": "run.py", "responsibility": "replication"}],
            "dependency_order": ["run.py"],
            "entry_points": ["python run.py"],
            "shared_state": "none",
            "node_updates": [
                {
                    "node_id": "P1",
                    "issues": [{"description": "split seed omitted", "paper_page": 4}],
                    "resolution_candidate": {"seed": 0},
                }
            ],
            "remote_compute": None,
        }
    )
    assert plan.node_updates[0].resolution_candidate == {"seed": 0}

    with pytest.raises(ValidationError, match="extra"):
        CodegenPlan.model_validate({**plan.model_dump(), "legacy_ambiguities": []})


def test_agent_results_require_explicit_errors() -> None:
    AgentStageResult(status="completed", error=None)
    with pytest.raises(ValidationError, match="non-empty error"):
        AgentStageResult(status="blocked", error=None)


def test_evidence_environment_allows_audit_metadata() -> None:
    evidence = EvidenceSummary.model_validate(
        {
            "environment": {
                "python_version": "3.12",
                "gpu_available": False,
                "gpu_model": None,
                "key_packages": {},
                "container_digest": "sha256:abc",
            }
        }
    )
    assert evidence.environment.container_digest == "sha256:abc"


def test_report_requires_each_claim_in_graph_order_and_explicit_verdict() -> None:
    graph = PaperGraph.model_validate(
        {
            "version": 1,
            "datasets": [_node("D1", [])],
            "preprocessing": [_node("P1", ["D1"])],
            "training": [],
            "models": [],
            "validations": [_node("V1", ["P1"])],
            "claims": [_node("C1", ["V1"], paper_result=0.7)],
        }
    )
    report = """# Reproduction Report

## Claim C1
Paper result: 0.7
Reproduced result: 0.69
Upstream node results: D1, P1, V1
Direct comparison: -0.01
Scope blockers: none
Lineage issues: none
Assessment: close
"""
    validate_reproduction_report(report, graph)
    with pytest.raises(ValueError, match="explicit"):
        validate_reproduction_report(
            report.replace("Assessment: close", "Assessment: similar"), graph
        )
