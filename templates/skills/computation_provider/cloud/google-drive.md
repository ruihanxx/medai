# Google Drive through Vast.ai

Read this document together with `../references/vastai.md` before using cloud
data. It defines the Google Drive materialization contract for the `vastai`
adapter; do not use a direct Google client, rclone configuration, browser token,
or local raw-data copy.

## Configure the Account Connection

Set the resolved drive selector to `google-drive` and configure the non-secret
connection ID in the project `.env`:

```dotenv
MEDAI_DRIVE_PROVIDER=google-drive
VASTAI_GOOGLE_DRIVE_CONNECTION_ID=<Vast-cloud-connection-id>
```

Before a run, connect a dedicated Google Drive account in Vast Settings → Cloud
Connections. Vast connects at account scope, temporarily places the connection
credentials on the host during Cloud Sync, and supports Cloud Sync only for
Docker—not VM/KVM—instances. The provider adapter therefore accepts only its
verified Docker SSH instances and validates that the configured connection is
exactly one `cloud_type=drive` entry. See
<https://docs.vast.ai/guides/instances/storage/cloud-sync> and
<https://docs.vast.ai/api-reference/accounts/show-connections>.

## Materialize a Dataset

Store the source directory at `medai/<dataset>`. After the run-owned instance
exists and before any remote data inspection, the normal reviewed command is:

```bash
python <skill-dir>/scripts/vastai.py cloud-pull \
  --state <run-state-path> \
  --dataset <safe-dataset-name>
```

Repeat the command once for every selected dataset. The provider records each
materialization independently under `provider_state.cloud_drives[<dataset>]`;
one failed or incomplete entry keeps the overall run incomplete.

For an opted-in Codex command handoff, the active agent must first run:

```bash
python <skill-dir>/scripts/vastai.py cloud-pull \
  --state <run-state-path> \
  --dataset <safe-dataset-name> \
  --prepare
```

`--prepare` requires an activated, initialized running instance. It proves SSH
access, checks the exact owned staging and target parents, creates and removes
write probes, then powers the instance off and records `handoff_ready=true`.
Only after this command succeeds may the agent return this foreground local
command and end its turn:

```bash
python <skill-dir>/scripts/vastai.py cloud-pull \
  --state <run-state-path> \
  --dataset <safe-dataset-name> \
  --monitor
```

`--monitor` refuses a running or unprepared instance. It requests Vast Cloud
Copy from the stopped instance into the exact run-owned staging path, records
only non-secret progress data, and prints changed status messages while polling
every 30 seconds. It never persists the Cloud Copy `result_url` or signed URLs.
At every terminal result it starts the same instance and verifies SSH before
returning control to the agent. On a timeout it cancels sync while stopped,
then starts the instance and cleans only the recorded exact staging path after
the cancellation request is confirmed. Vast documents these endpoints at
<https://docs.vast.ai/api-reference/instances/cloud-copy> and
<https://docs.vast.ai/api-reference/instances/cancel-sync>.

The first successful download does not prove a pre-existing Drive inventory or
preflight the source size. Instead, the adapter creates a deterministic local
inventory from the remote staging tree. The first dataset retains
`remote_compute/cloud-inventory.v1.json`; additional datasets use
`remote_compute/cloud-inventory.<dataset>.v1.json`, and each filename is stored
in its provider-state record.
It rejects an empty tree, symlinks, special files, invalid relative paths, and
duplicate paths. The version-1 JSON contains the dataset name, `sha256`
algorithm, sorted `{path, size, sha256}` entries, file count, and total bytes.

The adapter verifies the generated inventory after moving the staging directory
atomically to:

```text
/workspace/medai/<run_token>/data/<dataset>
```

After Vast reports Cloud Copy completion, the adapter probes the exact staging
directory. If host-side copied data is not yet visible in the running Docker
container, it stops and restarts that same instance once, then requires the
staging path to become visible before generating the inventory. It never rents
a replacement or starts a second Cloud Copy for this mount refresh.

It then makes every target read-only, records its path and inventory digest in
provider state, and prints the path. For one dataset use its exact completed
`target_path` as `remote_dataset_dir`; for multiple datasets use their common
`/workspace/medai/<run_token>/data` parent and address each named child. Never
rematerialize or copy raw cloud data locally.

The inventory becomes the run's baseline. Repeated pulls and replacement
instances must regenerate exactly the same inventory before the adapter sets
`completed=true`; a changed Drive tree remains incomplete and stops the run.
