from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

SSH_SCRIPT = Path(__file__).resolve().with_name("ssh.py")
NO_INVENTORY_MARKERS = (
    "no inventory",
    "out of stock",
    "not rentable",
    "unavailable",
    "already rented",
    "offer is no longer available",
)


class VastApiError(RuntimeError):
    def __init__(self, status: int | None, detail: str):
        self.status = status
        self.detail = detail
        prefix = f"Vast API HTTP {status}" if status is not None else "Vast API error"
        super().__init__(f"{prefix}: {detail}")


def _environment(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default or "").strip().strip("'\"")
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def _positive_integer(name: str, default: str) -> int:
    value = _environment(name, default)
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return parsed


def _positive_number(name: str, default: str) -> float:
    value = _environment(name, default)
    try:
        parsed = float(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive number") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} must be a positive number")
    return parsed


def _api_base_url() -> str:
    base = _environment("VASTAI_API_BASE_URL", "https://console.vast.ai").rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("VASTAI_API_BASE_URL must be an HTTP(S) origin")
    return base


def _redact(value: str) -> str:
    token = os.environ.get("VAST_API_KEY", "").strip().strip("'\"")
    return value.replace(token, "<redacted>") if token else value


def request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> Any:
    token = _environment("VAST_API_KEY")
    url = _api_base_url() + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    http_request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(http_request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = _redact(exc.read().decode("utf-8", errors="replace"))
        raise VastApiError(exc.code, detail or "request rejected") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VastApiError(None, _redact(str(exc))) from exc
    except json.JSONDecodeError as exc:
        raise VastApiError(None, "response was not valid JSON") from exc
    return payload


def _successful(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise VastApiError(None, "response must be a JSON object")
    if payload.get("success") is False:
        detail = payload.get("msg") or payload.get("error") or "operation was rejected"
        raise VastApiError(None, _redact(str(detail)))
    return payload


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _required_string(mapping: dict[str, Any], name: str, label: str) -> str:
    value = mapping.get(name)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Vast state is missing {label}.{name}")
    return value


def _required_number(mapping: dict[str, Any], name: str, label: str) -> float:
    value = mapping.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise RuntimeError(f"Vast state has an invalid {label}.{name}")
    return float(value)


def load_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Vast state is missing: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Vast state is unreadable or invalid: {path}") from exc
    if not isinstance(state, dict) or state.get("provider") != "vastai":
        raise RuntimeError("State does not belong to the Vast provider")
    if state.get("created_by_run") is not True:
        raise RuntimeError("Vast state lacks current-run ownership")
    provider_state = state.get("provider_state")
    if not isinstance(provider_state, dict) or provider_state.get("schema_version") != 1:
        raise RuntimeError("Vast state has an unsupported provider_state schema")
    _required_string(provider_state, "run_token", "provider_state")
    _required_string(provider_state, "label", "provider_state")
    requested = provider_state.get("requested")
    if not isinstance(requested, dict):
        raise RuntimeError("Vast state is missing provider_state.requested")
    for name in ("gpu_count", "min_gpu_ram_gb", "min_cpu_ram_gb", "max_dph", "disk_gb"):
        _required_number(requested, name, "provider_state.requested")
    _required_string(requested, "image", "provider_state.requested")
    selected = provider_state.get("selected_offer")
    if not isinstance(selected, dict):
        raise RuntimeError("Vast state is missing provider_state.selected_offer")
    _offer_record(selected)
    if provider_state.get("creation_uncertain") is not True:
        _required_string(provider_state, "instance_id", "provider_state")
    return state


def validate_state(args: argparse.Namespace) -> dict[str, Any]:
    return load_state(args.state)


def _offer_id(offer: dict[str, Any]) -> str:
    for name in ("id", "ask_contract_id"):
        value = offer.get(name)
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value):
            return str(value)
    raise RuntimeError("Vast offer is missing an identifier")


def _number(offer: dict[str, Any], name: str) -> float:
    value = offer.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"Vast offer has an invalid {name}")
    return float(value)


def _positive_offer_integer(offer: dict[str, Any], name: str) -> int:
    value = _number(offer, name)
    if not value.is_integer() or value <= 0:
        raise RuntimeError(f"Vast offer has an invalid {name}")
    return int(value)


