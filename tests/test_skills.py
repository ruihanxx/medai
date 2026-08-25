import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
COMPUTATION_PROVIDER_SSH_SCRIPT = (
    ROOT
    / "templates"
    / "skills"
    / "computation_provider"
    / "scripts"
    / "ssh.py"
)


def fake_ssh_environment(tmp_path: Path, probe_exit: int) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "ssh-commands.log"
    ssh = fake_bin / "ssh"
    ssh.write_text(
        """#!/usr/bin/env bash
if [[ -n "${COMPUTATION_PROVIDER_SSH_PASSWORD:-}" ]]; then
    exit 97
fi
printf 'ssh %s\\n' "$*" >> "$MEDAI_TEST_SSH_COMMAND_LOG"
if [[ "${!#}" == "true" ]]; then
    exit "$MEDAI_TEST_SSH_PROBE_EXIT"
fi
exit 0
""",
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    sshpass = fake_bin / "sshpass"
    sshpass.write_text(
        """#!/usr/bin/env bash
if [[ -n "${COMPUTATION_PROVIDER_SSH_PASSWORD:-}" ]]; then
    exit 97
fi
if [[ -n "${SSHPASS:-}" ]]; then
    password_state=set
else
    password_state=missing
fi
printf 'sshpass %s password=%s\\n' "$*" "$password_state" >> "$MEDAI_TEST_SSH_COMMAND_LOG"
exit 0
""",
        encoding="utf-8",
    )
    sshpass.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "MEDAI_TEST_SSH_COMMAND_LOG": str(command_log),
        "MEDAI_TEST_SSH_PROBE_EXIT": str(probe_exit),
    }
    return environment, command_log


def test_computation_provider_prefers_configured_ssh_identity(tmp_path: Path):
    environment, command_log = fake_ssh_environment(tmp_path, probe_exit=0)
    identity = tmp_path / "id_remote"
    identity.write_text("test identity", encoding="utf-8")
    environment.update(
        {
            "COMPUTATION_PROVIDER_SSH_IDENTITY_FILE": str(identity),
            "COMPUTATION_PROVIDER_SSH_PASSWORD": "unused-fallback-password",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(COMPUTATION_PROVIDER_SSH_SCRIPT),
            "--host",
            "remote.example",
            "--port",
            "2200",
            "--user",
            "root",
            "exec",
            "--",
            "echo",
            "ready",
        ],
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    commands = command_log.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 2
    assert all("sshpass" not in command for command in commands)
    assert all(f"-i {identity}" in command for command in commands)
    assert commands[0].endswith("root@remote.example true")
    assert commands[1].endswith("root@remote.example echo ready")
