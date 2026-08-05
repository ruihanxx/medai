# Aliyun Drive Materialization on AutoDL

Use this document only after selecting AutoDL and when the run manifest sets
`clouddrive: true`, `drive_provider: aliyun`, and a safe `cloud_dataset`.
Materialize the complete directory; this is not a FUSE mount or a streaming
adapter.

## Fixed Mapping

Map dataset `<name>` exactly as follows:

| Role | Path |
| --- | --- |
| Aliyun source | `medai/<name>` |
| AutoPanel download staging | `/root/autodl-tmp/<name>` |
| Canonical read-only dataset | `/root/autodl-tmp/medai/<name>` |

Accept only one directory name made from ASCII letters, digits, `.`, `_`, and
`-`, beginning with a letter or digit. Reject `/`, absolute paths, `.`, `..`,
path traversal, and multiple components.

## Required Command

After `autodl.py create` reports a running instance, invoke:

```bash
python <skill-dir>/scripts/autodl.py cloud-pull \
  --state <run-state-path> \
  --dataset <name>
```

Do this before any remote data inspection, dependency adaptation, code
implementation, preprocessing audit, training, tuning, or evaluation. On
success, read `provider_state.cloud_drive.target_path` from the state and use it
unchanged as every plan's `remote_dataset_dir`.

## Authentication and API Boundary

Require `AUTODL_AUTOPANEL_PASSWORD` in the process environment. Derive the
AutoPanel HTTPS origin and instance token from the current Pro snapshot. Hash
the standalone password only in memory for sign-in. Never place the password,
hash, AutoPanel session, Jupyter token, root password, or drive credentials in
arguments, state, prompts, transcripts, stdout, stderr, or logs.

The command uses these private AutoPanel endpoints:

| Purpose | Method and path |
| --- | --- |
| Sign in | `POST /autopanel/v1/sign_in` |
| List bound drives | `GET /autopanel/v1/netdisk/list` |
| List drive directory | `GET /autopanel/v1/netdisk/file` |
| Start download | `POST /autopanel/v1/netdisk/download` |
| Poll tasks | `GET /autopanel/v1/netdisk/task` |

These endpoints are not covered by the official Pro API compatibility
contract. Accept only response structures implemented and tested by the
provider script. On any authentication failure, ambiguous or non-Aliyun
binding, unknown field structure, or unknown task status, fail immediately.
Never open a browser, display a QR code, refresh authorization, guess a
fallback endpoint, or use another drive.

Require exactly one binding explicitly labeled Aliyun. The account is assumed
to have AutoDL's account-level automatic Aliyun authorization. Treat expired or
missing authorization as a terminal run error.

## Download and Verification

Recursively locate `medai/<name>` and require it to be one unambiguous
directory. Traverse all pages and subdirectories to compute the remote regular
file count and total bytes. Check `/root/autodl-tmp` free bytes before starting
the task. Fail on insufficient space; do not reduce or sample the dataset.

AutoPanel expands one directory request into a batch of file-download tasks and
does not return a batch identifier. Snapshot the existing task identifiers
before enqueueing, then accept only the new batch whose file count, aggregate
bytes, binding, drive, and staging-tree paths match the Aliyun inventory. Poll
every exact task identifier until AutoPanel explicitly reports success. The
default timeout is 1800 seconds and may be changed only with
`AUTODL_CLOUDDRIVE_TIMEOUT_SECONDS`. A timeout exits nonzero even if the task is
still active. A later retry must continue polling that active task rather than
start another download.

After success, compare the entire staging tree's file count and bytes with the
Aliyun inventory, move it to the canonical path on the same data disk, compare
the entire final tree again, and recursively remove write permission. Treat an
empty but valid directory distinctly from a missing directory.

Never download raw dataset files to the local MedAI run. Only audit statistics,
logs, reports, and final experiment evidence may be retrieved.

## State and Retry Safety

The command records only non-sensitive data under
`provider_state.cloud_drive`: provider, dataset, source/staging/target paths,
ownership marker, status and timestamps, task identifiers, remote/local file
counts, and remote/local total bytes.

Reuse a completed target on the same instance only after its full file count
and byte total still match. If a prior task is active, poll it. After an
explicitly terminal task failure, delete only the exact staging and target
paths whose names and current-run ownership are proven by state, then perform
one complete new download. Never use a wildcard, an unresolved variable, or an
unvalidated path for cleanup. If ownership or paths do not match the fixed
mapping, fail without deleting anything.

Every error exits nonzero so orchestration can release the current-run instance.
Do not continue locally or rent a replacement until release is confirmed. On a
later explicit resume, follow the AutoDL reference's instance-history rule.
The provider script binds a replacement to the run manifest's current
`resume_count` and refuses another replacement for that same manual resume.

## Official Guarantees and Private Assumption

AutoDL officially documents that AutoPanel starts by default, network-drive
downloads enter `/root/autodl-tmp`, Aliyun downloads support resumption, and
account-level automatic authorization is available. The Pro snapshot officially
provides the Jupyter domain and instance token used to reach AutoPanel:

- [Public network drives](https://www.autodl.com/docs/netdisk/)
- [Container Instance Pro API](https://www.autodl.com/docs/instance_pro_api/)

Automation of AutoPanel itself is a deliberately fail-fast private-interface
assumption, not an official API guarantee.
