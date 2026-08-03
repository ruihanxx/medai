from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VALID_PROVIDERS = {"claude", "codex", "codex-siliconflow"}
VALID_CODEX_REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}


@dataclass(frozen=True)
class RunConfig:
    paper: Path
    output: Path
    provider: str
    repo: Path | None = None
    data: Path | None = None
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
        data: Path | None,
        siliconflow_config: Path | None,
        codex_model: str | None = None,
        codex_reasoning_effort: str | None = None,
        smart_replicate: bool = False,
    ) -> "RunConfig":
        normalized_provider = provider.strip().casefold()
        if normalized_provider == "codex":
            codex_model = codex_model or os.environ.get("MEDAI_CODEX_MODEL")
            codex_reasoning_effort = codex_reasoning_effort or os.environ.get(
                "MEDAI_CODEX_REASONING_EFFORT"
            )
        config = cls(
            paper=paper.expanduser().resolve(),
            output=output.expanduser().resolve(),
            provider=normalized_provider,
            repo=repo.expanduser().resolve() if repo else None,
            data=data.expanduser().resolve() if data else None,
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
        siliconflow_config: Path | None,
        codex_model: str | None = None,
        codex_reasoning_effort: str | None = None,
    ) -> "AutoResearchConfig":
        resolved_base_run = base_run.expanduser().resolve()
        base_inputs = _load_base_inputs(resolved_base_run)
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
