#!/usr/bin/env python3
"""Generate a standalone interactive graph page from one MedAI v6 run."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import os
import re
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GRAPH_COLLECTIONS = (
    "datasets",
    "preprocessing",
    "training",
    "models",
    "validations",
    "claims",
)
TYPE_CODES = {
    "datasets": "D",
    "preprocessing": "P",
    "training": "T",
    "models": "M",
    "validations": "V",
    "claims": "C",
}
CLAIM_REPORT_LABELS = (
    "Paper result",
    "Reproduced result",
    "Upstream node results",
    "Direct comparison",
    "Scope blockers",
    "Lineage issues",
    "Assessment",
)
NODE_WIDTH = 210
NODE_HEIGHT = 68
HORIZONTAL_GAP = 92
VERTICAL_GAP = 30
MARGIN_X = 84
MARGIN_Y = 76


class VisualizationError(RuntimeError):
    """Raised when canonical run artifacts cannot produce a faithful page."""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise VisualizationError(f"Required run artifact is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise VisualizationError(f"Run artifact is not valid JSON: {path}: {exc}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_graph(graph: Any) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    if not isinstance(graph, dict) or graph.get("version") != 1:
        raise VisualizationError("paper_graph.json must contain graph version 1")

    nodes: list[dict[str, Any]] = []
    categories: dict[str, str] = {}
    for category in GRAPH_COLLECTIONS:
        collection = graph.get(category)
        if not isinstance(collection, list):
            raise VisualizationError(f"paper_graph.json field {category!r} must be a list")
        for node in collection:
            if not isinstance(node, dict):
                raise VisualizationError(f"Graph collection {category!r} contains a non-object")
            node_id = node.get("id")
            inputs = node.get("inputs")
            if not isinstance(node_id, str) or not node_id.strip():
                raise VisualizationError(f"Graph collection {category!r} has an invalid node ID")
            if not isinstance(inputs, list) or not all(isinstance(value, str) for value in inputs):
                raise VisualizationError(f"Graph node {node_id} has invalid inputs")
            if node_id in categories:
                raise VisualizationError(f"Graph contains duplicate node ID: {node_id}")
            categories[node_id] = category
            nodes.append(node)

    node_ids = set(categories)
    unknown = sorted(
        {input_id for node in nodes for input_id in node["inputs"] if input_id not in node_ids}
    )
    if unknown:
        raise VisualizationError(f"Graph inputs reference unknown nodes: {unknown}")

    original_index = {node["id"]: index for index, node in enumerate(nodes)}
    indegree = {node["id"]: len(node["inputs"]) for node in nodes}
    consumers: dict[str, list[str]] = {node["id"]: [] for node in nodes}
    for node in nodes:
        for input_id in node["inputs"]:
            consumers[input_id].append(node["id"])

    ready = [
        (original_index[node_id], node_id) for node_id, degree in indegree.items() if degree == 0
    ]
    heapq.heapify(ready)
    topological_order: list[str] = []
    while ready:
        _, node_id = heapq.heappop(ready)
        topological_order.append(node_id)
        for consumer in consumers[node_id]:
            indegree[consumer] -= 1
            if indegree[consumer] == 0:
                heapq.heappush(ready, (original_index[consumer], consumer))
    if len(topological_order) != len(nodes):
        raise VisualizationError("paper_graph.json contains a cycle")
    return nodes, categories, topological_order


def _node_label(node: dict[str, Any]) -> str:
    for key in ("statement", "name", "title", "description"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    method = node.get("method")
    if isinstance(method, str) and method.strip():
        return method.strip()
    if isinstance(method, dict):
        for value in method.values():
            if isinstance(value, str) and value.strip():
                return value.strip()
    return node["id"]


def _parse_claim_report(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    labels = "|".join(re.escape(label) for label in CLAIM_REPORT_LABELS)
    matches = list(re.finditer(rf"^({labels}):[ \t]*", text, re.MULTILINE))
    fields: dict[str, str] = {}
    for index, match in enumerate(matches):
        label = match.group(1)
        if label in fields:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        fields[label] = text[match.end() : end].strip()
    return fields


def _safe_json(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    return value


def _evidence_link(evidence: str, run_dir: Path, output_dir: Path) -> str | None:
    value = evidence.strip()
    if not value:
        return None
    workspace_prefix = "/workspace/output/"
    if value.startswith(workspace_prefix):
        value = value[len(workspace_prefix) :]
    elif Path(value).is_absolute():
        return None

    candidates = [run_dir / value]
    if not value.startswith("codegen/codebase/"):
        candidates.append(run_dir / "codegen" / "codebase" / value)
    if not value.startswith("replication/"):
        candidates.append(run_dir / "replication" / value)

    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(run_dir)
        except ValueError:
            continue
        if not resolved.exists():
            continue
        try:
            relative = os.path.relpath(resolved, output_dir)
        except ValueError:
            return None
        return Path(relative).as_posix()
    return None


def _layout_graph(
    nodes_by_id: dict[str, dict[str, Any]],
    topological_order: list[str],
) -> tuple[dict[str, dict[str, float]], int, int]:
    rank: dict[str, int] = {}
    consumers: dict[str, list[str]] = defaultdict(list)
    original_index = {node_id: index for index, node_id in enumerate(topological_order)}
    for node_id in topological_order:
        inputs = nodes_by_id[node_id]["inputs"]
        rank[node_id] = max((rank[input_id] + 1 for input_id in inputs), default=0)
        for input_id in inputs:
            consumers[input_id].append(node_id)

    layers: dict[int, list[str]] = defaultdict(list)
    for node_id in topological_order:
        layers[rank[node_id]].append(node_id)
    maximum_rank = max(layers, default=0)

    for _ in range(3):
        positions = {
            node_id: index / max(1, len(layers[layer_rank]) - 1)
            for layer_rank in range(maximum_rank + 1)
            for index, node_id in enumerate(layers[layer_rank])
        }
        for layer_rank in range(1, maximum_rank + 1):
            layers[layer_rank].sort(
                key=lambda node_id: (
                    sum(positions[input_id] for input_id in nodes_by_id[node_id]["inputs"])
                    / max(1, len(nodes_by_id[node_id]["inputs"])),
                    original_index[node_id],
                )
            )
        positions = {
            node_id: index / max(1, len(layers[layer_rank]) - 1)
            for layer_rank in range(maximum_rank + 1)
            for index, node_id in enumerate(layers[layer_rank])
        }
        for layer_rank in range(maximum_rank - 1, -1, -1):
            layers[layer_rank].sort(
                key=lambda node_id: (
                    sum(positions[consumer] for consumer in consumers[node_id])
                    / max(1, len(consumers[node_id])),
                    original_index[node_id],
                )
            )

    maximum_layer_size = max((len(layer) for layer in layers.values()), default=1)
    canvas_height = max(
        760,
        2 * MARGIN_Y + maximum_layer_size * NODE_HEIGHT + (maximum_layer_size - 1) * VERTICAL_GAP,
    )
    canvas_width = max(
        1180,
        2 * MARGIN_X + (maximum_rank + 1) * NODE_WIDTH + maximum_rank * HORIZONTAL_GAP,
    )
    layout: dict[str, dict[str, float]] = {}
    usable_height = canvas_height - 2 * MARGIN_Y
    for layer_rank, layer in layers.items():
        layer_height = len(layer) * NODE_HEIGHT + max(0, len(layer) - 1) * VERTICAL_GAP
        start_y = MARGIN_Y + (usable_height - layer_height) / 2
        for index, node_id in enumerate(layer):
            layout[node_id] = {
                "x": MARGIN_X + NODE_WIDTH / 2 + layer_rank * (NODE_WIDTH + HORIZONTAL_GAP),
                "y": start_y + NODE_HEIGHT / 2 + index * (NODE_HEIGHT + VERTICAL_GAP),
                "rank": layer_rank,
            }
    return layout, canvas_width, canvas_height


def build_run_graph_snapshot(run_dir: Path, output_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    manifest_path = run_dir / "manifest.json"
    graph_path = run_dir / "preprocessing" / "paper_graph.json"
    node_state_path = run_dir / "graph" / "node_state.json"
    scope_path = run_dir / "preprocessing" / "execution_scope.json"

    manifest = _load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("version") != 6:
        raise VisualizationError("The graph visualizer supports MedAI manifest v6 runs only")
    graph = _load_json(graph_path)
    node_state = _load_json(node_state_path)
    nodes, categories, topological_order = _validate_graph(graph)
    graph_sha256 = _sha256_file(graph_path)
    if not isinstance(node_state, dict) or node_state.get("paper_graph_sha256") != graph_sha256:
        raise VisualizationError("node_state.json is not bound to the current paper graph")

    scope: dict[str, Any] = {}
    if scope_path.is_file():
        loaded_scope = _load_json(scope_path)
        if not isinstance(loaded_scope, dict):
            raise VisualizationError("execution_scope.json must contain an object")
        if loaded_scope.get("paper_graph_sha256") != graph_sha256:
            raise VisualizationError("execution_scope.json is not bound to the current paper graph")
        scope = loaded_scope

    updates = node_state.get("updates")
    if not isinstance(updates, list):
        raise VisualizationError("node_state.json field 'updates' must be a list")
    updates_by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for update in updates:
        if not isinstance(update, dict):
            raise VisualizationError("node_state.json contains a non-object update")
        node_id = update.get("node_id")
        source = update.get("source")
        if node_id not in categories or not isinstance(source, str) or not source.strip():
            raise VisualizationError("node_state.json contains an invalid node update")
        updates_by_node[node_id].append(update)

    nodes_by_id = {node["id"]: node for node in nodes}
    topological_index = {node_id: index for index, node_id in enumerate(topological_order)}
    ancestors: dict[str, set[str]] = {}
    for node_id in topological_order:
        lineage: set[str] = set()
        for input_id in nodes_by_id[node_id]["inputs"]:
            lineage.add(input_id)
            lineage.update(ancestors[input_id])
        ancestors[node_id] = lineage

    layout, canvas_width, canvas_height = _layout_graph(nodes_by_id, topological_order)
    runnable_ids = set(scope.get("runnable_node_ids", []))
    blocked_by_id = {
        blocker.get("node_id"): blocker
        for blocker in scope.get("blocked_nodes", [])
        if isinstance(blocker, dict) and isinstance(blocker.get("node_id"), str)
    }

    snapshot_nodes = []
    source_names: set[str] = set()
    for node in nodes:
        node_id = node["id"]
        node_updates = updates_by_node[node_id]
        source_names.update(update["source"] for update in node_updates)
        actual_update = next(
            (update for update in node_updates if update["source"] == "replicate_agent"),
            None,
        )

        issue_groups: dict[str, dict[str, Any]] = {}
        for update in node_updates:
            issues = update.get("issues", [])
            if not isinstance(issues, list):
                raise VisualizationError(f"Node update for {node_id} has invalid issues")
            for issue in issues:
                if not isinstance(issue, dict) or not str(issue.get("description", "")).strip():
                    raise VisualizationError(f"Node update for {node_id} has an invalid issue")
                issue_key = json.dumps(
                    issue, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                )
                group = issue_groups.setdefault(
                    issue_key,
                    {"sources": [], "issue": _safe_json(issue)},
                )
                group["sources"].append(update["source"])
        local_issues = []
        for group in issue_groups.values():
            group["sources"] = sorted(set(group["sources"]))
            local_issues.append(group)

        scope_status = "unknown"
        if node_id in runnable_ids:
            scope_status = "runnable"
        elif node_id in blocked_by_id:
            scope_status = "blocked"

        evidence_items = []
        if actual_update is not None:
            evidence = actual_update.get("evidence", [])
            if isinstance(evidence, list):
                for item in evidence:
                    if isinstance(item, str) and item.strip():
                        evidence_items.append(
                            {
                                "path": item,
                                "href": _evidence_link(item, run_dir, output_dir),
                            }
                        )

        claim_comparison = None
        if categories[node_id] == "claims":
            report_path = run_dir / "report" / "claims" / f"{node_id}.md"
            report_fields = _parse_claim_report(report_path)
            report_href = None
            if report_path.is_file():
                try:
                    report_href = Path(os.path.relpath(report_path, output_dir)).as_posix()
                except ValueError:
                    report_href = None
            claim_comparison = {
                "paper_result": _safe_json(node.get("paper_result")),
                "reproduced_result": report_fields.get("Reproduced result"),
                "direct_comparison": report_fields.get("Direct comparison"),
                "assessment": report_fields.get("Assessment"),
                "report_href": report_href,
            }

        snapshot_nodes.append(
            {
                "id": node_id,
                "category": categories[node_id],
                "type_code": TYPE_CODES[categories[node_id]],
                "label": _node_label(node),
                "inputs": list(node["inputs"]),
                "method": _safe_json(node.get("method")),
                "provenance": _safe_json(node.get("provenance", [])),
                "paper_result": _safe_json(node.get("paper_result")),
                "scope_status": scope_status,
                "blocker": _safe_json(blocked_by_id.get(node_id)),
                "completion_status": (
                    actual_update.get("completion_status") if actual_update is not None else None
                ),
                "actual_result": (
                    _safe_json(actual_update.get("result")) if actual_update is not None else None
                ),
                "evidence": evidence_items,
                "local_issues": local_issues,
                "update_sources": sorted(update["source"] for update in node_updates),
                "ancestor_node_ids": sorted(ancestors[node_id], key=topological_index.__getitem__),
                "layout": layout[node_id],
                "claim_comparison": claim_comparison,
            }
        )

    edges = [
        {"id": f"{input_id}--{node['id']}", "source": input_id, "target": node["id"]}
        for node in nodes
        for input_id in node["inputs"]
    ]
    source_hashes = {
        "manifest.json": _sha256_file(manifest_path),
        "preprocessing/paper_graph.json": graph_sha256,
        "graph/node_state.json": _sha256_file(node_state_path),
    }
    if scope_path.is_file():
        source_hashes["preprocessing/execution_scope.json"] = _sha256_file(scope_path)

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": {
            "id": run_dir.name,
            "status": manifest.get("status"),
            "manifest_version": manifest.get("version"),
            "scope_verdict": scope.get("verdict"),
            "source_hashes": source_hashes,
        },
        "summary": {
            "node_count": len(snapshot_nodes),
            "edge_count": len(edges),
            "claim_count": sum(node["category"] == "claims" for node in snapshot_nodes),
            "issue_count": sum(len(node["local_issues"]) for node in snapshot_nodes),
            "sources": sorted(source_names),
        },
        "layout": {
            "canvas_width": canvas_width,
            "canvas_height": canvas_height,
            "node_width": NODE_WIDTH,
            "node_height": NODE_HEIGHT,
        },
        "nodes": snapshot_nodes,
        "edges": edges,
    }


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>MedAI Run Graph</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #08111f;
      --panel: #0e1a2d;
      --panel-2: #13233b;
      --line: #29405f;
      --text: #e9f1ff;
      --muted: #93a8c7;
      --accent: #69d6ff;
      --danger: #ff7185;
      --warning: #ffca67;
      --ok: #6de2a1;
      --node-d: #2878a7;
      --node-p: #6f5bd3;
      --node-t: #b05b9f;
      --node-m: #d16b62;
      --node-v: #b8862e;
      --node-c: #27866f;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.5 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    button, input { font: inherit; }
    .topbar { min-height: 72px; display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 14px 22px; border-bottom: 1px solid var(--line); background: linear-gradient(105deg, #10213a, #0a1424); }
    .title h1 { margin: 0; font-size: 18px; letter-spacing: .01em; }
    .title p { margin: 3px 0 0; color: var(--muted); font-size: 12px; }
    .stats { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
    .pill { display: inline-flex; align-items: center; gap: 6px; min-height: 27px; padding: 4px 9px; border: 1px solid var(--line); border-radius: 999px; background: #13233a; color: #c9d8ef; font-size: 12px; }
    .pill strong { color: white; }
    .app { --details-width: 430px; display: grid; grid-template-columns: minmax(0, 1fr) 8px var(--details-width); height: calc(100vh - 72px); min-height: 620px; }
    .workspace { min-width: 0; display: flex; flex-direction: column; }
    .toolbar { display: flex; align-items: center; gap: 8px; min-height: 52px; padding: 9px 14px; border-bottom: 1px solid var(--line); background: #0b1728; }
    .toolbar input { width: min(330px, 40vw); padding: 8px 11px; border: 1px solid #385274; border-radius: 8px; background: #071221; color: var(--text); outline: none; }
    .toolbar input:focus { border-color: var(--accent); box-shadow: 0 0 0 2px #69d6ff24; }
    .toolbar button { min-width: 34px; height: 34px; padding: 0 10px; border: 1px solid #385274; border-radius: 8px; background: #13243b; color: var(--text); cursor: pointer; }
    .toolbar button:hover { background: #1b3150; }
    .hint { margin-left: auto; color: var(--muted); font-size: 12px; white-space: nowrap; }
    .graph-viewport { position: relative; flex: 1; overflow: hidden; touch-action: none; background-color: #07111f; background-image: radial-gradient(#29415e 1px, transparent 1px); background-size: 22px 22px; cursor: grab; }
    .graph-viewport.dragging { cursor: grabbing; user-select: none; }
    svg { display: block; width: 100%; height: 100%; }
    .edge { fill: none; stroke: #395474; stroke-width: 1.45; opacity: .67; transition: opacity .12s, stroke .12s, stroke-width .12s; }
    .edge.dimmed { opacity: .08; }
    .edge.lineage { opacity: 1; stroke: var(--accent); stroke-width: 2.6; }
    .node { cursor: pointer; outline: none; transition: opacity .12s; }
    .node.dimmed { opacity: .14; }
    .node .node-box { stroke: #7591b6; stroke-width: 1.2; filter: drop-shadow(0 6px 8px #0007); transition: stroke .12s, stroke-width .12s, filter .12s; }
    .node[data-category="datasets"] .node-box { fill: var(--node-d); }
    .node[data-category="preprocessing"] .node-box { fill: var(--node-p); }
    .node[data-category="training"] .node-box { fill: var(--node-t); }
    .node[data-category="models"] .node-box { fill: var(--node-m); }
    .node[data-category="validations"] .node-box { fill: var(--node-v); }
    .node[data-category="claims"] .node-box { fill: var(--node-c); }
    .node.blocked .node-box { stroke: var(--danger); stroke-width: 2.5; stroke-dasharray: 6 3; }
    .node.has-issues .node-box { stroke: var(--warning); stroke-width: 2.25; }
    .node.lineage .node-box { stroke: #d9f6ff; stroke-width: 2.5; filter: drop-shadow(0 0 8px #69d6ff99); }
    .node.focused .node-box { stroke: white; stroke-width: 3.5; filter: drop-shadow(0 0 11px #69d6ffcc); }
    .node.search-hit .node-box { stroke: white; stroke-width: 3; }
    .node text { fill: white; pointer-events: none; }
    .node .node-id { font-size: 15px; font-weight: 750; }
    .node .node-type { font-size: 10px; font-weight: 700; opacity: .8; letter-spacing: .08em; }
    .node .node-label { font-size: 11px; opacity: .9; }
    .node .node-status { font-size: 10px; opacity: .72; }
    .issue-badge { fill: #23160a; stroke: var(--warning); stroke-width: 1.4; }
    .issue-count { fill: var(--warning) !important; font-size: 10px; font-weight: 800; text-anchor: middle; dominant-baseline: central; }
    .details-resizer { position: relative; z-index: 2; cursor: col-resize; touch-action: none; background: #0a1627; outline: none; }
    .details-resizer::after { content: ""; position: absolute; inset: 0 3px; background: var(--line); transition: background .12s, box-shadow .12s; }
    .details-resizer:hover::after, .details-resizer:focus-visible::after, body.resizing-details .details-resizer::after { background: var(--accent); box-shadow: 0 0 8px #69d6ff88; }
    body.resizing-details { cursor: col-resize; user-select: none; }
    .details-panel { min-width: 0; overflow: auto; background: var(--panel); }
    .details-inner { padding: 20px; }
    .empty-state { min-height: 340px; display: grid; place-items: center; text-align: center; color: var(--muted); }
    .empty-state strong { display: block; color: var(--text); font-size: 17px; margin-bottom: 8px; }
    .detail-title { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
    .detail-title h2 { margin: 0; font-size: 23px; }
    .detail-title p { margin: 3px 0 0; color: var(--muted); }
    .section { margin-top: 16px; padding-top: 15px; border-top: 1px solid var(--line); }
    .section h3 { margin: 0 0 9px; font-size: 13px; text-transform: uppercase; letter-spacing: .08em; color: #b9cbea; }
    .section p { margin: 6px 0; }
    .muted { color: var(--muted); }
    pre { margin: 0; padding: 11px; max-height: 290px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; border: 1px solid #2b4464; border-radius: 8px; background: #081423; color: #dfeaff; font: 11px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .issue-card { margin: 8px 0; padding: 11px; border: 1px solid #6a5226; border-left: 3px solid var(--warning); border-radius: 8px; background: #241c0e; }
    .issue-card .source { color: var(--warning); font-size: 11px; margin-bottom: 5px; }
    .compare-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
    .compare-card { min-width: 0; padding: 10px; border: 1px solid #2d4667; border-radius: 8px; background: #0a1728; }
    .compare-card h4 { margin: 0 0 7px; color: #a9bddb; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }
    .compare-card pre { max-height: 240px; border: 0; padding: 0; background: transparent; }
    .assessment { display: inline-flex; margin: 8px 0 0; padding: 5px 9px; border-radius: 999px; font-weight: 750; text-transform: uppercase; font-size: 11px; }
    .assessment.close { background: #123c2b; color: var(--ok); }
    .assessment.not-close { background: #471c25; color: #ff93a3; }
    .assessment.not-assessable { background: #473613; color: var(--warning); }
    .assessment.unknown { background: #23344a; color: var(--muted); }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .evidence-list { margin: 6px 0 0; padding-left: 18px; }
    details { border: 1px solid #2b4464; border-radius: 8px; background: #0a1728; }
    details + details { margin-top: 7px; }
    summary { cursor: pointer; padding: 9px 11px; color: #c7d7ee; }
    details pre { border: 0; border-top: 1px solid #2b4464; border-radius: 0; }
    .legend { display: flex; flex-wrap: wrap; gap: 6px; }
    .legend .pill { border: 0; }
    .legend .datasets { background: var(--node-d); }
    .legend .preprocessing { background: var(--node-p); }
    .legend .training { background: var(--node-t); }
    .legend .models { background: var(--node-m); }
    .legend .validations { background: var(--node-v); }
    .legend .claims { background: var(--node-c); }
    @media (max-width: 980px) {
      .app { grid-template-columns: 1fr; height: auto; }
      .workspace { height: 65vh; min-height: 520px; }
      .details-resizer { display: none; }
      .details-panel { min-height: 35vh; border-left: 0; border-top: 1px solid var(--line); }
      .hint { display: none; }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="title"><h1 id="run-title">MedAI Run Graph</h1><p id="run-subtitle"></p></div>
    <div class="stats" id="stats"></div>
  </header>
  <main class="app">
    <section class="workspace">
      <div class="toolbar">
        <input id="search" type="search" placeholder="Search node ID, label, or issue…" aria-label="Search graph nodes">
        <button id="zoom-out" title="Zoom out">−</button>
        <button id="zoom-in" title="Zoom in">+</button>
        <button id="fit" title="Fit graph">Fit</button>
        <span class="hint">Hover: lineage · Ctrl+wheel: zoom · Drag: move camera</span>
      </div>
      <div class="graph-viewport" id="graph-viewport">
        <svg id="graph" role="img" aria-label="MedAI claim provenance graph"></svg>
      </div>
    </section>
    <div class="details-resizer" id="details-resizer" role="separator" aria-label="Resize details panel" aria-orientation="vertical" tabindex="0"></div>
    <aside class="details-panel" id="details-panel"><div class="details-inner" id="details"></div></aside>
  </main>
  <script id="run-graph-data" type="application/json">__MEDAI_RUN_GRAPH_JSON__</script>
  <script>
  "use strict";
  const DATA = JSON.parse(document.getElementById("run-graph-data").textContent);
  const SVG_NS = "http://www.w3.org/2000/svg";
  const nodes = new Map(DATA.nodes.map(node => [node.id, node]));
  const app = document.querySelector(".app");
  const svg = document.getElementById("graph");
  const viewport = document.getElementById("graph-viewport");
  const detailsResizer = document.getElementById("details-resizer");
  const detailsRoot = document.getElementById("details");
  let selectedId = null;
  let zoom = 1;
  let panX = 0;
  let panY = 0;
  let query = "";
  let detailsWidth = 430;

  function htmlElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }
  function svgElement(tag, attributes = {}) {
    const element = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  }
  function jsonText(value) {
    if (value === null || value === undefined) return "Not available";
    return typeof value === "string" ? value : JSON.stringify(value, null, 2);
  }
  function shortText(value, limit = 31) {
    const normalized = String(value || "").replace(/\s+/g, " ").trim();
    return normalized.length > limit ? normalized.slice(0, limit - 1) + "…" : normalized;
  }
  function addPill(parent, label, value) {
    const pill = htmlElement("span", "pill");
    pill.append(label + " ");
    pill.appendChild(htmlElement("strong", "", value));
    parent.appendChild(pill);
  }
  function addSection(title) {
    const section = htmlElement("section", "section");
    section.appendChild(htmlElement("h3", "", title));
    detailsRoot.appendChild(section);
    return section;
  }
  function addPre(parent, value) {
    parent.appendChild(htmlElement("pre", "", jsonText(value)));
  }
  function addDisclosure(parent, title, value) {
    const disclosure = htmlElement("details");
    disclosure.appendChild(htmlElement("summary", "", title));
    addPre(disclosure, value);
    parent.appendChild(disclosure);
  }

  document.getElementById("run-title").textContent = DATA.run.id;
  document.getElementById("run-subtitle").textContent =
    `manifest v${DATA.run.manifest_version} · ${DATA.run.status || "unknown"} · generated ${DATA.generated_at}`;
  const stats = document.getElementById("stats");
  addPill(stats, "Nodes", DATA.summary.node_count);
  addPill(stats, "Edges", DATA.summary.edge_count);
  addPill(stats, "Claims", DATA.summary.claim_count);
  addPill(stats, "Issues", DATA.summary.issue_count);
  addPill(stats, "Scope", DATA.run.scope_verdict || "N/A");

  const defs = svgElement("defs");
  const marker = svgElement("marker", {id: "arrow", markerWidth: 8, markerHeight: 8, refX: 7, refY: 3.5, orient: "auto", markerUnits: "strokeWidth"});
  marker.appendChild(svgElement("path", {d: "M0,0 L0,7 L7,3.5 z", fill: "context-stroke"}));
  defs.appendChild(marker);
  svg.appendChild(defs);
  const scene = svgElement("g", {class: "scene"});
  const edgeLayer = svgElement("g", {class: "edges"});
  const nodeLayer = svgElement("g", {class: "nodes"});
  scene.append(edgeLayer, nodeLayer);
  svg.appendChild(scene);

  const nodeWidth = DATA.layout.node_width;
  const nodeHeight = DATA.layout.node_height;
  DATA.edges.forEach(edge => {
    const source = nodes.get(edge.source).layout;
    const target = nodes.get(edge.target).layout;
    const x1 = source.x + nodeWidth / 2;
    const x2 = target.x - nodeWidth / 2;
    const bend = Math.max(34, (x2 - x1) * 0.45);
    const path = svgElement("path", {
      class: "edge",
      d: `M ${x1} ${source.y} C ${x1 + bend} ${source.y}, ${x2 - bend} ${target.y}, ${x2} ${target.y}`,
      "marker-end": "url(#arrow)",
      "data-source": edge.source,
      "data-target": edge.target,
    });
    edgeLayer.appendChild(path);
  });

  DATA.nodes.forEach(node => {
    const group = svgElement("g", {
      class: `node ${node.scope_status === "blocked" ? "blocked" : ""} ${node.local_issues.length ? "has-issues" : ""}`,
      transform: `translate(${node.layout.x - nodeWidth / 2},${node.layout.y - nodeHeight / 2})`,
      "data-id": node.id,
      "data-category": node.category,
      tabindex: 0,
      role: "button",
      "aria-label": `${node.id}, ${node.category}, ${node.local_issues.length} issues`,
    });
    group.appendChild(svgElement("rect", {class: "node-box", width: nodeWidth, height: nodeHeight, rx: 10}));
    const type = svgElement("text", {class: "node-type", x: 14, y: 17});
    type.textContent = node.type_code;
    const id = svgElement("text", {class: "node-id", x: 14, y: 37});
    id.textContent = node.id;
    const label = svgElement("text", {class: "node-label", x: 55, y: 36});
    label.textContent = shortText(node.label);
    const status = svgElement("text", {class: "node-status", x: 14, y: 56});
    status.textContent = node.scope_status + (node.completion_status ? ` · ${node.completion_status}` : "");
    group.append(type, id, label, status);
    if (node.local_issues.length) {
      group.appendChild(svgElement("circle", {class: "issue-badge", cx: nodeWidth - 16, cy: 16, r: 10}));
      const count = svgElement("text", {class: "issue-count", x: nodeWidth - 16, y: 16});
      count.textContent = node.local_issues.length;
      group.appendChild(count);
    }
    group.addEventListener("mouseenter", () => applyFocus(node.id));
    group.addEventListener("mouseleave", () => applyFocus(selectedId));
    group.addEventListener("click", event => {
      event.stopPropagation();
      selectedId = node.id;
      applyFocus(selectedId);
      showNode(node);
    });
    group.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        group.click();
      }
    });
    nodeLayer.appendChild(group);
  });

  function matchesSearch(node) {
    if (!query) return true;
    const issueText = node.local_issues.map(item => item.issue.description || "").join(" ");
    return `${node.id} ${node.category} ${node.label} ${issueText}`.toLowerCase().includes(query);
  }
  function applyFocus(focusId) {
    const related = focusId ? new Set([focusId, ...nodes.get(focusId).ancestor_node_ids]) : null;
    document.querySelectorAll(".node").forEach(element => {
      const node = nodes.get(element.dataset.id);
      element.classList.remove("dimmed", "lineage", "focused", "search-hit");
      if (related) {
        element.classList.toggle("dimmed", !related.has(node.id));
        element.classList.toggle("lineage", related.has(node.id));
        element.classList.toggle("focused", node.id === focusId);
      } else if (query) {
        const match = matchesSearch(node);
        element.classList.toggle("dimmed", !match);
        element.classList.toggle("search-hit", match);
      }
    });
    document.querySelectorAll(".edge").forEach(element => {
      element.classList.remove("dimmed", "lineage");
      if (related) {
        const inLineage = related.has(element.dataset.source) && related.has(element.dataset.target);
        element.classList.toggle("dimmed", !inLineage);
        element.classList.toggle("lineage", inLineage);
      } else if (query) {
        element.classList.add("dimmed");
      }
    });
  }

  function showOverview() {
    detailsRoot.replaceChildren();
    const empty = htmlElement("div", "empty-state");
    const content = htmlElement("div");
    content.appendChild(htmlElement("strong", "", "Explore this run"));
    content.appendChild(htmlElement("span", "", "Hover a node to highlight all upstream dependencies. Click a node to inspect its origin-local issues, result, evidence, and claim comparison."));
    const legendSection = htmlElement("div", "section");
    const legend = htmlElement("div", "legend");
    ["datasets", "preprocessing", "training", "models", "validations", "claims"].forEach(category => {
      legend.appendChild(htmlElement("span", `pill ${category}`, `${category[0].toUpperCase()} · ${category}`));
    });
    legendSection.appendChild(legend);
    content.appendChild(legendSection);
    empty.appendChild(content);
    detailsRoot.appendChild(empty);
  }

  function showNode(node) {
    detailsRoot.replaceChildren();
    const title = htmlElement("div", "detail-title");
    const titleText = htmlElement("div");
    titleText.appendChild(htmlElement("h2", "", node.id));
    titleText.appendChild(htmlElement("p", "", node.label));
    title.appendChild(titleText);
    title.appendChild(htmlElement("span", `pill ${node.category}`, `${node.type_code} · ${node.category}`));
    detailsRoot.appendChild(title);

    const meta = htmlElement("div", "legend");
    meta.appendChild(htmlElement("span", "pill", node.scope_status));
    meta.appendChild(htmlElement("span", "pill", `${node.ancestor_node_ids.length} upstream`));
    meta.appendChild(htmlElement("span", "pill", `${node.local_issues.length} issues`));
    detailsRoot.appendChild(meta);

    if (node.claim_comparison) {
      const comparison = addSection("Claim comparison");
      const grid = htmlElement("div", "compare-grid");
      const paper = htmlElement("div", "compare-card");
      paper.appendChild(htmlElement("h4", "", "Paper result"));
      addPre(paper, node.claim_comparison.paper_result);
      const reproduced = htmlElement("div", "compare-card");
      reproduced.appendChild(htmlElement("h4", "", "Reproduced result"));
      addPre(reproduced, node.claim_comparison.reproduced_result || node.actual_result);
      grid.append(paper, reproduced);
      comparison.appendChild(grid);
      const assessmentValue = (node.claim_comparison.assessment || "unknown").trim().toLowerCase();
      comparison.appendChild(htmlElement("div", `assessment ${assessmentValue.replaceAll(" ", "-")}`, assessmentValue));
      if (node.claim_comparison.report_href) {
        const reportLink = htmlElement("a", "", "Open complete claim report →");
        reportLink.href = node.claim_comparison.report_href;
        reportLink.target = "_blank";
        reportLink.rel = "noopener";
        comparison.appendChild(htmlElement("p")).appendChild(reportLink);
      }
      if (node.claim_comparison.direct_comparison) {
        addDisclosure(comparison, "Direct comparison details", node.claim_comparison.direct_comparison);
      }
    }

    const issues = addSection("Origin-local issues");
    if (!node.local_issues.length) {
      issues.appendChild(htmlElement("p", "muted", "No issues are recorded at this node."));
    } else {
      node.local_issues.forEach(item => {
        const card = htmlElement("div", "issue-card");
        card.appendChild(htmlElement("div", "source", item.sources.join(" · ")));
        card.appendChild(htmlElement("div", "", item.issue.description));
        const extra = {...item.issue};
        delete extra.description;
        if (Object.keys(extra).length) addDisclosure(card, "Additional issue fields", extra);
        issues.appendChild(card);
      });
    }

    const result = addSection("Replication result");
    addPre(result, node.actual_result);
    if (node.evidence.length) {
      const list = htmlElement("ul", "evidence-list");
      node.evidence.forEach(item => {
        const entry = htmlElement("li");
        if (item.href) {
          const link = htmlElement("a", "", item.path);
          link.href = item.href;
          link.target = "_blank";
          link.rel = "noopener";
          entry.appendChild(link);
        } else {
          entry.textContent = item.path;
        }
        list.appendChild(entry);
      });
      result.appendChild(list);
    }

    if (node.blocker) {
      const blockers = addSection("Scope blocker");
      addPre(blockers, node.blocker);
    }
    const definition = addSection("Paper definition");
    addDisclosure(definition, "Method", node.method);
    addDisclosure(definition, "Provenance", node.provenance);
    if (node.update_sources.length) addDisclosure(definition, "Update sources", node.update_sources);
  }

  function syncViewport() {
    svg.setAttribute("viewBox", `0 0 ${Math.max(1, viewport.clientWidth)} ${Math.max(1, viewport.clientHeight)}`);
  }
  function applyCamera() {
    scene.setAttribute("transform", `translate(${panX} ${panY}) scale(${zoom})`);
  }
  function setZoom(
    nextZoom,
    focusX = viewport.clientWidth / 2,
    focusY = viewport.clientHeight / 2,
  ) {
    const graphX = (focusX - panX) / zoom;
    const graphY = (focusY - panY) / zoom;
    zoom = Math.min(1.8, Math.max(.22, nextZoom));
    panX = focusX - graphX * zoom;
    panY = focusY - graphY * zoom;
    applyCamera();
  }
  function fitGraph() {
    syncViewport();
    const horizontal = (viewport.clientWidth - 24) / DATA.layout.canvas_width;
    const vertical = (viewport.clientHeight - 24) / DATA.layout.canvas_height;
    zoom = Math.min(1.8, Math.max(.22, Math.min(1, horizontal, vertical)));
    panX = (viewport.clientWidth - DATA.layout.canvas_width * zoom) / 2;
    panY = (viewport.clientHeight - DATA.layout.canvas_height * zoom) / 2;
    applyCamera();
  }
  document.getElementById("zoom-in").addEventListener("click", () => setZoom(zoom * 1.2));
  document.getElementById("zoom-out").addEventListener("click", () => setZoom(zoom / 1.2));
  document.getElementById("fit").addEventListener("click", fitGraph);
  viewport.addEventListener("wheel", event => {
    if (!event.ctrlKey) return;
    event.preventDefault();
    const rect = viewport.getBoundingClientRect();
    const pointerX = event.clientX - rect.left;
    const pointerY = event.clientY - rect.top;
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.clientHeight : 1;
    setZoom(zoom * Math.exp(-event.deltaY * unit * .0015), pointerX, pointerY);
  }, {passive: false});
  document.getElementById("search").addEventListener("input", event => {
    query = event.target.value.trim().toLowerCase();
    selectedId = null;
    applyFocus(null);
  });
  svg.addEventListener("click", event => {
    if (performance.now() < suppressCanvasClickUntil) return;
    if (event.target === svg || event.target.closest(".edges")) {
      selectedId = null;
      applyFocus(null);
      showOverview();
    }
  });

  let cameraDrag = null;
  let suppressCanvasClickUntil = 0;
  viewport.addEventListener("pointerdown", event => {
    if (event.button !== 0 || event.target.closest(".node")) return;
    cameraDrag = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      panX,
      panY,
      moved: false,
    };
    viewport.classList.add("dragging");
    event.preventDefault();
  });
  window.addEventListener("pointermove", event => {
    if (!cameraDrag || event.pointerId !== cameraDrag.pointerId) return;
    const deltaX = event.clientX - cameraDrag.x;
    const deltaY = event.clientY - cameraDrag.y;
    cameraDrag.moved ||= Math.abs(deltaX) + Math.abs(deltaY) > 3;
    panX = cameraDrag.panX + deltaX;
    panY = cameraDrag.panY + deltaY;
    applyCamera();
  });
  function finishCameraDrag(event) {
    if (!cameraDrag || event.pointerId !== cameraDrag.pointerId) return;
    if (cameraDrag.moved) suppressCanvasClickUntil = performance.now() + 100;
    cameraDrag = null;
    viewport.classList.remove("dragging");
  }
  window.addEventListener("pointerup", finishCameraDrag);
  window.addEventListener("pointercancel", finishCameraDrag);

  function detailsWidthBounds() {
    return {minimum: 300, maximum: Math.max(300, Math.min(760, app.clientWidth - 328))};
  }
  function setDetailsWidth(nextWidth) {
    const bounds = detailsWidthBounds();
    detailsWidth = Math.min(bounds.maximum, Math.max(bounds.minimum, nextWidth));
    app.style.setProperty("--details-width", `${detailsWidth}px`);
    detailsResizer.setAttribute("aria-valuemin", bounds.minimum);
    detailsResizer.setAttribute("aria-valuemax", bounds.maximum);
    detailsResizer.setAttribute("aria-valuenow", Math.round(detailsWidth));
    syncViewport();
  }
  let detailsResize = null;
  detailsResizer.addEventListener("pointerdown", event => {
    detailsResize = {right: app.getBoundingClientRect().right, pointerId: event.pointerId};
    document.body.classList.add("resizing-details");
    event.preventDefault();
  });
  window.addEventListener("pointermove", event => {
    if (!detailsResize || event.pointerId !== detailsResize.pointerId) return;
    setDetailsWidth(detailsResize.right - event.clientX);
  });
  function finishDetailsResize(event) {
    if (!detailsResize || event.pointerId !== detailsResize.pointerId) return;
    detailsResize = null;
    document.body.classList.remove("resizing-details");
  }
  window.addEventListener("pointerup", finishDetailsResize);
  window.addEventListener("pointercancel", finishDetailsResize);
  detailsResizer.addEventListener("keydown", event => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const direction = event.key === "ArrowLeft" ? 1 : -1;
    setDetailsWidth(detailsWidth + direction * (event.shiftKey ? 50 : 20));
  });
  window.addEventListener("resize", () => setDetailsWidth(detailsWidth));

  showOverview();
  setDetailsWidth(detailsWidth);
  requestAnimationFrame(fitGraph);
  </script>
</body>
</html>
"""


