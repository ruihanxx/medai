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
continue code generation. Perform only bounded, safe diagnostics. Before
returning, repeat the selected drive reference's complete initialized-instance,
SSH, target-path, permission, and stop preparation procedure, then return
exactly one next non-empty foreground monitor Bash command using the required
output schema. Do not run or monitor the returned command in this turn.

If recovery is not possible, make the Codex CLI exit nonzero rather than
returning a command or continuing without completed data.
