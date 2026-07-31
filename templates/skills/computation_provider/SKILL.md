---
name: computation-provider
description: Connect to and operate remote computation providers. Use when local CPU, memory, storage, accelerator capacity, or runtime availability cannot satisfy an experiment and remote infrastructure must be inspected, acquired, connected, initialized, supplied with code or data, operated, powered down, or released.
---

# Computation Provider

## Overview

Use this skill as the provider-independent entry point for remote computation.
Treat provider selection, resource discovery, instance operations, data movement,
and remote execution as separate capabilities. Combine only the capabilities the
task requires; their order below is not a mandatory workflow.

After determining the provider, read `references/<provider>.md` before invoking
any provider operation. Follow that reference for configuration names, supported
operations, scripts, state fields, safety checks, and failure handling.

## When to Use

Use this skill when an experiment requires a remote computation platform because
the available local environment cannot meet its full-scale execution needs.

## Supported Providers

- `autodl`: read `references/autodl.md` after selecting this provider.

Do not infer support for a provider that is not listed here. Stop explicitly if
the required provider has no reference document or the required capability is
not documented there.

## Local Configs

Store provider keys, API URLs, and other local provider configuration in the
project-root `.env`. Keep only empty or non-secret defaults in the project-root
`.env.example`. Read the selected provider reference for its exact configuration
contract.

Never copy secrets into a run state file, generated prompt, transcript, command
output, remote log, or result artifact. Persist only the non-secret identifiers
and connection metadata required to resume or clean up the current run.

## Sub Skills

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

### Connect to a Remote Machine

Confirm the instance is running and use the connection method documented by the
provider. Keep authentication material local, validate the remote identity, and
avoid exposing credentials through arguments, logs, transcripts, or artifacts.
Fail explicitly when the connection cannot be authenticated or established.

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

During the `replicate` stage, release every current-run instance immediately
after all remote experiments finish and their required outputs are transferred.
Attempt release on failure paths as well. Release must be idempotent or guarded by
persisted release state so cleanup never targets an already released instance.
