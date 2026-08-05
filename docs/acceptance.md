# Acceptance Checks

Run `pytest`, `ruff check .`, `python -m medai --help`, and
`python -m medai.cli --help`. Tests mock provider, MinerU, and SSH
boundaries; tests never rent hardware.

Cloud-drive mock acceptance covers AutoPanel sign-in, explicit unique Aliyun
binding, recursive directory inventory, task polling and timeout reuse, remote
tree aggregation, read-only materialization, secret non-persistence, and
released-instance history. The internal AutoPanel HTTP endpoints are not an
official compatibility surface: unknown authentication, binding, listing, or
task response structures must fail rather than trigger a guessed fallback.

A real cloud-drive E2E is manual and billable. Configure
`AUTODL_AUTOPANEL_PASSWORD` only in the local `.env`, create an isolated
disposable Pro instance, run `cloud-pull --dataset mimic-iv`, compare the full
Aliyun and `/root/autodl-tmp/medai/mimic-iv` file/byte aggregates, confirm that
no raw data reached the local run, and release the instance on success or
failure. A timeout is a failed E2E and still requires release.