def _offer_record(offer: dict[str, Any]) -> dict[str, Any]:
    if {
        "id",
        "gpu_name",
        "cpu_arch",
        "gpu_count",
        "gpu_ram_mb",
        "cpu_ram_mb",
        "total_flops",
        "dph_total",
        "reliability",
    } <= set(offer):
        return {
            "id": _required_string(offer, "id", "offer"),
            "gpu_name": _required_string(offer, "gpu_name", "offer"),
            "cpu_arch": _required_string(offer, "cpu_arch", "offer"),
            "gpu_count": int(_required_number(offer, "gpu_count", "offer")),
            "gpu_ram_mb": int(_required_number(offer, "gpu_ram_mb", "offer")),
            "cpu_ram_mb": int(_required_number(offer, "cpu_ram_mb", "offer")),
            "total_flops": _required_number(offer, "total_flops", "offer"),
            "dph_total": _required_number(offer, "dph_total", "offer"),
            "reliability": _required_number(offer, "reliability", "offer"),
        }
    gpu_name = offer.get("gpu_name")
    cpu_arch = offer.get("cpu_arch")
    if not isinstance(gpu_name, str) or not gpu_name:
        raise RuntimeError("Vast offer is missing gpu_name")
    if not isinstance(cpu_arch, str) or not cpu_arch:
        raise RuntimeError("Vast offer is missing cpu_arch")
    return {
        "id": _offer_id(offer),
        "gpu_name": gpu_name,
        "cpu_arch": cpu_arch,
        "gpu_count": _positive_offer_integer(offer, "num_gpus"),
        "gpu_ram_mb": _positive_offer_integer(offer, "gpu_ram"),
        "cpu_ram_mb": _positive_offer_integer(offer, "cpu_ram"),
        "total_flops": _number(offer, "total_flops"),
        "dph_total": _number(offer, "dph_total"),
        "reliability": _number(offer, "reliability"),
    }


def _offer_matches(record: dict[str, Any], specification: dict[str, Any]) -> bool:
    gpu_name = specification.get("gpu_name")
    return (
        record["cpu_arch"].casefold() in {"amd64", "x86_64"}
        and (gpu_name is None or record["gpu_name"].casefold() == str(gpu_name).casefold())
        and record["gpu_count"] >= specification["gpu_count"]
        and record["gpu_ram_mb"] >= specification["min_gpu_ram_gb"] * 1024
        and record["cpu_ram_mb"] >= specification["min_cpu_ram_gb"] * 1024
        and record["dph_total"] <= specification["max_dph"]
        and record["reliability"] >= specification["min_reliability"]
    )


def _offers_payload(payload: Any) -> list[dict[str, Any]]:
    values = payload
    if isinstance(payload, dict):
        values = payload.get("offers", payload.get("bundles"))
    if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
        raise RuntimeError("Vast offer search returned an unsupported response structure")
    return values


def search_offers(specification: dict[str, Any]) -> list[dict[str, Any]]:
    payload = request(
        "POST",
        "/api/v0/bundles",
        {
            "limit": 100,
            "type": "on-demand",
            "verified": {"eq": True},
            "rentable": {"eq": True},
            "rented": {"eq": False},
        },
    )
    candidates = []
    for raw in _offers_payload(payload):
        try:
            record = _offer_record(raw)
        except RuntimeError:
            continue
        if _offer_matches(record, specification):
            candidates.append(record)
    return sorted(
        candidates,
        key=lambda offer: (offer["dph_total"], -offer["reliability"], offer["id"]),
    )


def _specification_from_args(args: argparse.Namespace) -> dict[str, Any]:
    gpu_count = args.gpu_count or _positive_integer("VASTAI_DEFAULT_GPU_COUNT", "1")
    min_gpu_ram_gb = args.min_gpu_ram_gb or _positive_integer("VASTAI_MIN_GPU_RAM_GB", "24")
    min_cpu_ram_gb = args.min_cpu_ram_gb or _positive_integer("VASTAI_MIN_CPU_RAM_GB", "32")
    disk_gb = args.disk_gb or _positive_integer("VASTAI_DISK_GB", "64")
    max_dph = args.max_dph or _positive_number("VASTAI_MAX_DPH", "2")
    min_reliability = args.min_reliability or _positive_number("VASTAI_MIN_RELIABILITY", "0.99")
    if min_reliability > 1:
        raise RuntimeError("VASTAI_MIN_RELIABILITY must be at most 1")
    if any(isinstance(value, bool) or value <= 0 for value in (gpu_count, min_gpu_ram_gb, min_cpu_ram_gb, disk_gb, max_dph)):
        raise RuntimeError("Vast resource requirements must be positive")
    gpu_name = args.gpu_name.strip() if getattr(args, "gpu_name", None) else None
    return {
        "gpu_name": gpu_name,
        "gpu_count": int(gpu_count),
        "min_gpu_ram_gb": int(min_gpu_ram_gb),
        "min_cpu_ram_gb": int(min_cpu_ram_gb),
        "max_dph": float(max_dph),
        "min_reliability": float(min_reliability),
        "disk_gb": int(disk_gb),
        "image": (getattr(args, "image", None) or _environment("VASTAI_IMAGE")).strip(),
    }


