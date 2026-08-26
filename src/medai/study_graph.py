"""Paper-graph traversal and orchestrator-owned node-state operations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from medai.models import NodeState, NodeUpdate, PaperGraph, PendingNodeUpdate


def graph_ancestors(graph: PaperGraph, node_id: str, *, include_self: bool = True) -> set[str]:
    """Return the transitive AND-dependencies of a graph node."""
    nodes = graph.node_map
    if node_id not in nodes:
        raise ValueError(f"Unknown paper graph node ID: {node_id}")
    result: set[str] = {node_id} if include_self else set()

    def visit(current: str) -> None:
        for input_id in nodes[current].inputs:
            if input_id not in result:
                result.add(input_id)
                visit(input_id)

    visit(node_id)
    return result


def graph_descendants(graph: PaperGraph, node_id: str, *, include_self: bool = True) -> set[str]:
    """Return nodes transitively affected by a graph node."""
    if node_id not in graph.node_map:
        raise ValueError(f"Unknown paper graph node ID: {node_id}")
    consumers: dict[str, list[str]] = {node.id: [] for node in graph.nodes}
    for node in graph.nodes:
        for input_id in node.inputs:
            consumers[input_id].append(node.id)
    result: set[str] = {node_id} if include_self else set()

    def visit(current: str) -> None:
        for consumer in consumers[current]:
            if consumer not in result:
                result.add(consumer)
                visit(consumer)

    visit(node_id)
    return result


def runnable_subgraph(graph: PaperGraph, runnable_node_ids: Iterable[str]) -> PaperGraph:
    """Project a graph onto an already dependency-closed runnable node set."""
    runnable = set(runnable_node_ids)
    unknown = sorted(runnable - set(graph.node_map))
    if unknown:
        raise ValueError(f"Runnable subgraph references unknown node IDs: {unknown}")
    missing_inputs = sorted(
        {
            input_id
            for node_id in runnable
            for input_id in graph.node_map[node_id].inputs
            if input_id not in runnable
        }
    )
    if missing_inputs:
        raise ValueError(f"Runnable node set is not dependency closed: {missing_inputs}")
    payload: dict[str, Any] = {"version": graph.version}
    for category, nodes in graph.collections:
        payload[category] = [node.model_dump(mode="json") for node in nodes if node.id in runnable]
    return PaperGraph.model_validate(payload)


def load_node_state(path: Path) -> NodeState:
    try:
        return NodeState.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Node state is missing: {path}") from exc


def write_empty_node_state(path: Path, paper_graph_sha256: str) -> NodeState:
    state = NodeState(paper_graph_sha256=paper_graph_sha256, updates=[])
    _write_model(path, state)
    return state


def merge_node_updates(
    path: Path,
    graph: PaperGraph,
    paper_graph_sha256: str,
    source: str,
    updates: Iterable[PendingNodeUpdate | dict[str, Any]],
) -> NodeState:
    """Idempotently replace updates owned by one stage source."""
    if not source.strip():
        raise ValueError("Node-update source must not be blank")
    state = (
        load_node_state(path)
        if path.is_file()
        else NodeState(paper_graph_sha256=paper_graph_sha256, updates=[])
    )
    if state.paper_graph_sha256 != paper_graph_sha256:
        raise ValueError("Node state does not match the immutable paper graph")
    known_ids = set(graph.node_map)
    parsed = [
        update if isinstance(update, PendingNodeUpdate) else PendingNodeUpdate.model_validate(update)
        for update in updates
    ]
    node_ids = [update.node_id for update in parsed]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError(f"Source {source!r} contains duplicate node updates")
    unknown = sorted(set(node_ids) - known_ids)
    if unknown:
        raise ValueError(f"Node updates reference unknown paper graph IDs: {unknown}")

    replacements: dict[tuple[str, str], NodeUpdate] = {}
    for update in parsed:
        payload = update.model_dump(mode="python")
        payload.pop("source", None)
        replacements[(source, update.node_id)] = NodeUpdate(source=source, **payload)
    merged: list[NodeUpdate] = []
    for existing in state.updates:
        key = (existing.source, existing.node_id)
        if key not in replacements:
            merged.append(existing)
    merged.extend(replacements[key] for key in sorted(replacements))
    result = NodeState(paper_graph_sha256=paper_graph_sha256, updates=merged)
    _write_model(path, result)
    return result


def remove_node_updates(
    path: Path,
    *,
    sources: Iterable[str] = (),
    source_prefixes: Iterable[str] = (),
) -> NodeState:
    """Remove exactly the updates owned by invalidated stages or attempts."""
    state = load_node_state(path)
    exact = set(sources)
    prefixes = tuple(source_prefixes)
    kept = [
        update
        for update in state.updates
        if update.source not in exact and not update.source.startswith(prefixes)
    ]
    result = NodeState(paper_graph_sha256=state.paper_graph_sha256, updates=kept)
    _write_model(path, result)
    return result


def collect_lineage_issues(
    graph: PaperGraph,
    node_state: NodeState,
    node_id: str,
) -> list[dict[str, Any]]:
    """Collect local issues from the node and true ancestors without copying them."""
    ancestors = graph_ancestors(graph, node_id)
    paths_by_origin = {
        origin: _paths_from_ancestor(graph, origin, node_id) for origin in ancestors
    }
    collected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for update in node_state.updates:
        if update.node_id not in ancestors:
            continue
        for issue in update.issues:
            issue_payload = issue.model_dump(mode="json")
            issue_hash = hashlib.sha256(
                json.dumps(issue_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            key = (update.node_id, issue_hash)
            if key in seen:
                continue
            seen.add(key)
            collected.append(
                {
                    "origin_node_id": update.node_id,
                    "sources": sorted(
                        {
                            candidate.source
                            for candidate in node_state.updates
                            if candidate.node_id == update.node_id
                            and any(
                                hashlib.sha256(
                                    json.dumps(
                                        candidate_issue.model_dump(mode="json"),
                                        sort_keys=True,
                                        separators=(",", ":"),
                                    ).encode("utf-8")
                                ).hexdigest()
                                == issue_hash
                                for candidate_issue in candidate.issues
                            )
                        }
                    ),
                    "paths": paths_by_origin[update.node_id],
                    "issue": issue_payload,
                }
            )
    return collected


def _paths_from_ancestor(graph: PaperGraph, origin: str, target: str) -> list[list[str]]:
    paths: list[list[str]] = []

    def walk(current: str, reverse_path: list[str]) -> None:
        if current == origin:
            paths.append(list(reversed(reverse_path)))
            return
        for input_id in graph.node_map[current].inputs:
            walk(input_id, [*reverse_path, input_id])

    walk(target, [target])
    return paths


def _write_model(path: Path, model: NodeState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
