from __future__ import annotations

from pathlib import Path

from medai.models import GraphNode, SmartReplicateLog, validate_smart_replicate_log


def test_smart_replicate_is_claim_keyed_and_requires_paper_anchor() -> None:
    claim = GraphNode(
        id="C1",
        inputs=["V1"],
        method={"comparison": "difference"},
        paper_result={"auroc": 0.8},
        provenance=[],
    )
    log = SmartReplicateLog.model_validate(
        {
            "claim_id": "C1",
            "baseline_result": {"auroc": 0.77},
            "paper_result": {"auroc": 0.8},
            "rounds": [],
            "final_result": {"auroc": 0.79},
        }
    )
    validate_smart_replicate_log(claim, log)
    assert Path("replication/claims") / claim.id / "smart_replicate_log.json" == Path(
        "replication/claims/C1/smart_replicate_log.json"
    )
