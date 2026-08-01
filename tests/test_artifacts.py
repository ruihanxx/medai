import json
from pathlib import Path

import pytest

from medai.models import (
    ClaimsFile,
    CodegenPlan,
    DataInventory,
    ExperimentResult,
    ExperimentTodo,
    ReplicationPlan,
    validate_data_inventory,
    validate_experiment_coverage,
    validate_experiment_result,
    validate_replication_plan,
    validate_reproduction_report,
)


def claims_payload():
    return {
        "claims": [
            {
                "claim_id": "C1",
                "statement": "Accuracy improved.",
                "role": "validation",
                "kind": "numeric",
                "paper_result": 0.91,
                "provenance": {
                    "page": 3,
                    "section": "Results",
                    "quote": "Accuracy improved to 0.91.",
                },
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


def test_reproduction_report_requires_all_audit_content():
    claims = ClaimsFile.model_validate(claims_payload())
    experiments = ExperimentTodo.model_validate(todo_payload())
    codegen_plan = CodegenPlan.model_validate(
        {
            "files": [{"path": "run.py", "responsibility": "Run"}],
            "dependency_order": ["run.py"],
            "entry_points": ["run.py"],
            "shared_state": "Files",
            "ambiguities": [
                {
                    "question": "The batch size is unspecified.",
                    "assumption": "Use batch size 32.",
                }
            ],
        }
    )
    report = (
        "## 1. Per-experiment reports\nE1 C1 Figure 1\n"
        "## 2. Validation claim assessment\nC1 close\n"
        "## 3. Replication risk list\n"
        "The batch size is unspecified. Use batch size 32.\n"
    )
    validate_reproduction_report(report, claims, experiments, codegen_plan)

    with pytest.raises(ValueError, match="required section"):
        validate_reproduction_report(
            report.replace("## 2. Validation claim assessment", "Validation"),
            claims,
            experiments,
            codegen_plan,
        )
    with pytest.raises(ValueError, match="ambiguity risks"):
        validate_reproduction_report(
            report.replace("The batch size is unspecified.", "Unspecified input."),
            claims,
            experiments,
            codegen_plan,
        )
