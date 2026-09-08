# Auto Research validation command result

The orchestration attempt for the operation requested by this Codex session
reached a terminal state. Its result is at `{{ command_result_path }}` and its
complete combined log is at `{{ command_log_path }}`. It exited with code
{{ exit_code }} after {{ duration_seconds }} seconds. Local orchestration has
powered the campaign instance off before resuming this session.

Retain the original terminal-evidence delegation policy. Readers may diagnose
saved local results but cannot run remote work or repair audited source. The
parent owns any permitted environment repair and the next operation; finish
all readers before returning it.

The required local validation artifacts are not yet complete:

```text
{{ artifact_validation_error }}
```

Read the result and relevant log sections, then return exactly one next
`remote_exec` or `download` operation using the required output schema. For
an operation that did not run because setup failed, do not infer its outcome;
repair the environment when justified and submit the operation again. For
`remote_exec`, return only foreground Bash that should run inside the
synchronized remote codebase; never include an SSH, provider-adapter, Docker,
or lifecycle wrapper, and persist outputs only in the supplied remote artifact
directory. For `download`, request only a model, metric, log, or
aggregate-evidence path inside that remote artifact directory and a destination
inside the declared local artifact directory. Local orchestration will select a
usable campaign instance, synchronize the local mother code and environment,
execute the operation, power the pool off at terminal completion, and resume
this session again.

Reuse the validated local mother-environment definition unchanged by default.
If this or an earlier persisted operation result and log demonstrate a specific
missing dependency or runtime defect, you may make the smallest necessary
repair to its `setup.sh` and `environment.json`; do not modify orchestration-owned
`setup.log` or `validation.json`. Orchestration will treat changed hashes as an
unvalidated environment revision and must rerun setup successfully before the
next operation. Do not run or monitor remote work directly in this turn, modify
audited code, create or release an instance, rematerialize data, or download raw
or row-level dataset content.
