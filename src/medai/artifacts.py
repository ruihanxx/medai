from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def load_model(path: Path, model_type: type[ModelT]) -> ModelT:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required artifact is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Artifact is not valid JSON: {path}: {exc}") from exc
    return model_type.model_validate(payload)


def initialize_manifest(output: Path, inputs: dict[str, Any]) -> None:
    write_json(
        output / "manifest.json",
        {
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
            "inputs": inputs,
            "current_stage": None,
            "stages": {},
        },
    )


def record_stage(output: Path, stage: str, status: str, **details: Any) -> None:
    path = output / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat()
    stage_payload = payload["stages"].get(stage, {})
    if status == "running":
        stage_payload["started_at"] = now
        payload["current_stage"] = stage
    else:
        stage_payload["completed_at"] = now
        payload["current_stage"] = None
    stage_payload["status"] = status
    stage_payload.update(details)
    payload["stages"][stage] = stage_payload
    if status == "failed":
        payload["status"] = "failed"
    write_json(path, payload)


def complete_manifest(output: Path) -> None:
    path = output / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = "completed"
    payload["completed_at"] = datetime.now(timezone.utc).isoformat()
    payload["current_stage"] = None
    write_json(path, payload)


def fail_manifest(output: Path, error: str) -> None:
    path = output / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    current_stage = payload.get("current_stage")
    if current_stage:
        record_stage(output, current_stage, "failed", error=error)
        payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = "failed"
    payload["error"] = error
    payload["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(path, payload)
