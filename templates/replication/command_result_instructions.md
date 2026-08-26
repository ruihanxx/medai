# Replication command result

The command you requested has now reached a terminal state. Its result is
recorded at `{{ command_result_path }}` and its complete combined local log is
at `{{ command_log_path }}`. It exited with code {{ exit_code }} after
{{ duration_seconds }} seconds.

The replication artifacts are not yet complete. The current validation error is:

```text
{{ artifact_validation_error }}
```

Read the result and any relevant log sections, inspect or repair the writable
codebase as needed, then return exactly one next non-empty bash command using
the required output schema. That command will again be executed and monitored
by local workflow orchestration. Do not launch or monitor a large validation run,
test, provider command, or remote job directly in this turn.
