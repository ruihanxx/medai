# Resume incomplete preprocessing audit

Your previous turn returned successfully, but orchestration rejected stage
completion because the required audit artifact did not validate:

`{{ artifact_validation_error }}`

Continue this same audit conversation and preserve all valid work already
completed. Do not treat a progress message or a successful provider turn as
stage completion.

Retain the original audit delegation policy. Reuse completed evidence checks;
assign only substantial unresolved questions after existing processes settle.
The parent still owns complete coverage and the final audit report.

- Inspect the existing audit processes and artifacts before starting work again.
{% if remote_audit_dir %}
- Reuse the existing remote audit at `{{ remote_audit_dir }}`. Do not create,
  replace, stop, power off, or release a remote instance. If the process you
  launched is still active, continue monitoring it until it reaches a terminal
  state. If it finished, retrieve only the permitted aggregate evidence and
  logs.
{% endif %}
- Reuse completed checks and rerun only work whose completion is uncertain.
- Resolve the validation error and write or replace the complete compact report
  at `{{ report_path }}`. Supporting aggregate artifacts remain under
  `{{ results_dir }}`.
- Do not return another progress-only response while the report is absent or
  invalid. Complete the report only after the applicable audit checks finish.
- If an irrecoverable provider or audit-infrastructure failure prevents a
  complete verdict, surface that technical failure explicitly; never fabricate
  a scientific PASS or FAIL.

The canonical remote-compute state remains
`{{ remote_compute_state_path }}`. Resume the incomplete audit now.