def generate_run_graph_page(run_dir: Path, output_dir: Path | None = None) -> Path:
    run_dir = run_dir.expanduser().resolve()
    if not run_dir.is_dir():
        raise VisualizationError(f"Run directory does not exist: {run_dir}")
    resolved_output = (
        output_dir.expanduser().resolve() if output_dir is not None else run_dir / "visualization"
    )
    if resolved_output == run_dir:
        raise VisualizationError("Visualization output must not be the run root")
    resolved_output.mkdir(parents=True, exist_ok=True)

    snapshot = build_run_graph_snapshot(run_dir, resolved_output)
    json_text = json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    embedded_json = json.dumps(
        snapshot,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).replace("<", "\\u003c")
    html_text = HTML_TEMPLATE.replace("__MEDAI_RUN_GRAPH_JSON__", embedded_json, 1)

    json_path = resolved_output / "run_graph.json"
    html_path = resolved_output / "index.html"
    temporary_json = resolved_output / ".run_graph.json.tmp"
    temporary_html = resolved_output / ".index.html.tmp"
    temporary_json.write_text(json_text, encoding="utf-8")
    temporary_html.write_text(html_text, encoding="utf-8")
    temporary_json.replace(json_path)
    temporary_html.replace(html_path)
    return html_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a standalone interactive graph for one MedAI manifest v6 run."
    )
    parser.add_argument("run", type=Path, help="Path to the run directory")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory (default: <run>/visualization)",
    )
    parser.add_argument("--open", action="store_true", help="Open the generated page")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        page = generate_run_graph_page(args.run, args.output_dir)
    except (OSError, VisualizationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(page)
    if args.open:
        webbrowser.open(page.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
