# Replication command result

The experiment you handed to orchestration is now terminal. Its structured
result is at `{{ command_result_path }}` and its complete combined log is at
`{{ command_log_path }}`. The orchestration outcome exit code is
{{ exit_code }} after {{ duration_seconds }} seconds, against the requested hard
timeout of {{ hard_timeout_seconds }} seconds.

{% if timed_out %}
The experiment exceeded its hard timeout. Orchestration ran the exact graceful
stop command before settling its local process group. The stop-command result,
including its own log path, is at `{{ graceful_stop_result_path }}`.
{% endif %}

The lightweight progress-command result is at `{{ progress_result_path }}` and
its complete log is at `{{ progress_log_path }}`. Its bounded inline output is:

```json
{{ progress_json }}
```

Continue the original replication task. Read the result paths and only the
relevant bounded log sections. If the experiment timed out, use its elapsed
time and progress evidence to determine whether the implementation or resource
configuration is inefficient before changing it; preserve paper-prescribed
semantics and full scale. Record completed work and real artifact paths in the
canonical replication files.

Do not launch or monitor an experiment directly in this resumed turn. If another
experiment is required, return one new `status: command` handoff with a
foreground experiment command, positive `hard_timeout_seconds`, lightweight
progress command, exact graceful-stop command, and `error: null`. When all work
and artifacts are complete, return `status: completed` with all command,
timeout, and error fields null. Use `blocked` or `failed` only for a terminal
condition with a non-empty error.
