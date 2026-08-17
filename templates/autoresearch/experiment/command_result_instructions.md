# Auto Research experiment command result

The orchestration-owned operation requested by this Codex session reached a
terminal state. Its result is at `{{ command_result_path }}` and its complete combined
log is at `{{ command_log_path }}`. It exited with code {{ exit_code }} after
{{ duration_seconds }} seconds. Local orchestration has powered the campaign
instance off before resuming this session.

The required local experiment artifacts are not yet complete:

```text
{{ artifact_validation_error }}
```

Read the result and relevant log sections, then return exactly one next
`remote_exec` or `download` operation using the required output schema. For
`remote_exec`, return only foreground Bash that should run inside the
synchronized remote codebase; never include an SSH, provider-adapter, Docker,
or lifecycle wrapper, and persist outputs only in the supplied remote artifact
directory. For `download`, request only a model, metric, log, or
aggregate-evidence path inside that remote artifact directory and a destination
inside the declared local artifact directory. Local orchestration will select a
usable campaign instance, synchronize the local mother code and environment,
execute the operation, power the pool off at terminal completion, and resume
this session again. Do not run or monitor remote work directly in this turn,
modify audited code, create or release an instance, rematerialize data, or
download raw or row-level dataset content.
