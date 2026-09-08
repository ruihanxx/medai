"""Candidate validation and recoverable host promotion for cohort refinement."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from medai.data_availability import sha256_file
from medai.models import PendingNodeUpdate

REFINEMENT_SCRATCH = ".medai_refine"
REFINEMENT_CACHE_NAMES = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}


class UnhandledRefinementIssues(ValueError):
    """The same refinement session must finish its issue-coverage review."""


def validate_editable_paths(paths: Any) -> list[str]:
    if not isinstance(paths, list):
        raise ValueError("Audit preprocessing issues require an editable_paths list")
    for value in paths:
        if not isinstance(value, str) or not value:
            raise ValueError("Editable paths must be non-empty relative file paths")
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or path.as_posix() != value
            or ".." in path.parts
            or "\\" in value
            or any(char in value for char in "*?[]")
            or not path.parts
            or any(part in REFINEMENT_CACHE_NAMES | {REFINEMENT_SCRATCH} for part in path.parts)
            or path.name == "codegen_plan.json"
        ):
            raise ValueError(f"Invalid refinement editable path: {value!r}")
    return paths


def refinement_manifest(root: Path) -> dict[str, str]:
    """Hash source entries and modes without following links or retaining scratch."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"Refinement codebase is not a directory: {root}")
    manifest = {}
    for directory, directories, files in os.walk(root, followlinks=False):
        directories[:] = [
            name for name in directories
            if name not in REFINEMENT_CACHE_NAMES
            and not (Path(directory) == root and name == REFINEMENT_SCRATCH)
        ]
        for name in [*directories, *files]:
            if name in REFINEMENT_CACHE_NAMES:
                continue
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                manifest[relative] = f"link:{os.readlink(path)}"
            elif path.is_file():
                manifest[relative] = f"file:{path.stat().st_mode & 0o777}:{sha256_file(path)}"
            elif not path.is_dir():
                raise ValueError(f"Unsupported refinement file type: {relative}")
    return manifest


def read_refinement_updates(
    path: Path, audit_issues: list[dict[str, Any]], runnable_ids: set[str]
) -> list[PendingNodeUpdate]:
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Refinement node updates must be regular candidate-local files")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("node_updates.json must be a list of {node_id, issues} objects")
    if any(not isinstance(item, dict) or set(item) != {"node_id", "issues"} for item in payload):
        raise ValueError("Refinement node updates must contain exactly node_id and issues")
    updates = [PendingNodeUpdate.model_validate(item) for item in payload]
    node_ids = [update.node_id for update in updates]
    if len(node_ids) != len(set(node_ids)) or set(node_ids) - runnable_ids:
        raise ValueError("Refinement node updates contain duplicate or inactive node IDs")
    covered = set()
    references = set()
    for update in updates:
        for issue in update.issues:
            reference = getattr(issue, "audit_issue", None)
            if reference is None:
                continue  # Additional origin-local findings retain the open issue schema.
            if type(reference) is not int or not 1 <= reference <= len(audit_issues):
                raise ValueError(f"Invalid audit_issue reference: {reference!r}")
            if audit_issues[reference - 1]["node_id"] != update.node_id:
                raise ValueError(f"Audit issue {reference} was moved to another origin node")
            if reference in references:
                raise ValueError(f"Audit issue {reference} has duplicate dispositions")
            references.add(reference)
            resolution = getattr(issue, "resolution", None)
            if not isinstance(resolution, str) or not resolution.strip():
                continue
            covered.add(reference)
    missing = sorted(set(range(1, len(audit_issues) + 1)) - covered)
    if missing:
        raise UnhandledRefinementIssues(
            f"Finish handling audit issues {missing} in this same session. Record a concrete "
            "resolution for each, including justified assumptions, contradictions, refuted "
            "findings, or evidenced limitations. This coverage review does not require "
            "every scientific limitation to be eliminated and is not a failed refinement."
        )
    return updates


def validate_refinement_candidate(
    codebase: Path, candidate: Path, baseline: dict[str, str], allowed_paths: set[str]
) -> dict[str, str]:
    if refinement_manifest(codebase) != baseline:
        raise ValueError("Authoritative codebase changed during refinement; restore it from evidence")
    proposed = refinement_manifest(candidate)
    changed = {
        path for path in baseline.keys() | proposed.keys()
        if baseline.get(path) != proposed.get(path)
    }
    forbidden = sorted(changed - allowed_paths)
    if forbidden:
        raise ValueError(f"Candidate changed files outside audit editable_paths: {forbidden}")
    for relative in changed:
        for root in (codebase, candidate):
            path = root / relative
            cursor = root
            for part in PurePosixPath(relative).parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    raise ValueError(f"Changed refinement path crosses a symlink: {relative}")
            if path.exists() and not path.is_file():
                raise ValueError(f"Refinement may replace only regular files: {relative}")
    return proposed


def promote_refinement_candidate(
    codebase: Path, candidate: Path, baseline: dict[str, str], proposed: dict[str, str]
) -> None:
    """Resume a validated file replacement without rerunning the agent or losing caches."""
    current = refinement_manifest(codebase)
    for relative in current.keys() | baseline.keys() | proposed.keys():
        if current.get(relative) not in {baseline.get(relative), proposed.get(relative)}:
            raise RuntimeError(f"Code changed outside the recorded promotion: {relative}")
    if refinement_manifest(candidate) != proposed:
        raise RuntimeError("Validated refinement candidate changed before promotion")
    for relative in sorted(baseline.keys() | proposed.keys()):
        if current.get(relative) == proposed.get(relative):
            continue
        target = codebase / relative
        if relative not in proposed:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=candidate / REFINEMENT_SCRATCH, prefix="promotion-", delete=False,
            ) as stream:
                temporary = Path(stream.name)
            try:
                shutil.copy2(candidate / relative, temporary)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
    if refinement_manifest(codebase) != proposed:
        raise RuntimeError("Promoted code does not match the validated refinement candidate")
