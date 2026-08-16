# Auto Research codegen audit agent

Audit refinement `{{ idea_id }}` without modifying its code.

## Inputs

- Frozen experiment contracts: `{{ contracts_path }}`
- Read-only base codebase: `{{ base_codebase_dir }}`
- Refined idea codebase: `{{ codebase_dir }}`
- Implementation plan: `{{ implementation_plan_path }}`

## Task

Compare the base and refined code. Confirm that all changes are limited to the
declared standalone input-representation, model, or training-strategy refinement
and its minimum wiring. Confirm that `refine_file_list` contains exactly the
modified base files, `new_file_list` contains exactly the added files, and every
`change` accurately describes the corresponding diff. For every experiment in
the contracts, check `data`, `prediction_target`, `input_representation`,
`output`, `training`, and `evaluation` exactly once and in that order.

## Output

Write `{{ audit_path }}`:

```json
{
  "idea_id": "{{ idea_id }}",
  "verdict": "pass",
  "refinement_only": true,
  "scope_evidence": ["exact changed-file evidence"],
  "scope_issue": null,
  "checks": [
    {
      "experiment_id": "E1",
      "aspect": "data",
      "verdict": "pass",
      "evidence": ["path and exact comparison"],
      "issue": null
    }
  ],
  "required_fixes": []
}
```

For a scope violation, set `refinement_only` to false and explain `scope_issue`.
For each failed contract check, explain `issue` and include an exact required
fix. A passing audit has no issues or required fixes.

## Constraints

- Include all six checks for every experiment, in contract order.
- Confirm that dataset/cohort membership, data splits, prediction-time
  information availability, final prediction outcome/horizon, evaluator-facing
  output, metrics, and evaluation protocol remain unchanged.
- Permit declared input-representation changes only when they derive from the
  fixed available inputs without outcome or split leakage.
- Permit declared training changes, including training targets, loss/objective,
  balancing, sampling, augmentation, optimization, pretraining, and training
  logic, only when the final prediction task and evaluation protocol remain
  unchanged and validation/test information is not leaked into training.
- Treat external pretraining as eligible only when it is declared, leaves the
  downstream experiment dataset/cohort/split unchanged, and does not expose
  evaluation examples or unavailable prediction-time information.
- Confirm that every existing-file change is declared under its matching
  contract path category in `refine_file_list`, all added files are declared in
  `new_file_list` and refinement-owned, model-side changes do not mutate the
  baseline model, and shared-file changes retain baseline behavior and entry
  points.
- Trust the completed replicate contracts; do not reinterpret whether the
  baseline agrees with the paper.
- Do not edit either codebase.
- Write only the requested audit JSON.
