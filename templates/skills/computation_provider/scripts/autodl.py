from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

BASE_URL = os.environ.get("AUTODL_API_BASE_URL", "https://api.autodl.com").rstrip("/")
TOKEN = os.environ.get("AUTODL_TOKEN", "").strip().strip("'\"")
SSH_SCRIPT = Path(__file__).resolve().with_name("ssh.py")
SUPPORTED_GPU_SPECS = {
    "h800",
    "v-48g",
    "pro6000-p",
    "v-32g-p",
    "v-48g-350w",
    "5090-p",
    "4090D",
}
NO_INVENTORY_MARKERS = (
    "库存不足",
    "无库存",
    "暂无可用",
    "无可用资源",
    "暂无资源",
    "no inventory",
    "out of stock",
)
PANEL_PATHS = {
    "sign_in": "/autopanel/v1/sign_in",
    "bindings": "/autopanel/v1/netdisk/list",
    "files": "/autopanel/v1/netdisk/file",
    "download": "/autopanel/v1/netdisk/download",
    "tasks": "/autopanel/v1/netdisk/task",
}
ALIYUN_LABELS = {
    "aliyun",
    "aliyundrive",
    "alipan",
    "autodl_alipan",
    "autodl_alinetdisk",
    "阿里云盘",
}


def request(method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    if not TOKEN:
        raise RuntimeError("AUTODL_TOKEN is not configured")
    url = BASE_URL + path
    data = json.dumps(body).encode("utf-8")
    headers = {"Authorization": TOKEN, "Content-Type": "application/json"}
    if method == "GET":
        url += "?" + urllib.parse.urlencode(body)
        data = None
        headers.pop("Content-Type")
    http_request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(http_request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AutoDL HTTP {exc.code}: {detail}") from exc
    if payload.get("code") != "Success":
        raise RuntimeError(f"AutoDL API error: {payload.get('msg') or payload}")
    return payload


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def load_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"AutoDL state is missing: {path}") from exc
    if state.get("provider") != "autodl":
        raise RuntimeError("State does not belong to the AutoDL provider")
    provider_state = state.get("provider_state")
    if not isinstance(provider_state, dict) or not provider_state.get("instance_uuid"):
        raise RuntimeError("AutoDL state is missing provider_state.instance_uuid")
    return state


def snapshot(state: dict[str, Any]) -> dict[str, Any]:
    payload = request(
        "GET",
        "/api/v1/dev/instance/pro/snapshot",
        {"instance_uuid": state["provider_state"]["instance_uuid"]},
    )
    details = payload.get("data")
    if not isinstance(details, dict):
        raise RuntimeError("AutoDL snapshot returned an unsupported response structure")
    return details


def _manifest_resume_count(state_path: Path) -> int | None:
    manifest_path = state_path.parent.parent / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8")).get("resume_count")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Run manifest is invalid: {manifest_path}") from exc
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"Run manifest has an invalid resume_count: {manifest_path}")
    return value


def _history_from_released_state(
    state: dict[str, Any], state_path: Path
) -> tuple[list[dict[str, Any]], int | None]:
    if not state.get("created_by_run") or state.get("released") is not True:
        raise RuntimeError(
            "AutoDL state still owns an unreleased instance; refusing another rental"
        )
    provider_state = state["provider_state"]
    resume_count = _manifest_resume_count(state_path)
    if (
        resume_count is not None
        and provider_state.get("created_for_resume_count") == resume_count
    ):
        raise RuntimeError(
            "A replacement AutoDL instance was already created for this manual resume"
        )
    history = provider_state.get("instance_history", [])
    if not isinstance(history, list):
        raise RuntimeError("AutoDL instance history has an invalid structure")
    archived = {
        name: provider_state[name]
        for name in ("instance_uuid", "gpu_spec_uuid", "gpu_count", "image_uuid")
        if name in provider_state
    }
    if isinstance(provider_state.get("cloud_drive"), dict):
        archived["cloud_drive"] = provider_state["cloud_drive"]
    if "created_for_resume_count" in provider_state:
        archived["created_for_resume_count"] = provider_state[
            "created_for_resume_count"
        ]
    archived["released_at_unix"] = state.get("released_at_unix")
    return [*history, archived], resume_count


