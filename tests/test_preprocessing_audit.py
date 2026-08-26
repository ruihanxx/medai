from __future__ import annotations

import json

import pytest

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
