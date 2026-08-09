from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import shlex
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
CLOUD_COPY_TIMEOUT_SECONDS = 3600
INVENTORY_FILENAME = "cloud-inventory.v1.json"
SSH_KEY_TYPES = {
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "sk-ecdsa-sha2-nistp256@openssh.com",
    "sk-ssh-ed25519@openssh.com",
    "ssh-ed25519",
    "ssh-rsa",
}
INVENTORY_PROGRAM = r'''
import hashlib
import json
import os
import stat
import sys

root = os.path.realpath(sys.argv[-2])
dataset = sys.argv[-1]
if not os.path.isdir(root):
    raise SystemExit("inventory root is missing")
files = []
for current, directories, names in os.walk(root, followlinks=False):
    directories.sort()
    names.sort()
    for directory in directories:
        if os.path.islink(os.path.join(current, directory)):
            raise SystemExit("inventory does not permit symlink directories")
    for name in names:
        path = os.path.join(current, name)
        mode = os.lstat(path).st_mode
        if not stat.S_ISREG(mode):
            raise SystemExit("inventory permits regular files only")
        digest = hashlib.sha256()
        with open(path, "rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        files.append(
            {
                "path": os.path.relpath(path, root).replace(os.sep, "/"),
                "size": os.path.getsize(path),
                "sha256": digest.hexdigest(),
            }
        )
files.sort(key=lambda item: item["path"])
if not files:
    raise SystemExit("inventory does not permit an empty dataset")
print(
    json.dumps(
        {
            "version": 1,
            "algorithm": "sha256",
            "dataset": dataset,
            "files": files,
            "file_count": len(files),
            "total_bytes": sum(item["size"] for item in files),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
)
'''


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