def search(args: argparse.Namespace) -> None:
    specification = _specification_from_args(args)
    specification.pop("image")
    print(json.dumps({"offers": search_offers(specification)}, indent=2, sort_keys=True))


def _selected_offer(offer_id: str, specification: dict[str, Any]) -> dict[str, Any]:
    matches = [offer for offer in search_offers(specification) if offer["id"] == offer_id]
    if len(matches) != 1:
        raise RuntimeError("Selected Vast offer is unavailable or no longer eligible")
    return matches[0]


def _stronger_or_equal(fallback: dict[str, Any], primary: dict[str, Any]) -> bool:
    return (
        fallback["gpu_count"] >= primary["gpu_count"]
        and fallback["gpu_ram_mb"] >= primary["gpu_ram_mb"]
        and fallback["cpu_ram_mb"] >= primary["cpu_ram_mb"]
        and fallback["total_flops"] >= primary["total_flops"]
        and fallback["dph_total"] <= primary["dph_total"]
    )


def _manifest_resume_count(state_path: Path) -> int | None:
    manifest_path = state_path.parent.parent / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Run manifest is invalid: {manifest_path}") from exc
    value = manifest.get("resume_count")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"Run manifest has an invalid resume_count: {manifest_path}")
    return value


def _history_from_released_state(
    state_path: Path, state: dict[str, Any]
) -> tuple[list[dict[str, Any]], int | None, str]:
    if state.get("released") is not True:
        raise RuntimeError("Vast state still owns an unreleased instance; refusing another rental")
    provider_state = state["provider_state"]
    resume_count = _manifest_resume_count(state_path)
    if resume_count is not None and provider_state.get("created_for_resume_count") == resume_count:
        raise RuntimeError("A replacement Vast instance was already created for this manual resume")
    history = provider_state.get("instance_history", [])
    if not isinstance(history, list):
        raise RuntimeError("Vast instance history has an invalid structure")
    archived = {
        name: provider_state[name]
        for name in (
            "instance_id",
            "label",
            "requested",
            "selected_offer",
            "fallback_offer",
            "remote_working_dir",
            "creation_uncertain",
            "unavailable_reason",
            "cloud_drive",
            "created_for_resume_count",
        )
        if name in provider_state
    }
    archived["released_at_unix"] = state.get("released_at_unix")
    return [*history, archived], resume_count, _required_string(provider_state, "run_token", "provider_state")


def _restore_after_known_create_failure(path: Path, previous: dict[str, Any] | None) -> None:
    if previous is None:
        if path.exists():
            path.unlink()
        return
    save_state(path, previous)


def _instances_by_label(label: str) -> list[dict[str, Any]]:
    payload = request(
        "GET",
        "/api/v1/instances/",
        query={"limit": 25, "select_filters": json.dumps({"label": {"eq": label}})},
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("instances"), list):
        raise RuntimeError("Vast instance listing returned an unsupported response structure")
    instances = payload["instances"]
    if not all(isinstance(item, dict) for item in instances):
        raise RuntimeError("Vast instance listing returned an unsupported response structure")
    return [item for item in instances if item.get("label") == label]


def _activate_instance(state_path: Path, state: dict[str, Any], instance_id: str) -> str:
    provider_state = state["provider_state"]
    provider_state["instance_id"] = str(instance_id)
    provider_state["creation_uncertain"] = False
    state["released"] = False
    state.pop("released_at_unix", None)
    save_state(state_path, state)
    return str(instance_id)


