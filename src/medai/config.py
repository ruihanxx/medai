from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from medai.computation_providers import (
    ProviderAdapter,
    environment_value,
    get_provider_adapter,
    load_provider_adapters,
    migrate_legacy_provider_inputs,
)

VALID_PROVIDERS = {"claude", "codex", "codex-siliconflow"}
VALID_CODEX_REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
VALID_PARTIAL_DATA_POLICIES = {"ask", "continue", "stop"}
CLOUD_DATASET_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


@dataclass(frozen=True)
class RunConfig:
    paper: Path
    output: Path
    provider: str
    repo: Path | None = None
    data: Path | None = None
    datasets: tuple[str, ...] = ()
    local_data_paths: tuple[Path, ...] = ()
    clouddrive: bool = False
    force_remote: bool = False
    computation_provider: str | None = None
    computation_provider_config: dict[str, Any] | None = None
    computation_provider_reference: Path | None = None
    drive_provider: str | None = None
    drive_reference: Path | None = None
    cloud_dataset: str | None = None
    cloud_source: str | None = None
    cloud_datasets: tuple[str, ...] = ()
    cloud_sources: tuple[str, ...] = ()
    siliconflow_config: Path | None = None
    codex_model: str | None = None
    codex_reasoning_effort: str | None = None
    smart_replicate: bool = False
    on_partial_data: str = "continue"

    @property
    def dataset_names(self) -> tuple[str, ...]:
        return self.datasets or ((self.data.name,) if self.data is not None else ())

    @property
    def dataset_paths(self) -> tuple[Path, ...]:
        if self.local_data_paths:
            return self.local_data_paths
        if self.data is None:
            return ()
        if len(self.dataset_names) <= 1:
            return (self.data,)
        return tuple(self.data / dataset for dataset in self.dataset_names)

    @property
    def selected_cloud_datasets(self) -> tuple[str, ...]:
        return self.cloud_datasets or (
            (self.cloud_dataset,) if self.cloud_dataset is not None else ()
        )

    @property
    def selected_cloud_sources(self) -> tuple[str, ...]:
        return self.cloud_sources or (
            (self.cloud_source,) if self.cloud_source is not None else ()
        )

    def validate(self) -> None:
        if not self.paper.is_file():
            raise ValueError(f"Paper does not exist: {self.paper}")
        if self.paper.suffix.casefold() != ".pdf":
            raise ValueError(f"Paper must be a PDF: {self.paper}")
        if self.repo is not None and not self.repo.is_dir():
            raise ValueError(f"Repository does not exist: {self.repo}")
        for data_path in self.dataset_paths:
            if not data_path.is_dir():
                raise ValueError(f"Data directory does not exist: {data_path}")
        cloud_datasets = self.selected_cloud_datasets
        cloud_sources = self.selected_cloud_sources
        if self.clouddrive:
            if not cloud_datasets:
                raise ValueError("--clouddrive requires at least one --data dataset name")
            if len(set(cloud_datasets)) != len(cloud_datasets):
                raise ValueError("Cloud dataset names must be unique")
            if any(
                dataset in {".", ".."}
                or not CLOUD_DATASET_PATTERN.fullmatch(dataset)
                for dataset in cloud_datasets
            ):
                raise ValueError("--clouddrive requires each --data as a safe directory name")
            if (
                self.computation_provider is None
                or self.computation_provider_config is None
                or self.computation_provider_reference is None
                or self.drive_provider is None
                or self.drive_reference is None
                or len(cloud_sources) != len(cloud_datasets)
            ):
                raise ValueError("--clouddrive requires a configured computation provider and drive")
        elif (
            self.cloud_dataset is not None
            or self.cloud_datasets
            or self.drive_provider is not None
            or self.drive_reference is not None
            or self.cloud_source is not None
            or self.cloud_sources
        ):
            raise ValueError("Cloud-drive configuration requires --clouddrive")
        if self.force_remote and (
            self.computation_provider is None
            or self.computation_provider_config is None
            or self.computation_provider_reference is None
        ):
            raise ValueError(
                "--force-remote requires a configured computation provider; set "
                "MEDAI_COMPUTATION_PROVIDER"
            )
        input_dirs = (("repository", self.repo),) + tuple(
            ("data", path) for path in self.dataset_paths
        )
        for name, input_dir in input_dirs:
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
        if self.on_partial_data not in VALID_PARTIAL_DATA_POLICIES:
            choices = ", ".join(sorted(VALID_PARTIAL_DATA_POLICIES))
            raise ValueError(f"Unsupported partial-data policy; choose one of: {choices}")

    @classmethod
    def create(
        cls,
        *,
        paper: Path,
        output: Path,
        provider: str,
        repo: Path | None,
        data: Path | str | Sequence[Path | str] | None,
        siliconflow_config: Path | None,
        datasets: Sequence[str] | None = None,
        codex_model: str | None = None,
        codex_reasoning_effort: str | None = None,
        smart_replicate: bool = False,
        on_partial_data: str = "continue",
        clouddrive: bool = False,
        force_remote: bool = False,
        cloud_dataset: str | Sequence[str] | None = None,
    ) -> "RunConfig":
        normalized_provider = provider.strip().casefold()
        if normalized_provider == "codex":
            codex_model = codex_model or os.environ.get("MEDAI_CODEX_MODEL")
            codex_reasoning_effort = codex_reasoning_effort or os.environ.get(
                "MEDAI_CODEX_REASONING_EFFORT"
            )
        if cloud_dataset is not None and not clouddrive:
            raise ValueError("--cloud-dataset requires --clouddrive")
        data_values = _as_sequence(data)
        cloud_values = _as_sequence(cloud_dataset)
        resolved_cloud_datasets = tuple(
            str(value).strip()
            for value in (cloud_values or (data_values if clouddrive else ()))
        )
        (
            computation_provider,
            computation_provider_config,
            computation_provider_reference,
            drive_provider,
            drive_reference,
            cloud_sources,
        ) = _resolve_computation_selection(
            output=output,
            clouddrive=clouddrive,
            cloud_datasets=resolved_cloud_datasets,
        )
        local_data_paths = tuple(
            Path(value).expanduser().resolve()
            for value in (
                data_values if not clouddrive or cloud_values else ()
            )
        )
        local_data = _common_data_root(local_data_paths)
        dataset_names = (
            tuple(str(value).strip() for value in datasets)
            if datasets is not None
            else tuple(path.name for path in local_data_paths)
        )
        if len(dataset_names) != len(local_data_paths):
            raise ValueError("--dataset-name must match every local --data directory")
        if len(set(dataset_names)) != len(dataset_names) or any(
            dataset in {".", ".."}
            or not CLOUD_DATASET_PATTERN.fullmatch(dataset)
            for dataset in dataset_names
        ):
            raise ValueError("Local dataset names must be unique safe directory names")
        config = cls(
            paper=paper.expanduser().resolve(),
            output=output.expanduser().resolve(),
            provider=normalized_provider,
            repo=repo.expanduser().resolve() if repo else None,
            data=local_data,
            datasets=dataset_names,
            local_data_paths=local_data_paths,
            clouddrive=clouddrive,
            force_remote=force_remote,
            computation_provider=computation_provider,
            computation_provider_config=computation_provider_config,
            computation_provider_reference=computation_provider_reference,
            drive_provider=drive_provider,
            drive_reference=drive_reference,
            cloud_dataset=(
                resolved_cloud_datasets[0] if len(resolved_cloud_datasets) == 1 else None
            ),
            cloud_source=cloud_sources[0] if len(cloud_sources) == 1 else None,
            cloud_datasets=resolved_cloud_datasets,
            cloud_sources=cloud_sources,
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
            on_partial_data=on_partial_data.strip().casefold(),
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
    datasets: tuple[str, ...] = ()
    local_data_paths: tuple[Path, ...] = ()
    clouddrive: bool = False
    computation_provider: str | None = None
    computation_provider_config: dict[str, Any] | None = None
    computation_provider_reference: Path | None = None
    drive_provider: str | None = None
    drive_reference: Path | None = None
    cloud_dataset: str | None = None
    cloud_source: str | None = None
    cloud_datasets: tuple[str, ...] = ()
    cloud_sources: tuple[str, ...] = ()
    siliconflow_config: Path | None = None
    codex_model: str | None = None
    codex_reasoning_effort: str | None = None

    @property
    def dataset_names(self) -> tuple[str, ...]:
        return self.datasets or ((self.data.name,) if self.data is not None else ())

    @property
    def dataset_paths(self) -> tuple[Path, ...]:
        if self.local_data_paths:
            return self.local_data_paths
        if self.data is None:
            return ()
        if len(self.dataset_names) <= 1:
            return (self.data,)
        return tuple(self.data / dataset for dataset in self.dataset_names)

    @property
    def selected_cloud_datasets(self) -> tuple[str, ...]:
        return self.cloud_datasets or (
            (self.cloud_dataset,) if self.cloud_dataset is not None else ()
        )

    @property
    def selected_cloud_sources(self) -> tuple[str, ...]:
        return self.cloud_sources or (
            (self.cloud_source,) if self.cloud_source is not None else ()
        )

    def validate(self) -> None:
        if not (self.base_run / "manifest.json").is_file():
            raise ValueError(f"Base run does not contain manifest.json: {self.base_run}")
        if self.output == self.base_run:
            raise ValueError("Auto Research output must be separate from the read-only base run")
        if not 1 <= self.max_iter <= 10:
            raise ValueError("--max-iter must be between 1 and 10")
        if not math.isfinite(self.assessment_threshold) or self.assessment_threshold < 0:
            raise ValueError("--assessment-threshold must be a finite non-negative number")
        for data_path in self.dataset_paths:
            if not data_path.is_dir():
                raise ValueError(f"Base run data directory does not exist: {data_path}")
        cloud_datasets = self.selected_cloud_datasets
        cloud_sources = self.selected_cloud_sources
        if self.clouddrive:
            if (
                self.computation_provider is None
                or self.drive_provider is None
                or self.computation_provider_config is None
                or self.computation_provider_reference is None
                or self.drive_reference is None
                or len(cloud_sources) != len(cloud_datasets)
                or not cloud_datasets
                or len(set(cloud_datasets)) != len(cloud_datasets)
                or any(
                    dataset in {".", ".."}
                    or not CLOUD_DATASET_PATTERN.fullmatch(dataset)
                    for dataset in cloud_datasets
                )
            ):
                raise ValueError(
                    "Cloud-backed Auto Research requires inherited computation-provider "
                    "and drive configuration"
                )
        elif any(
            value is not None
            for value in (
                self.drive_provider,
                self.drive_reference,
                self.cloud_dataset,
                self.cloud_source,
            )
        ) or self.cloud_datasets or self.cloud_sources:
            raise ValueError("Auto Research cloud configuration requires a cloud-backed base run")
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
        clouddrive = base_inputs.get("clouddrive") is True
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
        datasets = _string_tuple(base_inputs.get("datasets"))
        if not datasets and data is not None:
            source_value = base_inputs.get("data_source")
            datasets = (
                Path(str(source_value)).name if source_value else data.name,
            )
        cloud_datasets = _string_tuple(base_inputs.get("cloud_datasets")) or (
            (str(base_inputs.get("cloud_dataset", "")).strip(),)
            if clouddrive and base_inputs.get("cloud_dataset")
            else ()
        )
        (
            computation_provider,
            computation_provider_config,
            computation_provider_reference,
            drive_provider,
            drive_reference,
            cloud_sources,
        ) = _resolve_computation_selection(
            output=output,
            clouddrive=clouddrive,
            cloud_datasets=cloud_datasets,
            inherited_inputs=base_inputs,
        )
        if clouddrive and (
            base_inputs.get("computation_provider") != computation_provider
            or base_inputs.get("drive_provider") != drive_provider
            or not cloud_datasets
            or _string_tuple(base_inputs.get("cloud_sources"))
            not in {(), cloud_sources}
            or (
                not base_inputs.get("cloud_sources")
                and base_inputs.get("cloud_source") != cloud_sources[0]
            )
        ):
            raise ValueError(
                "Cloud-backed Auto Research requires the base run and current configuration "
                "to select the same computation provider, drive, and dataset"
            )
        config = cls(
            base_run=resolved_base_run,
            output=output.expanduser().resolve(),
            provider=normalized_provider,
            max_iter=max_iter,
            assessment_threshold=assessment_threshold,
            data=data,
            datasets=datasets,
            clouddrive=clouddrive,
            computation_provider=computation_provider,
            computation_provider_config=computation_provider_config,
            computation_provider_reference=computation_provider_reference,
            drive_provider=drive_provider,
            drive_reference=drive_reference,
            cloud_dataset=cloud_datasets[0] if len(cloud_datasets) == 1 else None,
            cloud_source=cloud_sources[0] if len(cloud_sources) == 1 else None,
            cloud_datasets=cloud_datasets,
            cloud_sources=cloud_sources,
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


def _resolve_computation_selection(
    *,
    output: Path,
    clouddrive: bool,
    cloud_datasets: tuple[str, ...],
    inherited_inputs: dict[str, Any] | None = None,
) -> tuple[
    tuple[str, ...],
    dict[str, Any] | None,
    Path | None,
    str | None,
    Path | None,
    str | None,
]:
    recorded = _recorded_computation_inputs(output)
    if not recorded and inherited_inputs is not None:
        recorded = migrate_legacy_provider_inputs(inherited_inputs)
    configured_provider = environment_value("MEDAI_COMPUTATION_PROVIDER").casefold()
    configured_drive = environment_value("MEDAI_DRIVE_PROVIDER").casefold()
    adapters = load_provider_adapters()
    recorded_provider = recorded.get("computation_provider")
    provider_name = configured_provider or (
        recorded_provider if isinstance(recorded_provider, str) else ""
    )
    if not provider_name:
        configured = [adapter for adapter in adapters.values() if adapter.supports_configuration()]
        if len(configured) == 1:
            provider_name = configured[0].name
        elif len(configured) > 1:
            raise ValueError(
                "Multiple computation providers are configured; set "
                "MEDAI_COMPUTATION_PROVIDER explicitly"
            )
    if not provider_name:
        if clouddrive:
            raise ValueError(
                "--clouddrive requires a configured computation provider; set "
                "MEDAI_COMPUTATION_PROVIDER"
            )
        return None, None, None, None, None, ()
    adapter = _adapter_for_selection(provider_name)
    recorded_drive = recorded.get("drive_provider")
    drive_name = configured_drive or (
        recorded_drive if isinstance(recorded_drive, str) else ""
    )
    if clouddrive:
        drive_name = drive_name or adapter.default_drive or ""
        if not drive_name:
            raise ValueError(
                f"Computation provider {adapter.name!r} has no default drive; "
                "set MEDAI_DRIVE_PROVIDER"
            )
        drive = adapter.drive(drive_name)
    else:
        drive_name = ""
        drive = None
    missing = adapter.missing_environment(drive_name or None)
    if missing:
        raise ValueError(
            "Configured computation provider requires environment variable(s): "
            + ", ".join(missing)
        )
    return (
        adapter.name,
        adapter.configuration(drive_name or None),
        adapter.reference,
        drive.name if drive else None,
        drive.reference if drive else None,
        tuple(adapter.cloud_source(drive.name, dataset) for dataset in cloud_datasets)
        if drive
        else (),
    )


def _as_sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, Path)):
        return (value,)
    return tuple(value)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _common_data_root(paths: tuple[Path, ...]) -> Path | None:
    if not paths:
        return None
    if len(paths) == 1:
        return paths[0]
    parents = {path.parent for path in paths}
    if len(parents) != 1:
        raise ValueError("Repeated --data directories must share one parent directory")
    if len({path.name for path in paths}) != len(paths):
        raise ValueError("Repeated --data directories must be unique")
    return paths[0].parent


def _adapter_for_selection(name: str) -> ProviderAdapter:
    try:
        return get_provider_adapter(name)
    except ValueError as exc:
        raise ValueError(f"Invalid computation-provider selection: {exc}") from exc


def _recorded_computation_inputs(output: Path) -> dict[str, Any]:
    manifest_path = output.expanduser().resolve() / "manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Existing run manifest is unreadable: {manifest_path}") from exc
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError(f"Existing run manifest has invalid inputs: {manifest_path}")
    return migrate_legacy_provider_inputs(inputs)
