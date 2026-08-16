# Auto Research refinement-codegen agent

Implement standalone refinement `{{ idea_id }}` and embed it into every existing
replicated experiment.

## Inputs

- Paper Markdown: `{{ paper_markdown }}`
- All ideas for the round: `{{ ideas_path }}`
- Eligibility and research brief: `{{ eligibility_path }}`
- Frozen experiment contracts: `{{ contracts_path }}`
- Experiment definitions: `{{ experiments_path }}`
- Base codegen and replication plans: `{{ base_codegen_plan_path }}`,
  `{{ base_replicate_plan_path }}`
- Read-only base codebase: `{{ base_codebase_dir }}`
- Writable idea codebase: `{{ codebase_dir }}`
{% if repair_audit_path %}
- Failed audit requiring one repair: `{{ repair_audit_path }}`
{% endif %}

## Task

Inspect the paper, refinement contracts, and replicated code. Design the
input-representation, model, or training-strategy refinement, using new
standalone files when the implementation warrants them. Make only the minimum
declared changes needed to select and run it in every existing experiment.
Preserve the fixed data, prediction outcome, evaluator-facing outputs, and
evaluation protocol.

Before editing code, write the implementation plan below. Any new refinement
files must not replace files from the base codebase. Existing-file changes may
touch only the corresponding `input_representation_paths`, `training_paths`, or
`integration_paths` recorded in the contracts.

## Output

Write `{{ implementation_plan_path }}`:

```json
{
  "idea_id": "{{ idea_id }}",
  "summary": "specific standalone refinement",
  "refinement_types": ["training_strategy"],
  "refinement_description": "mechanism, implementation, and executable interface",
  "new_refinement_files": ["relative/path/to/new_refinement.py"],
  "experiment_integrations": [
    {
      "experiment_id": "E1",
      "refinement_changes": [
        {
          "path": "contract-declared existing file",
          "aspect": "training_strategy",
          "change": "minimal refinement wiring or scoped implementation change",
          "rationale": "make the refinement selectable while preserving the baseline"
        }
      ],
      "baseline_entry_points": ["unchanged baseline command"],
      "refinement_entry_points": ["command that runs only the refinement"]
    }
  ]
}
```

## Constraints

- Include every frozen experiment exactly once and in order.
- List each applicable refinement type once. Allowed values are
  `input_representation`, `model`, and `training_strategy`; allowed existing-file
  change aspects are `input_representation`, `training_strategy`, and
  `integration`.
- Modify only new refinement files and the contract-declared existing files
  listed in the implementation plan inside `{{ codebase_dir }}`.
- A model refinement must use at least one new refinement file. A representation
  or training-only refinement may use an empty `new_refinement_files` list when
  it is implemented wholly in declared existing paths.
- Do not replace or mutate the baseline model for a model-side refinement. A
  shared existing file may change only for its declared representation,
  training, or integration responsibility, and baseline behavior must remain
  available.
- Do not change dataset/cohort membership, train/validation/test assignment,
  information availability at prediction time, final prediction outcome or
  horizon, evaluator-facing output, metrics, or evaluation protocol.
- Input-representation refinements may change feature construction or encoding
  only from the fixed available inputs and without introducing post-outcome or
  split leakage.
- Training-strategy refinements may change training targets, loss/objective,
  sampling or balancing, augmentation, optimization, pretraining, and training
  logic. They must preserve the final prediction task, use validation/test data
  only through the existing protocol, and keep refinement outputs compatible
  with the existing evaluator.
- External pretraining is permitted only as a declared training strategy. It
  must not alter the downstream experiment dataset, cohort, or split, expose
  evaluation examples, or introduce unavailable prediction-time information.
- Keep all baseline entry points runnable.
- Do not run full experiments; that is a later stage.
- Do not modify the read-only base codebase or source data.
