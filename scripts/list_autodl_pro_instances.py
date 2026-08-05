#!/usr/bin/env python3
"""List AutoDL Container Instance Pro instances configured in a local dotenv file."""
from __future__ import annotations

import argparse
import json
import urllib.error
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".env",
        help="dotenv file containing AUTODL_TOKEN (default: repository-root .env)",
    )
    parser.add_argument("--page-index", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args()
    if args.page_index < 1 or args.page_size < 1:
        raise SystemExit("--page-index and --page-size must be positive")

    try:
        values = load_dotenv(args.env_file)
    except OSError as exc:
        raise SystemExit(f"Cannot read dotenv file: {args.env_file}: {exc}") from exc
    token = values.get("AUTODL_TOKEN", "")
    if not token:
        raise SystemExit(f"AUTODL_TOKEN is missing from {args.env_file}")
    base_url = values.get("AUTODL_API_BASE_URL", "https://api.autodl.com").rstrip("/")
    if not base_url:
        base_url = "https://api.autodl.com"
    request = urllib.request.Request(
        base_url + "/api/v1/dev/instance/pro/list",
        data=json.dumps(
            {"page_index": args.page_index, "page_size": args.page_size}
        ).encode("utf-8"),
        method="POST",
        headers={"Authorization": token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").replace(token, "[REDACTED]")
        raise SystemExit(f"AutoDL HTTP {exc.code}: {detail}") from exc
    except OSError as exc:
        raise SystemExit(f"AutoDL request failed: {exc}") from exc
    if payload.get("code") != "Success":
        message = str(payload.get("msg") or payload).replace(token, "[REDACTED]")
        raise SystemExit(f"AutoDL API error: {message}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
