from __future__ import annotations

import pytest
from medai.models import (
    AgentStageResult,
    CodegenPlan,
    EvidenceSummary,
)
from pydantic import ValidationError


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
