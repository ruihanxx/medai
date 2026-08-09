# Vast.ai

Read this document before invoking the `vastai` adapter. It defines all
Vast-specific configuration, resource selection, lifecycle, connection, and
recovery rules. The parent computation-provider skill defines the common
orchestration envelope.

## Configuration

Set `MEDAI_COMPUTATION_PROVIDER=vastai`. Configure the following values in the
project `.env`:

```dotenv
VAST_API_KEY=<scoped-key>
VASTAI_IMAGE=<explicit-compatible-container-image>
VASTAI_MAX_DPH=2
VASTAI_DISK_GB=64
VASTAI_DEFAULT_GPU_COUNT=1
VASTAI_MIN_GPU_RAM_GB=24
VASTAI_MIN_CPU_RAM_GB=32
VASTAI_MIN_RELIABILITY=0.99
```

`VASTAI_API_BASE_URL` defaults to `https://console.vast.ai`; set it only for a
controlled private endpoint or adapter test. `VAST_API_KEY` may contain one
outer pair of Docker env-file quotes; the adapter removes only that pair. Never
place the key in state, commands, output, prompts, logs, or transferred files.

Create a scoped API key with `misc`, `user_read`, `instance_read`, and
`instance_write`. Vast documents Bearer authentication and the permission
categories at <https://docs.vast.ai/api-reference/authentication> and
<https://docs.vast.ai/api-reference/permissions>.

Add a public SSH key to the Vast account and keep the matching private key under
the host `~/.ssh`. Set `COMPUTATION_PROVIDER_SSH_IDENTITY_FILE` only when the
normal OpenSSH configuration cannot select the correct key. When it is set, keep
the matching public key at `<identity-file>.pub`; before renting, the adapter
verifies that key against the Vast account and injects it through the instance
`onstart` command without persisting it in run state. Vast does not use a
password fallback.

## Select and Create

Use the reviewed adapter rather than the Vast CLI:

```bash
python <skill-dir>/scripts/vastai.py search \
  --gpu-count <required-count> \
  --min-gpu-ram-gb <required-per-gpu-vram> \
  --min-cpu-ram-gb <required-cpu-ram>

python <skill-dir>/scripts/vastai.py create \
  --state <run-state-path> \
  --offer-id <selected-offer-id> \
  --fallback-offer-id <one-stronger-offer-id> \
  --gpu-count <required-count> \
  --min-gpu-ram-gb <required-per-gpu-vram> \
  --min-cpu-ram-gb <required-cpu-ram>
```

`search` is read-only. It accepts provider-default resource floors when no
arguments are supplied, then returns only on-demand, verified, rentable,
unrented AMD64 offers within the selected price and reliability limits. Its
stable order is hourly price, descending reliability, then offer ID. Inspect
the returned GPU name, count, per-GPU memory, CPU RAM, total FLOPS, price, and
reliability before choosing an offer.

Treat paper-stated GPU count and per-GPU VRAM as hard floors. If the exact GPU
is unavailable, document the closest eligible substitute and the divergence in
the plan and final report. A fallback is optional but, when supplied, must be a
different offer whose count, per-GPU VRAM, CPU RAM, total FLOPS, and disk are
all at least the primary offer's values. The adapter makes that one additional
billable request only after an explicit primary no-inventory response and after
it confirms that the primary did not create an instance. It never retries an
ambiguous create response.

The adapter creates an on-demand Docker SSH instance with the explicit image,
disk size, and a run-owned label. It records non-secret requested and selected
resource details in `remote_compute/instance.json`. The Vast API workflow is
documented at <https://docs.vast.ai/api-reference/search/search-offers> and
<https://docs.vast.ai/api-reference/instances/create-instance>.

## State, SSH, and Lifecycle

The adapter owns the state schema. Do not hand-edit it. It records a stable
`run_token`; use these paths unchanged in remote plans:

```text
/workspace/medai/<run_token>/work
/workspace/medai/<run_token>/data/<dataset>
```

Before every SSH, upload, download, or execution operation, the adapter reads
the current instance, prefers its direct SSH endpoint when present, otherwise
uses its proxy endpoint, and delegates to the shared `scripts/ssh.py` helper.
If direct public-key authentication fails during the helper's harmless probe,
the adapter tries the proxy endpoint; it never retries an operation that may
already have executed.
Use `exec` for short checks and `upload` only for code and non-cloud inputs.
Retrieve outputs, logs, and exit-status evidence before the replication plan
powers the instance off.

Use only these common commands after state exists:

```bash
python <skill-dir>/scripts/vastai.py validate-state --state <run-state-path>
python <skill-dir>/scripts/vastai.py status --state <run-state-path>
python <skill-dir>/scripts/vastai.py power-on --state <run-state-path>
python <skill-dir>/scripts/vastai.py power-off --state <run-state-path>
python <skill-dir>/scripts/vastai.py reconcile --state <run-state-path>
python <skill-dir>/scripts/vastai.py release --state <run-state-path>
```

`reconcile` starts a stopped instance, probes an active instance once through
SSH, and permits one replacement per manifest resume count. It may replace only
after Vast confirms the original is missing or after the adapter has
successfully stopped and destroyed an SSH-unreachable original. It never
replaces after an ambiguous API response. A create response without an
unambiguous instance ID remains `creation_uncertain`; a later resume may adopt
exactly one instance found by its run label, otherwise it fails explicitly.

For the selected Google Drive command handoff, never stop a merely provisioning
instance. First complete the reviewed `cloud-pull --prepare` procedure in
`../cloud/google-drive.md`; it proves an activated instance ID, onstart-backed
SSH access, and writable run-owned paths before stopping the instance. The
returned `cloud-pull --monitor` command runs locally while the Codex session is
paused, then starts the same instance and verifies SSH before that session
resumes.

Power-off and release differ. Stopping retains the container disk and can still
incur storage charges; destroying is irreversible and deletes that disk. The
adapter refuses normal release before report and pipeline completion. See
<https://docs.vast.ai/api-reference/instances/show-instance>,
<https://docs.vast.ai/api-reference/instances/manage-instance>,
<https://docs.vast.ai/api-reference/instances/destroy-instance>, and
<https://docs.vast.ai/guides/instances/storage/types>.

## Google Drive

For a cloud-backed run, also set `MEDAI_DRIVE_PROVIDER=google-drive`, configure
`VASTAI_GOOGLE_DRIVE_CONNECTION_ID`, and read `../cloud/google-drive.md` before
creating or inspecting a dataset. Invoke only the adapter's `cloud-pull`
command; its completed target is the sole raw-data location for the remote plan.
