import json

import pytest

from medai.models import (
    ClaimsFile,
    CodegenAudit,
    CodegenPlan,
    EligibilityResult,
    EvidenceSummary,
    ExperimentTodo,
    IdeaAssessment,
    IdeaImplementationPlan,
    ReplicationLog,
    ReplicationPlan,
    RoundSummary,
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


def test_evidence_environment_accepts_additional_audit_metadata():
    evidence = EvidenceSummary.model_validate(
        {
            "environment": {
                "python_version": "3.12",
                "gpu_available": False,
                "gpu_model": None,
                "key_packages": {"numpy": "2.0"},
                "r_version": "4.6.1",
                "resources": {"logical_cpu_cores": 8, "memory_total_gb": 7.75},
            }
        }
    )

    assert evidence.environment.r_version == "4.6.1"
    assert evidence.environment.resources["logical_cpu_cores"] == 8


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


def test_autoresearch_artifacts_enforce_anchor_and_improvement_contracts():
    with pytest.raises(ValueError, match="research anchors"):
        EligibilityResult.model_validate(
            {"eligible": True, "reason": "Predictive task", "evidence_paths": []}
        )

    implementation = IdeaImplementationPlan.model_validate(
        {
            "idea_id": "R01-I01",
            "summary": "Add a calibrated refinement head.",
            "change_points": [
                {
                    "path": "src/refinement.py",
                    "change": "Add the refinement.",
                    "rationale": "Test the idea without replacing the baseline.",
                }
            ],
            "baseline_entry_points": ["python run.py --model baseline"],
            "refinement_entry_points": ["python run.py --model refinement"],
            "preserved_anchors": [
                "task_and_prediction_target",
                "dataset_cohort_and_io",
                "metrics_and_protocol",
                "baseline_method",
            ],
        }
    )
    assert implementation.idea_id == "R01-I01"

    audit = CodegenAudit.model_validate(
        {
            "idea_id": "R01-I01",
            "verdict": "pass",
            "checks": [
                {"anchor": anchor, "verdict": "pass", "evidence": ["diff"]}
                for anchor in implementation.preserved_anchors
            ],
            "required_fixes": [],
        }
    )
    assert audit.verdict == "pass"

    assessment = IdeaAssessment.model_validate(
        {
            "idea_id": "R01-I01",
            "verdict": "valid",
            "summary": "Accuracy improved.",
            "audit_passed": True,
            "protocol_consistent": True,
            "primary_metric": {
                "name": "accuracy",
                "direction": "higher",
                "baseline_value": 0.8,
                "refined_value": 0.82,
                "absolute_delta": 0.02,
                "relative_delta": 0.025,
                "uncertainty_available": False,
                "noise_threshold": None,
                "uncertainty_method": None,
                "improvement_supported": True,
            },
            "secondary_metrics": [],
            "evidence_paths": ["metrics.json"],
            "failure_reasons": [],
        }
    )
    summary = RoundSummary.model_validate(
        {
            "round": 1,
            "ideas": [
                {
                    "idea_id": f"R01-I{index:02d}",
                    "verdict": "valid" if index == 1 else "invalid",
                    "reason": "assessment complete",
                    "assessment_path": f"idea_{index:02d}/assessment.json",
                }
                for index in range(1, 4)
            ],
            "has_valid_refinement": True,
        }
    )
    assert assessment.primary_metric is not None
    assert summary.has_valid_refinement is True

    with pytest.raises(ValueError, match="declared criterion"):
        IdeaAssessment.model_validate(
            {
                **assessment.model_dump(mode="json"),
                "primary_metric": {
                    **assessment.primary_metric.model_dump(mode="json"),
                    "improvement_supported": False,
                },
            }
        )
