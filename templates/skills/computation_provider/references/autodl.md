# AutoDL Provider Reference

Use this reference only after selecting `autodl` through the parent
`computation-provider` skill. It documents the supported AutoDL Container
Instance Pro operations and the exact behavior of `../scripts/autodl.py`.

## Contents

- [Safety Boundary](#safety-boundary)
- [Local Configuration](#local-configuration)
- [Choose a Machine Type](#choose-a-machine-type)
- [Script and State Contract](#script-and-state-contract)
- [Create and Inspect an Instance](#create-and-inspect-an-instance)
- [Connect and Initialize the Environment](#connect-and-initialize-the-environment)
- [Upload Code and Data](#upload-code-and-data)
- [Run an Experiment](#run-an-experiment)
- [Download Results](#download-results)
- [Power and Release](#power-and-release)
- [Failure Handling](#failure-handling)
- [Official Documentation](#official-documentation)

## Safety Boundary

- Use AutoDL only when its credentials are configured and local resources cannot
  satisfy the recorded full-scale experiment requirements.
- Treat `create` as billable and `release` as irreversible.
- Operate only on the instance UUID stored in the current run's state file.
- Never release an instance unless `created_by_run` is exactly `true`.
- Never substitute a weaker GPU, fewer GPUs, less memory, a reduced dataset, or
  a reduced experiment when the required resource is unavailable.
- Transfer all required outputs, logs, exit-status evidence, and artifacts to
  persistent run output before releasing the instance.
- In the `replicate` stage, attempt release after all remote experiments finish
  and also on every failure path. Surface cleanup failures explicitly.

## Local Configuration

AutoDL Pro API access requires an individually or organizationally verified
AutoDL account. Obtain the developer token from the AutoDL console under account
settings and store configuration in the repository-root `.env`:

| Variable | Required | Purpose |
| --- | --- | --- |
| `AUTODL_TOKEN` | Yes | Developer token sent in the API `Authorization` header. |
| `AUTODL_IMAGE_UUID` | Yes | Default private or public image UUID used when the paper has no explicit software versions. |
| `AUTODL_API_BASE_URL` | No | API origin; the script defaults to `https://api.autodl.com`. |

Do not print these values or copy them into prompts, transcripts, state files,
remote commands, logs, or result artifacts. The runtime must provide Python,
OpenSSH client tools, and `sshpass` when the API returns a root password. The
project Docker image already supplies these tools.

The current script cannot list images. `AUTODL_IMAGE_UUID` is the default image;
pass `create --image-uuid <uuid>` only after the paper-version selection below.
Select and validate an image UUID in the AutoDL console before the run, including
framework, Python, CUDA, and disk requirements. Stop if a compatible image
UUID cannot be confirmed.

## Choose a Machine Type

First record the required GPU model, GPU count, per-GPU VRAM, CPU, RAM, disk,
architecture, framework, CUDA compatibility, and expected run duration. AutoDL
allocates CPU and RAM in proportion to GPU count, and the limits shown in its
market are per GPU. Memory is a hard container limit; exceeding it can terminate
the process rather than transparently spilling to disk.

The Pro API documentation currently maps these GPU labels to `--gpu-spec` IDs.
The listed capacity is per-GPU VRAM and is the capacity used for fallback
selection:

| AutoDL label | VRAM | Pro API GPU specification ID |
| --- | --- | --- |
| H800-80G | 80 GB | `h800` |
| 4090-48G | 48 GB | `v-48g` |
| PRO6000-96G | 96 GB | `pro6000-p` |
| 4080(S)-32G | 32 GB | `v-32g-p` |
| 3090-48G | 48 GB | `v-48g-350w` |
| 5090-32G | 32 GB | `5090-p` |
| 4090D | Not stated in the API appendix | `4090D` |

Before *every* `create`, follow this selection procedure:

1. Read the paper's GPU model, count, and VRAM. When the paper names a GPU but
   not its VRAM, obtain the VRAM from the manufacturer's authoritative
   specification; do not guess from a similarly named product.
2. Check whether the exact model appears in the table. If it does, use its
   corresponding ID. If it does not, exclude every pool GPU with unknown or
   lower VRAM, then choose the closest remaining model: prefer the same vendor
   and architecture/generation, then the smallest VRAM surplus. Record the
   paper GPU, the selected pool GPU, their VRAM, and why it is the closest
   eligible substitute in the plan and final report.
3. Stop explicitly if no listed GPU has sufficient documented VRAM. Never use
   `4090D` as a fallback while its VRAM is unstated; it may be used only when it
   is the paper's exact model and its capacity is confirmed in the AutoDL
   console.
4. Pass only the selected table ID to `create --gpu-spec`. The script repeats
   this pool-membership check and rejects every other value before any API call.
5. After creation, use `nvidia-smi` to confirm the observed model, GPU count,
   and VRAM before uploading data or starting the experiment.

Recheck the official Pro API appendix before every rental because this mapping
may change. The public Pro API does not expose a read-only endpoint for current
rentable inventory. When the market or console cannot be queried, choose one
stronger eligible pool GPU in advance and pass it as `--fallback-gpu-spec` to
the reviewed `create` command. The script makes that one additional billable
request only when the first create response explicitly says the selected GPU is
out of inventory. A second out-of-inventory response, or any other API error,
stops the run; do not try further GPUs.

The Pro API accepts one to four GPUs per instance. Stop if the experiment needs
more than four GPUs or another unsupported topology. Do not split the experiment
across instances unless the paper and replication plan explicitly require a
supported distributed topology.

## Select an Image

If the paper does not state framework, Python, CUDA, or other material software
versions, use the configured default `AUTODL_IMAGE_UUID`. The project example
defaults it to `base-image-l2t43iu6uk` (PyTorch 2.0.0, CUDA 11.8, Python 3.8).

If the paper states material software versions, select an image from the
official Pro API public-image appendix before creation. Prefer an exact match;
otherwise choose the closest image with the same framework, then the nearest
framework version, Python version, and CUDA version in that order. For a
framework absent from the table, choose the closest Miniconda entry and install
the paper-pinned framework afterwards. Do not silently use the default image
when the paper states versions. Record the chosen image, the candidate
environment, every mismatch, and the installation command that resolves it.

| Framework | Public image UUID | Image environment |
| --- | --- | --- |
| PyTorch | `base-image-12be412037` | CUDA 11.1, cuDNN 8, Ubuntu 18.04, Python 3.8, PyTorch 1.9.0 |
| PyTorch | `base-image-u9r24vthlk` | CUDA 11.3, cuDNN 8, Ubuntu 20.04, Python 3.8, PyTorch 1.10.0 |
| PyTorch | `base-image-l374uiucui` | CUDA 11.3, cuDNN 8, Ubuntu 20.04, Python 3.8, PyTorch 1.11.0 |
| PyTorch | `base-image-l2t43iu6uk` | CUDA 11.8, cuDNN 8, Ubuntu 20.04, Python 3.8, PyTorch 2.0.0 |
| TensorFlow | `base-image-0gxqmciyth` | CUDA 11.2, cuDNN 8, Ubuntu 18.04, Python 3.8, TensorFlow 2.5.0 |
| TensorFlow | `base-image-uxeklgirir` | CUDA 11.2, cuDNN 8, Ubuntu 20.04, Python 3.8, TensorFlow 2.9.0 |
| TensorFlow | `base-image-4bpg0tt88l` | CUDA 11.4, Python 3.8, TensorFlow 1.15.5 |
| Miniconda | `base-image-mbr2n4urrc` | CUDA 11.6, cuDNN 8, Ubuntu 20.04, Python 3.8 |
| Miniconda | `base-image-qkkhitpik5` | CUDA 10.2, cuDNN 7, Ubuntu 18.04, Python 3.8 |
| Miniconda | `base-image-h041hn36yt` | CUDA 11.1, cuDNN 8, Ubuntu 18.04, Python 3.8 |
| Miniconda | `base-image-7bn8iqhkb5` | CUDA GL 11.3, cuDNN 8, Ubuntu 20.04, Python 3.8 |
| Miniconda | `base-image-k0vep6kyq8` | CUDA 9.0, cuDNN 7, Ubuntu 16.04, Python 3.6 |
| TensorRT | `base-image-l2843iu23k` | CUDA 11.8, cuDNN 8, Ubuntu 20.04, Python 3.8, TensorRT 8.5.1 |

Pass an explicit selected image with:

```bash
python <skill-dir>/scripts/autodl.py create \
  --gpu-spec <gpu-specification-id> \
  --image-uuid <paper-selected-image-uuid> \
  --gpu-count <count> \
  --state <run-state-path>
```

## Script and State Contract

Invoke the provider script through its path under the selected skill:

```bash
python <skill-dir>/scripts/autodl.py --help
```

Use the generic run-owned state path supplied by the orchestration prompt:
`remote_compute/instance.json`. Never create a provider-named state file or
reuse a state file from another run.

After successful creation, the script writes:

```json
{
  "provider": "autodl",
  "created_by_run": true,
  "released": false,
  "provider_state": {
    "instance_uuid": "<provider-instance-uuid>",
    "gpu_spec_uuid": "<selected-pro-specification-id>",
    "gpu_count": 1,
    "image_uuid": "<selected-image-uuid>"
  }
}
```

The top-level fields form the generic orchestration envelope. The AutoDL script
owns the exact `provider_state` format and requires `instance_uuid`. It also
records the selected GPU specification/count and non-secret image UUID for
auditability. The instance UUID is sufficient for the script to fetch current
SSH host, port, and password from the snapshot API immediately before each
connection or transfer. Do not persist the returned password or Jupyter token.
Record the selection rationale in the plan artifacts; do not hand-edit the
provider, ownership, lifecycle, or provider-state fields.

The script sends `POST` request bodies as JSON. For the provider's `GET`
operations, it sends `instance_uuid` as a URL query parameter (not a JSON
body), because the current API rejects GET JSON bodies with a parameter error.
It uses these reviewed Pro API operations:

| Purpose | Method and path |
| --- | --- |
| Create | `POST /api/v1/dev/instance/pro/create` |
| Read status | `GET /api/v1/dev/instance/pro/status` |
| Fetch current SSH details | `GET /api/v1/dev/instance/pro/snapshot` |
| Power off during release | `POST /api/v1/dev/instance/pro/power_off` |
| Release | `POST /api/v1/dev/instance/pro/release` |

After successful release, the script changes `released` to `true` and adds the
top-level `released_at_unix` timestamp. Treat that marker as a guard against
duplicate release.

## Create and Inspect an Instance

Create only after the exact requirement and image UUID have been validated:

```bash
python <skill-dir>/scripts/autodl.py create \
  --gpu-spec <gpu-specification-id> \
  --fallback-gpu-spec <one-stronger-gpu-specification-id> \
  --gpu-count <count> \
  --state <run-state-path>
```

Require the state path to be absent before creation. If it already exists,
inspect and resume or clean up that recorded instance; never overwrite the state
and create another billable instance.

The current script:

- creates a pay-as-you-go Container Instance Pro instance;
- makes one preselected stronger-GPU create attempt only when the first request
  explicitly reports no inventory;
- lets AutoDL choose the data center;
- requests no system-disk expansion;
- requires a host driver compatible with CUDA 11.8 or newer;
- uses `--image-uuid` when supplied, otherwise `AUTODL_IMAGE_UUID`, and a
  timestamped `medai-` instance name;
- records current-run ownership and the returned instance UUID immediately
  after AutoDL accepts the create request; and
- waits up to ten minutes, polling every ten seconds for `running` before
  returning success.

If the experiment needs a specific region, system-disk expansion, another CUDA
driver floor, a different billing mode, or more than four GPUs, this script does
not support the requirement. Stop instead of silently changing it.

Check lifecycle state before SSH, transfer, or execution:

```bash
python <skill-dir>/scripts/autodl.py status --state <run-state-path>
```

Continue only when the returned state is `running`. A successful API response
does not prove the requested hardware or runtime is usable; verify them remotely
before uploading large data or starting the experiment.

## Connect and Initialize the Environment

The `exec` action fetches the current instance snapshot, uses `root` with the
snapshot proxy host and SSH port, and supplies the snapshot password through
`sshpass` when present. It uses `StrictHostKeyChecking=accept-new`; never replace
that with disabled host-key checking. AutoDL also supports account-level SSH
public keys configured through its console.

The script provides non-interactive SSH execution, not an interactive shell:

```bash
python <skill-dir>/scripts/autodl.py exec \
  --state <run-state-path> -- <command> <arguments>
```

Initialize and verify the environment through auditable non-interactive commands:

1. Source `/root/.bashrc` before using AutoDL's Conda environment.
2. Inspect `nvidia-smi`, GPU count and VRAM, CPU architecture, RAM, mounted
   disks, free space, Python, framework, CUDA, and cuDNN versions.
3. Confirm the observed hardware satisfies the recorded experiment requirement.
4. Install dependencies from the copied codebase's lockfile or manifest. Pin
   paper-specified versions and record every installation command.
5. Run a minimal accelerator smoke check before the full experiment.

Each `exec` call opens a new non-interactive shell, so shell state does not carry
to the next call. Source the profile and run environment-dependent commands in
the same shell:

```bash
python <skill-dir>/scripts/autodl.py exec \
  --state <run-state-path> -- bash -lc \
  'source /root/.bashrc && <environment-dependent-command>'
```

AutoDL images include Miniconda. Install environments and ordinary dependencies
on the system disk unless capacity requires an explicitly planned alternative.
Use `/root/autodl-tmp` for large, high-I/O code, data, checkpoints, logs, and
results. `/root/autodl-fs` is network file storage, and `/root/autodl-pub` is
read-only public data. AutoDL container instances cannot run nested Docker.

## Upload Code and Data

Create the remote parent directory first, then upload from the local runtime:

```bash
python <skill-dir>/scripts/autodl.py exec \
  --state <run-state-path> -- mkdir -p <remote-parent>
python <skill-dir>/scripts/autodl.py upload \
  --state <run-state-path> \
  --source <local-file-or-directory> \
  --remote <remote-destination>
```

The upload action uses recursive `scp`. Check the resulting remote layout because
copying a directory into an existing destination nests its basename. Verify file
counts, sizes, and checksums when correctness depends on exact transfer. Do not
modify the local read-only source dataset.

Recursive SCP has no resume or exclusion support and can be slow for many small
files. Package small files before transfer when appropriate. AutoDL recommends
cloud storage for large transfers, but this skill currently has no reviewed
cloud-provider document under `cloud/`; do not improvise cloud credentials or
sync commands until such a document exists.

## Run an Experiment

Use synchronous `exec` only for short inspections, initialization, smoke checks,
and polling. SSH disconnection can terminate an unprotected foreground process.
For a long experiment:

1. Upload a run-owned wrapper that changes to the intended working directory,
   executes the exact audited command, redirects stdout and stderr to a log, and
   writes the final numeric exit status to a dedicated file.
2. Start the wrapper under `nohup`, `screen`, or `tmux` as a detached process.
3. Save its PID in the remote run directory.
4. Poll the PID, log, exit-status file, output paths, disk use, and accelerator
   use with short `exec` calls.
5. Treat a missing exit-status file, nonzero status, stopped instance, OOM,
   missing output, or truncated artifact as an explicit experiment failure.

AutoDL officially recommends `screen` or `tmux` for programs launched through
SSH. Keep all run logs under the data disk and transfer them even when execution
fails. Do not infer success from an absent process alone.

After uploading a wrapper that records its own exit status, a detached launch
may use this form:

```bash
python <skill-dir>/scripts/autodl.py exec \
  --state <run-state-path> -- bash -lc \
  'cd <remote-run-directory> && nohup bash run_remote.sh > run.log 2>&1 < /dev/null & echo $! > run.pid'
```

## Download Results

Download required files or directories before release:

```bash
python <skill-dir>/scripts/autodl.py download \
  --state <run-state-path> \
  --remote <remote-file-or-directory> \
  --destination <persistent-local-destination>
```

The download action uses recursive `scp` and creates the local destination's
parent directory. Transfer the command wrapper, logs, PID, exit-status file,
checkpoints needed as evidence, result files, and generated artifacts. Validate
their local existence, size, readability, and expected structure. Do not release
the instance while any required evidence exists only on AutoDL storage.

## Power and Release

The official Pro API exposes separate `power_on`, `power_off`, and `release`
operations, and requires power-off before release. The current script does not
expose independent power-on or power-off actions. It supports:

- `create`, which creates and starts an instance;
- `status`, which reads lifecycle state; and
- `release`, which calls power-off and then release.

If a workflow requires an independent stop/restart cycle, stop explicitly and
request a script extension. Do not issue ad hoc lifecycle requests outside the
reviewed script.

Before release, read the state and confirm all of the following:

- the state belongs to the current run;
- `created_by_run` is `true`;
- `released` is not `true`;
- no remote experiment is still running; and
- all required outputs and failure evidence have been downloaded.

Then release:

```bash
python <skill-dir>/scripts/autodl.py release --state <run-state-path>
```

On success, confirm the state file contains `released: true`. Release destroys
the instance and its local data. Power-off alone preserves instance data only
temporarily; AutoDL currently documents automatic release after fifteen
consecutive powered-off days and warns that local instance disks are not a
durable backup.

## Failure Handling

- **API or HTTP error:** Preserve the complete non-secret error and stop the
  current operation. The only exception is the script's one preselected
  `--fallback-gpu-spec` attempt after an explicit no-inventory response; do not
  choose another resource or retry billable creation beyond it. A failed
  `create` must make the invoking Codex agent exit nonzero; do not continue the
  run locally or with another rental.
- **Creation timeout or status-poll failure:** The current-run state is written
  as soon as AutoDL returns the instance UUID, before polling starts. Inspect
  that state with `status`, then power off and release the recorded instance if
  it cannot be used. Do not call `create` again while that state exists.
- **SSH failure:** Recheck `status`; then validate the current snapshot host,
  port, credential availability, local `ssh`/`scp`/`sshpass`, network access,
  and host identity. Never disable host verification to force a connection.
- **Transfer failure:** Inspect both endpoints before retrying. Remove or replace
  partial files only after confirming the exact run-owned paths.
- **Remote command failure:** Preserve logs and the exit-status file, download
  available evidence, mark the experiment failed, and continue to cleanup.
- **Release failure:** Preserve the state file and error. Do not set `released`
  manually. The host cleanup path may retry; if the instance is powered off but
  the script cannot complete release, verify and release it through the AutoDL
  console. Report the cleanup failure with the experiment failure.

## Official Documentation

- [Container Instance Pro API](https://www.autodl.com/docs/instance_pro_api/)
- [GPU selection](https://www.autodl.com/docs/gpu/)
- [SSH](https://www.autodl.com/docs/ssh/)
- [Upload data](https://www.autodl.com/docs/scp/)
- [Download data](https://www.autodl.com/docs/down/)
- [Instance storage layout](https://www.autodl.com/docs/env/)
- [Dependency installation](https://www.autodl.com/docs/deps/)
- [Background processes](https://www.autodl.com/docs/daemon/)
- [Instance data retention](https://www.autodl.com/docs/instance_data/)
