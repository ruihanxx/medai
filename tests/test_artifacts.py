import json

import pytest

from medai.models import (
    ClaimsFile,
    CodegenPlan,
    ExperimentTodo,
    ReplicationLog,
    ReplicationPlan,
    validate_experiment_coverage,
    validate_replication_log,
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


def replication_plan_payload():
    return {
        "environment": {
            "language": "Python",
            "key_dependencies": ["numpy"],
            "setup_hints": "Use the available CPU.",
        },
        "steps": [
            {
                "id": 1,
                "description": "Install dependencies.",
                "command_hint": "python -m pip install -r requirements.txt",
                "expected_outcome": "Dependencies import successfully.",
                "verifies": [],
            },
            {
                "id": 2,
                "description": "Run evaluation.",
                "command_hint": "python run.py",
                "expected_outcome": "Writes metrics.json.",
                "verifies": ["C1"],
            },
            {
                "id": 3,
                "description": "Render the figure.",
                "command_hint": "python plot.py",
                "expected_outcome": "Writes figure.png.",
                "verifies": ["Figure 1"],
            },
        ],
    }


def test_claim_and_experiment_coverage_is_exact():
    claims = ClaimsFile.model_validate(claims_payload())
    todo = ExperimentTodo.model_validate(todo_payload())
    validate_experiment_coverage(claims, todo)

    todo.experiments[0].claims = ["C2"]
    with pytest.raises(ValueError, match="unknown claims"):
        validate_experiment_coverage(claims, todo)


def test_replication_plan_must_cover_claims_and_artifacts():
    todo = ExperimentTodo.model_validate(todo_payload())
    plan = ReplicationPlan.model_validate(replication_plan_payload())
    validate_replication_plan(todo, plan)
    plan.steps[2].verifies = []
    with pytest.raises(ValueError, match="missing references"):
        validate_replication_plan(todo, plan)


def test_replication_log_must_follow_plan_and_record_outputs():
    plan = ReplicationPlan.model_validate(replication_plan_payload())
    log = ReplicationLog.model_validate(
        {
            "step_outcomes": [
                {
                    "step_id": step.id,
                    "description": step.description,
                    "command_executed": step.command_hint,
                    "exit_code": 0,
                    "stdout": "done",
                    "stderr": "",
                    "output_files": [] if step.id == 1 else [f"step-{step.id}.json"],
                    "duration_seconds": 1.0,
                    "fixes_applied": [],
                    "code_modified": False,
                    "notes": "",
                }
                for step in plan.steps
            ],
        }
    )
    validate_replication_log(plan, log)
    log.step_outcomes[1].output_files = []
    with pytest.raises(ValueError, match="no output files"):
        validate_replication_log(plan, log)


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
    with pytest.raises(ValueError, match="missing experiments"):
        validate_reproduction_report(
            report.replace("E1 C1 Figure 1", "E10 C10 Figure 1"),
            claims,
            experiments,
            codegen_plan,
        )
