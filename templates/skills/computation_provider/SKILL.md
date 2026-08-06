---
name: computation-provider
description: Acquire and operate remote computation resources, including provider selection, lifecycle management, key-first SSH authentication, environment initialization, file transfer, remote execution, result retrieval, and cleanup. Use when local CPU, memory, storage, accelerator capacity, or runtime availability cannot satisfy an experiment.
---

# Computation Provider

## Overview

Use this skill as the single entry point for remote computation. Treat provider
selection, resource discovery, instance lifecycle, SSH access, data movement,
and remote execution as separate internal capabilities. Combine only the
capabilities the task requires; their order below is not a mandatory workflow.

After determining the provider, read `references/<provider>.md` before invoking
any provider operation. Follow that reference for configuration names, supported
operations, scripts, state fields, provider-specific connection resolution,
safety checks, and failure handling.

When the run supplies cloud-backed data, also read the selected drive document
directly from this skill. The only current drive document is
`cloud/aliyun.md`; use it only with the AutoDL provider and an `aliyun` drive
selection.

## Capability Boundary

Keep provider API calls, machine selection, instance lifecycle, connection
metadata resolution, and provider-specific filesystem or image rules in the
provider adapter and `references/<provider>.md`.

Keep SSH authentication, command execution, upload, and download in the shared
`scripts/ssh.py` helper. Treat this helper as an internal sub-capability, not as
a provider or a separately triggered skill. A provider adapter may expose
`exec`, `upload`, and `download` commands, but it must only refresh and validate
provider connection metadata before delegating the actual SSH operation to the
shared helper.

## Supported Providers

The provider references present under `references/` are the complete supported
provider set. After selecting a configured provider, require its matching
`references/<provider>.md`. Do not infer support for a provider with no matching
reference, or for a capability that its reference does not document.

## Local Configs

Store provider keys, API URLs, and other local provider configuration in the
project-root `.env`. Keep only empty or non-secret defaults in the project-root
`.env.example`. Read the selected provider reference for its exact configuration
contract. Keep the matching SSH private key under the host `~/.ssh` directory.
Set `COMPUTATION_PROVIDER_SSH_IDENTITY_FILE` only when a specific key must be
selected; otherwise allow OpenSSH to use its normal config and default identities.
Never configure `COMPUTATION_PROVIDER_SSH_PASSWORD` in `.env`; reserve it for a
provider adapter to pass an ephemeral fallback password to the SSH child process.

Never copy secrets into a run state file, generated prompt, transcript, command
output, remote log, or result artifact. Persist only the non-secret identifiers
and connection metadata required to resume or clean up the current run.

## Capabilities

### Determine the Provider

Match configured providers against the experiment's required compute and the
supported-provider list. Select a provider only after confirming that its local
configuration is present. Read its reference document before taking any further
provider action.

### Query Machine Types

Record the experiment's required accelerator type, count, memory, CPU, RAM,
storage, architecture, and runtime constraints. Query the provider using the
read-only method documented in its reference. Do not silently choose weaker
hardware, reduce experiment scale, or substitute a different execution mode.

### Rent a Machine and Save Connection State

Acquire only the selected machine type. Save the provider name, provider-issued
instance identifier, requested resource specification, current lifecycle state,
and an explicit current-run ownership marker at the designated run state path.
Persist only non-secret connection information. Verify the saved state before
using it for SSH, transfer, power, or release operations.

Use the orchestration-owned `remote_compute/instance.json` path for every
provider. Read the selected provider reference for the exact state schema; never
derive a provider-specific state filename.

### Connect to a Remote Machine

Confirm the instance is running, then let the selected provider resolve only its
provider-specific SSH host, port, user, and optional fallback password. Delegate
authentication, command execution, and transfers to `scripts/ssh.py` through the
provider adapter.

For every operation, the shared helper first runs the harmless remote command
`true` with `BatchMode=yes`. If public-key authentication succeeds, use the same
identity for the requested command or transfer. If the probe fails and the
provider supplied a fallback password, use `sshpass -e`; keep the password only
in the child environment and never pass it as a command argument. Fail explicitly
when neither method authenticates.

Use `StrictHostKeyChecking=accept-new`. Never disable host-key checking, print or
persist authentication material, or retry the requested remote operation after
a connection failure. Authentication fallback may occur only during the
side-effect-free probe.

### Initialize the Remote Environment

Inspect the remote image, operating system, drivers, accelerator runtime, disks,
and available space before installing dependencies. Reproduce the experiment's
required environment without changing its methodology. Record initialization
commands and failures so another stage can audit the environment.

### Upload Code and Data

Verify source and destination paths, capacity, and transfer completion. Keep code,
input data, and outputs distinguishable. Preserve read-only source-data semantics
where required, and never place credentials in transferred content. For cloud data,
read the applicable document under `cloud/` before synchronizing a dataset.

### Run Programs Remotely

Execute the complete planned experiment at its prescribed scale. Capture the exact
command, exit status, logs, and output locations. Make long-running execution
resilient to connection loss. Do not report success until required evidence and
artifacts have been transferred to persistent run output.

### Power Instances On and Off

Use power controls only on an instance identified by validated current-run state.
Wait for the requested lifecycle state before continuing. Treat power-off and
release as distinct operations, and do not assume powered-off data is permanent.

### Create and Release Instances

Treat creation as a billable side effect and release as irreversible. Never
release an instance unless its state explicitly proves that the current run
created it. Transfer all required results, logs, and evidence before release.

During the `replicate` stage, power off every current-run instance after all
remote experiments finish and their required outputs are transferred. Attempt
the same idempotent power-off on failure paths. Release only after the report
artifacts have been validated and the pipeline is completed. The sole earlier
release case is resume reconciliation: an instance that is still recorded by
the provider but fails the one harmless SSH probe must be powered off and
successfully released before one replacement may be created. Persisted lifecycle
state must guard every release and replacement.
