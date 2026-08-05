---
name: remote-server
description: Connect to an already provisioned remote server, run commands, and transfer files with provider-independent SSH authentication.
---

# Remote Server

Use this skill only after a computation-provider reference has resolved the
remote SSH host, port, user, and any provider-supplied fallback password. Keep
provider APIs, instance lifecycle, and provider state outside this skill.

Run `scripts/ssh.py --help` for the reviewed provider-independent operations.
It supports `exec`, `upload`, and `download`.

## Authentication

The launcher copies the host `~/.ssh` directory into the agent's ephemeral
HOME. `REMOTE_SERVER_SSH_IDENTITY_FILE` may select one private key from that
directory; otherwise OpenSSH uses its normal config and default identities.
The configured path may use `~` and must resolve to an existing regular file.

For every operation, the script first runs the harmless remote command `true`
with `BatchMode=yes`. If public-key authentication succeeds, it uses that same
identity for the requested command or transfer. If the probe fails and the
selected provider supplied `REMOTE_SERVER_PASSWORD`, it falls back to
`sshpass -e`. The password stays in the child environment and is never passed
as a command argument. If neither method authenticates, fail explicitly.

Use `StrictHostKeyChecking=accept-new`. Never disable host-key checking, print
authentication material, persist it in run state, or retry the requested
remote operation after a connection failure; authentication fallback happens
only during the side-effect-free probe.