def _extract_created_instance(payload: Any) -> str | None:
    if not isinstance(payload, dict) or payload.get("success") is False:
        return None
    for name in ("new_contract", "instance_id", "id"):
        value = payload.get(name)
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value):
            return str(value)
    return None


def _is_explicit_no_inventory(error: VastApiError) -> bool:
    return error.status in {400, 404, 409} and any(
        marker in error.detail.casefold() for marker in NO_INVENTORY_MARKERS
    )


def _create_offer(state_path: Path, state: dict[str, Any], offer: dict[str, Any]) -> str:
    provider_state = state["provider_state"]
    requested = provider_state["requested"]
    payload = request(
        "PUT",
        f"/api/v0/asks/{offer['id']}/",
        {
            "image": requested["image"],
            "disk": requested["disk_gb"],
            "runtype": "ssh",
            "target_state": "running",
            "label": provider_state["label"],
        },
    )
    payload = _successful(payload)
    instance_id = _extract_created_instance(payload)
    if instance_id:
        return _activate_instance(state_path, state, instance_id)
    matches = _instances_by_label(provider_state["label"])
    if len(matches) == 1:
        return _activate_instance(state_path, state, _offer_id(matches[0]))
    if len(matches) > 1:
        raise RuntimeError("Vast create response is ambiguous: multiple instances share the run label")
    raise RuntimeError("Vast create response is uncertain; inspect the run label before retrying")


def create_instance(args: argparse.Namespace) -> str:
    specification = _specification_from_args(args)
    primary = _selected_offer(str(args.offer_id), specification)
    fallback = None
    if args.fallback_offer_id:
        if str(args.fallback_offer_id) == primary["id"]:
            raise RuntimeError("Vast fallback offer must differ from the primary offer")
        fallback_specification = dict(specification)
        fallback_specification["gpu_name"] = None
        fallback = _selected_offer(str(args.fallback_offer_id), fallback_specification)
        if not _stronger_or_equal(fallback, primary):
            raise RuntimeError("Vast fallback offer must be at least as capable as the primary offer")

    previous = load_state(args.state) if args.state.exists() else None
    if previous is None:
        history: list[dict[str, Any]] = []
        resume_count = _manifest_resume_count(args.state)
        run_token = uuid.uuid4().hex
    else:
        history, resume_count, run_token = _history_from_released_state(args.state, previous)
    provider_state: dict[str, Any] = {
        "schema_version": 1,
        "run_token": run_token,
        "label": f"medai-{run_token}",
        "creation_uncertain": True,
        "requested": specification,
        "selected_offer": primary,
        "remote_working_dir": f"/workspace/medai/{run_token}/work",
    }
    if fallback is not None:
        provider_state["fallback_offer"] = fallback
    if history:
        provider_state["instance_history"] = history
    if resume_count is not None:
        provider_state["created_for_resume_count"] = resume_count
    state = {
        "provider": "vastai",
        "created_by_run": True,
        "released": False,
        "provider_state": provider_state,
    }
    save_state(args.state, state)
    try:
        instance_id = _create_offer(args.state, state, primary)
    except VastApiError as exc:
        if not _is_explicit_no_inventory(exc):
            raise
        matches = _instances_by_label(provider_state["label"])
        if len(matches) == 1:
            instance_id = _activate_instance(args.state, state, _offer_id(matches[0]))
        elif len(matches) > 1:
            raise RuntimeError("Vast create response is ambiguous: multiple instances share the run label")
        elif fallback is None:
            _restore_after_known_create_failure(args.state, previous)
            raise RuntimeError("Selected Vast offer explicitly has no inventory") from exc
        else:
            provider_state["primary_offer"] = primary
            provider_state["selected_offer"] = fallback
            provider_state.pop("fallback_offer", None)
            save_state(args.state, state)
            try:
                instance_id = _create_offer(args.state, state, fallback)
            except VastApiError as fallback_error:
                if _is_explicit_no_inventory(fallback_error):
                    matches = _instances_by_label(provider_state["label"])
                    if not matches:
                        _restore_after_known_create_failure(args.state, previous)
                        raise RuntimeError("Fallback Vast offer explicitly has no inventory") from fallback_error
                    if len(matches) == 1:
                        instance_id = _activate_instance(args.state, state, _offer_id(matches[0]))
                    else:
                        raise RuntimeError("Vast create response is ambiguous: multiple instances share the run label")
                else:
                    raise
    saved = load_state(args.state)
    _wait_for_status(saved, "running", 840, 10)
    return instance_id


