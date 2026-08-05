from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BASE_URL = os.environ.get("AUTODL_API_BASE_URL", "https://api.autodl.com").rstrip("/")
TOKEN = os.environ.get("AUTODL_TOKEN", "")
SUPPORTED_GPU_SPECS = {
    "h800",
    "v-48g",
    "pro6000-p",
    "v-32g-p",
    "v-48g-350w",
    "5090-p",
    "4090D",
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
    http_request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(http_request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AutoDL HTTP {exc.code}: {detail}") from exc
    if payload.get("code") != "Success":
        raise RuntimeError(f"AutoDL API error: {payload.get('msg') or payload}")
    return payload


def load_state(path: Path) -> dict[str, Any]:
    state = json.loads(path.read_text(encoding="utf-8"))
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
    return payload["data"]


def ssh_prefix(details: dict[str, Any]) -> list[str]:
    password = str(details.get("root_password") or "")
    if password:
        sshpass = shutil.which("sshpass")
        if sshpass is None:
            raise RuntimeError("Password SSH requires sshpass")
        return [sshpass, "-p", password]
    return []


def create_instance(args: argparse.Namespace) -> None:
    if args.state.exists():
        raise SystemExit(
            f"AutoDL state already exists; inspect or release it before creating: {args.state}"
        )
    if args.gpu_spec not in SUPPORTED_GPU_SPECS:
        choices = ", ".join(sorted(SUPPORTED_GPU_SPECS))
        raise SystemExit(
            f"Unsupported AutoDL Pro GPU specification: {args.gpu_spec}; choose one of {choices}"
        )
    if not 1 <= args.gpu_count <= 4:
        raise SystemExit("AutoDL Pro GPU count must be between 1 and 4")
    image_uuid = (args.image_uuid or os.environ.get("AUTODL_IMAGE_UUID", "")).strip()
    if not image_uuid:
        raise SystemExit("Configure AUTODL_IMAGE_UUID or pass --image-uuid")
    payload = request(
        "POST",
        "/api/v1/dev/instance/pro/create",
        {
            "req_gpu_amount": args.gpu_count,
            "expand_system_disk_by_gb": 0,
            "gpu_spec_uuid": args.gpu_spec,
            "image_uuid": image_uuid,
            "cuda_v_from": 118,
            "instance_name": f"medai-{int(time.time())}",
            "start_command": "sleep 1",
        },
    )
    instance_uuid = str(payload["data"])
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.state.write_text(
        json.dumps(
            {
                "provider": "autodl",
                "created_by_run": True,
                "released": False,
                "provider_state": {
                    "instance_uuid": instance_uuid,
                    "gpu_spec_uuid": args.gpu_spec,
                    "gpu_count": args.gpu_count,
                    "image_uuid": image_uuid,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
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
        raise SystemExit(f"AutoDL instance did not start; last status={status}")
    print(instance_uuid)


parser = argparse.ArgumentParser()
subparsers = parser.add_subparsers(dest="action", required=True)

create = subparsers.add_parser("create")
create.add_argument("--gpu-spec", required=True)
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

args = parser.parse_args()

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
    state = load_state(args.state)
    if not state.get("created_by_run"):
        raise SystemExit("Refusing to release an instance not created by this run")
    request(
        "POST",
        "/api/v1/dev/instance/pro/power_off",
        {"instance_uuid": state["provider_state"]["instance_uuid"]},
    )
    request(
        "POST",
        "/api/v1/dev/instance/pro/release",
        {"instance_uuid": state["provider_state"]["instance_uuid"]},
    )
    state["released"] = True
    state["released_at_unix"] = int(time.time())
    args.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
elif args.action in {"exec", "upload", "download"}:
    state = load_state(args.state)
    details = snapshot(state)
    host = str(details["proxy_host"])
    port = str(details["ssh_port"])
    target = f"root@{host}"
    prefix = ssh_prefix(details)
    if args.action == "exec":
        command_parts = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command_parts:
            raise SystemExit("exec requires a command")
        remote_command = " ".join(shlex.quote(item) for item in command_parts)
        command = [
            *prefix,
            "ssh",
            "-p",
            port,
            "-o",
            "StrictHostKeyChecking=accept-new",
            target,
            remote_command,
        ]
    elif args.action == "upload":
        command = [
            *prefix,
            "scp",
            "-rP",
            port,
            "-o",
            "StrictHostKeyChecking=accept-new",
            str(args.source),
            f"{target}:{args.remote}",
        ]
    else:
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        command = [
            *prefix,
            "scp",
            "-rP",
            port,
            "-o",
            "StrictHostKeyChecking=accept-new",
            f"{target}:{args.remote}",
            str(args.destination),
        ]
    raise SystemExit(subprocess.run(command).returncode)