def _public_key_identity(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parts = value.split()
    if len(parts) < 2 or parts[0] not in SSH_KEY_TYPES:
        return None
    try:
        decoded = base64.b64decode(parts[1], validate=True)
    except (ValueError, binascii.Error):
        return None
    return f"{parts[0]} {parts[1]}" if decoded else None


def _configured_ssh_public_key() -> str | None:
    raw_identity = (
        os.environ.get("COMPUTATION_PROVIDER_SSH_IDENTITY_FILE", "")
        .strip()
        .strip("'\"")
    )
    if not raw_identity:
        return None
    public_key_path = Path(f"{Path(raw_identity).expanduser()}.pub")
    try:
        lines = [
            line.strip()
            for line in public_key_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except OSError as exc:
        raise RuntimeError(f"Vast SSH public key is missing: {public_key_path}") from exc
    if len(lines) != 1:
        raise RuntimeError("Vast SSH public key file must contain exactly one key")
    public_key = _public_key_identity(lines[0])
    if public_key is None:
        raise RuntimeError("Vast SSH public key is invalid or unsupported")
    return public_key


def _validate_account_ssh_key(public_key: str) -> None:
    payload = request("GET", "/api/v0/ssh")
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise RuntimeError("Vast account SSH-key listing returned an unsupported response structure")
    matches = [
        item
        for item in payload
        if item.get("deleted_at") in {None, ""}
        and _public_key_identity(item.get("public_key") or item.get("key")) == public_key
    ]
    if not matches:
        raise RuntimeError("Configured SSH public key is not registered with the Vast account")


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


def search_offers(
    specification: dict[str, Any], offer_id: str | None = None
) -> list[dict[str, Any]]:
    body = {
        "limit": 1 if offer_id is not None else 100,
        "type": "on-demand",
        "verified": {"eq": True},
        "rentable": {"eq": True},
        "rented": {"eq": False},
        "cpu_arch": {"in": ["amd64", "x86_64"]},
        "num_gpus": {"gte": specification["gpu_count"]},
        "gpu_ram": {"gte": specification["min_gpu_ram_gb"] * 1024},
        "cpu_ram": {"gte": specification["min_cpu_ram_gb"] * 1024},
        "dph_total": {"lte": specification["max_dph"]},
        "reliability": {"gte": specification["min_reliability"]},
        "disk_space": {"gte": specification["disk_gb"]},
        "allocated_storage": specification["disk_gb"],
        "order": [
            ["dph_total", "asc"],
            ["reliability", "desc"],
            ["id", "asc"],
        ],
    }
    if offer_id is not None:
        body["ask_contract_id"] = {
            "eq": int(offer_id) if offer_id.isdecimal() else offer_id
        }
    payload = request("POST", "/api/v0/bundles", body)
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
    matches = [
        offer
        for offer in search_offers(specification, offer_id=offer_id)
        if offer["id"] == offer_id
    ]
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


def _create_offer(
    state_path: Path,
    state: dict[str, Any],
    offer: dict[str, Any],
    ssh_public_key: str | None,
) -> str:
    provider_state = state["provider_state"]
    requested = provider_state["requested"]
    body = {
        "image": requested["image"],
        "disk": requested["disk_gb"],
        "runtype": "ssh",
        "target_state": "running",
        "label": provider_state["label"],
    }
    if ssh_public_key is not None:
        quoted_key = shlex.quote(ssh_public_key)
        body["onstart"] = (
            "install -d -m 700 /root/.ssh && "
            "touch /root/.ssh/authorized_keys && "
            f"(grep -qxF {quoted_key} /root/.ssh/authorized_keys || "
            f"printf '%s\\n' {quoted_key} >> /root/.ssh/authorized_keys) && "
            "chmod 600 /root/.ssh/authorized_keys"
        )
    payload = request(
        "PUT",
        f"/api/v0/asks/{offer['id']}/",
        body,
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
    ssh_public_key = _configured_ssh_public_key()
    if ssh_public_key is not None:
        _validate_account_ssh_key(ssh_public_key)
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
    if previous is not None:
        prior_cloud = previous["provider_state"].get("cloud_drive")
        if isinstance(prior_cloud, dict):
            cloud = dict(prior_cloud)
            cloud["completed"] = False
            cloud["status"] = "replacement_pending"
            cloud.pop("materialized", None)
            provider_state["cloud_drive"] = cloud
    state = {
        "provider": "vastai",
        "created_by_run": True,
        "released": False,
        "provider_state": provider_state,
    }
    save_state(args.state, state)
    try:
        instance_id = _create_offer(args.state, state, primary, ssh_public_key)
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
                instance_id = _create_offer(args.state, state, fallback, ssh_public_key)
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
    if "actual_status" in instance and instance.get("actual_status") is None:
        return "provisioning"
    raw = instance.get("actual_status", instance.get("cur_state"))
    if not isinstance(raw, str) or not raw:
        raise RuntimeError("Vast instance status is missing")
    normalized = raw.casefold()
    control_state = instance.get("cur_state", instance.get("intended_status"))
    if normalized == "exited" and isinstance(control_state, str):
        if control_state.casefold() == "stopped":
            return "stopped"
        if control_state.casefold() == "running":
            return "provisioning"
    if normalized == "running":
        return "running"
    if normalized == "stopped":
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
        if last_status in {"exited", "offline", "unknown"}:
            raise RuntimeError(
                f"Vast instance entered terminal status={last_status} while waiting for {expected}"
            )
        time.sleep(interval_seconds)
    raise RuntimeError(f"Vast instance did not reach {expected}; last status={last_status}")


def _ssh_command(
    state: dict[str, Any], action: str, arguments: list[str]
) -> subprocess.CompletedProcess[str]:
    if state.get("released") is True:
        raise RuntimeError("Vast instance has already been released")
    instance = show_instance(state)
    direct_host = instance.get("public_ipaddr")
    direct_port = instance.get("machine_dir_ssh_port")
    proxy_host = instance.get("ssh_host")
    proxy_port = instance.get("ssh_port")
    endpoints: list[tuple[str, int | str]] = []
    if (
        isinstance(direct_host, str)
        and direct_host
        and not isinstance(direct_port, bool)
        and isinstance(direct_port, (int, str))
    ):
        endpoints.append((direct_host, direct_port))
    if (
        isinstance(proxy_host, str)
        and proxy_host
        and not isinstance(proxy_port, bool)
        and isinstance(proxy_port, (int, str))
        and (proxy_host, str(proxy_port))
        not in {(host, str(port)) for host, port in endpoints}
    ):
        endpoints.append((proxy_host, proxy_port))
    if not endpoints:
        raise RuntimeError("Vast instance is missing SSH connection details")
    environment = os.environ.copy()
    environment.pop("COMPUTATION_PROVIDER_SSH_PASSWORD", None)
    for index, (host, port) in enumerate(endpoints):
        completed = subprocess.run(
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
        if (
            completed.returncode == 0
            or index == len(endpoints) - 1
            or "SSH public-key authentication failed and no fallback password is available"
            not in completed.stderr
        ):
            return completed
    raise RuntimeError("Vast SSH endpoint selection failed")


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
    except RuntimeError:
        payload = request(
            "GET",
            "/api/v1/instances/",
            query={
                "limit": 25,
                "select_filters": json.dumps(
                    {"id": {"eq": int(instance_id) if instance_id.isdigit() else instance_id}}
                ),
            },
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("instances"), list):
            raise RuntimeError("Vast instance listing returned an unsupported response structure")
        if not all(isinstance(item, dict) for item in payload["instances"]):
            raise RuntimeError("Vast instance listing returned an unsupported response structure")
        matches = [
            item
            for item in payload["instances"]
            if str(item.get("id")) == instance_id
        ]
        if not matches:
            _mark_released(args.state, state)
            return
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


def _safe_dataset(value: str) -> str:
    dataset = value.strip()
    if (
        not dataset
        or dataset in {".", ".."}
        or len(dataset) > 128
        or not dataset[0].isalnum()
        or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in dataset)
    ):
        raise RuntimeError("cloud-pull requires one safe dataset directory name")
    return dataset


def _cloud_paths(state: dict[str, Any], dataset: str) -> tuple[str, str]:
    run_token = _required_string(state["provider_state"], "run_token", "provider_state")
    root = f"/workspace/medai/{run_token}"
    return f"{root}/.staging/{dataset}", f"{root}/data/{dataset}"


def _inventory_path(state_path: Path) -> Path:
    return state_path.with_name(INVENTORY_FILENAME)


def _inventory_digest(inventory: dict[str, Any]) -> str:
    encoded = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_inventory_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        return False
    parts = value.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def _validate_inventory(value: Any, dataset: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("Cloud inventory must be a JSON object")
    if value.get("version") != 1 or value.get("algorithm") != "sha256" or value.get("dataset") != dataset:
        raise RuntimeError("Cloud inventory has an unsupported identity")
    files = value.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("Cloud inventory must contain at least one file")
    normalized: list[dict[str, Any]] = []
    paths: list[str] = []
    total_bytes = 0
    for item in files:
        if not isinstance(item, dict) or not _valid_inventory_path(item.get("path")):
            raise RuntimeError("Cloud inventory contains an invalid relative path")
        size = item.get("size")
        digest = item.get("sha256")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise RuntimeError("Cloud inventory contains an invalid size")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise RuntimeError("Cloud inventory contains an invalid SHA-256 digest")
        path = item["path"]
        paths.append(path)
        total_bytes += size
        normalized.append({"path": path, "size": size, "sha256": digest})
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise RuntimeError("Cloud inventory paths must be sorted and unique")
    if value.get("file_count") != len(normalized) or value.get("total_bytes") != total_bytes:
        raise RuntimeError("Cloud inventory totals do not match its files")
    return {
        "version": 1,
        "algorithm": "sha256",
        "dataset": dataset,
        "files": normalized,
        "file_count": len(normalized),
        "total_bytes": total_bytes,
    }


def _load_inventory(path: Path, dataset: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Cloud inventory is missing: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cloud inventory is unreadable or invalid: {path}") from exc
    return _validate_inventory(value, dataset)


def _write_inventory(path: Path, inventory: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _remote_inventory(state: dict[str, Any], path: str, dataset: str) -> dict[str, Any]:
    output = remote_exec(
        state,
        ["python3", "-c", INVENTORY_PROGRAM, "medai-cloud-inventory", path, dataset],
    )
    try:
        return _validate_inventory(json.loads(output), dataset)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Remote cloud inventory was not valid JSON") from exc


def _drive_connection_id() -> str:
    selected = _environment("VASTAI_GOOGLE_DRIVE_CONNECTION_ID")
    payload = request("GET", "/api/v0/users/cloud_integrations")
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise RuntimeError("Vast cloud-connection listing returned an unsupported response structure")
    matches = [item for item in payload if str(item.get("id")) == selected]
    if len(matches) != 1 or matches[0].get("cloud_type") != "drive":
        raise RuntimeError("VASTAI_GOOGLE_DRIVE_CONNECTION_ID must identify exactly one Google Drive connection")
    return selected


def _update_cloud(state_path: Path, state: dict[str, Any], cloud: dict[str, Any], status: str) -> None:
    cloud["status"] = status
    cloud["completed"] = status == "completed"
    cloud["updated_at_unix"] = int(time.time())
    state["provider_state"]["cloud_drive"] = cloud
    save_state(state_path, state)


def _cloud_state(
    state_path: Path, state: dict[str, Any], dataset: str, connection_id: str
) -> dict[str, Any]:
    source_path = f"medai/{dataset}"
    staging_path, target_path = _cloud_paths(state, dataset)
    prior = state["provider_state"].get("cloud_drive")
    if prior is None:
        cloud = {
            "drive": "google-drive",
            "dataset": dataset,
            "source_path": source_path,
            "connection_id": connection_id,
            "staging_path": staging_path,
            "target_path": target_path,
            "owned_paths": True,
            "inventory_path": INVENTORY_FILENAME,
            "started_at_unix": int(time.time()),
        }
        _update_cloud(state_path, state, cloud, "new")
        return cloud
    if not isinstance(prior, dict):
        raise RuntimeError("Vast cloud-drive state has an invalid structure")
    expected = {
        "drive": "google-drive",
        "dataset": dataset,
        "source_path": source_path,
        "connection_id": connection_id,
        "staging_path": staging_path,
        "target_path": target_path,
        "owned_paths": True,
        "inventory_path": INVENTORY_FILENAME,
    }
    if any(prior.get(name) != value for name, value in expected.items()):
        raise RuntimeError("Vast cloud-drive state is inconsistent with this run configuration")
    if not isinstance(prior.get("completed"), bool) or not isinstance(prior.get("status"), str):
        raise RuntimeError("Vast cloud-drive state has an invalid completion status")
    return prior


def _wait_for_cloud_copy(state: dict[str, Any], cloud: dict[str, Any]) -> str:
    started_at = cloud.get("copy_started_at_unix")
    if isinstance(started_at, bool) or not isinstance(started_at, int) or started_at <= 0:
        raise RuntimeError("Vast cloud-copy state is missing its start time")
    remaining = CLOUD_COPY_TIMEOUT_SECONDS - max(0, int(time.time()) - started_at)
    deadline = time.monotonic() + max(0, remaining)
    while time.monotonic() < deadline:
        instance = show_instance(state)
        message = instance.get("status_msg")
        text = message.casefold() if isinstance(message, str) else ""
        if any(
            marker in text
            for marker in (
                "cloud copy operation finished",
                "cloud copy operation complete",
            )
        ):
            return "completed"
        if any(marker in text for marker in ("error", "failed", "cancelled", "canceled")):
            return "failed"
        time.sleep(30)
    return "timeout"


def _cleanup_cloud_staging(state: dict[str, Any], cloud: dict[str, Any]) -> None:
    dataset = cloud.get("dataset")
    if not isinstance(dataset, str):
        raise RuntimeError("Cloud-drive cleanup state is missing its dataset")
    expected_staging, expected_target = _cloud_paths(state, dataset)
    if (
        cloud.get("owned_paths") is not True
        or cloud.get("staging_path") != expected_staging
        or cloud.get("target_path") != expected_target
    ):
        raise RuntimeError("Cloud-drive cleanup cannot prove ownership of its paths")
    remote_exec(state, ["rm", "-rf", "--", expected_staging])


def _cancel_cloud_copy(state: dict[str, Any], cloud: dict[str, Any]) -> None:
    instance_id = _required_string(state["provider_state"], "instance_id", "provider_state")
    _successful(request("DELETE", "/api/v0/commands/rclone/", {"dst_id": instance_id}))
    cloud["cancel_confirmed"] = True
    _cleanup_cloud_staging(state, cloud)


def _ensure_cloud_staging_visible(
    state_path: Path, state: dict[str, Any], cloud: dict[str, Any]
) -> None:
    command = ["--", "test", "-d", cloud["staging_path"]]
    if _ssh_command(state, "exec", command).returncode == 0:
        return
    lifecycle_args = argparse.Namespace(state=state_path)
    power_off_instance(lifecycle_args)
    power_on_instance(lifecycle_args)
    if _ssh_command(state, "exec", command).returncode != 0:
        raise RuntimeError("Vast cloud-copy staging is not visible after instance restart")


def _start_cloud_copy(state_path: Path, state: dict[str, Any], cloud: dict[str, Any]) -> None:
    cloud["copy_started_at_unix"] = int(time.time())
    cloud["copy_requested"] = True
    cloud.pop("materialized", None)
    _update_cloud(state_path, state, cloud, "requesting")
    instance_id = _required_string(state["provider_state"], "instance_id", "provider_state")
    _successful(
        request(
            "POST",
            "/api/v0/commands/rclone/",
            {
                "instance_id": instance_id,
                "src": cloud["source_path"],
                "dst": cloud["staging_path"],
                "selected": cloud["connection_id"],
                "transfer": "Cloud To Instance",
                "flags": [],
            },
        )
    )
    _update_cloud(state_path, state, cloud, "copying")


def _complete_cloud_pull(
    state_path: Path, state: dict[str, Any], cloud: dict[str, Any], dataset: str
) -> str:
    inventory_path = _inventory_path(state_path)
    expected_inventory = _load_inventory(inventory_path, dataset) if inventory_path.is_file() else None
    staging_path = cloud["staging_path"]
    target_path = cloud["target_path"]
    if cloud.get("materialized") is True:
        final_inventory = _remote_inventory(state, target_path, dataset)
    else:
        staging_inventory = _remote_inventory(state, staging_path, dataset)
        if expected_inventory is not None and staging_inventory != expected_inventory:
            _update_cloud(state_path, state, cloud, "failed")
            raise RuntimeError("Google Drive dataset inventory changed from the run baseline")
        remote_exec(state, ["mkdir", "-p", target_path.rsplit("/", 1)[0]])
        remote_exec(state, ["test", "!", "-e", target_path])
        remote_exec(state, ["mv", "--", staging_path, target_path])
        cloud["materialized"] = True
        _update_cloud(state_path, state, cloud, "verifying")
        final_inventory = _remote_inventory(state, target_path, dataset)
    if expected_inventory is not None and final_inventory != expected_inventory:
        _update_cloud(state_path, state, cloud, "failed")
        raise RuntimeError("Google Drive materialization changed from the run baseline")
    remote_exec(state, ["chmod", "-R", "a-w", "--", target_path])
    _write_inventory(inventory_path, final_inventory)
    cloud["inventory_sha256"] = _inventory_digest(final_inventory)
    cloud["file_count"] = final_inventory["file_count"]
    cloud["total_bytes"] = final_inventory["total_bytes"]
    cloud["completed_at_unix"] = int(time.time())
    _update_cloud(state_path, state, cloud, "completed")
    return target_path


def cloud_pull(args: argparse.Namespace) -> None:
    dataset = _safe_dataset(args.dataset)
    drive_provider = os.environ.get("MEDAI_DRIVE_PROVIDER", "google-drive").strip().strip("'\"").casefold()
    if drive_provider != "google-drive":
        raise RuntimeError("MEDAI_DRIVE_PROVIDER must be 'google-drive'")
    state = load_state(args.state)
    if state.get("released") is True:
        raise RuntimeError("Vast instance has already been released")
    connection_id = _drive_connection_id()
    status = instance_status(state)
    if status == "stopped":
        raise RuntimeError("Cannot materialize Google Drive data on a stopped Vast instance")
    if status != "running":
        _wait_for_status(state, "running", 840, 10)
    cloud = _cloud_state(args.state, state, dataset, connection_id)
    inventory_path = _inventory_path(args.state)
    if cloud["completed"]:
        expected_inventory = _load_inventory(inventory_path, dataset)
        if cloud.get("inventory_sha256") != _inventory_digest(expected_inventory):
            raise RuntimeError("Vast cloud-drive state does not match its local inventory")
        observed_inventory = _remote_inventory(state, cloud["target_path"], dataset)
        if observed_inventory != expected_inventory:
            _update_cloud(args.state, state, cloud, "failed")
            raise RuntimeError("Google Drive materialization changed from the run baseline")
        remote_exec(state, ["chmod", "-R", "a-w", "--", cloud["target_path"]])
        print(cloud["target_path"])
        return
    if cloud.get("status") == "failed":
        _cleanup_cloud_staging(state, cloud)
        _start_cloud_copy(args.state, state, cloud)
    elif cloud.get("status") in {"new", "replacement_pending"}:
        remote_exec(state, ["test", "!", "-e", cloud["target_path"]])
        _start_cloud_copy(args.state, state, cloud)
    elif cloud.get("status") == "verifying":
        if cloud.get("materialized") is not True:
            _ensure_cloud_staging_visible(args.state, state, cloud)
        print(_complete_cloud_pull(args.state, state, cloud, dataset))
        return
    elif cloud.get("status") not in {"requesting", "copying"}:
        raise RuntimeError("Vast cloud-drive state has an unsupported status")
    copy_status = _wait_for_cloud_copy(state, cloud)
    if copy_status == "timeout":
        _cancel_cloud_copy(state, cloud)
        _update_cloud(args.state, state, cloud, "failed")
        raise RuntimeError("Vast Google Drive cloud copy timed out and was cancelled")
    if copy_status == "failed":
        _update_cloud(args.state, state, cloud, "failed")
        raise RuntimeError("Vast Google Drive cloud copy failed")
    _update_cloud(args.state, state, cloud, "verifying")
    _ensure_cloud_staging_visible(args.state, state, cloud)
    print(_complete_cloud_pull(args.state, state, cloud, dataset))


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
