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

Discover supported adapters from `providers/*.json`. Select only metadata that
matches the run's resolved provider. Read its `reference` before invoking any
provider operation. For cloud-backed data, read the selected drive's `reference`
from that same metadata before materialization or remote data access.

Metadata is the contract between orchestration and an adapter. It declares the
provider script, required local configuration, non-secret configuration
fingerprint, supported drives, cloud-source mapping, action timeouts, and legacy
manifest migration fields. Do not infer an adapter, drive, command, path, or
environment variable outside its metadata and referenced documents.

## Capability Boundary

Keep provider API calls, machine selection, instance lifecycle, connection
metadata resolution, and provider-specific filesystem or image rules in the
provider adapter and its metadata-selected reference.

Keep SSH authentication, command execution, upload, and download in the shared
`scripts/ssh.py` helper. Treat this helper as an internal sub-capability, not as
a provider or a separately triggered skill. A provider adapter may expose
`exec`, `upload`, and `download` commands, but it must only refresh and validate
provider connection metadata before delegating the actual SSH operation to the
shared helper.

## Adapter protocol

Each adapter script must support these actions: `validate-state`, `status`,
`power-on`, `power-off`, `reconcile`, `release`, `cloud-pull`, `exec`, `upload`,
and `download`. The adapter owns provider-specific state validation. The shared
orchestrator may check only the public envelope and the cloud fields `drive`,
`dataset`, `completed`, and `target_path`.

`providers/<provider>.json` is the complete supported provider set. Do not infer
support for a provider, drive, or capability that metadata and its selected
reference do not document.

A drive may set `cloud_pull_handoff: true` when its reference defines a safe
preparation and local-monitor procedure. Direct Codex data availability uses
that opt-in for every state-changing acquisition and materialization action:
the agent selects the reviewed operation, local orchestration runs its returned
foreground command, and the same session resumes from the terminal result.
Codegen uses the same handoff for every cloud-materialization action, including
preparation and monitoring. Auto Research planning may retain an already
prepared instance and hand off only the foreground monitor. Orchestration
validates canonical state between turns and owns subsequent power-off and
release.

## Local Configs

Store provider keys, API URLs, and other local provider configuration in the
project-root `.env`. Keep only empty or non-secret defaults in the project-root
`.env.example`. Read the selected provider reference for its exact configuration
contract. Keep the matching SSH private key under the host `~/.ssh` directory.
Set `COMPUTATION_PROVIDER_SSH_IDENTITY_FILE` only when a specific key must be
selected; otherwise allow OpenSSH to use its normal config and default identities.
Never configure `COMPUTATION_PROVIDER_SSH_PASSWORD` in `.env`; reserve it for a
provider adapter to pass an ephemeral fallback password to the SSH child process.

The host launcher injects the selected configuration into the agent process
environment; it does not mount the project `.env` into the stage working
directory. Never infer that provider configuration is missing because `.env` is
absent there. Invoke the reviewed adapter, which reads the inherited environment,
or check only whether required variable names are set without printing values.

Never copy secrets into a run state file, generated prompt, transcript, command
output, remote log, or result artifact. Persist only the non-secret identifiers
and connection metadata required to resume or clean up the current run.

## Capabilities

### Determine the Provider

Use the provider and drive already resolved in the run configuration. Read their
metadata-selected reference documents before taking any further provider action.

### Query Machine Types

Record the experiment's required accelerator type, count, memory, CPU, RAM,
storage, architecture, and runtime constraints. Query the provider using the
read-only method documented in its reference. Do not silently choose weaker
hardware, reduce experiment scale, or substitute a different execution mode.
For a Codegen request, accept only resource floors justified by its paper-hard-
requirement, dataset-inventory, planned streaming/chunked/out-of-core memory,
and capacity-probe evidence. Do not raise an unstated CPU-only requirement above
eight physical cores from dataset size alone. Let `D` be the complete dataset
size and `W` the peak writable work-file size; when `W` is unknown, request
remote disk of at least `D + max(D, 10 GiB)`. Require RAM with 20% headroom over
the planned implementation's estimated or measured peak.
For a CPU-only workload, proceed only when the selected provider reference
explicitly documents a CPU-only procedure and representation. Do not infer that
zero GPUs is valid or apply another provider's minimum-GPU workaround. If the
reference has no CPU-only procedure, fail explicitly. Among offers satisfying
every hard floor, select the lowest total hourly price using the reference's
stable tie breakers.

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
the same idempotent power-off on failure paths. On every terminal workflow
outcome, including failure before report completion, power off and release each
unambiguously run-owned instance before exit. The resumable partial-data
confirmation pause powers off without release. A failed instance must be powered
off and successfully released before one replacement may be created. Persisted
lifecycle state must guard every release and replacement.

For a cloud-backed Auto Research campaign, create the first campaign-owned
instance only when the first audited idea reaches experiment planning. A
provider may maintain a bounded pool in canonical state, select a retained
usable member before each foreground experiment command, and add one only after
an unambiguous capacity conflict. Every newly selected member independently
materializes and verifies the inherited inventory. Orchestration synchronizes
the local audited mother code and local idempotent mother-environment definition,
powers every member off in `finally`, and resumes the agent. Every terminal
campaign outcome releases each unambiguously owned member; successful completion
does so after final-report validation.
