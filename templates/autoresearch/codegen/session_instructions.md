# Auto Research codegen agent

Implement the standalone model refinement `{{ idea_id }}` and embed it into
every existing replicated experiment.

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

Inspect the paper, frozen contracts, and replicated code. First design and add
the refinement as a standalone new model implementation. Only after that model
is complete, make the minimum wiring changes needed to select and run it in
every existing experiment. Use each experiment's existing inputs and return the
exact outputs its existing training and evaluation code expects.

Before editing code, write the implementation plan below. New model files must
not replace files from the base codebase. Integration changes may touch only the
existing `integration_paths` recorded in the frozen contracts.

## Output

Write `{{ implementation_plan_path }}`:

```json
{
  "idea_id": "{{ idea_id }}",
  "summary": "specific standalone model refinement",
  "model_description": "architecture and interface of the new model",
  "new_model_files": ["relative/path/to/new_refined_model.py"],
  "experiment_integrations": [
    {
      "experiment_id": "E1",
      "integration_changes": [
        {
          "path": "existing experiment integration file",
          "change": "minimal model-selection wiring",
          "rationale": "make the new model selectable without changing the experiment"
        }
      ],
      "baseline_entry_points": ["unchanged baseline command"],
      "refinement_entry_points": ["command that runs only the new model"]
    }
  ]
}
```

## Constraints

- Include every frozen experiment exactly once and in order.
- Modify only new model files and declared experiment integration files inside
  `{{ codebase_dir }}`.
- Do not change existing model implementations, data/cohort processing, inputs,
  targets, outputs, loss, optimizer, training loops, inference strategy,
  augmentation, metrics, evaluation, or baseline behavior.
- Keep all baseline entry points runnable.
- Do not run full experiments; that is a later stage.
- Do not modify the read-only base codebase or source data.