def show_instance(state: dict[str, Any]) -> dict[str, Any]:
    instance_id = _required_string(state["provider_state"], "instance_id", "provider_state")
    payload = request("GET", f"/api/v0/instances/{instance_id}/")
    if not isinstance(payload, dict):
        raise RuntimeError("Vast show-instance returned an unsupported response structure")
    instance = payload.get("instances", payload.get("instance"))
    if isinstance(instance, list) and len(instance) == 1:
        instance = instance[0]
    if not isinstance(instance, dict):
        raise RuntimeError("Vast show-instance returned an unsupported response structure")
    return instance


def instance_status(state: dict[str, Any]) -> str:
    instance = show_instance(state)
    raw = instance.get("actual_status", instance.get("cur_state"))
    if not isinstance(raw, str) or not raw:
        raise RuntimeError("Vast instance status is missing")
    normalized = raw.casefold()
    if normalized == "running":
        return "running"
    if normalized in {"stopped", "exited"}:
        return "stopped"
    return normalized


def _wait_for_status(
    state: dict[str, Any], expected: str, timeout_seconds: int, interval_seconds: int
) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_status = ""
    while time.monotonic() < deadline:
        last_status = instance_status(state)
        if last_status == expected:
            return last_status
        time.sleep(interval_seconds)
    raise RuntimeError(f"Vast instance did not reach {expected}; last status={last_status}")


def _ssh_command(
    state: dict[str, Any], action: str, arguments: list[str]
) -> subprocess.CompletedProcess[str]:
    if state.get("released") is True:
        raise RuntimeError("Vast instance has already been released")
    instance = show_instance(state)
    host = instance.get("ssh_host")
    port = instance.get("ssh_port")
    if not isinstance(host, str) or not host or isinstance(port, bool) or not isinstance(port, (int, str)):
        raise RuntimeError("Vast instance is missing SSH connection details")
    environment = os.environ.copy()
    environment.pop("COMPUTATION_PROVIDER_SSH_PASSWORD", None)
    return subprocess.run(
        [
            sys.executable,
            str(SSH_SCRIPT),
            "--host",
            host,
            "--port",
            str(port),
            "--user",
            "root",
            action,
            *arguments,
        ],
        capture_output=True,
        text=True,
        env=environment,
    )


def remote_exec(state: dict[str, Any], command: list[str]) -> str:
    completed = _ssh_command(state, "exec", ["--", *command])
    if completed.returncode != 0:
        raise RuntimeError("Vast remote command failed")
    return completed.stdout.strip()


def power_on_instance(args: argparse.Namespace, *, known_status: str | None = None) -> str:
    state = load_state(args.state)
    if state.get("released") is True:
        raise RuntimeError("Vast instance has already been released")
    status = known_status or instance_status(state)
    if status == "running":
        return status
    if status != "stopped":
        raise RuntimeError(f"Cannot power on Vast instance from status={status}")
    instance_id = _required_string(state["provider_state"], "instance_id", "provider_state")
    _successful(request("PUT", f"/api/v0/instances/{instance_id}/", {"state": "running"}))
    return _wait_for_status(state, "running", 840, 10)


def power_off_instance(args: argparse.Namespace) -> str:
    state = load_state(args.state)
    if state.get("released") is True:
        return "released"
    status = instance_status(state)
    if status == "stopped":
        return status
    if status != "running":
        raise RuntimeError(f"Cannot power off Vast instance from status={status}")
    instance_id = _required_string(state["provider_state"], "instance_id", "provider_state")
    _successful(request("PUT", f"/api/v0/instances/{instance_id}/", {"state": "stopped"}))
    return _wait_for_status(state, "stopped", 240, 5)


def _manifest_report_completed(state_path: Path) -> bool | None:
    manifest_path = state_path.parent.parent / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Run manifest is invalid: {manifest_path}") from exc
    inputs = manifest.get("inputs")
    if isinstance(inputs, dict) and inputs.get("workflow") == "autoresearch":
        return None
    stages = manifest.get("stages")
    if not isinstance(stages, dict):
        raise RuntimeError(f"Run manifest has invalid stages: {manifest_path}")
    report_stage = stages.get("report_agents")
    return (
        manifest.get("status") == "completed"
        and isinstance(report_stage, dict)
        and report_stage.get("status") == "completed"
    )