def create_instance(args: argparse.Namespace) -> None:
    history: list[dict[str, Any]] = []
    resume_count = _manifest_resume_count(args.state)
    if args.state.exists():
        history, resume_count = _history_from_released_state(
            load_state(args.state), args.state
        )
    for gpu_spec in (args.gpu_spec, args.fallback_gpu_spec):
        if gpu_spec and gpu_spec not in SUPPORTED_GPU_SPECS:
            choices = ", ".join(sorted(SUPPORTED_GPU_SPECS))
            raise RuntimeError(
                "Unsupported AutoDL Pro GPU specification: "
                f"{gpu_spec}; choose one of {choices}"
            )
    if args.fallback_gpu_spec == args.gpu_spec:
        raise RuntimeError("AutoDL fallback GPU specification must differ from --gpu-spec")
    if not 1 <= args.gpu_count <= 4:
        raise RuntimeError("AutoDL Pro GPU count must be between 1 and 4")
    image_uuid = (args.image_uuid or os.environ.get("AUTODL_IMAGE_UUID", "")).strip()
    if not image_uuid:
        raise RuntimeError("Configure AUTODL_IMAGE_UUID or pass --image-uuid")
    gpu_specs = [args.gpu_spec]
    if args.fallback_gpu_spec:
        gpu_specs.append(args.fallback_gpu_spec)
    for attempt, selected_gpu_spec in enumerate(gpu_specs):
        try:
            payload = request(
                "POST",
                "/api/v1/dev/instance/pro/create",
                {
                    "req_gpu_amount": args.gpu_count,
                    "expand_system_disk_by_gb": 0,
                    "gpu_spec_uuid": selected_gpu_spec,
                    "image_uuid": image_uuid,
                    "cuda_v_from": 118,
                    "instance_name": f"medai-{int(time.time())}",
                    "start_command": "sleep 1",
                },
            )
            break
        except RuntimeError as exc:
            if attempt == 0 and len(gpu_specs) == 2 and any(
                marker in str(exc).lower() for marker in NO_INVENTORY_MARKERS
            ):
                continue
            raise
    instance_uuid = str(payload["data"])
    provider_state: dict[str, Any] = {
        "instance_uuid": instance_uuid,
        "gpu_spec_uuid": selected_gpu_spec,
        "gpu_count": args.gpu_count,
        "image_uuid": image_uuid,
    }
    if history:
        provider_state["instance_history"] = history
    if resume_count is not None:
        provider_state["created_for_resume_count"] = resume_count
    save_state(
        args.state,
        {
            "provider": "autodl",
            "created_by_run": True,
            "released": False,
            "provider_state": provider_state,
        },
    )
    deadline = time.monotonic() + 600
    status = ""
    while time.monotonic() < deadline:
        status = str(
            request(
                "GET",
                "/api/v1/dev/instance/pro/status",
                {"instance_uuid": instance_uuid},
            )["data"]
        )
        if status == "running":
            break
        time.sleep(10)
    if status != "running":
        raise RuntimeError(f"AutoDL instance did not start; last status={status}")
    print(instance_uuid)


def _ssh_command(
    state: dict[str, Any], action: str, arguments: list[str]
) -> subprocess.CompletedProcess[str]:
    if state.get("released") is True:
        raise RuntimeError("AutoDL instance has already been released")
    details = snapshot(state)
    required = ("proxy_host", "ssh_port")
    if any(not details.get(name) for name in required):
        raise RuntimeError("AutoDL snapshot is missing SSH connection details")
    command = [
        sys.executable,
        str(SSH_SCRIPT),
        "--host",
        str(details["proxy_host"]),
        "--port",
        str(details["ssh_port"]),
        "--user",
        "root",
        action,
        *arguments,
    ]
    environment = os.environ.copy()
    environment.pop("COMPUTATION_PROVIDER_SSH_PASSWORD", None)
    password = str(details.get("root_password") or "")
    if password:
        environment["COMPUTATION_PROVIDER_SSH_PASSWORD"] = password
    return subprocess.run(command, env=environment, capture_output=True, text=True)


def remote_exec(state: dict[str, Any], command: list[str]) -> str:
    completed = _ssh_command(state, "exec", ["--", *command])
    if completed.returncode != 0:
        for safe_error in (
            "Password SSH fallback requires sshpass",
            "SSH public-key authentication failed and no fallback password is available",
        ):
            if safe_error in completed.stderr:
                raise RuntimeError(f"AutoDL remote command failed: {safe_error}")
        raise RuntimeError("AutoDL remote command failed")
    return completed.stdout.strip()


