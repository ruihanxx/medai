# Auto Research experiment-contract agent

Extract the executable contract and permitted refinement boundary of every
replicated experiment before any refinement code is generated.

## Inputs

- Experiment definitions: `{{ experiments_path }}`
- Base codegen plan: `{{ codegen_plan_path }}`
- Base replication plan: `{{ replicate_plan_path }}`
- Completed read-only base codebase: `{{ base_codebase_dir }}`

## Task

Treat the completed replicate code as authoritative. For each experiment, trace
its actual entry points and code to identify the model implementation, input
representation, training procedure, and the files that wire them into the
experiment. Record both the immutable scientific/evaluation contracts and the
baseline representation, training target, loss, and training strategy that a
refinement may improve. Do not evaluate whether the replicated code agrees with
the paper; that work is already complete and is outside Auto Research.

## Output

Write `{{ contracts_path }}`:

```json
{
  "experiments": [
    {
      "experiment_id": "E1",
      "baseline_entry_points": ["existing command or entry point"],
      "model_implementation_paths": ["existing/model_file.py"],
      "input_representation_paths": ["existing/feature_or_input_file.py"],
      "training_paths": ["existing/training_file.py"],
      "integration_paths": ["existing/experiment_file.py"],
      "data_contract": "fixed downstream dataset, cohort, split, prediction-time information, and raw modalities",
      "prediction_target_contract": "fixed final prediction outcome and horizon evaluated by the experiment",
      "input_representation_contract": "baseline feature construction or representation from the code",
      "output_contract": "fixed evaluator-facing model output",
      "training_target_contract": "baseline target supplied to the training objective",
      "loss_contract": "baseline loss or objective from the code",
      "training_contract": "baseline sampling, augmentation, optimization, and training procedure",
      "evaluation_contract": "unchanged evaluation procedure from the code",
      "metrics": ["unchanged metric computed by the code"],
      "primary_metric": "actual primary metric used by the evaluator",
      "metric_direction": "higher"
    }
  ]
}
```

## Constraints

- Include every experiment exactly once and in input order.
- Paths must be relative paths to existing files in the base codebase.
- A path may appear in more than one path list when one file has multiple
  responsibilities; include every file that a permitted refinement may need to
  wire or minimally change.
- Use `"higher"` or `"lower"` for `metric_direction` according to the actual evaluator.
- Do not use result values to define a contract.
- Do not modify the base codebase or write implementation code.
- Write only the requested JSON artifact.
