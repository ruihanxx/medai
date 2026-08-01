import json
from pathlib import Path

import pytest

from medai.models import (
    ClaimsFile,
    DataInventory,
    ExperimentResult,
    ExperimentTodo,
    ReplicationPlan,
    validate_data_inventory,
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
                "role": "final",
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


def data_inventory_payload(
    *,
    status: str = "not_supplied",
    root: str | None = None,
) -> dict:
    explored = status == "explored"
    return {
        "schema_version": 1,
        "dataset": {
            "id": "dataset" if explored else None,
            "root": root if explored else None,
            "adapter": "generic" if explored else None,
            "status": status,
        },
        "scan": {
            "files_scanned": 1 if explored else 0,
            "bytes_scanned": 10 if explored else 0,
            "truncated": False,
            "limits": {"max_files": 100} if explored else {},
        },
        "catalog": [{"format": "csv"}] if explored else [],
        "explored_files": [],
        "warnings": [],
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
                            "verifies": ["C1", "Figure 1"],
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


def test_data_inventory_matches_configured_data_state(tmp_path: Path):
    not_supplied = DataInventory.model_validate(data_inventory_payload())
    validate_data_inventory(None, not_supplied)

    data = tmp_path / "raw"
    data.mkdir()
    explored = DataInventory.model_validate(
        data_inventory_payload(status="explored", root=str(data))
    )
    validate_data_inventory(data, explored)

    with pytest.raises(ValueError, match="must report explored"):
        validate_data_inventory(data, not_supplied)
    with pytest.raises(ValueError, match="must report not_supplied"):
        validate_data_inventory(None, explored)


def test_data_inventory_rejects_wrong_root_and_nonempty_not_supplied(tmp_path: Path):
    data = tmp_path / "raw"
    data.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    wrong_root = DataInventory.model_validate(
        data_inventory_payload(status="explored", root=str(other))
    )
    with pytest.raises(ValueError, match="root does not match"):
        validate_data_inventory(data, wrong_root)

    payload = data_inventory_payload()
    payload["catalog"] = [{"path": "unexpected.csv"}]
    nonempty = DataInventory.model_validate(payload)
    with pytest.raises(ValueError, match="must be empty"):
        validate_data_inventory(None, nonempty)