def _panel_base(details: dict[str, Any]) -> tuple[str, str]:
    domain = str(details.get("jupyter_domain") or "").strip()
    token = str(details.get("jupyter_token") or "").strip()
    if not domain or not token:
        raise RuntimeError("AutoDL snapshot is missing AutoPanel access details")
    if "://" not in domain:
        domain = "https://" + domain
    parsed = urllib.parse.urlsplit(domain)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("AutoDL snapshot contains an invalid AutoPanel domain")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", "")), token


def _panel_request(
    *,
    base: str,
    panel_token: str,
    authorization: str | None,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> Any:
    url = base + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"AutodlAutoPanelToken": panel_token}
    if authorization:
        headers["Authorization"] = authorization
    if data is not None:
        headers["Content-Type"] = "application/json"
    http_request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(http_request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"AutoPanel request failed with HTTP {exc.code}") from exc
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError("AutoPanel request failed or returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"AutoPanel returned a non-object response at {path}"
        )
    response_code = payload.get("code")
    if str(response_code or "").casefold() != "success":
        safe_code = response_code if isinstance(response_code, (str, int)) else "unknown"
        raise RuntimeError(
            f"AutoPanel rejected the request at {path} (code={safe_code})"
        )
    if "data" not in payload:
        raise RuntimeError("AutoPanel returned an unsupported response structure")
    return payload["data"]


def _panel_login(details: dict[str, Any]) -> tuple[str, str, str]:
    password = os.environ.get("AUTODL_AUTOPANEL_PASSWORD", "").strip().strip("'\"")
    if not password:
        raise RuntimeError("AUTODL_AUTOPANEL_PASSWORD is not configured")
    base, panel_token = _panel_base(details)
    password_hash = hashlib.sha1(
        f"autodl{password}AutoDL".encode("utf-8")
    ).hexdigest()
    data = _panel_request(
        base=base,
        panel_token=panel_token,
        authorization=None,
        method="POST",
        path=PANEL_PATHS["sign_in"],
        body={"password": password_hash},
    )
    if isinstance(data, str) and data:
        authorization = data
    elif isinstance(data, dict) and isinstance(
        data.get("authorization") or data.get("token"), str
    ):
        authorization = str(data.get("authorization") or data.get("token"))
    else:
        raise RuntimeError("AutoPanel sign-in returned an unsupported response structure")
    if not authorization:
        raise RuntimeError("AutoPanel sign-in did not return a session")
    return base, panel_token, authorization


def _panel_list(data: Any, label: str) -> list[dict[str, Any]]:
    values = data
    if isinstance(data, dict):
        values = data.get("list", data.get("List"))
    if isinstance(values, dict):
        values = values.get("List")
    if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
        raise RuntimeError(f"AutoPanel {label} response has an unsupported structure")
    return values


def _binding_fsid(
    *, base: str, panel_token: str, authorization: str
) -> tuple[str, str, list[str]]:
    data = _panel_request(
        base=base,
        panel_token=panel_token,
        authorization=authorization,
        method="GET",
        path=PANEL_PATHS["bindings"],
    )
    bindings = _panel_list(data, "binding list")
    aliyun = []
    for binding in bindings:
        labels = {
            str(binding.get(name, "")).strip().casefold()
            for name in ("provider", "type", "name")
            if binding.get(name) is not None
        }
        if labels & ALIYUN_LABELS:
            aliyun.append(binding)
    if len(aliyun) != 1:
        raise RuntimeError("AutoPanel must expose exactly one explicit Aliyun binding")
    binding = aliyun[0]
    fsid = binding.get("fsid", binding.get("fs_id"))
    binding_type = binding.get("type")
    user_info = binding.get("user_info")
    if (
        not isinstance(fsid, str)
        or not fsid
        or not isinstance(binding_type, str)
        or binding_type.casefold() not in ALIYUN_LABELS
        or not isinstance(user_info, dict)
    ):
        raise RuntimeError("AutoPanel Aliyun binding has an unsupported structure")
    drive_ids = []
    for name in ("default_drive_id", "resource_drive_id"):
        value = user_info.get(name)
        if isinstance(value, str) and value and value not in drive_ids:
            drive_ids.append(value)
    if not drive_ids:
        raise RuntimeError("AutoPanel Aliyun binding does not expose a usable drive")
    return fsid, binding_type, drive_ids


def _item_name(item: dict[str, Any]) -> str:
    value = item.get("name", item.get("file_name", item.get("Name")))
    if not isinstance(value, str) or not value:
        raise RuntimeError("AutoPanel file entry is missing a name")
    return value


