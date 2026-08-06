"""Discover and validate computation-provider adapters staged with runtime skills."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ACTION_NAMES = frozenset(
    {
        "validate-state",
        "status",
        "power-on",
        "power-off",
        "reconcile",
        "release",
        "cloud-pull",
        "exec",
        "upload",
        "download",
    }
)
_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\Z")
_ENVIRONMENT_NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")


@dataclass(frozen=True)
class EnvironmentVariable:
    name: str
    secret: bool
    required: bool
    default: str | None = None


@dataclass(frozen=True)
class DriveAdapter:
    name: str
    reference: Path
    source_template: str
    environment: tuple[EnvironmentVariable, ...]
    configuration_fingerprint: tuple[str, ...]


@dataclass(frozen=True)
class ProviderAdapter:
    name: str
    adapter_version: int
    metadata_path: Path
    reference: Path
    script: Path
    environment: tuple[EnvironmentVariable, ...]
    configuration_fingerprint: tuple[str, ...]
    drives: dict[str, DriveAdapter]
    default_drive: str | None
    action_timeouts: dict[str, int]
    legacy_config_fields: dict[str, str]

    def drive(self, name: str) -> DriveAdapter:
        drive = self.drives.get(name)
        if drive is None:
            choices = ", ".join(sorted(self.drives)) or "none"
            raise ValueError(
                f"Computation provider {self.name!r} does not support drive "
                f"{name!r}; available drives: {choices}"
            )
        return drive

    def environment_value(self, item: EnvironmentVariable) -> str:
        return environment_value(item.name, item.default or "")

    def configuration(self, drive_name: str | None = None) -> dict[str, Any]:
        entries = list(self.environment)
        fingerprint = set(self.configuration_fingerprint)
        if drive_name is not None:
            drive = self.drive(drive_name)
            entries.extend(drive.environment)
            fingerprint.update(drive.configuration_fingerprint)
        names = {entry.name: entry for entry in entries}
        return {
            "provider": self.name,
            "drive": drive_name,
            "values": {
                name: self.environment_value(names[name])
                for name in sorted(fingerprint)
                if self.environment_value(names[name])
            },
        }

    def missing_environment(self, drive_name: str | None = None) -> list[str]:
        entries = list(self.environment)
        if drive_name is not None:
            entries.extend(self.drive(drive_name).environment)
        return [
            item.name
            for item in entries
            if item.required and not self.environment_value(item)
        ]

    def supports_configuration(self) -> bool:
        return not self.missing_environment()

    def cloud_source(self, drive_name: str, dataset: str) -> str:
        try:
            return self.drive(drive_name).source_template.format(dataset=dataset)
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"Provider metadata has an invalid cloud source template for {drive_name!r}"
            ) from exc


def skills_dir() -> Path:
    configured = os.environ.get("MEDAI_SKILLS_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    repository_skills = Path(__file__).resolve().parents[2] / "templates" / "skills"
    if repository_skills.is_dir():
        return repository_skills
    return Path(__file__).parent / "templates" / "skills"


def environment_value(name: str, default: str = "") -> str:
    """Read an env-file-compatible scalar without exposing it in errors."""
    value = os.environ.get(name, default).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value


def load_provider_adapters(root: Path | None = None) -> dict[str, ProviderAdapter]:
    skill_root = (root or skills_dir()) / "computation_provider"
    providers_dir = skill_root / "providers"
    if not providers_dir.is_dir():
        raise ValueError(f"Computation-provider metadata directory is missing: {providers_dir}")
    resolved_providers_dir = providers_dir.resolve()
    adapters: dict[str, ProviderAdapter] = {}
    for path in sorted(providers_dir.glob("*.json")):
        if path.resolve().parent != resolved_providers_dir:
            raise ValueError(f"Provider metadata must be contained in its skill directory: {path}")
        adapter = _load_provider_adapter(path, skill_root)
        if path.stem != adapter.name:
            raise ValueError(
                f"Provider metadata filename does not match its provider name: {path}"
            )
        if adapter.name in adapters:
            raise ValueError(f"Duplicate computation-provider metadata: {adapter.name}")
        adapters[adapter.name] = adapter
    if not adapters:
        raise ValueError(f"No computation-provider metadata files found: {providers_dir}")
    return adapters


def get_provider_adapter(name: str, root: Path | None = None) -> ProviderAdapter:
    normalized = _slug(name, "provider")
    adapters = load_provider_adapters(root)
    try:
        return adapters[normalized]
    except KeyError as exc:
        choices = ", ".join(sorted(adapters))
        raise ValueError(
            f"Unknown computation provider {normalized!r}; available providers: {choices}"
        ) from exc


def configured_provider_adapters(root: Path | None = None) -> list[ProviderAdapter]:
    return [adapter for adapter in load_provider_adapters(root).values() if adapter.supports_configuration()]


def migrate_legacy_provider_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Replace adapter-specific legacy manifest fields with generic configuration."""
    migrated = dict(inputs)
    configuration = migrated.get("computation_provider_config")
    if isinstance(configuration, dict):
        return migrated
    provider_name = migrated.get("computation_provider")
    if not isinstance(provider_name, str) or not provider_name:
        migrated["computation_provider_config"] = None
        return migrated
    adapter = get_provider_adapter(provider_name)
    values: dict[str, str] = {}
    for environment_name, legacy_field in adapter.legacy_config_fields.items():
        value = migrated.pop(legacy_field, None)
        if isinstance(value, str) and value:
            values[environment_name] = value
    migrated["computation_provider_config"] = {
        "provider": adapter.name,
        "drive": migrated.get("drive_provider"),
        "values": values,
    }
    return migrated