def _mark_released(state_path: Path, state: dict[str, Any], reason: str | None = None) -> None:
    state["released"] = True
    state["released_at_unix"] = int(time.time())
    if reason:
        state["provider_state"]["unavailable_reason"] = reason
    save_state(state_path, state)


def release_instance(args: argparse.Namespace, *, allow_before_report: bool = False) -> None:
    state = load_state(args.state)
    if state.get("released") is True:
        return
    if not allow_before_report and _manifest_report_completed(args.state) is False:
        raise RuntimeError("Refusing to release Vast instance before report and pipeline completion")
    instance_id = _required_string(state["provider_state"], "instance_id", "provider_state")
    try:
        power_off_instance(args)
    except VastApiError as exc:
        if exc.status != 404:
            raise
    try:
        _successful(request("DELETE", f"/api/v0/instances/{instance_id}/"))
    except VastApiError as exc:
        if exc.status != 404:
            raise
    try:
        show_instance(state)
    except VastApiError as exc:
        if exc.status == 404:
            _mark_released(args.state, state)
            return
        raise
    raise RuntimeError("Vast instance remains visible after destroy")


def _ensure_replacement_allowed(state_path: Path, state: dict[str, Any]) -> None:
    resume_count = _manifest_resume_count(state_path)
    if (
        resume_count is not None
        and state["provider_state"].get("created_for_resume_count") == resume_count
    ):
        raise RuntimeError("A replacement Vast instance was already created for this manual resume")


def _replacement_args(state_path: Path, state: dict[str, Any]) -> argparse.Namespace:
    provider_state = state["provider_state"]
    requested = provider_state["requested"]
    selected = provider_state["selected_offer"]
    _offer_record(selected)
    replacement_specification = dict(requested)
    replacement_specification.update(
        {
            "gpu_name": selected["gpu_name"],
            "gpu_count": selected["gpu_count"],
            "min_gpu_ram_gb": (selected["gpu_ram_mb"] + 1023) // 1024,
            "min_cpu_ram_gb": (selected["cpu_ram_mb"] + 1023) // 1024,
            "min_reliability": min(requested["min_reliability"], selected["reliability"]),
        }
    )
    primary_candidates = search_offers(replacement_specification)
    if not primary_candidates:
        raise RuntimeError("No current Vast offer can recreate the recorded primary resource")
    primary = primary_candidates[0]
    fallback_id = None
    fallback = provider_state.get("fallback_offer")
    if isinstance(fallback, dict):
        fallback_record = _offer_record(fallback)
        fallback_specification = dict(replacement_specification)
        fallback_specification.update(
            {
                "gpu_name": fallback_record["gpu_name"],
                "gpu_count": fallback_record["gpu_count"],
                "min_gpu_ram_gb": (fallback_record["gpu_ram_mb"] + 1023) // 1024,
                "min_cpu_ram_gb": (fallback_record["cpu_ram_mb"] + 1023) // 1024,
            }
        )
        fallback_candidates = search_offers(fallback_specification)
        eligible = [candidate for candidate in fallback_candidates if _stronger_or_equal(candidate, primary)]
        if eligible:
            fallback_id = eligible[0]["id"]
    return argparse.Namespace(
        state=state_path,
        offer_id=primary["id"],
        fallback_offer_id=fallback_id,
        gpu_name=primary["gpu_name"],
        gpu_count=primary["gpu_count"],
        min_gpu_ram_gb=(primary["gpu_ram_mb"] + 1023) // 1024,
        min_cpu_ram_gb=(primary["cpu_ram_mb"] + 1023) // 1024,
        max_dph=requested["max_dph"],
        min_reliability=min(requested["min_reliability"], primary["reliability"]),
        disk_gb=requested["disk_gb"],
        image=requested["image"],
    )


def _resolve_uncertain_creation(state_path: Path, state: dict[str, Any]) -> dict[str, Any]:
    provider_state = state["provider_state"]
    if provider_state.get("creation_uncertain") is not True:
        return state
    matches = _instances_by_label(_required_string(provider_state, "label", "provider_state"))
    if len(matches) != 1:
        raise RuntimeError("Vast creation remains uncertain; expected exactly one run-labelled instance")
    _activate_instance(state_path, state, _offer_id(matches[0]))
    return load_state(state_path)


