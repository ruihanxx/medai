from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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
        )
        config.validate()
        return config