def _load_provider_adapter(path: Path, skill_root: Path) -> ProviderAdapter:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Provider metadata is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Provider metadata must be a JSON object: {path}")
    name = _slug(payload.get("provider"), "provider")
    adapter_version = payload.get("adapter_version")
    if isinstance(adapter_version, bool) or not isinstance(adapter_version, int) or adapter_version < 1:
        raise ValueError(f"Provider metadata adapter_version must be a positive integer: {path}")
    environment = _parse_environment(payload.get("environment"), path)
    fingerprint = _parse_fingerprint(
        payload.get("configuration_fingerprint", []), environment, path
    )
    drives_payload = payload.get("drives", {})
    if not isinstance(drives_payload, dict):
        raise ValueError(f"Provider metadata drives must be an object: {path}")
    drives: dict[str, DriveAdapter] = {}
    for drive_name, drive_payload in drives_payload.items():
        normalized_drive = _slug(drive_name, "drive")
        if not isinstance(drive_payload, dict):
            raise ValueError(f"Provider metadata drive must be an object: {path}")
        drive_environment = _parse_environment(drive_payload.get("environment", []), path)
        drives[normalized_drive] = DriveAdapter(
            name=normalized_drive,
            reference=_safe_relative_path(skill_root, drive_payload.get("reference"), path),
            source_template=_source_template(drive_payload.get("source_template"), path),
            environment=drive_environment,
            configuration_fingerprint=_parse_fingerprint(
                drive_payload.get("configuration_fingerprint", []),
                drive_environment,
                path,
            ),
        )
    default_drive = payload.get("default_drive")
    if default_drive is not None:
        default_drive = _slug(default_drive, "default_drive")
        if default_drive not in drives:
            raise ValueError(f"Provider metadata default_drive is unsupported: {path}")
    actions = payload.get("actions")
    if not isinstance(actions, dict) or set(actions) != ACTION_NAMES:
        raise ValueError(
            "Provider metadata must declare exactly the common provider actions: "
            f"{path}"
        )
    action_timeouts: dict[str, int] = {}
    for action, timeout in actions.items():
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
            raise ValueError(f"Provider metadata action timeout is invalid for {action!r}: {path}")
        action_timeouts[action] = timeout
    legacy = payload.get("legacy_manifest", {})
    if not isinstance(legacy, dict):
        raise ValueError(f"Provider metadata legacy_manifest must be an object: {path}")
    legacy_fields = legacy.get("configuration_fields", {})
    if not isinstance(legacy_fields, dict):
        raise ValueError(f"Provider metadata legacy configuration_fields must be an object: {path}")
    environment_names = {item.name for item in environment}
    parsed_legacy_fields: dict[str, str] = {}
    for environment_name, legacy_name in legacy_fields.items():
        if environment_name not in environment_names or not isinstance(legacy_name, str):
            raise ValueError(f"Provider metadata legacy configuration field is invalid: {path}")
        parsed_legacy_fields[environment_name] = legacy_name
    return ProviderAdapter(
        name=name,
        adapter_version=adapter_version,
        metadata_path=path,
        reference=_safe_relative_path(skill_root, payload.get("reference"), path),
        script=_safe_relative_path(skill_root, payload.get("script"), path),
        environment=environment,
        configuration_fingerprint=fingerprint,
        drives=drives,
        default_drive=default_drive,
        action_timeouts=action_timeouts,
        legacy_config_fields=parsed_legacy_fields,
    )


