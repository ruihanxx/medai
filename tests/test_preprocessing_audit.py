from __future__ import annotations

import json

import pytest

from medai.prompts import TEMPLATES_DIR
from medai.workflow import read_audit_report


def test_audit_issue_has_one_origin_node_and_open_details(tmp_path) -> None:
    path = tmp_path / "audit.json"
    path.write_text(
        json.dumps(
            {
                "verdict": "FAIL",
                "issues": [
                    {
                        "node_id": "P_split_2",
                        "description": "test split cannot be reconstructed",
                        "route": "preprocessing_fix",
                        "required_fix": {"inspect": "supplement"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report = read_audit_report(path)
    assert report["issues"][0]["required_fix"] == {"inspect": "supplement"}


@pytest.mark.parametrize(
    "payload",
    [
        {"verdict": "PASS", "issues": [{"node_id": "P1", "description": "x"}]},
        {"verdict": "FAIL", "issues": []},
        {"verdict": "FAIL", "issues": [{"node_id": "", "description": "x"}]},
        {"verdict": "FAIL", "issues": [{"node_id": "P1", "description": ""}]},
    ],
)
def test_audit_report_rejects_inconsistent_or_empty_issues(tmp_path, payload) -> None:
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError):
        read_audit_report(path)


def test_cohort_refinement_forbids_paper_result_gates() -> None:
    prompt = (TEMPLATES_DIR / "cohort_refine" / "session_instructions.md").read_text(
        encoding="utf-8"
    )
    prompt = " ".join(prompt.split())
    assert "graph `paper_result` as an observed reference output" in prompt
    assert "runtime assertion, reconciliation gate" in prompt
    assert "Only source, method, schema, and artifact-integrity conditions" in prompt


def test_cohort_refinement_requires_candidate_semantic_delta_review() -> None:
    prompt = (TEMPLATES_DIR / "cohort_refine" / "session_instructions.md").read_text(
        encoding="utf-8"
    )
    prompt = " ".join(prompt.split())
    assert "`baseline_codebase` and `candidate_codebase` copies" in prompt
    assert "self-audit the complete candidate delta against the untouched baseline" in prompt
    assert "Revert every unrelated delta" in prompt
    assert "If any extra effect contradicts the paper" in prompt
