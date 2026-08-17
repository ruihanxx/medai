# Acceptance Checks

Run `pytest`, `ruff check .`, `python -m medai --help`, and
`python -m medai.cli --help`. Tests mock provider, MinerU, and SSH
boundaries; tests never rent hardware.

Cloud-drive mock acceptance covers provider-authorized sign-in, explicit drive
selection, recursive directory inventory, task polling and timeout reuse, remote
tree aggregation, read-only materialization, secret non-persistence, and
released-instance history. Provider-private API response structures are not a
generic compatibility surface: unknown authentication, binding, listing, or task
responses must fail rather than trigger a guessed fallback.

For a drive that opts into Codex cloud-pull handoff, mocks additionally cover
active-instance initialization, SSH and write-path preparation before power-off,
rejection of an unprepared monitor, stopped-instance polling, restart plus SSH
probe before success or failure returns, cancellation before exact cleanup, and
same-session Codex command/result recovery. The tests assert that no monitor
starts before preparation, no uncertain Cloud Copy is posted twice, and no raw
data reaches the local run.

Resume mocks cover shutdown reuse with one SSH probe, released/missing/SSH-failed
replacement, uncertain-provider and failed-release safety, recorded fallback
capacity, replication/report rollback archives, early codegen infrastructure
resume, repeated cloud pull, report-completed no-op, power-off-before-report,
and persistent cleanup warnings. Tests assert that no safety failure creates a
second instance.

Codex replication mocks cover thread-ID extraction, explicit-session resume
with the same output schema and appended transcript, rejection of blank or
extra structured output, command/log/result persistence, nonzero command
handoff for debugging, validation-driven continuation, final-only power-off,
and unchanged one-turn behavior for other providers.

Preprocessing-audit mocks cover the compact JSON verdict/issue contract with
separate non-empty evidence, diagnosis, and required-fix fields; rejection of
the former combined error field; exhaustive issue-accumulation, root-cause, and
feature-propagation prompt requirements; legacy Markdown verdict reads;
audit-to-cohort-refinement routing; three-round exhaustion that continues to
planning; local and cloud permission boundaries; same-round technical retries;
and codegen remaining a single scientific stage.

Auto Research mocks cover input-representation, model, and training-strategy
implementation plans; declared changed-file boundaries; preservation of data,
final prediction target, evaluator-facing output, and evaluation contracts; and
the ordered six-aspect refinement audit. They also cover the campaign-wide
candidate pool, six-candidate review, three-candidate selection, selected-idea
removal, and reuse of the remaining candidates in later rounds. Cloud-backed
coverage verifies inherited provider/drive configuration without a local data
mount, copied base inventory, base-resource preference through the selected
provider reference, initial prepare/local-monitor/power-off/same-session resume, one
campaign instance across ideas and rounds, per-command power-on and `finally`
power-off before agent resume, replacement resume with a fresh offline pull and
inventory verification, failure-only power-off, and final-only release.

A real cloud-drive E2E is manual and billable. Use an isolated disposable
instance, run the selected adapter's `cloud-pull` for a disposable dataset,
compare source and materialized file/byte aggregates, confirm that no raw data
reached the local run, and release the instance on success or failure. A timeout
is a failed E2E and still requires release. Provider-specific procedures live in
the selected skill reference.
