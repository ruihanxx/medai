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
VASTAI_MAX_CAMPAIGN_INSTANCES=3
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

For a real GPU workload:

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

For a CPU-only workload:

```bash
python <skill-dir>/scripts/vastai.py search \
  --cpu-only \
  --min-cpu-cores <required-effective-cores> \
  --min-cpu-ram-gb <required-cpu-ram> \
  --disk-gb <required-disk>

python <skill-dir>/scripts/vastai.py create \
  --state <run-state-path> \
  --offer-id <selected-offer-id> \
  --fallback-offer-id <optional-nonweaker-offer-id> \
  --cpu-only \
  --min-cpu-cores <required-effective-cores> \
  --min-cpu-ram-gb <required-cpu-ram> \
  --disk-gb <required-disk>
```

`search` is read-only. It accepts provider-default resource floors when no
arguments are supplied, then returns only on-demand, verified, rentable,
unrented AMD64 offers within the selected price and reliability limits. Its
stable order is hourly price, descending reliability, then offer ID. Inspect
the returned GPU name, count, per-GPU memory, CPU RAM, total FLOPS, price, and
reliability before choosing an offer.

Vast does not provide a supported standalone CPU instance through this
adapter. CPU and RAM are portions of a GPU host bundle; live zero-GPU bundle
records expose no usable CPU RAM and are therefore ineligible. For a CPU-only
workload, `--cpu-only` deliberately requests Vast's minimum usable carrier of
one GPU, but that GPU is incidental compute-provider capacity. The adapter
requires `--min-cpu-cores`, filters on effective CPU cores, CPU RAM, disk,
reliability, and total hourly price, and selects the cheapest eligible offer.
It bypasses `VASTAI_DEFAULT_GPU_COUNT` and `VASTAI_MIN_GPU_RAM_GB`, using only an
internal one-GPU/1-GiB eligibility floor; the normal default 24-GiB VRAM floor
does not apply. Do not combine `--cpu-only` with `--gpu-name`, `--gpu-count`, or
`--min-gpu-ram-gb`. The GPU may still appear in selected-offer state and billing
because Vast uses it as the host bundle carrier; do not describe it as a
scientific GPU requirement.

Treat paper-stated GPU count and per-GPU VRAM as hard floors. If the exact GPU
is unavailable, document the closest eligible substitute and the divergence in
the plan and final report. A fallback is optional but, when supplied, must be a
different offer whose count, per-GPU VRAM, CPU RAM, total FLOPS, and disk are
all at least the primary offer's values. The adapter makes that one additional
billable request only after an explicit primary no-inventory response and after
it confirms that the primary did not create an instance. It never retries an
ambiguous create response.

For CPU-only requests, the optional fallback and every resume replacement must
have at least the selected offer's effective CPU cores, CPU RAM, and disk
capacity. Compare those fields rather than GPU model, VRAM, or total FLOPS; a
lower-FLOPS incidental GPU is not a weaker CPU-only replacement. Every candidate
must still meet the original price and reliability limits. State records
`cpu_only`, the requested effective-core floor, and each selected offer's
effective CPU cores and disk capacity. GPU requests retain the GPU comparison
and stronger-resource fallback rules above.

For a cloud-backed Auto Research campaign, read the completed Replicate state
at the supplied base-state path. Its `provider_state.selected_offer` is the
actual Replicate resource: use `gpu_name` as the first exact search,
`gpu_count` as the count floor, and the ceiling GiB values of `gpu_ram_mb` and
`cpu_ram_mb` as the GPU- and CPU-memory floors. The new campaign owns a separate
state and instance. If the exact model has no eligible inventory, use only the
stronger fallback procedure above.

The adapter creates an on-demand Docker `ssh_direct` instance with the explicit
image, disk size, and a run-owned label. Direct SSH is the primary transport;
the Vast proxy remains the fallback when the provider does not expose a usable
direct endpoint. The adapter records non-secret requested and selected resource
details in `remote_compute/instance.json`. The Vast API workflow is documented
at <https://docs.vast.ai/api-reference/search/search-offers> and
<https://docs.vast.ai/api-reference/instances/create-instance>.

After the first successful Auto Research rental, the adapter upgrades this
state to a bounded campaign pool. `VASTAI_MAX_CAMPAIGN_INSTANCES` is a positive
integer and defaults to three. Before each foreground experiment command the
adapter tries the active member and then the other retained members. Only the
explicit Vast response that required resources are unavailable and the state
change is queued permits a new rental. Because Vast may complete that queued
power-on asynchronously, the adapter first waits up to 60 seconds for the
retained member to reach `running`. Only if it remains unavailable does the
adapter cancel that queued start, preserve the stopped member and its disk, and
create a uniquely labelled pool member from the same resource floors. Unknown,
ambiguous, and non-capacity failures never expand the pool.

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

For Replicate, `reconcile` starts a stopped instance, probes it once through SSH,
and retains the single-instance replacement contract. For Auto Research,
`power-on` and `reconcile` select a reachable pool member and return structured
acquisition metadata, including whether cloud materialization is required. A
create response without an unambiguous instance ID remains
`creation_uncertain`; a later resume may adopt exactly one instance found by
that member's unique label, otherwise it fails explicitly.

`create` waits at most 600 seconds for a confirmed instance to reach `running`,
then retries the shared helper's harmless SSH public-key probe for at most 180
seconds. It returns success only after that probe succeeds. If either readiness
check fails after state records an unambiguous current-run instance, the adapter
marks `creation_failed=true`, records a non-secret `creation_failure`, and keeps
released failed attempts in `instance_history`. State records
`failed_create_retries` from zero through two. Release the failed instance with
the reviewed `release` command before searching for and creating a different
eligible offer. The adapter permits at most two such replacement creates and
rejects reuse of the failed offer. If creation is uncertain, release is not
confirmed, no different eligible offer exists, or the third create attempt
fails, stop explicitly without another rental.

For a selected Google Drive command handoff, never stop a merely provisioning
instance. Data availability returns `create` as a foreground command so local
orchestration waits through running and SSH readiness before resuming the agent.
It then hands off the reviewed `cloud-pull --prepare` and `cloud-pull --monitor`
operations defined in `../cloud/google-drive.md`. Each terminal local result is
persisted before the same session resumes. The prepare operation proves an
activated instance ID, onstart-backed SSH access, and writable run-owned paths
in one remote preflight command before stopping the instance; monitor starts
that same instance and verifies SSH before it returns. Never inspect transient
state while a returned command is running or repeat an ambiguous create.

Power-off and release differ. Stopping retains the container disk and can still
incur storage charges; destroying is irreversible and deletes that disk. Auto
Research power-off covers every retained pool member and restores the selected
member in canonical state. Release attempts every member and reports all
failures rather than abandoning later members after the first error. The adapter
accepts release whenever orchestration enters a terminal path, including before
report completion, while still requiring unambiguous current-run ownership. See
<https://docs.vast.ai/api-reference/instances/show-instance>,
<https://docs.vast.ai/api-reference/instances/manage-instance>,
<https://docs.vast.ai/api-reference/instances/destroy-instance>, and
<https://docs.vast.ai/guides/instances/storage/types>.

## Google Drive

For a cloud-backed run, also set `MEDAI_DRIVE_PROVIDER=google-drive`, configure
`VASTAI_GOOGLE_DRIVE_CONNECTION_ID`, and read `../cloud/google-drive.md` before
creating or inspecting a dataset. Invoke only the adapter's `cloud-pull`
command; its completed target is the sole raw-data location for the remote plan.
