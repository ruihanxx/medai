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
completed experiments, dataset transfers, remote provisioning, or remote
lifecycle actions merely because validation failed. Resolve the reported
contract error, check the complete artifact set rather than only the named
symptom, and return only after the corrected artifacts satisfy the original
stage instructions. If the error is caused by an irrecoverable external or
infrastructure condition, surface that condition explicitly instead of
fabricating a valid-looking artifact.
