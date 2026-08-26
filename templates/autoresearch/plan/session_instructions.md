# Refined-V execution planner

Plan refinement `{{ idea_id }}` using:

- contracts/weights: `{{ contracts_path }}`, `{{ weights_path }}`
- refinement graph: `{{ refinement_graph_path }}`
- implementation/audit: `{{ implementation_plan_path }}`, `{{ audit_path }}`
- audited codebase: `{{ codebase_dir }}`

Create one validation entry for every new refined V corresponding to a
positive-weight baseline V, in contract order. Do not include zero-weight V
nodes. Execute only new refinement nodes and the full Cartesian product of each
refined V. Reuse frozen baseline values from the base run; never invoke a
baseline entry point.

Write `{{ validation_plan_path }}`:

```json
{
  "environment": {
    "language": "Python",
    "key_dependencies": [],
    "setup_hints": "reproducible environment"
  },
  "validations": [
    {
      "validation_id": "V_refined_1",
      "baseline_validation_id": "V1",
      "steps": [
        {
          "id": 1,
          "description": "execute refinement-only path and frozen evaluator",
          "command_hint": "python ...",
          "expected_outcome": "numeric metric and evidence",
          "verifies": ["M_refined_1", "V_refined_1"]
        }
      ]
    }
  ],
  "remote_compute": null
}
```

Use 1–10 ordered steps per refined V. `verifies` uses refinement node IDs.
Commands must write artifacts under `{{ codebase_dir }}` or
`{{ validation_dir }}` and must not modify audited source during execution.

{% if cloud_drive_enabled %}
Follow `{{ computation_provider_reference }}` and `{{ drive_reference }}` and
reuse `{{ computation_provider_state_path }}`. Keep raw data remote and plan
downloads only for aggregate result/evidence artifacts. Never reduce scale to
fit weaker resources.
{% endif %}
