# Auto Research cloud materialization result

The foreground cloud monitor requested by this Codex session has reached a
terminal local result. Its saved result is at `{{ command_result_path }}` and
its complete combined local log is at `{{ command_log_path }}`. It exited with
code {{ exit_code }} after {{ duration_seconds }} seconds.

Cloud materialization is still incomplete:

```text
{{ artifact_validation_error }}
```

Read the result, relevant log sections, and the non-secret provider state at
`{{ computation_provider_state_path }}`. Perform only bounded, safe diagnostics.
Before returning, repeat the selected drive reference's complete preparation
procedure and leave the instance stopped, then return exactly one next
non-empty foreground monitor Bash command using the required output schema.
Do not inspect raw cloud data or continue experiment planning while state is
incomplete. Exit nonzero when safe recovery is not possible.
