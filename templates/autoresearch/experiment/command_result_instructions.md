# Auto Research experiment command result

The foreground command requested by this Codex session reached a terminal
state. Its result is at `{{ command_result_path }}` and its complete combined
log is at `{{ command_log_path }}`. It exited with code {{ exit_code }} after
{{ duration_seconds }} seconds. Local orchestration has powered the campaign
instance off before resuming this session.

The required local experiment artifacts are not yet complete:

```text
{{ artifact_validation_error }}
```

Read the result and relevant log sections, then return exactly one next
non-empty foreground Bash command using the required output schema. Local
orchestration will power on the same instance only while executing that command,
power it off at terminal completion, and resume this session again. Do not run
or monitor remote work directly in this turn, modify audited code, create or
release an instance, rematerialize data, or download raw dataset content.
