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
exists and before any remote data inspection, execute:

```bash
python <skill-dir>/scripts/vastai.py cloud-pull \
  --state <run-state-path> \
  --dataset <safe-dataset-name>
```

The adapter requests Vast Cloud Copy from that source to the exact run-owned
staging path, records only non-secret progress data, and polls the instance
status message. It proceeds only after the Cloud Copy completion marker. On a
timeout it asks Vast to cancel sync, and cleans only its recorded exact staging
path after the cancellation request is confirmed. It never persists the Cloud
Copy `result_url` or signed URLs. Vast documents these endpoints at
<https://docs.vast.ai/api-reference/instances/cloud-copy> and
<https://docs.vast.ai/api-reference/instances/cancel-sync>.

The first successful download does not prove a pre-existing Drive inventory or
preflight the source size. Instead, the adapter creates a deterministic local
artifact `remote_compute/cloud-inventory.v1.json` from the remote staging tree.
It rejects an empty tree, symlinks, special files, invalid relative paths, and
duplicate paths. The version-1 JSON contains the dataset name, `sha256`
algorithm, sorted `{path, size, sha256}` entries, file count, and total bytes.

The adapter verifies the generated inventory after moving the staging directory
atomically to:

```text
/workspace/medai/<run_token>/data/<dataset>
```

It then makes that target read-only, records its path and inventory digest in
provider state, and prints the path. Use that exact completed `target_path` as
every remote plan's `remote_dataset_dir`; never rematerialize or copy raw cloud
data locally.

The inventory becomes the run's baseline. Repeated pulls and replacement
instances must regenerate exactly the same inventory before the adapter sets
`completed=true`; a changed Drive tree remains incomplete and stops the run.
