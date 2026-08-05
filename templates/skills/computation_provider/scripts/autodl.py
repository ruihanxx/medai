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
from typing import Any

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
ALIYUN_LABELS = {"aliyun", "aliyundrive", "alipan", "阿里云盘"}


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
    authorization: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> Any:
    url = base + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "Autodl-Autopanel-Token": panel_token,
        "Authorization": authorization,
    }
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
    if not isinstance(payload, dict) or str(payload.get("code", "")).casefold() != "success":
        raise RuntimeError("AutoPanel rejected the request")
    if "data" not in payload:
        raise RuntimeError("AutoPanel returned an unsupported response structure")
    return payload["data"]


def _panel_login(details: dict[str, Any]) -> tuple[str, str, str]:
    password = os.environ.get("AUTODL_AUTOPANEL_PASSWORD", "").strip().strip("'\"")
    if not password:
        raise RuntimeError("AUTODL_AUTOPANEL_PASSWORD is not configured")
    base, panel_token = _panel_base(details)
    password_hash = hashlib.sha1(password.encode("utf-8")).hexdigest()
    data = _panel_request(
        base=base,
        panel_token=panel_token,
        authorization="null",
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
    if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
        raise RuntimeError(f"AutoPanel {label} response has an unsupported structure")
    return values


def _binding_fsid(
    *, base: str, panel_token: str, authorization: str
) -> tuple[str, str]:
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
    root_id = binding.get("root_file_id", binding.get("root_id", "root"))
    if not isinstance(fsid, str) or not fsid or not isinstance(root_id, str) or not root_id:
        raise RuntimeError("AutoPanel Aliyun binding has an unsupported structure")
    return fsid, root_id


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
            query={"fs_id": fsid, "file_id": directory_id, "marker": marker},
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
) -> dict[str, Any]:
    current_id = root_id
    current: dict[str, Any] | None = None
    for component in components:
        matches = [
            item
            for item in list_directory(current_id)
            if _item_name(item) == component and _item_is_dir(item)
        ]
        if len(matches) != 1:
            raise RuntimeError(
                "Aliyun source directory is missing or ambiguous: "
                + "/".join(components)
            )
        current = matches[0]
        current_id = _item_id(current)
    assert current is not None
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
        "import os,sys\n"
        "path=sys.argv[1]\n"
        "if not os.path.isdir(path): print('missing'); raise SystemExit(0)\n"
        "n=s=0\n"
        "for root,_,files in os.walk(path):\n"
        "  for name in files:\n"
        "    n+=1; s+=os.path.getsize(os.path.join(root,name))\n"
        "print(n,s)"
    )
    output = remote_exec(state, ["python3", "-c", program, path])
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


def _task_id(data: Any) -> str:
    if isinstance(data, str) and data:
        return data
    if isinstance(data, dict):
        value = data.get("task_id", data.get("id"))
        if isinstance(value, str) and value:
            return value
    raise RuntimeError("AutoPanel download returned an unsupported task structure")


def _task_lists(data: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(data, dict):
        raise RuntimeError("AutoPanel task response has an unsupported structure")
    doing = data.get("task_doing")
    done = data.get("task_done")
    if not isinstance(doing, list) or not isinstance(done, list):
        raise RuntimeError("AutoPanel task response has an unsupported structure")
    if not all(isinstance(item, dict) for item in [*doing, *done]):
        raise RuntimeError("AutoPanel task response has an unsupported structure")
    return doing, done


def _matching_task(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any] | None:
    matches = [
        item
        for item in tasks
        if str(item.get("task_id", item.get("id", ""))) == task_id
    ]
    if len(matches) > 1:
        raise RuntimeError("AutoPanel returned duplicate download task identifiers")
    return matches[0] if matches else None


def _poll_download(
    *,
    base: str,
    panel_token: str,
    authorization: str,
    task_id: str,
    timeout_seconds: int,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    observed = False
    while time.monotonic() < deadline:
        data = _panel_request(
            base=base,
            panel_token=panel_token,
            authorization=authorization,
            method="GET",
            path=PANEL_PATHS["tasks"],
            query={"limit": 20},
        )
        doing, done = _task_lists(data)
        if _matching_task(doing, task_id) is not None:
            observed = True
            time.sleep(5)
            continue
        finished = _matching_task(done, task_id)
        if finished is not None:
            status = str(finished.get("status", "")).casefold()
            if status in {"success", "completed", "finished"}:
                return "completed"
            if status in {"failed", "error", "cancelled", "canceled"}:
                return "failed"
            raise RuntimeError("AutoPanel download task has an unknown terminal status")
        if observed:
            raise RuntimeError("AutoPanel download task disappeared before completion")
        time.sleep(2)
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
    fsid, root_id = _binding_fsid(
        base=base, panel_token=panel_token, authorization=authorization
    )
    def list_directory(directory_id: str) -> list[dict[str, Any]]:
        return _list_directory(
            base=base,
            panel_token=panel_token,
            authorization=authorization,
            fsid=fsid,
            directory_id=directory_id,
        )
    source_path = f"medai/{dataset}"
    staging_path = f"/root/autodl-tmp/{dataset}"
    target_path = f"/root/autodl-tmp/medai/{dataset}"
    source = _find_directory(
        components=["medai", dataset], root_id=root_id, list_directory=list_directory
    )
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
    if not is_new and cloud.get("status") in {"failed", "locating", "located"}:
        _controlled_cleanup(state, cloud)

    ready_to_finalize = cloud.get("status") == "verifying"
    if not ready_to_finalize:
        free_bytes = _remote_free_bytes(state)
        if free_bytes < total_bytes:
            cloud["available_bytes"] = free_bytes
            _update_cloud(args.state, state, cloud, "failed")
            raise RuntimeError("AutoDL data disk does not have enough free space")

        task_id = cloud.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            download_data = _panel_request(
                base=base,
                panel_token=panel_token,
                authorization=authorization,
                method="POST",
                path=PANEL_PATHS["download"],
                body={
                    "dst_path": "",
                    "fsid": fsid,
                    "src_path": source_path + "/",
                    "file_id": _item_id(source),
                    "is_dir": True,
                    "download_url": str(source.get("download_url") or ""),
                    "file_size": total_bytes,
                },
            )
            task_id = _task_id(download_data)
            cloud["task_id"] = task_id
            _update_cloud(args.state, state, cloud, "downloading")

        task_status = _poll_download(
            base=base,
            panel_token=panel_token,
            authorization=authorization,
            task_id=task_id,
            timeout_seconds=_timeout_seconds(),
        )
        if task_status == "timeout":
            _update_cloud(args.state, state, cloud, "timed_out")
            raise RuntimeError("AutoPanel cloud-drive download timed out")
        if task_status == "failed":
            cloud.pop("task_id", None)
            _update_cloud(args.state, state, cloud, "failed")
            raise RuntimeError("AutoPanel cloud-drive download task failed")

        cloud.pop("task_id", None)
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