def _parse_environment(value: Any, metadata_path: Path) -> tuple[EnvironmentVariable, ...]:
    if not isinstance(value, list):
        raise ValueError(f"Provider metadata environment must be a list: {metadata_path}")
    parsed: list[EnvironmentVariable] = []
    names: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"Provider metadata environment entry must be an object: {metadata_path}")
        name = item.get("name")
        if not isinstance(name, str) or not _ENVIRONMENT_NAME.fullmatch(name):
            raise ValueError(f"Provider metadata environment name is invalid: {metadata_path}")
        if name in names or not isinstance(item.get("secret"), bool):
            raise ValueError(f"Provider metadata environment entry is invalid: {metadata_path}")
        required = item.get("required", True)
        default = item.get("default")
        if not isinstance(required, bool) or default is not None and not isinstance(default, str):
            raise ValueError(f"Provider metadata environment entry is invalid: {metadata_path}")
        names.add(name)
        parsed.append(
            EnvironmentVariable(name=name, secret=item["secret"], required=required, default=default)
        )
    return tuple(parsed)


def _parse_fingerprint(
    value: Any, environment: tuple[EnvironmentVariable, ...], metadata_path: Path
) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
        raise ValueError(f"Provider metadata configuration_fingerprint must be a list: {metadata_path}")
    entries = {item.name: item for item in environment}
    if len(value) != len(set(value)) or any(
        name not in entries or entries[name].secret for name in value
    ):
        raise ValueError(
            "Provider metadata configuration_fingerprint may contain only unique "
            f"non-secret environment names: {metadata_path}"
        )
    return tuple(value)


def _safe_relative_path(root: Path, value: Any, metadata_path: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Provider metadata path is missing: {metadata_path}")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Provider metadata path must be relative and contained: {metadata_path}")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise ValueError(f"Provider metadata path does not resolve to a skill file: {metadata_path}")
    return resolved


def _source_template(value: Any, metadata_path: Path) -> str:
    if not isinstance(value, str) or not value or "{dataset}" not in value:
        raise ValueError(f"Provider metadata source_template must contain {{dataset}}: {metadata_path}")
    try:
        value.format(dataset="dataset")
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Provider metadata source_template is invalid: {metadata_path}") from exc
    return value


def _slug(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Provider metadata {label} must be a slug")
    normalized = value.strip().casefold()
    if not _SLUG.fullmatch(normalized):
        raise ValueError(f"Provider metadata {label} must be a lowercase slug: {value!r}")
    return normalized
