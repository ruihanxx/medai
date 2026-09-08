# Data-availability provider command result

The foreground provider command requested by this Codex session has reached a
terminal local result while the session was paused. Its saved result is at
`{{ command_result_path }}` and its complete combined log is at
`{{ command_log_path }}`. It exited with code {{ exit_code }} after
{{ duration_seconds }} seconds.

Retain the original source-evidence delegation policy. The parent processes
this provider result and owns the next operation; readers may inspect saved
evidence only, and must finish before another handoff.

Continue the original data-availability task. Read the bounded non-secret log
evidence and reread the canonical provider state at
`{{ computation_provider_state_path }}`; never infer the outcome from state
captured before this command ran. Do not blindly repeat a billable or ambiguous
operation.

If another reviewed state-changing provider or cloud-materialization operation,
or any remote source inspection, is required, return exactly
`{"status":"command","command":"<foreground adapter command>","error":null}`
and do not run it in this turn. Combine checks that inspect the same remote source
into one command.
Never launch overlapping command executions or an equivalent replacement before
the prior execution reaches a terminal state. Wait on or poll the same execution
handle. Before returning any structured result, ensure every command or tool call
from the current turn has reached a terminal state.
Once materialization and read-only source inspection are complete, write the
required availability report and return
`{"status":"completed","command":null,"error":null}`. A terminal provider
failure normally becomes source `unknown` with non-secret evidence in the
report. Use `blocked` or `failed` with `command:null` and a non-empty `error`
only when the original stage cannot produce a valid report.
