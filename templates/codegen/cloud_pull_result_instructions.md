# Cloud materialization result

The foreground cloud monitor requested by this Codex session has reached a
terminal local result. Its saved result is at `{{ command_result_path }}` and
its complete combined local log is at `{{ command_log_path }}`. It exited with
code {{ exit_code }} after {{ duration_seconds }} seconds.

Cloud materialization is still incomplete:

```text
{{ artifact_validation_error }}
```

Read the result, relevant log sections, and the non-secret provider state at
`{{ computation_provider_state_path }}`. Do not inspect raw cloud data or
continue code generation. Perform only bounded, safe diagnostics. If another
reviewed cloud-materialization action is required, including `--prepare` before
another `--monitor`, return `status: command`, a non-empty foreground adapter
command, and `error: null`. Do not run the returned command in this turn.
Orchestration runs it to a terminal result while this Codex process is absent,
saves its complete log and result, and resumes this same session. Reread
canonical provider state after every resume. Never launch overlapping command
executions or inspect provider state while a handed-off command is running.
Before returning any structured result, ensure every command or tool call from
the current turn has reached a terminal state.

If an external prerequisite is irrecoverably unavailable, return `status:
blocked`, `command: null`, and a non-empty `error`. If bounded provider or
technical recovery fails, return `status: failed`, `command: null`, and a
non-empty `error`. Do not use a shell `exit 1` or continue without completed
data.
