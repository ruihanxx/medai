"""Persistent stage state for resumable MedAI runs."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from medai.config import AutoResearchConfig, RunConfig

MANIFEST_VERSION = 2
SUPPORTED_MANIFEST_VERSIONS = {1, MANIFEST_VERSION}


def build_run_inputs(config: RunConfig) -> dict[str, Any]:
    """Build the output-affecting input fingerprint stored with a run."""
    inputs = {
        "paper": str(config.paper),
        "paper_source": os.environ.get("MEDAI_HOST_PAPER", str(config.paper)),
        "paper_sha256": _sha256(config.paper),
        "repo": str(config.repo) if config.repo else None,
        "repo_source": os.environ.get(
            "MEDAI_HOST_REPO",
            str(config.repo) if config.repo else "",
        )
        or None,
        "data": str(config.data) if config.data else None,
        "data_source": os.environ.get(
            "MEDAI_HOST_DATA",
            str(config.data) if config.data else "",
        )
        or None,
        "provider": config.provider,
        "codex_model": config.codex_model,
        "codex_reasoning_effort": config.codex_reasoning_effort,
        "smart_replicate": config.smart_replicate,
        "computation_provider": (
            "autodl"
            if os.environ.get("AUTODL_TOKEN") and os.environ.get("AUTODL_IMAGE_UUID")
            else None
        ),
        "autodl_image_uuid": (
            os.environ.get("AUTODL_IMAGE_UUID")
            if os.environ.get("AUTODL_TOKEN") and os.environ.get("AUTODL_IMAGE_UUID")
            else None
        ),
    }
    if config.siliconflow_config is not None:
        from medai.siliconflow_adapter import SiliconFlowConfig

        siliconflow = SiliconFlowConfig.from_dotenv(config.siliconflow_config)
        inputs.update(
            {
                "siliconflow_base_url": siliconflow.base_url,
                "siliconflow_model": siliconflow.model,
                "siliconflow_context_window": siliconflow.context_window,
            }
        )
    return inputs


def build_autoresearch_inputs(config: AutoResearchConfig) -> dict[str, Any]:
    """Build the immutable campaign fingerprint for an Auto Research run."""
    inputs = {
        "workflow": "autoresearch",
        "base_run": str(config.base_run),
        "base_run_source": os.environ.get("MEDAI_HOST_BASE_RUN", str(config.base_run)),
        "base_artifact_fingerprint": _base_artifact_fingerprint(config.base_run),
        "data": str(config.data) if config.data else None,
        "data_source": os.environ.get(
            "MEDAI_HOST_DATA",
            str(config.data) if config.data else "",
        )
        or None,
        "provider": config.provider,
        "codex_model": config.codex_model,
        "codex_reasoning_effort": config.codex_reasoning_effort,
        "max_iter": config.max_iter,
        "assessment_threshold": config.assessment_threshold,
        "computation_provider": (
            "autodl"
            if os.environ.get("AUTODL_TOKEN") and os.environ.get("AUTODL_IMAGE_UUID")
            else None
        ),
        "autodl_image_uuid": (
            os.environ.get("AUTODL_IMAGE_UUID")
            if os.environ.get("AUTODL_TOKEN") and os.environ.get("AUTODL_IMAGE_UUID")
            else None
        ),
    }
    if config.siliconflow_config is not None:
        from medai.siliconflow_adapter import SiliconFlowConfig

        siliconflow = SiliconFlowConfig.from_dotenv(config.siliconflow_config)
        inputs.update(
            {
                "siliconflow_base_url": siliconflow.base_url,
                "siliconflow_model": siliconflow.model,
                "siliconflow_context_window": siliconflow.context_window,
            }
        )
    return inputs


class PipelineState:
    """Read and update the canonical ``manifest.json`` pipeline state."""

    def __init__(self, output: Path):
        self.output = Path(output)
        self.path = self.output / "manifest.json"
        try:
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RuntimeError(f"Pipeline state is missing: {self.path}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Pipeline state is not valid JSON: {self.path}: {exc}") from exc

        version = self.state.get("version")
        if version not in SUPPORTED_MANIFEST_VERSIONS:
            raise RuntimeError(
                f"Unsupported pipeline state version at {self.path}: "
                f"{version!r}; expected one of {sorted(SUPPORTED_MANIFEST_VERSIONS)}. "
                "Use a new output directory."
            )
        if not isinstance(self.state.get("inputs"), dict) or not isinstance(
            self.state.get("stages"), dict
        ):
            raise RuntimeError(f"Pipeline state has an invalid structure: {self.path}")

    @classmethod
    def create(cls, output: Path, inputs: dict[str, Any]) -> "PipelineState":
        path = Path(output) / "manifest.json"
        if path.exists():
            raise RuntimeError(f"Pipeline state already exists: {path}")
        Path(output).mkdir(parents=True, exist_ok=True)
        state = cls.__new__(cls)
        state.output = Path(output)
        state.path = path
        state.state = {
            "version": MANIFEST_VERSION,
            "created_at": _now(),
            "status": "running",
            "inputs": inputs,
            "current_stage": None,
            "stages": {},
            "resume_count": 0,
        }
        state._save()
        return state

    def resume(self, inputs: dict[str, Any]) -> None:
        recorded = self.state["inputs"]
        changed = [
            name
            for name, value in inputs.items()
            if name in recorded and recorded[name] != value
        ]
        if changed:
            raise RuntimeError(
                "Cannot resume because run inputs or output-affecting configuration "
                f"changed: {', '.join(changed)}. Use a new output directory."
            )

        recorded.update({name: value for name, value in inputs.items() if name not in recorded})
        self.state["version"] = MANIFEST_VERSION
        self.state["status"] = "running"
        self.state["current_stage"] = None
        self.state["resume_count"] = int(self.state.get("resume_count", 0)) + 1
        self.state["last_resumed_at"] = _now()
        self.state.pop("completed_at", None)
        self.state.pop("error", None)
        self._save()

    def get_stage_status(self, name: str) -> str | None:
        return self.state["stages"].get(name, {}).get("status")

    def is_stage_completed(self, name: str) -> bool:
        return self.get_stage_status(name) == "completed"

    def get_stage_checkpoints(self, name: str) -> dict[str, Any]:
        checkpoints = self.state["stages"].get(name, {}).get("checkpoints", {})
        return dict(checkpoints) if isinstance(checkpoints, dict) else {}

    def start_stage(self, name: str) -> None:
        previous = self.state["stages"].get(name, {})
        prior_attempts = previous.get("attempts", 1 if previous else 0)
        self.state["stages"][name] = {
            "status": "running",
            "started_at": _now(),
            "completed_at": None,
            "success": None,
            "attempts": int(prior_attempts) + 1,
            "checkpoints": self.get_stage_checkpoints(name),
            "outputs": [],
        }
        self.state["status"] = "running"
        self.state["current_stage"] = name
        self._save()

    def update_stage_checkpoints(self, name: str, checkpoints: dict[str, Any]) -> None:
        stage = self.state["stages"].get(name)
        if stage is None or stage.get("status") != "running":
            raise RuntimeError(f"Cannot checkpoint stage that is not running: {name}")
        stage.setdefault("checkpoints", {}).update(checkpoints)
        self._save()

    def complete_stage(self, name: str, outputs: list[str]) -> None:
        stage = self.state["stages"].get(name)
        if stage is None:
            raise RuntimeError(f"Cannot complete stage that was not started: {name}")
        stage.update(
            {
                "status": "completed",
                "completed_at": _now(),
                "success": True,
                "outputs": outputs,
            }
        )
        stage.pop("error", None)
        self.state["current_stage"] = None
        self._save()

    def mark_completed(self) -> None:
        self.state["status"] = "completed"
        self.state["completed_at"] = _now()
        self.state["current_stage"] = None
        self.state.pop("error", None)
        self._save()

    def mark_ineligible(self, reason: str) -> None:
        self.state["status"] = "ineligible"
        self.state["completed_at"] = _now()
        self.state["current_stage"] = None
        self.state["ineligible_reason"] = reason
        self.state.pop("error", None)
        self._save()

    def fail(self, error: str) -> None:
        current_stage = self.state.get("current_stage")
        if current_stage:
            stage = self.state["stages"].setdefault(current_stage, {})
            stage.update(
                {
                    "status": "failed",
                    "completed_at": _now(),
                    "success": False,
                    "error": error,
                }
            )
        self.state["status"] = "failed"
        self.state["current_stage"] = None
        self.state["error"] = error
        self.state["completed_at"] = _now()
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


def _sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _base_artifact_fingerprint(base_run: Path) -> str:
    required_files = [
        "manifest.json",
        "preflight/resources.json",
        "preprocessing/paper.md",
        "preprocessing/claims.json",
        "preprocessing/experiment_todo.json",
        "codegen/codebase/codegen_plan.json",
        "plan/replicate_plan.json",
        "replication/replication_log.json",
        "replication/evidence_summary.json",
        "report/reproduction_report.md",
    ]
    digest = hashlib.sha256()
    for relative in required_files:
        path = base_run / relative
        if not path.is_file():
            raise ValueError(f"Base run artifact is missing: {path}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        _update_digest_from_file(digest, path)

    ignored_names = {
        ".git",
        ".venv",
        ".cache",
        ".hypothesis",
        ".ipynb_checkpoints",
        ".mypy_cache",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
    }
    _update_digest_from_directory(
        digest,
        base_run,
        Path("preprocessing/artifacts"),
        set(),
    )
    _update_digest_from_directory(
        digest,
        base_run,
        Path("codegen/codebase"),
        ignored_names,
    )
    _update_digest_from_directory(
        digest,
        base_run,
        Path("replication"),
        ignored_names,
    )
    return digest.hexdigest()


def _update_digest_from_directory(
    digest: Any,
    base_run: Path,
    relative_directory: Path,
    ignored_names: set[str],
) -> None:
    directory = base_run / relative_directory
    if not directory.is_dir():
        raise ValueError(f"Base run artifact directory is missing: {directory}")
    digest.update(f"{relative_directory.as_posix()}/".encode("utf-8"))
    digest.update(b"\0")
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if (
            any(part in ignored_names for part in relative.parts)
            or path.suffix in {".pyc", ".pyo"}
            or not path.is_file()
        ):
            continue
        artifact_path = relative_directory / relative
        digest.update(artifact_path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        _update_digest_from_file(digest, path)


def _update_digest_from_file(digest: Any, path: Path) -> None:
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
