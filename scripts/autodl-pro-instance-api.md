# AutoDL Container Instance Pro API operations

Use this guide to inspect, power on, power off, or release an existing AutoDL
Container Instance Pro instance. It is a manual operator guide, not a
replacement for the run-owned `templates/skills/computation_provider` workflow.
That workflow must only operate on instances recorded in the current run's
`remote_compute/instance.json` with `created_by_run: true`.

## Prerequisites

Run commands from the repository root. The project `.env` must contain
`AUTODL_TOKEN`; `AUTODL_API_BASE_URL` is optional and defaults to the public API
origin. The helper reads these values directly, so do not print or commit the
token.

```bash
python3 scripts/autodl_pro_instances.py --help
```

## List existing Pro instances

The list endpoint is read-only. Its response contains each instance's `uuid`,
`created_at`, and `status`.

The `list` command reads the repository-root `.env` by default and prints the
complete API response. It does not require an instance UUID:

```bash
python3 scripts/autodl_pro_instances.py list
```

Pass an alternate local dotenv file only when needed:

```bash
python3 scripts/autodl_pro_instances.py --env-file /absolute/path/to/.env list
```

The response includes `uuid`, `created_at`, and `status`. Copy the chosen UUID
only after confirming the instance in the AutoDL console.

## Power on

Powering on allocates the recorded GPU resource and may start billing. Do not
use it as an availability probe.

```bash
python3 scripts/autodl_pro_instances.py power-on pro-...
```

Use `list` until the instance reports `running` before connecting or starting
work.

## Power off

Powering off stops the instance but does not release it. Its data may remain
available under AutoDL's retention rules.

```bash
python3 scripts/autodl_pro_instances.py power-off pro-...
```

Use `list` until the instance reports `shutdown`.

## Release

Release is irreversible and destroys the instance's local data. First download
all required outputs and evidence, then power off and confirm `shutdown`. The
command independently checks for `shutdown` before it calls the release API.

```bash
python3 scripts/autodl_pro_instances.py release pro-...
```

For a MedAI run, after a successful release, update only through the AutoDL
provider script so its run state records `released: true`. Do not hand-edit the
state file.

## Reference

- [AutoDL Container Instance Pro API](https://www.autodl.com/docs/instance_pro_api/)
