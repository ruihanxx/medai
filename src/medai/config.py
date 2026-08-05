from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VALID_PROVIDERS = {"claude", "codex", "codex-siliconflow"}
VALID_CODEX_REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
CLOUD_DATASET_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


@dataclass(frozen=True)
class RunConfig:
    paper: Path
    output: Path
    provider: str
    repo: Path | None = None
    data: Path | None = None
    clouddrive: bool = False
    drive_provider: str | None = None
    cloud_dataset: str | None = None
    siliconflow_config: Path | None = None
    codex_model: str | None = None
    codex_reasoning_effort: str | None = None
    smart_replicate: bool = False

    def validate(self) -> None:
        if not self.paper.is_file():
            raise ValueError(f"Paper does not exist: {self.paper}")
        if self.paper.suffix.casefold() != ".pdf":
            raise ValueError(f"Paper must be a PDF: {self.paper}")
        if self.repo is not None and not self.repo.is_dir():
            raise ValueError(f"Repository does not exist: {self.repo}")
        if self.data is not None and not self.data.is_dir():
            raise ValueError(f"Data directory does not exist: {self.data}")
        if self.clouddrive:
            if self.data is not None:
                raise ValueError("--clouddrive cannot use a local data directory")
            if not self.cloud_dataset or not CLOUD_DATASET_PATTERN.fullmatch(
                self.cloud_dataset
            ):
                raise ValueError(
                    "--clouddrive requires --data as one safe directory name"
                )
            if self.cloud_dataset in {".", ".."}:
                raise ValueError("Cloud dataset name cannot be '.' or '..'")
            if self.drive_provider != "aliyun":
                raise ValueError(
                    "MEDAI_DRIVE_PROVIDER must be 'aliyun' while --clouddrive is enabled"
                )
            required = (
                "AUTODL_TOKEN",
                "AUTODL_IMAGE_UUID",
                "AUTODL_AUTOPANEL_PASSWORD",
            )
            missing = [name for name in required if not _environment_value(name)]
            if missing:
                raise ValueError(
                    "--clouddrive requires environment variable(s): "
                    + ", ".join(missing)
                )
            timeout_value = _environment_value(
                "AUTODL_CLOUDDRIVE_TIMEOUT_SECONDS", "1800"
            )
            try:
                timeout_seconds = int(timeout_value)
            except ValueError as exc:
                raise ValueError(
                    "AUTODL_CLOUDDRIVE_TIMEOUT_SECONDS must be a positive integer"
                ) from exc
            if timeout_seconds <= 0:
                raise ValueError(
                    "AUTODL_CLOUDDRIVE_TIMEOUT_SECONDS must be a positive integer"
                )
        elif self.cloud_dataset is not None or self.drive_provider is not None:
            raise ValueError("Cloud-drive configuration requires --clouddrive")
        for name, input_dir in (("repository", self.repo), ("data", self.data)):
            if input_dir is not None and self.output.is_relative_to(input_dir):
                raise ValueError(
                    f"Output directory cannot be inside the {name} input: {self.output}"
                )
        if self.provider not in VALID_PROVIDERS:
            raise ValueError(f"Unsupported provider: {self.provider}")
        if self.provider == "codex-siliconflow":
            if self.siliconflow_config is None or not self.siliconflow_config.is_file():
                raise ValueError("codex-siliconflow requires --siliconflow-config")
        elif self.siliconflow_config is not None:
            raise ValueError("--siliconflow-config requires --provider codex-siliconflow")
        if self.provider != "codex" and (
            self.codex_model is not None or self.codex_reasoning_effort is not None
        ):
            raise ValueError("Codex model settings require --provider codex")
        if (
            self.codex_reasoning_effort is not None
            and self.codex_reasoning_effort not in VALID_CODEX_REASONING_EFFORTS
        ):
            choices = ", ".join(sorted(VALID_CODEX_REASONING_EFFORTS))
            raise ValueError(f"Unsupported Codex reasoning effort; choose one of: {choices}")

    @classmethod
    def create(
        cls,
        *,
        paper: Path,
        output: Path,
        provider: str,
        repo: Path | None,
        data: Path | str | None,
        siliconflow_config: Path | None,
        codex_model: str | None = None,
        codex_reasoning_effort: str | None = None,
        smart_replicate: bool = False,
        clouddrive: bool = False,
    ) -> "RunConfig":
        normalized_provider = provider.strip().casefold()
        if normalized_provider == "codex":
            codex_model = codex_model or os.environ.get("MEDAI_CODEX_MODEL")
            codex_reasoning_effort = codex_reasoning_effort or os.environ.get(
                "MEDAI_CODEX_REASONING_EFFORT"
            )
        cloud_dataset = str(data).strip() if clouddrive and data is not None else None
        drive_provider = (
            _environment_value("MEDAI_DRIVE_PROVIDER", "aliyun").casefold()
            if clouddrive
            else None
        )
        local_data = None if clouddrive or data is None else Path(data).expanduser().resolve()
        config = cls(
            paper=paper.expanduser().resolve(),
            output=output.expanduser().resolve(),
            provider=normalized_provider,
            repo=repo.expanduser().resolve() if repo else None,
            data=local_data,
            clouddrive=clouddrive,
            drive_provider=drive_provider,
            cloud_dataset=cloud_dataset,
            siliconflow_config=(
                siliconflow_config.expanduser().resolve() if siliconflow_config else None
            ),
            codex_model=codex_model.strip() if codex_model else None,
            codex_reasoning_effort=(
                codex_reasoning_effort.strip().casefold()
                if codex_reasoning_effort
                else None
            ),
            smart_replicate=smart_replicate,
        )
        config.validate()
        return config


