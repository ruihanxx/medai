import json

import pytest

from medai.models import (
    ClaimsFile,
    ExperimentResult,
    ExperimentTodo,
    ReplicationPlan,
    validate_experiment_coverage,
    validate_experiment_result,
    validate_replication_plan,
)


def claims_payload():
    return {
        "claims": [
            {
                "claim_id": "C1",
                "statement": "Accuracy improved.",
                "kind": "numeric",
                "paper_result": 0.91,
                "provenance": {"page": 3, "section": "Results"},
            }
        ]
    }


def todo_payload():
    return {
        "experiments": [
            {
                "experiment_id": "E1",
                "description": "Train and evaluate the model.",
                "claims": ["C1"],
                "artifacts": ["Figure 1"],
            }
        ]
    }


def test_claim_and_experiment_coverage_is_exact():
    claims = ClaimsFile.model_validate(claims_payload())
    todo = ExperimentTodo.model_validate(todo_payload())
    validate_experiment_coverage(claims, todo)

    todo.experiments[0].claims = ["C2"]
    with pytest.raises(ValueError, match="unknown claims"):
        validate_experiment_coverage(claims, todo)


def test_replication_plan_must_preserve_mappings():
    todo = ExperimentTodo.model_validate(todo_payload())
    plan = ReplicationPlan.model_validate(
        {
            "experiments": [
                {
                    "experiment_id": "E1",
                    "claims": ["C1"],
                    "artifacts": ["Figure 1"],
                    "steps": [
                        {
                            "step_id": "S1",
                            "description": "Run",
                            "command": "python run.py",
                            "expected_outputs": ["figure.png"],
                        }
                    ],
                }
            ]
        }
    )
    validate_replication_plan(todo, plan)
    plan.experiments[0].artifacts = []
    with pytest.raises(ValueError, match="does not match"):
        validate_replication_plan(todo, plan)


def test_experiment_result_must_cover_claims_and_artifacts():
    experiment = ExperimentTodo.model_validate(todo_payload()).experiments[0]
    result = ExperimentResult.model_validate(
        {
            "experiment_id": "E1",
            "claims": [
                {
                    "claim_id": "C1",
                    "reproduced_result": 0.9,
                    "evidence": ["metrics.json"],
                }
            ],
            "artifacts": [{"artifact_id": "Figure 1", "path": "figure.png"}],
            "commands": ["python run.py"],
        }
    )
    validate_experiment_result(experiment, result)
    result.claims = []
    with pytest.raises(ValueError, match="claim coverage"):
        validate_experiment_result(experiment, result)


def test_duplicate_claim_ids_are_rejected():
    payload = claims_payload()
    payload["claims"].append(json.loads(json.dumps(payload["claims"][0])))
    with pytest.raises(ValueError, match="unique"):
        ClaimsFile.model_validate(payload)


def test_unknown_contract_fields_are_rejected():
    payload = claims_payload()
    payload["fallback"] = {"claims": []}
    with pytest.raises(ValueError, match="Extra inputs"):
        ClaimsFile.model_validate(payload)