def _item_id(item: dict[str, Any]) -> str:
    value = item.get("file_id", item.get("id", item.get("FileId")))
    if not isinstance(value, str) or not value:
        raise RuntimeError("AutoPanel file entry is missing a file identifier")
    return value


def _item_is_dir(item: dict[str, Any]) -> bool:
    value = item.get("is_dir")
    if isinstance(value, bool):
        return value
    kind = item.get("type", item.get("file_type"))
    if isinstance(kind, str) and kind.casefold() in {"dir", "folder", "directory"}:
        return True
    if isinstance(kind, str) and kind.casefold() in {"file", "regular"}:
        return False
    raise RuntimeError("AutoPanel file entry does not explicitly identify its type")


def _item_size(item: dict[str, Any]) -> int:
    value = item.get("file_size", item.get("size", item.get("Size")))
    if isinstance(value, bool):
        raise RuntimeError("AutoPanel file entry has an invalid size")
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("AutoPanel file entry has an invalid size") from exc
    if size < 0:
        raise RuntimeError("AutoPanel file entry has an invalid size")
    return size


def _list_directory(
    *,
    base: str,
    panel_token: str,
    authorization: str,
    fsid: str,
    drive_id: str,
    directory_id: str,
) -> list[dict[str, Any]]:
    marker = ""
    entries: list[dict[str, Any]] = []
    seen_markers: set[str] = set()
    while True:
        data = _panel_request(
            base=base,
            panel_token=panel_token,
            authorization=authorization,
            method="GET",
            path=PANEL_PATHS["files"],
            query={
                "fs_id": fsid,
                "driver_id": drive_id,
                "file_id": directory_id,
                "marker": marker,
            },
        )
        entries.extend(_panel_list(data, "file list"))
        if isinstance(data, dict):
            next_marker = data.get("next_marker", data.get("NextMarker", ""))
        else:
            next_marker = ""
        if next_marker in (None, ""):
            return entries
        if not isinstance(next_marker, str) or next_marker in seen_markers:
            raise RuntimeError("AutoPanel file pagination has an unsupported structure")
        seen_markers.add(next_marker)
        marker = next_marker


def _find_directory(
    *,
    components: list[str],
    root_id: str,
    list_directory: Any,
) -> dict[str, Any] | None:
    current_id = root_id
    current: dict[str, Any] | None = None
    for component in components:
        matches = [
            item
            for item in list_directory(current_id)
            if _item_name(item) == component and _item_is_dir(item)
        ]
        if not matches:
            return None
        if len(matches) != 1:
            raise RuntimeError(
                "Aliyun source directory is missing or ambiguous: "
                + "/".join(components)
            )
        current = matches[0]
        current_id = _item_id(current)
    return current


def _inventory_tree(directory_id: str, list_directory: Any) -> tuple[int, int]:
    files = 0
    total_bytes = 0
    pending = [directory_id]
    while pending:
        current_id = pending.pop()
        for item in list_directory(current_id):
            if _item_is_dir(item):
                pending.append(_item_id(item))
            else:
                files += 1
                total_bytes += _item_size(item)
    return files, total_bytes


def _remote_free_bytes(state: dict[str, Any]) -> int:
    output = remote_exec(state, ["df", "-PB1", "/root/autodl-tmp"])
    lines = [line for line in output.splitlines() if line.strip()]
    try:
        return int(lines[-1].split()[3])
    except (IndexError, ValueError) as exc:
        raise RuntimeError("Could not parse AutoDL data-disk capacity") from exc


def _remote_inventory(state: dict[str, Any], path: str) -> tuple[int, int]:
    program = (
        'if [[ ! -d "$1" ]]; then printf "missing\\n"; exit 0; fi\n'
        "LC_ALL=C find -- \"$1\" -type f -printf '%s\\n' | "
        "awk '{ count += 1; total += $1 } "
        "END { printf \"%.0f %.0f\\n\", count, total }'"
    )
    output = remote_exec(state, ["bash", "-lc", program, "medai-inventory", path])
    if output == "missing":
        return -1, -1
    try:
        count_text, bytes_text = output.split()
        return int(count_text), int(bytes_text)
    except ValueError as exc:
        raise RuntimeError("Could not parse the AutoDL dataset inventory") from exc


def _update_cloud(
    state_path: Path, state: dict[str, Any], cloud: dict[str, Any], status: str
) -> None:
    cloud["status"] = status
    cloud["updated_at_unix"] = int(time.time())
    state["provider_state"]["cloud_drive"] = cloud
    save_state(state_path, state)


