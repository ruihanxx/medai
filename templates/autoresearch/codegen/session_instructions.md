# Auto Research codegen agent

Implement refinement `{{ idea_id }}` in its isolated writable codebase.

## Inputs

- All ideas for the round: `{{ ideas_path }}`
- Eligibility and fixed anchors: `{{ eligibility_path }}`
- Read-only base codebase: `{{ base_codebase_dir }}`
- Writable idea codebase: `{{ codebase_dir }}`
- Data: `{{ data_dir or "not supplied" }}`
{% if repair_audit_path %}
- Failed audit requiring one repair: `{{ repair_audit_path }}`
{% endif %}

## Task

First write the implementation plan below, then implement only this idea. Keep
the original baseline entry point and semantics available; prefer additive
refinement modules and make only necessary shared-code changes.

## Output

Write `{{ implementation_plan_path }}`:

```json
{
  "idea_id": "{{ idea_id }}",
  "summary": "specific refinement",
  "change_points": [
    {"path": "relative file", "change": "exact change", "rationale": "why"}
  ],
  "baseline_entry_points": ["unchanged baseline command or entry point"],
  "refinement_entry_points": ["new refinement command or entry point"],
  "preserved_anchors": [
    "task_and_prediction_target",
    "dataset_cohort_and_io",
    "metrics_and_protocol",
    "baseline_method"
  ]
}
```

## Constraints

- Modify only `{{ codebase_dir }}` and the requested plan artifact.
- Do not modify the read-only base codebase or source data.
- Do not run the full experiment; that is a later stage.
