from __future__ import annotations

import pytest
from pydantic import ValidationError

from medai.models import (
    AutoResearchValidationLog,
    AutoResearchValidationPlan,
    IdeaAssessment,
    PaperGraph,
    ValidationCodegenAudit,
    ValidationContracts,
    ValidationWeights,
    validate_autoresearch_validation_log,
    validate_autoresearch_validation_plan,
    validate_codegen_audit,
    validate_refinement_graph,
    validate_validation_contracts,
    validate_validation_weights,
)


def _node(node_id: str, inputs: list[str], **extra: object) -> dict[str, object]:
    return {
        "id": node_id,
        "inputs": inputs,
        "method": extra.pop("method", node_id),
        "paper_result": extra.pop("paper_result", None),
        "provenance": extra.pop("provenance", [{"page": 1}]),
        **extra,
    }


def _base_graph() -> PaperGraph:
    return PaperGraph.model_validate(
        {
            "version": 1,
            "datasets": [_node("D1", [])],
            "preprocessing": [_node("P1", ["D1"])],
            "training": [_node("T1", ["P1"])],
            "models": [_node("M1", ["T1"])],
            "validations": [
                _node("V1", ["M1", "P1"], method={"metric": "AUROC"}),
                _node("V2", ["P1"], method={"statistic": "prevalence"}),
            ],
            "claims": [
                _node("C1", ["V1"], paper_result={"AUROC": 0.8}),
                _node("C2", ["V2"], paper_result={"prevalence": 0.2}),
            ],
        }
    )


def _weights() -> ValidationWeights:
    return ValidationWeights.model_validate(
        {
            "validations": [
                {"validation_id": "V1", "weight": 1.0, "rationale": "prediction"},
                {"validation_id": "V2", "weight": 0.0, "rationale": "sparse"},
            ]
        }
    )


def _contracts() -> ValidationContracts:
    return ValidationContracts.model_validate(
        {
            "validations": [
                {
                    "validation_id": "V1",
                    "baseline_entry_points": ["python baseline.py"],
                    "editable_paths": ["model.py"],
                    "frozen_contract": {"data": "P1", "target": "fixed"},
                    "primary_metric": "AUROC",
                    "comparison_rule": {"direction": "higher"},
                    "paper_specific": True,
                }
            ]
        }
    )


def _refinement_graph() -> PaperGraph:
    payload = _base_graph().model_dump(mode="python")
    payload["training"].append(_node("T_new", ["P1"], method={"optimizer": "new"}))
    payload["models"].append(_node("M_new", ["T_new"], method={"seed": 2}))
    payload["validations"].append(
        _node(
            "V_new",
            ["M_new", "P1"],
            method={"metric": "AUROC"},
            baseline_validation_id="V1",
        )
    )
    payload["claims"].append(
        _node(
            "C_new",
            ["V_new"],
            method={"assessment": "refined"},
            baseline_claim_id="C1",
        )
    )
    return PaperGraph.model_validate(payload)


def _step(step_id: int = 1) -> dict[str, object]:
    return {
        "id": step_id,
        "description": "run refined V",
        "command_hint": "python refined.py",
        "expected_outcome": "metric",
        "verifies": ["T_new", "M_new", "V_new", "C_new"],
    }


def _outcome(step_id: int = 1) -> dict[str, object]:
    return {
        "step_id": step_id,
        "description": "run refined V",
        "command_executed": "python refined.py",
        "exit_code": 0,
        "stdout": "ok",
        "stderr": "",
        "output_files": ["metric.json"],
        "duration_seconds": 1,
        "fixes_applied": [],
        "code_modified": False,
        "notes": "",
    }


def test_zero_weight_validation_has_no_contract_or_execution() -> None:
    graph = _base_graph()
    weights = _weights()
    contracts = _contracts()

    validate_validation_weights(graph, weights)
    validate_validation_contracts(weights, contracts)
    assert weights.positive_ids == ["V1"]
    assert [item.validation_id for item in contracts.validations] == ["V1"]


def test_positive_weights_must_normalize_and_include_one_positive() -> None:
    with pytest.raises(ValidationError, match="sum to 1"):
        ValidationWeights.model_validate(
            {
                "validations": [
                    {"validation_id": "V1", "weight": 0.4, "rationale": "a"},
                    {"validation_id": "V2", "weight": 0.4, "rationale": "b"},
                ]
            }
        )
    with pytest.raises(ValidationError, match="positive"):
        ValidationWeights.model_validate(
            {"validations": [{"validation_id": "V1", "weight": 0, "rationale": "a"}]}
        )


def test_refinement_graph_preserves_base_and_adds_new_model_validation() -> None:
    validate_refinement_graph(_base_graph(), _refinement_graph(), _weights())

    payload = _refinement_graph().model_dump(mode="python")
    next(node for node in payload["models"] if node["id"] == "M1")["method"] = "changed"
    with pytest.raises(ValueError, match="modifies base"):
        validate_refinement_graph(
            _base_graph(),
            PaperGraph.model_validate(payload),
            _weights(),
        )


def test_free_form_audit_covers_each_positive_validation() -> None:
    audit = ValidationCodegenAudit.model_validate(
        {
            "idea_id": "R01-I01",
            "verdict": "pass",
            "refinement_only": True,
            "scope_evidence": ["diff.txt"],
            "scope_issue": None,
            "checks": [
                {
                    "validation_id": "V1",
                    "name": "custom leakage and calibration check",
                    "verdict": "pass",
                    "evidence": ["audit.json"],
                    "issue": None,
                    "custom": {"allowed": True},
                }
            ],
            "required_fixes": [],
        }
    )

    validate_codegen_audit(_contracts(), audit)


def test_validation_plan_and_log_cover_refinement_only_nodes() -> None:
    graph = _refinement_graph()
    plan = AutoResearchValidationPlan.model_validate(
        {
            "environment": {"language": "Python", "key_dependencies": [], "setup_hints": ""},
            "validations": [
                {
                    "validation_id": "V_new",
                    "baseline_validation_id": "V1",
                    "steps": [_step()],
                }
            ],
            "remote_compute": None,
        }
    )
    validate_autoresearch_validation_plan(_contracts(), graph, plan)
    updates = [
        {"node_id": node_id, "result": node_id, "evidence": ["metric.json"]}
        for node_id in ("T_new", "M_new", "V_new", "C_new")
    ]
    log = AutoResearchValidationLog.model_validate(
        {
            "validations": [{"validation_id": "V_new", "step_outcomes": [_outcome()]}],
            "node_updates": updates,
        }
    )
    validate_autoresearch_validation_log(_base_graph(), graph, plan, log)


def test_numeric_validation_assessment_uses_weighted_score() -> None:
    assessment = IdeaAssessment.model_validate(
        {
            "idea_id": "R01-I01",
            "verdict": "valid",
            "summary": "improved",
            "audit_passed": True,
            "protocol_consistent": True,
            "validations": [
                {
                    "validation_id": "V1",
                    "refined_validation_id": "V_new",
                    "primary_metric": "AUROC",
                    "comparison_rule": {"direction": "higher"},
                    "weight": 1.0,
                    "baseline_value": 0.8,
                    "refined_value": 0.82,
                    "absolute_delta": 0.02,
                    "relative_delta": 0.025,
                    "score": 2,
                    "score_rationale": "clear improvement",
                    "weighted_score": 2.0,
                    "evidence_paths": ["baseline.json", "refined.json"],
                }
            ],
            "weighted_score": 2.0,
            "threshold": 0,
            "failure_reasons": [],
        }
    )

    assert assessment.weighted_score == 2
