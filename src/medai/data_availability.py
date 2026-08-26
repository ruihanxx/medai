"""Validation and orchestration-owned derivation of replication execution scope."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from medai.models import (
    BlockedNode,
    GraphDataAvailabilityReport,
    GraphExecutionScope,
    PaperGraph,
)
from medai.study_graph import graph_ancestors


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def derive_graph_execution_scope(
    graph: PaperGraph,
    report: GraphDataAvailabilityReport,
    *,
    paper_graph_sha256: str,
    report_sha256: str,
) -> GraphExecutionScope:
    """Validate P×upstream-D coverage and derive the maximal runnable claim subgraph."""
    category = graph.category_map
    expected_pairs = {
        (node.id, ancestor_id)
        for node in graph.preprocessing
        for ancestor_id in graph_ancestors(graph, node.id, include_self=False)
        if category[ancestor_id] == "datasets"
    }
    actual_pairs = [
        (item.preprocessing_id, item.dataset_id) for item in report.requirements
    ]
    if len(actual_pairs) != len(set(actual_pairs)):
        raise ValueError("Data availability contains duplicate preprocessing/dataset pairs")
    if set(actual_pairs) != expected_pairs:
        missing = sorted(expected_pairs - set(actual_pairs))
        extra = sorted(set(actual_pairs) - expected_pairs)
        raise ValueError(
            f"Data availability coverage mismatch; missing={missing!r}, extra={extra!r}"
        )

    direct_status = {node.id: "available" for node in graph.nodes}
    direct_blockers: dict[str, list[str]] = {node.id: [] for node in graph.nodes}
    for requirement in report.requirements:
        preprocessing_id = requirement.preprocessing_id
        if requirement.status == "unknown":
            direct_status[preprocessing_id] = "unknown"
        elif (
            requirement.status == "source_blocked"
            and direct_status[preprocessing_id] != "unknown"
        ):
            direct_status[preprocessing_id] = "source_blocked"
        if requirement.status != "available":
            direct_blockers[preprocessing_id].append(
                f"{requirement.dataset_id}: {requirement.required_content} — "
                f"{requirement.evidence}"
            )

    resolved: dict[str, str] = {}

    def resolve(node_id: str) -> str:
        if node_id in resolved:
            return resolved[node_id]
        inherited = [resolve(input_id) for input_id in graph.node_map[node_id].inputs]
        if direct_status[node_id] == "unknown" or "unknown" in inherited:
            status = "unknown"
        elif direct_status[node_id] == "source_blocked" or "source_blocked" in inherited:
            status = "source_blocked"
        else:
            status = "available"
        resolved[node_id] = status
        return status

    for node in graph.nodes:
        resolve(node.id)

    runnable_claim_ids = [claim.id for claim in graph.claims if resolved[claim.id] == "available"]
    runnable_set: set[str] = set()
    for claim_id in runnable_claim_ids:
        runnable_set.update(graph_ancestors(graph, claim_id))
    runnable = [node.id for node in graph.nodes if node.id in runnable_set]
    blocked = [
        BlockedNode(
            node_id=node.id,
            status=resolved[node.id],
            direct_data_blockers=direct_blockers[node.id],
            dependency_paths=_graph_blocking_paths(
                graph,
                node.id,
                direct_status,
                resolved,
            ),
        )
        for node in graph.nodes
        if resolved[node.id] != "available"
    ]

    blocked_claims = [item for item in blocked if category[item.node_id] == "claims"]
    if not runnable_claim_ids:
        verdict = "NONE"
    elif blocked_claims:
        verdict = "PARTIAL"
    else:
        verdict = "FULL"

    active_sources: list[str] = []
    for requirement in report.requirements:
        if (
            requirement.preprocessing_id in runnable_set
            and requirement.source_name
            and requirement.source_name not in active_sources
        ):
            active_sources.append(requirement.source_name)
    unsigned = {
        "paper_graph_sha256": paper_graph_sha256,
        "availability_report_sha256": report_sha256,
        "verdict": verdict,
        "runnable_node_ids": runnable,
        "blocked_nodes": [item.model_dump(mode="json") for item in blocked],
        "active_sources": active_sources,
        "execution_location": report.capacity_decision.execution_location,
    }
    scope_hash = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return GraphExecutionScope(scope_sha256=scope_hash, **unsigned)


def _graph_blocking_paths(
    graph: PaperGraph,
    node_id: str,
    direct_status: dict[str, str],
    resolved: dict[str, str],
) -> list[list[str]]:
    paths: list[list[str]] = []

    def walk(current: str, path: list[str]) -> None:
        if direct_status[current] != "available":
            paths.append(path)
            return
        for input_id in graph.node_map[current].inputs:
            if resolved[input_id] != "available":
                walk(input_id, [*path, input_id])

    walk(node_id, [node_id])
    return paths
