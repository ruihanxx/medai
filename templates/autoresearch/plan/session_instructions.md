# Auto Research experiment-plan agent

Create the execution plan for refinement `{{ idea_id }}`.

## Inputs

- Round ideas: `{{ ideas_path }}`
- Eligibility and anchors: `{{ eligibility_path }}`
- Implementation plan: `{{ implementation_plan_path }}`
- Passing audit: `{{ audit_path }}`
- Writable idea codebase: `{{ codebase_dir }}`
- Base replication log: `{{ base_replication_log }}`
- Remote-compute state path: `{{ computation_provider_state_path }}`

## Task

Plan the ordered commands and evidence needed to evaluate only this refinement
against the existing baseline evidence.

## Output

Write `{{ experiment_plan_path }}` with the same schema as a replicate plan:

```json
{
  "environment": {
    "language": "implementation language",
    "key_dependencies": ["main dependencies"],
    "setup_hints": "environment and hardware setup"
  },
  "steps": [
    {
      "id": 1,
      "description": "ordered step",
      "command_hint": "command to execute",
      "expected_outcome": "output shape or path, not a target value",
      "verifies": ["refinement or metric identifier"]
    }
  ]
}
```

Use 3–10 ordered steps. Add the existing optional `remote_compute` object from
the replicate-plan schema only when remote compute is required.

## Constraints

- Plan the refinement experiment only; the existing base evidence is the baseline.
- Keep every fixed anchor and write only the requested JSON plan.
