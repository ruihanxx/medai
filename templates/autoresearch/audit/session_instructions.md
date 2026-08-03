# Auto Research codegen audit agent

Audit refinement `{{ idea_id }}` without modifying its code.

## Inputs

- Eligibility and fixed anchors: `{{ eligibility_path }}`
- Read-only base codebase: `{{ base_codebase_dir }}`
- Refined idea codebase: `{{ codebase_dir }}`
- Implementation plan: `{{ implementation_plan_path }}`

## Task

Compare the base and refined code. Check exactly the four anchor categories
below and nothing beyond this audit scope.

## Output

Write `{{ audit_path }}`:

```json
{
  "idea_id": "{{ idea_id }}",
  "verdict": "pass or fail",
  "checks": [
    {"anchor": "task_and_prediction_target", "verdict": "pass or fail", "evidence": ["path/detail"], "issue": null},
    {"anchor": "dataset_cohort_and_io", "verdict": "pass or fail", "evidence": ["path/detail"], "issue": null},
    {"anchor": "metrics_and_protocol", "verdict": "pass or fail", "evidence": ["path/detail"], "issue": null},
    {"anchor": "baseline_method", "verdict": "pass or fail", "evidence": ["path/detail"], "issue": null}
  ],
  "required_fixes": []
}
```

For each failed check, replace `issue` with the concrete violation and include
at least one exact fix. A passing audit has no required fixes.

## Constraints

- Do not edit either codebase.
- Write only the requested audit JSON.