def _task_lists(
    data: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(data, dict):
        raise RuntimeError("AutoPanel task response has an unsupported structure")
    pre = data.get("task_pre")
    doing = data.get("task_doing")
    done = data.get("task_done")
    if not isinstance(pre, list) or not isinstance(doing, list) or not isinstance(done, list):
        raise RuntimeError("AutoPanel task response has an unsupported structure")
    if not all(isinstance(item, dict) for item in [*pre, *doing, *done]):
        raise RuntimeError("AutoPanel task response has an unsupported structure")
    return pre, doing, done


def _read_tasks(
    *,
    base: str,
    panel_token: str,
    authorization: str,
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    request_limit = max(limit, 20)
    for _ in range(2):
        data = _panel_request(
            base=base,
            panel_token=panel_token,
            authorization=authorization,
            method="GET",
            path=PANEL_PATHS["tasks"],
            query={"limit": request_limit},
        )
        task_lists = _task_lists(data)
        total = data.get("task_total") if isinstance(data, dict) else None
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            break
        observed = sum(len(items) for items in task_lists)
        if total == observed:
            return task_lists
        if total > request_limit:
            request_limit = total
            continue
        break
    raise RuntimeError("AutoPanel task totals have an unsupported structure")


def _discover_download_task_ids(
    *,
    base: str,
    panel_token: str,
    authorization: str,
    fsid: str,
    drive_id: str,
    staging_path: str,
    excluded_task_ids: set[str],
    expected_file_count: int,
    expected_total_bytes: int,
    timeout_seconds: int = 60,
) -> list[str]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        task_lists = _read_tasks(
            base=base,
            panel_token=panel_token,
            authorization=authorization,
            limit=expected_file_count,
        )
        tasks = [item for items in task_lists for item in items]
        new_tasks = [
            item
            for item in tasks
            if str(item.get("task_id") or "") not in excluded_task_ids
        ]
        matches = [
            item
            for item in new_tasks
            if str(item.get("task_type")) == "2"
            and item.get("fsid") == fsid
            and item.get("drive_id") == drive_id
            and (
                item.get("dst_path") == staging_path
                or str(item.get("dst_path") or "").startswith(staging_path + "/")
            )
        ]
        if len(matches) == expected_file_count:
            if len(matches) != len(new_tasks):
                raise RuntimeError(
                    "AutoPanel contains unrelated transfer tasks during cloud pull"
                )
            if sum(_item_size(item) for item in matches) != expected_total_bytes:
                raise RuntimeError(
                    "AutoPanel download task bytes do not match the Aliyun inventory"
                )
            task_ids = [str(item.get("task_id") or "") for item in matches]
            if any(not task_id for task_id in task_ids) or len(set(task_ids)) != len(
                task_ids
            ):
                raise RuntimeError(
                    "AutoPanel download tasks have invalid or duplicate identifiers"
                )
            return task_ids
        if new_tasks and (
            len(matches) != len(new_tasks) or len(matches) > expected_file_count
        ):
            raise RuntimeError(
                "AutoPanel contains unrelated transfer tasks during cloud pull"
            )
        time.sleep(2)
    raise RuntimeError("AutoPanel did not expose the queued download tasks")


def _poll_download(
    *,
    base: str,
    panel_token: str,
    authorization: str,
    task_ids: list[str],
    expected_file_count: int,
    timeout_seconds: int,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    expected_ids = set(task_ids)
    if len(expected_ids) != expected_file_count:
        raise RuntimeError("AutoPanel download task state is incomplete")
    while time.monotonic() < deadline:
        pre, doing, done = _read_tasks(
            base=base,
            panel_token=panel_token,
            authorization=authorization,
            limit=expected_file_count,
        )
        active_ids = {
            str(item.get("task_id") or "")
            for item in [*pre, *doing]
            if str(item.get("task_id") or "") in expected_ids
        }
        done_by_id = {
            str(item.get("task_id") or ""): item
            for item in done
            if str(item.get("task_id") or "") in expected_ids
        }
        observed_ids = active_ids | set(done_by_id)
        if observed_ids != expected_ids:
            raise RuntimeError("AutoPanel download task batch changed during polling")
        terminal_statuses = {
            str(item.get("status", "")).casefold() for item in done_by_id.values()
        }
        if terminal_statuses - {
            "success",
            "completed",
            "finished",
            "failed",
            "error",
            "cancel",
            "cancelled",
            "canceled",
        }:
            raise RuntimeError("AutoPanel download task has an unknown terminal status")
        if terminal_statuses & {
            "failed",
            "error",
            "cancel",
            "cancelled",
            "canceled",
        }:
            return "failed"
        if set(done_by_id) == expected_ids:
            return "completed"
        if active_ids:
            time.sleep(5)
            continue
        raise RuntimeError("AutoPanel download task batch disappeared before completion")
    return "timeout"


def _timeout_seconds() -> int:
    value = os.environ.get("AUTODL_CLOUDDRIVE_TIMEOUT_SECONDS", "1800").strip().strip(
        "'\""
    )
    try:
        seconds = int(value)
    except ValueError as exc:
        raise RuntimeError(
            "AUTODL_CLOUDDRIVE_TIMEOUT_SECONDS must be a positive integer"
        ) from exc
    if seconds <= 0:
        raise RuntimeError("AUTODL_CLOUDDRIVE_TIMEOUT_SECONDS must be a positive integer")
    return seconds


def _controlled_cleanup(state: dict[str, Any], cloud: dict[str, Any]) -> None:
    if cloud.get("owned_paths") is not True:
        raise RuntimeError("Cloud-drive retry cannot prove ownership of partial paths")
    dataset = str(cloud.get("dataset") or "")
    expected = (
        f"/root/autodl-tmp/{dataset}",
        f"/root/autodl-tmp/medai/{dataset}",
    )
    actual = (cloud.get("staging_path"), cloud.get("target_path"))
    if actual != expected:
        raise RuntimeError("Cloud-drive retry state contains unexpected cleanup paths")
    remote_exec(state, ["rm", "-rf", "--", *expected])


def cloud_pull(args: argparse.Namespace) -> None:
    dataset = args.dataset.strip()
    if (
        not dataset
        or dataset in {".", ".."}
        or any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for character in dataset
        )
        or not dataset[0].isalnum()
        or len(dataset) > 128
    ):
        raise RuntimeError("cloud-pull requires one safe dataset directory name")
    provider = os.environ.get("MEDAI_DRIVE_PROVIDER", "aliyun").strip().strip("'\"").casefold()
    if provider != "aliyun":
        raise RuntimeError("MEDAI_DRIVE_PROVIDER must be 'aliyun'")
    state = load_state(args.state)
    details = snapshot(state)
    base, panel_token, authorization = _panel_login(details)
    fsid, binding_type, drive_ids = _binding_fsid(
        base=base, panel_token=panel_token, authorization=authorization
    )
    source_path = f"medai/{dataset}"
    staging_path = f"/root/autodl-tmp/{dataset}"
    target_path = f"/root/autodl-tmp/medai/{dataset}"
    sources: list[
        tuple[str, dict[str, Any], Callable[[str], list[dict[str, Any]]]]
    ] = []
    for drive_id in drive_ids:
        def list_drive_directory(
            directory_id: str, *, selected_drive: str = drive_id
        ) -> list[dict[str, Any]]:
            return _list_directory(
                base=base,
                panel_token=panel_token,
                authorization=authorization,
                fsid=fsid,
                drive_id=selected_drive,
                directory_id=directory_id,
            )

        source = _find_directory(
            components=["medai", dataset],
            root_id="/",
            list_directory=list_drive_directory,
        )
        if source is None:
            continue
        sources.append((drive_id, source, list_drive_directory))
    if len(sources) != 1:
        raise RuntimeError(
            f"Aliyun source directory is missing or ambiguous: {source_path}"
        )
    drive_id, source, list_directory = sources[0]
    file_count, total_bytes = _inventory_tree(_item_id(source), list_directory)
    prior = state["provider_state"].get("cloud_drive")
    if prior is not None and not isinstance(prior, dict):
        raise RuntimeError("AutoDL cloud-drive state has an invalid structure")
    if prior and (
        prior.get("provider") != "aliyun" or prior.get("dataset") != dataset
    ):
        raise RuntimeError("AutoDL instance state belongs to a different cloud dataset")
    is_new = not prior
    if prior:
        cloud = prior
        if (
            cloud.get("remote_file_count") != file_count
            or cloud.get("remote_total_bytes") != total_bytes
        ):
            raise RuntimeError("Aliyun dataset inventory changed during this run")
    else:
        cloud = {
            "provider": "aliyun",
            "dataset": dataset,
            "source_path": source_path,
            "staging_path": staging_path,
            "target_path": target_path,
            "owned_paths": True,
            "started_at_unix": int(time.time()),
            "remote_file_count": file_count,
            "remote_total_bytes": total_bytes,
        }
        _update_cloud(args.state, state, cloud, "located")

    local_count, local_bytes = _remote_inventory(state, target_path)
    if (local_count, local_bytes) == (file_count, total_bytes):
        remote_exec(state, ["chmod", "-R", "a-w", "--", target_path])
        cloud["local_file_count"] = local_count
        cloud["local_total_bytes"] = local_bytes
        cloud["completed_at_unix"] = int(time.time())
        _update_cloud(args.state, state, cloud, "completed")
        print(target_path)
        return
    if not is_new and cloud.get("status") == "failed":
        _controlled_cleanup(state, cloud)

    ready_to_finalize = cloud.get("status") == "verifying"
    if not ready_to_finalize:
        raw_task_ids = cloud.get("task_ids")
        if raw_task_ids is not None and (
            not isinstance(raw_task_ids, list)
            or len(raw_task_ids) != file_count
            or not all(isinstance(value, str) and value for value in raw_task_ids)
            or len(set(raw_task_ids)) != len(raw_task_ids)
        ):
            raise RuntimeError("AutoDL cloud-drive task state has an invalid structure")
        task_ids = raw_task_ids or []
        if not task_ids:
            prior_task_ids = cloud.get("preexisting_task_ids")
            should_post = False
            if cloud.get("status") == "enqueueing":
                if not isinstance(prior_task_ids, list) or not all(
                    isinstance(value, str) and value for value in prior_task_ids
                ) or len(set(prior_task_ids)) != len(prior_task_ids):
                    raise RuntimeError(
                        "AutoDL enqueue recovery state has an invalid structure"
                    )
            else:
                free_bytes = _remote_free_bytes(state)
                if free_bytes < total_bytes:
                    cloud["available_bytes"] = free_bytes
                    _update_cloud(args.state, state, cloud, "failed")
                    raise RuntimeError("AutoDL data disk does not have enough free space")
                task_lists = _read_tasks(
                    base=base,
                    panel_token=panel_token,
                    authorization=authorization,
                    limit=file_count,
                )
                prior_task_ids = sorted(
                    str(item.get("task_id") or "")
                    for items in task_lists
                    for item in items
                )
                if any(not value for value in prior_task_ids) or len(
                    set(prior_task_ids)
                ) != len(prior_task_ids):
                    raise RuntimeError("AutoPanel task history has invalid identifiers")
                cloud["preexisting_task_ids"] = prior_task_ids
                cloud["post_requested"] = True
                _update_cloud(args.state, state, cloud, "enqueueing")
                should_post = True

            download_body = {
                "dst_path": "",
                "fsid": fsid,
                "src_path": "/" + source_path + "/",
                "file_id": _item_id(source),
                "is_dir": True,
                "download_url": str(source.get("download_url") or ""),
                "file_size": _item_size(source),
            }
            if binding_type == "AutoDL_AliPan":
                download_body["drive_id"] = drive_id
            if (
                cloud.get("status") != "enqueueing"
                or cloud.get("post_requested") is not True
                or "preexisting_task_ids" not in cloud
            ):
                raise RuntimeError("AutoDL cloud-drive enqueue state changed unexpectedly")
            if should_post:
                try:
                    _panel_request(
                        base=base,
                        panel_token=panel_token,
                        authorization=authorization,
                        method="POST",
                        path=PANEL_PATHS["download"],
                        body=download_body,
                    )
                except RuntimeError:
                    cloud.pop("preexisting_task_ids", None)
                    cloud.pop("post_requested", None)
                    _update_cloud(args.state, state, cloud, "failed")
                    raise

            if file_count == 0:
                cloud.pop("preexisting_task_ids", None)
                cloud.pop("post_requested", None)
                _update_cloud(args.state, state, cloud, "verifying")
                ready_to_finalize = True
            else:
                task_ids = _discover_download_task_ids(
                    base=base,
                    panel_token=panel_token,
                    authorization=authorization,
                    fsid=fsid,
                    drive_id=drive_id,
                    staging_path=staging_path,
                    excluded_task_ids=set(prior_task_ids),
                    expected_file_count=file_count,
                    expected_total_bytes=total_bytes,
                )
                cloud["task_ids"] = task_ids
                cloud.pop("preexisting_task_ids", None)
                cloud.pop("post_requested", None)
                _update_cloud(args.state, state, cloud, "downloading")

        if not ready_to_finalize:
            task_status = _poll_download(
                base=base,
                panel_token=panel_token,
                authorization=authorization,
                task_ids=task_ids,
                expected_file_count=file_count,
                timeout_seconds=_timeout_seconds(),
            )
            if task_status == "timeout":
                _update_cloud(args.state, state, cloud, "timed_out")
                raise RuntimeError("AutoPanel cloud-drive download timed out")
            if task_status == "failed":
                cloud.pop("task_ids", None)
                _update_cloud(args.state, state, cloud, "failed")
                raise RuntimeError("AutoPanel cloud-drive download task failed")

            cloud.pop("task_ids", None)
            _update_cloud(args.state, state, cloud, "verifying")
    staging_inventory = _remote_inventory(state, staging_path)
    if staging_inventory != (file_count, total_bytes):
        _update_cloud(args.state, state, cloud, "failed")
        raise RuntimeError("Cloud-drive staging inventory does not match Aliyun")
    remote_exec(state, ["mkdir", "-p", "/root/autodl-tmp/medai"])
    remote_exec(state, ["test", "!", "-e", target_path])
    remote_exec(state, ["mv", "--", staging_path, target_path])
    final_inventory = _remote_inventory(state, target_path)
    if final_inventory != (file_count, total_bytes):
        _update_cloud(args.state, state, cloud, "failed")
        raise RuntimeError("Materialized cloud dataset does not match Aliyun")
    remote_exec(state, ["chmod", "-R", "a-w", "--", target_path])
    cloud["local_file_count"], cloud["local_total_bytes"] = final_inventory
    cloud["completed_at_unix"] = int(time.time())
    _update_cloud(args.state, state, cloud, "completed")
    print(target_path)


def release_instance(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    if not state.get("created_by_run"):
        raise RuntimeError("Refusing to release an instance not created by this run")
    if state.get("released") is True:
        return
    try:
        request(
            "POST",
            "/api/v1/dev/instance/pro/power_off",
            {"instance_uuid": state["provider_state"]["instance_uuid"]},
        )
    except RuntimeError as exc:
        if "当前实例已关机" not in str(exc):
            raise
    deadline = time.monotonic() + 90
    status = ""
    while time.monotonic() < deadline:
        status = str(
            request(
                "GET",
                "/api/v1/dev/instance/pro/status",
                {"instance_uuid": state["provider_state"]["instance_uuid"]},
            )["data"]
        )
        if status == "shutdown":
            break
        time.sleep(5)
    if status != "shutdown":
        raise RuntimeError(
            "AutoDL instance did not reach shutdown before release; "
            f"last status={status}"
        )
    request(
        "POST",
        "/api/v1/dev/instance/pro/release",
        {"instance_uuid": state["provider_state"]["instance_uuid"]},
    )
    state["released"] = True
    state["released_at_unix"] = int(time.time())
    save_state(args.state, state)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--gpu-spec", required=True)
    create.add_argument(
        "--fallback-gpu-spec",
        help="One stronger eligible Pro GPU to try only when --gpu-spec is out of inventory.",
    )
    create.add_argument("--gpu-count", type=int, default=1)
    create.add_argument(
        "--image-uuid",
        help="Paper-specific image UUID; overrides the AUTODL_IMAGE_UUID default.",
    )
    create.add_argument("--state", type=Path, required=True)
    for name in ("status", "release"):
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
    if args.action == "create":
        create_instance(args)
    elif args.action == "status":
        state = load_state(args.state)
        print(
            request(
                "GET",
                "/api/v1/dev/instance/pro/status",
                {"instance_uuid": state["provider_state"]["instance_uuid"]},
            )["data"]
        )
    elif args.action == "release":
        release_instance(args)
    elif args.action == "cloud-pull":
        cloud_pull(args)
    else:
        state = load_state(args.state)
        if args.action == "exec":
            command_parts = args.command[1:] if args.command[:1] == ["--"] else args.command
            if not command_parts:
                raise RuntimeError("exec requires a command")
            arguments = ["--", *command_parts]
        elif args.action == "upload":
            arguments = ["--source", str(args.source), "--remote", args.remote]
        else:
            arguments = [
                "--remote",
                args.remote,
                "--destination",
                str(args.destination),
            ]
        completed = _ssh_command(state, args.action, arguments)
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        return completed.returncode
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
