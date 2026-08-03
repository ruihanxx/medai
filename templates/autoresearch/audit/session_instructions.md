# Auto Research codegen audit agent

Audit refinement `{{ idea_id }}` without modifying its code.

## Inputs

- Frozen experiment contracts: `{{ contracts_path }}`
- Read-only base codebase: `{{ base_codebase_dir }}`
- Refined idea codebase: `{{ codebase_dir }}`
- Implementation plan: `{{ implementation_plan_path }}`

## Task

Compare the base and refined code. Confirm that all changes are limited to a new
standalone model and the minimum wiring needed to embed it. For every experiment
in the frozen contracts, check `input`, `target`, `output`, `training`, and
`evaluation` exactly once and in that order.

## Output

Write `{{ audit_path }}`:

```json
{
  "idea_id": "{{ idea_id }}",
  "verdict": "pass",
  "model_only": true,
  "scope_evidence": ["exact changed-file evidence"],
  "scope_issue": null,
  "checks": [
    {
      "experiment_id": "E1",
      "aspect": "input",
      "verdict": "pass",
      "evidence": ["path and exact comparison"],
      "issue": null
    }
  ],
  "required_fixes": []
}
```

For a scope violation, set `model_only` to false and explain `scope_issue`.
For each failed contract check, explain `issue` and include an exact required
fix. A passing audit has no issues or required fixes.

## Constraints

- Include all five checks for every experiment, in contract order.
- Trust the frozen replicate contracts; do not reinterpret them from the paper.
- Do not edit either codebase.
- Write only the requested audit JSON.
