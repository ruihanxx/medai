# Auto Research experiment-plan agent

Create the execution plan for refinement `{{ idea_id }}` in every frozen
experiment.

## Inputs

- Frozen experiment contracts: `{{ contracts_path }}`
- Frozen result-blind experiment weights: `{{ weights_path }}`
- Implementation plan: `{{ implementation_plan_path }}`
- Passing audit: `{{ audit_path }}`
- Writable idea codebase: `{{ codebase_dir }}`
- Remote-compute state path: `{{ computation_provider_state_path }}`

## Task

For each experiment, inspect the audited code and implementation file lists,
identify the refinement-only entry point, and plan only the commands required
to run and evaluate it. The completed replicate run is the baseline; do not
plan any baseline command.

## Output

Write `{{ experiment_plan_path }}`:

```json
{
  "environment": {
    "language": "implementation language",
    "key_dependencies": ["existing dependencies"],
    "setup_hints": "environment and hardware setup"
  },
  "experiments": [
    {
      "experiment_id": "E1",
      "steps": [
        {
          "id": 1,
          "description": "run or evaluate the refinement",
          "command_hint": "refinement-only command",
          "expected_outcome": "actual output path or shape, never a target value",
          "verifies": ["primary metric or refinement output"]
        }
      ]
    }
  ]
}
```

Add the existing optional `remote_compute` object only when remote compute is
required. Copy its required `state_path`, `remote_working_dir`, and
`remote_dataset_dir` fields; additional provider and execution fields are
allowed.

## Constraints

- Include every frozen experiment exactly once and in order.
- Use 1–10 ordered refinement-only steps per experiment.
- Never rerun the replicated baseline.
- Do not modify the audited source, alter the fixed data, prediction target, or
  evaluation contracts, or write target metric values.
- Write only the requested JSON plan.