@dataclass(frozen=True)
class AutoResearchConfig:
    base_run: Path
    output: Path
    provider: str
    max_iter: int = 1
    assessment_threshold: float = 0.0
    data: Path | None = None
    siliconflow_config: Path | None = None
    codex_model: str | None = None
    codex_reasoning_effort: str | None = None

    def validate(self) -> None:
        if not (self.base_run / "manifest.json").is_file():
            raise ValueError(f"Base run does not contain manifest.json: {self.base_run}")
        if self.output == self.base_run:
            raise ValueError("Auto Research output must be separate from the read-only base run")
        if not 1 <= self.max_iter <= 10:
            raise ValueError("--max-iter must be between 1 and 10")
        if not math.isfinite(self.assessment_threshold) or self.assessment_threshold < 0:
            raise ValueError("--assessment-threshold must be a finite non-negative number")
        if self.data is not None and not self.data.is_dir():
            raise ValueError(f"Base run data directory does not exist: {self.data}")
        if self.provider not in VALID_PROVIDERS:
            raise ValueError(f"Unsupported provider: {self.provider}")
        if self.provider == "codex-siliconflow":
            if self.siliconflow_config is None or not self.siliconflow_config.is_file():
                raise ValueError("codex-siliconflow requires --siliconflow-config")
        elif self.siliconflow_config is not None:
            raise ValueError("--siliconflow-config requires --provider codex-siliconflow")
        if self.provider != "codex" and (
            self.codex_model is not None or self.codex_reasoning_effort is not None
        ):
            raise ValueError("Codex model settings require --provider codex")
        if (
            self.codex_reasoning_effort is not None
            and self.codex_reasoning_effort not in VALID_CODEX_REASONING_EFFORTS
        ):
            choices = ", ".join(sorted(VALID_CODEX_REASONING_EFFORTS))
            raise ValueError(f"Unsupported Codex reasoning effort; choose one of: {choices}")

    @classmethod
    def create(
        cls,
        *,
        base_run: Path,
        output: Path,
        provider: str | None,
        max_iter: int = 1,
        assessment_threshold: float = 0.0,
        siliconflow_config: Path | None,
        codex_model: str | None = None,
        codex_reasoning_effort: str | None = None,
    ) -> "AutoResearchConfig":
        resolved_base_run = base_run.expanduser().resolve()
        base_inputs = _load_base_inputs(resolved_base_run)
        if base_inputs.get("clouddrive"):
            raise ValueError("Auto Research does not support a cloud-backed base run")
        normalized_provider = (provider or str(base_inputs.get("provider", ""))).strip().casefold()
        if not normalized_provider:
            raise ValueError("Base run does not record a provider; pass --provider")

        if normalized_provider == "codex":
            codex_model = (
                codex_model
                or base_inputs.get("codex_model")
                or os.environ.get("MEDAI_CODEX_MODEL")
            )
            codex_reasoning_effort = (
                codex_reasoning_effort
                or base_inputs.get("codex_reasoning_effort")
                or os.environ.get("MEDAI_CODEX_REASONING_EFFORT")
            )
        else:
            codex_model = None if codex_model is None else codex_model
            codex_reasoning_effort = (
                None if codex_reasoning_effort is None else codex_reasoning_effort
            )

        data_value = base_inputs.get("data")
        data = Path(str(data_value)).expanduser().resolve() if data_value else None
        config = cls(
            base_run=resolved_base_run,
            output=output.expanduser().resolve(),
            provider=normalized_provider,
            max_iter=max_iter,
            assessment_threshold=assessment_threshold,
            data=data,
            siliconflow_config=(
                siliconflow_config.expanduser().resolve() if siliconflow_config else None
            ),
            codex_model=str(codex_model).strip() if codex_model else None,
            codex_reasoning_effort=(
                str(codex_reasoning_effort).strip().casefold()
                if codex_reasoning_effort
                else None
            ),
        )
        config.validate()
        return config


def _load_base_inputs(base_run: Path) -> dict[str, Any]:
    manifest_path = base_run / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Base run does not contain manifest.json: {base_run}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Base run manifest is not valid JSON: {manifest_path}") from exc
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError(f"Base run manifest has invalid inputs: {manifest_path}")
    return inputs


def _environment_value(name: str, default: str = "") -> str:
    """Read an env-file-compatible scalar without exposing it in errors."""
    value = os.environ.get(name, default).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value
