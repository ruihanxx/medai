#!/usr/bin/env python3
"""Inspect and operate AutoDL Container Instance Pro instances."""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name] = value
    return values


def request(
    base_url: str, token: str, method: str, path: str, payload: dict[str, object]
) -> dict[str, object]:
    url = base_url + path
    data = json.dumps(payload).encode("utf-8")
    headers = {"Authorization": token, "Content-Type": "application/json"}
    if method == "GET":
        url += "?" + urllib.parse.urlencode(payload)
        data = None
        headers.pop("Content-Type")
    http_request = urllib.request.Request(
        url, data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(http_request, timeout=30) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").replace(
            token, "[REDACTED]"
        )
        raise SystemExit(f"AutoDL HTTP {exc.code}: {detail}") from exc
    except OSError as exc:
        raise SystemExit(f"AutoDL request failed: {exc}") from exc
    if response_payload.get("code") != "Success":
        message = str(response_payload.get("msg") or response_payload).replace(
            token, "[REDACTED]"
        )
        raise SystemExit(f"AutoDL API error: {message}")
    return response_payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".env",
        help="dotenv file containing AUTODL_TOKEN (default: repository-root .env)",
    )
    commands = parser.add_subparsers(dest="command")
    list_command = commands.add_parser("list", help="list existing Pro instances")
    list_command.add_argument("--page-index", type=int, default=1)
    list_command.add_argument("--page-size", type=int, default=100)
    for name, help_text in (
        ("power-on", "start an existing instance"),
        ("power-off", "stop an existing instance"),
        ("release", "release a shutdown instance permanently"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("instance_uuid", help="AutoDL Pro instance UUID")
    args = parser.parse_args()
    command = args.command or "list"
    if command == "list" and (
        getattr(args, "page_index", 1) < 1 or getattr(args, "page_size", 100) < 1
    ):
        raise SystemExit("--page-index and --page-size must be positive")

    try:
        values = load_dotenv(args.env_file)
    except OSError as exc:
        raise SystemExit(f"Cannot read dotenv file: {args.env_file}: {exc}") from exc
    token = values.get("AUTODL_TOKEN", "")
    if not token:
        raise SystemExit(f"AUTODL_TOKEN is missing from {args.env_file}")
    base_url = values.get("AUTODL_API_BASE_URL", "https://api.autodl.com").rstrip(
        "/"
    )
    if not base_url:
        base_url = "https://api.autodl.com"

    if command == "list":
        payload = request(
            base_url,
            token,
            "POST",
            "/api/v1/dev/instance/pro/list",
            {
                "page_index": getattr(args, "page_index", 1),
                "page_size": getattr(args, "page_size", 100),
            },
        )
    elif command == "power-on":
        payload = request(
            base_url,
            token,
            "POST",
            "/api/v1/dev/instance/pro/power_on",
            {
                "instance_uuid": args.instance_uuid,
                "payload": "gpu",
                "start_command": "sleep 1",
            },
        )
    elif command == "power-off":
        payload = request(
            base_url,
            token,
            "POST",
            "/api/v1/dev/instance/pro/power_off",
            {"instance_uuid": args.instance_uuid},
        )
    else:
        status = request(
            base_url,
            token,
            "GET",
            "/api/v1/dev/instance/pro/status",
            {"instance_uuid": args.instance_uuid},
        )
        if status.get("data") != "shutdown":
            raise SystemExit(
                "Refusing release unless the instance status is shutdown; "
                f"current status={status.get('data')!r}"
            )
        payload = request(
            base_url,
            token,
            "POST",
            "/api/v1/dev/instance/pro/release",
            {"instance_uuid": args.instance_uuid},
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