def reconcile_instance(args: argparse.Namespace) -> dict[str, Any]:
    state = _resolve_uncertain_creation(args.state, load_state(args.state))
    if state.get("released") is True:
        instance_id = create_instance(_replacement_args(args.state, state))
        return {"replaced": True, "instance_id": instance_id, "status": "running"}
    try:
        status = instance_status(state)
    except VastApiError as exc:
        if exc.status != 404:
            raise
        _ensure_replacement_allowed(args.state, state)
        _mark_released(args.state, state, "provider_confirmed_missing")
        instance_id = create_instance(_replacement_args(args.state, load_state(args.state)))
        return {"replaced": True, "instance_id": instance_id, "status": "running"}
    if status == "stopped":
        power_on_instance(args, known_status=status)
    elif status != "running":
        raise RuntimeError(f"Cannot reconcile Vast instance from status={status}")
    state = load_state(args.state)
    probe = _ssh_command(state, "exec", ["--", "true"])
    if probe.returncode == 0:
        return {
            "replaced": False,
            "instance_id": state["provider_state"]["instance_id"],
            "status": "running",
        }
    _ensure_replacement_allowed(args.state, state)
    release_instance(args, allow_before_report=True)
    instance_id = create_instance(_replacement_args(args.state, load_state(args.state)))
    return {"replaced": True, "instance_id": instance_id, "status": "running"}


def cloud_pull(args: argparse.Namespace) -> None:
    raise RuntimeError("Vast Google Drive support is not configured in this adapter revision")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    search_parser = subparsers.add_parser("search")
    create = subparsers.add_parser("create")
    for command in (search_parser, create):
        command.add_argument("--gpu-name")
        command.add_argument("--gpu-count", type=int)
        command.add_argument("--min-gpu-ram-gb", type=int)
        command.add_argument("--min-cpu-ram-gb", type=int)
        command.add_argument("--max-dph", type=float)
        command.add_argument("--min-reliability", type=float)
        command.add_argument("--disk-gb", type=int)
    create.add_argument("--offer-id", required=True)
    create.add_argument("--fallback-offer-id")
    create.add_argument("--image")
    create.add_argument("--state", type=Path, required=True)
    for name in ("validate-state", "status", "power-on", "power-off", "release", "reconcile"):
        command = subparsers.add_parser(name)
        command.add_argument("--state", type=Path, required=True)
    execute = subparsers.add_parser("exec")
    execute.add_argument("--state", type=Path, required=True)
    execute.add_argument("command", nargs=argparse.REMAINDER)
    upload = subparsers.add_parser("upload")
    upload.add_argument("--state", type=Path, required=True)
    upload.add_argument("--source", type=Path, required=True)
    upload.add_argument("--remote", required=True)
    download = subparsers.add_parser("download")
    download.add_argument("--state", type=Path, required=True)
    download.add_argument("--remote", required=True)
    download.add_argument("--destination", type=Path, required=True)
    pull = subparsers.add_parser("cloud-pull")
    pull.add_argument("--state", type=Path, required=True)
    pull.add_argument("--dataset", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.action == "search":
        search(args)
    elif args.action == "create":
        print(create_instance(args))
    elif args.action == "validate-state":
        validate_state(args)
    elif args.action == "status":
        print(instance_status(load_state(args.state)))
    elif args.action == "power-on":
        print(power_on_instance(args))
    elif args.action == "power-off":
        print(power_off_instance(args))
    elif args.action == "release":
        release_instance(args)
    elif args.action == "reconcile":
        print(json.dumps(reconcile_instance(args), sort_keys=True))
    elif args.action == "cloud-pull":
        cloud_pull(args)
    else:
        state = load_state(args.state)
        if args.action == "exec":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            if not command:
                raise RuntimeError("exec requires a command")
            arguments = ["--", *command]
        elif args.action == "upload":
            arguments = ["--source", str(args.source), "--remote", args.remote]
        else:
            arguments = ["--remote", args.remote, "--destination", str(args.destination)]
        completed = _ssh_command(state, args.action, arguments)
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        return completed.returncode
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, TypeError, ValueError, KeyError) as exc:
        raise SystemExit(_redact(str(exc))) from None
