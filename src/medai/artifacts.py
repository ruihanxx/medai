from __future__ import annotations

import json
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
