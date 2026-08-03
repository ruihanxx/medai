import json

import pytest

from medai.models import (
    ClaimsFile,
    CodegenAudit,
    CodegenPlan,
    EligibilityResult,
    EvidenceSummary,
    ExperimentContracts,
    ExperimentTodo,
    ExperimentWeights,
    IdeaAssessment,
    IdeaImplementationPlan,
    ReplicationLog,
    ReplicationPlan,
    RoundSummary,
    validate_codegen_audit,
    validate_experiment_coverage,
    validate_idea_implementation_plan,
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


def test_autoresearch_artifacts_enforce_model_and_weighted_score_contracts():
    with pytest.raises(ValueError, match="research brief"):
        EligibilityResult.model_validate(
            {"eligible": True, "reason": "Predictive task", "evidence_paths": []}
        )

    eligibility = EligibilityResult.model_validate(
        {
            "eligible": True,
            "reason": "Predictive task",
            "evidence_paths": ["paper.md"],
            "research_brief": {
                "problem": "Predict an outcome.",
                "context": "Clinical prediction.",
                "proposed_method": "Base classifier.",
                "datasets": ["Cohort dataset"],
            },
        }
    )
    assert eligibility.research_brief is not None

    weights = ExperimentWeights.model_validate(
        {
            "experiments": [
                {
                    "experiment_id": "E1",
                    "weight": 1.0,
                    "rationale": "Primary experiment.",
                }
            ]
        }
    )
    contracts = ExperimentContracts.model_validate(
        {
            "experiments": [
                {
                    "experiment_id": "E1",
                    "baseline_entry_points": ["python run.py"],
                    "model_implementation_paths": ["src/model.py"],
                    "integration_paths": ["run.py"],
                    "input_contract": "feature vector",
                    "target_contract": "binary label",
                    "output_contract": "risk score",
                    "training_contract": "fixed training loop",
                    "evaluation_contract": "fixed evaluation",
                    "metrics": ["accuracy"],
                    "primary_metric": "accuracy",
                    "metric_direction": "higher",
                }
            ]
        }
    )
    assert weights.experiments[0].weight == 1.0

    implementation = IdeaImplementationPlan.model_validate(
        {
            "idea_id": "R01-I01",
            "summary": "Add a calibrated refinement head.",
            "model_description": "Standalone calibrated model.",
            "new_model_files": ["src/refinement.py"],
            "experiment_integrations": [
                {
                    "experiment_id": "E1",
                    "integration_changes": [
                        {
                            "path": "run.py",
                            "change": "Add model selection.",
                            "rationale": "Embed the new model.",
                        }
                    ],
                    "baseline_entry_points": ["python run.py --model baseline"],
                    "refinement_entry_points": ["python run.py --model refinement"],
                }
            ],
        }
    )
    validate_idea_implementation_plan(contracts, implementation)
    assert implementation.idea_id == "R01-I01"

    audit = CodegenAudit.model_validate(
        {
            "idea_id": "R01-I01",
            "verdict": "pass",
            "model_only": True,
            "scope_evidence": ["changed-file list"],
            "scope_issue": None,
            "checks": [
                {
                    "experiment_id": "E1",
                    "aspect": aspect,
                    "verdict": "pass",
                    "evidence": ["diff"],
                    "issue": None,
                }
                for aspect in ("input", "target", "output", "training", "evaluation")
            ],
            "required_fixes": [],
        }
    )
    validate_codegen_audit(contracts, audit)
    assert audit.verdict == "pass"

    assessment = IdeaAssessment.model_validate(
        {
            "idea_id": "R01-I01",
            "verdict": "valid",
            "summary": "Accuracy improved.",
            "audit_passed": True,
            "protocol_consistent": True,
            "experiments": [
                {
                    "experiment_id": "E1",
                    "metric_name": "accuracy",
                    "direction": "higher",
                    "weight": 1.0,
                    "baseline_value": 0.8,
                    "refined_value": 0.82,
                    "absolute_delta": 0.02,
                    "relative_delta": 0.025,
                    "score": 0.025,
                    "weighted_score": 0.025,
                    "evidence_paths": ["metrics.json"],
                }
            ],
            "weighted_score": 0.025,
            "threshold": 0.0,
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
    assert assessment.weighted_score == 0.025
    assert summary.has_valid_refinement is True

    with pytest.raises(ValueError, match="weighted score"):
        IdeaAssessment.model_validate(
            {
                **assessment.model_dump(mode="json"),
                "weighted_score": 0.5,
            }
        )

    with pytest.raises(ValueError, match="failed audit"):
        IdeaAssessment.model_validate(
            {
                **assessment.model_dump(mode="json"),
                "verdict": "inconclusive",
                "audit_passed": False,
                "failure_reasons": ["Audit failed."],
            }
        )
    with pytest.raises(ValueError, match="must list failure reasons"):
        IdeaAssessment.model_validate(
            {
                **assessment.model_dump(mode="json"),
                "verdict": "invalid",
                "threshold": 0.1,
                "failure_reasons": [],
            }
        )


def test_autoresearch_assessment_aggregates_direction_adjusted_experiment_scores():
    assessment = IdeaAssessment.model_validate(
        {
            "idea_id": "R01-I01",
            "verdict": "valid",
            "summary": "Weighted improvement exceeds the threshold.",
            "audit_passed": True,
            "protocol_consistent": True,
            "experiments": [
                {
                    "experiment_id": "E1",
                    "metric_name": "accuracy",
                    "direction": "higher",
                    "weight": 0.7,
                    "baseline_value": 0.8,
                    "refined_value": 0.88,
                    "absolute_delta": 0.08,
                    "relative_delta": 0.1,
                    "score": 0.1,
                    "weighted_score": 0.07,
                    "evidence_paths": ["e1.json"],
                },
                {
                    "experiment_id": "E2",
                    "metric_name": "error",
                    "direction": "lower",
                    "weight": 0.3,
                    "baseline_value": 2.0,
                    "refined_value": 1.8,
                    "absolute_delta": -0.2,
                    "relative_delta": -0.1,
                    "score": 0.1,
                    "weighted_score": 0.03,
                    "evidence_paths": ["e2.json"],
                },
            ],
            "weighted_score": 0.1,
            "threshold": 0.05,
            "failure_reasons": [],
        }
    )

    assert assessment.verdict == "valid"
