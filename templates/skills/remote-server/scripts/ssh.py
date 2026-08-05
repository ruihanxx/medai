from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--host", required=True)
parser.add_argument("--port", required=True)
parser.add_argument("--user", required=True)
subparsers = parser.add_subparsers(dest="action", required=True)

execute = subparsers.add_parser("exec")
execute.add_argument("command", nargs=argparse.REMAINDER)

upload = subparsers.add_parser("upload")
upload.add_argument("--source", type=Path, required=True)
upload.add_argument("--remote", required=True)

download = subparsers.add_parser("download")
download.add_argument("--remote", required=True)
download.add_argument("--destination", type=Path, required=True)

args = parser.parse_args()
target = f"{args.user}@{args.host}"
host_options = [
    "-o",
    "StrictHostKeyChecking=accept-new",
]
identity_options: list[str] = []
identity = os.environ.get("REMOTE_SERVER_SSH_IDENTITY_FILE", "").strip().strip("'\"")
if identity:
    identity_path = Path(identity).expanduser()
    if not identity_path.is_file():
        raise SystemExit(f"Remote SSH identity file is missing: {identity_path}")
    identity_options = ["-i", str(identity_path), "-o", "IdentitiesOnly=yes"]

environment = os.environ.copy()
password = environment.pop("REMOTE_SERVER_PASSWORD", "")
probe = subprocess.run(
    [
        "ssh",
        *identity_options,
        "-p",
        args.port,
        *host_options,
        "-o",
        "BatchMode=yes",
        target,
        "true",
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    env=environment,
)

prefix: list[str] = []
authentication_options = [*identity_options, "-o", "BatchMode=yes"]
if probe.returncode != 0:
    if not password:
        raise SystemExit(
            "SSH public-key authentication failed and no fallback password is available"
        )
    sshpass = shutil.which("sshpass")
    if sshpass is None:
        raise SystemExit("Password SSH fallback requires sshpass")
    environment["SSHPASS"] = password
    prefix = [sshpass, "-e"]
    authentication_options = [
        "-o",
        "PreferredAuthentications=password",
        "-o",
        "PubkeyAuthentication=no",
    ]

if args.action == "exec":
    command_parts = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command_parts:
        raise SystemExit("exec requires a command")
    remote_command = " ".join(shlex.quote(item) for item in command_parts)
    command = [
        *prefix,
        "ssh",
        *authentication_options,
        "-p",
        args.port,
        *host_options,
        target,
        remote_command,
    ]
elif args.action == "upload":
    command = [
        *prefix,
        "scp",
        *authentication_options,
        "-rP",
        args.port,
        *host_options,
        str(args.source),
        f"{target}:{args.remote}",
    ]
else:
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        *prefix,
        "scp",
        *authentication_options,
        "-rP",
        args.port,
        *host_options,
        f"{target}:{args.remote}",
        str(args.destination),
    ]

raise SystemExit(subprocess.run(command, env=environment).returncode)
