# Resume after artifact validation failure

Your previous `{{ stage_name }}` turn returned successfully, but orchestration
rejected stage completion because its owned artifacts did not validate.

The current validation error is:

```text
{{ artifact_validation_error }}
```

Inspect and repair the existing stage artifacts in place:
{% for artifact_path in artifact_paths %}
- `{{ artifact_path }}`
{% endfor %}

Continue this same conversation and preserve all valid work already completed.
Modify only artifacts owned by the original stage instructions. Do not repeat
completed computation, dataset transfers, remote provisioning, or remote
lifecycle actions merely because validation failed. Resolve the reported
contract error, check the complete artifact set rather than only the named
symptom, and return only after the corrected artifacts satisfy the original
stage instructions. If the error is caused by an irrecoverable external or
infrastructure condition, surface that condition explicitly instead of
fabricating a valid-looking artifact.
{% if experiment_handoff|default(false) %}

Do not launch or monitor an experiment directly during this repair turn. If a
new experiment is genuinely required, return the structured replication
experiment handoff with its command, hard timeout, lightweight progress command,
and exact graceful-stop command. Otherwise return `status: completed` with all
command, timeout, and error fields null only when the owned artifacts are ready
for validation. Return `blocked` or `failed` with null command and timeout fields
and a non-empty `error` for a terminal condition.
{% elif structured_stage_result|default(false) %}

End this repair turn with exactly the structured result required by the supplied
output schema. Return `{"status":"completed","error":null}` only when the owned
artifacts are ready for validation. Return `blocked` or `failed` with a non-empty
`error` for a terminal external or technical condition. Do not use a shell
`exit 1` as a stage result.
{% endif %}
