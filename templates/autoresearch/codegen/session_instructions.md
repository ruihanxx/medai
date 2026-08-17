# Auto Research refinement-codegen agent

Implement standalone refinement `{{ idea_id }}` in the writable idea codebase
and integrate it into every frozen strict prediction experiment. Ignore
uncontracted statistical experiments in the paper and base codebase.
{% if repair_audit_path %}
This is the single permitted repair after a failed audit. Preserve valid work,
read every required fix at `{{ repair_audit_path }}`, and rerun the complete
workflow below against the repaired implementation.
{% endif %}

## Inputs

- Writable idea codebase: `{{ codebase_dir }}`
- Read-only base codebase: `{{ base_codebase_dir }}`
- Paper Markdown: `{{ paper_markdown }}`
- Ideas for the round: `{{ ideas_path }}`
- Eligibility decision and research brief: `{{ eligibility_path }}`
- Frozen experiment contracts: `{{ contracts_path }}`
- Experiment definitions: `{{ experiments_path }}`
- Base codegen and replication plans: `{{ base_codegen_plan_path }}`,
  `{{ base_replicate_plan_path }}`
- Implementation plan to write: `{{ implementation_plan_path }}`
{% if repair_audit_path %}
- Failed audit to repair: `{{ repair_audit_path }}`
{% endif %}

## Workflow

Follow these four steps in order.

### 1. Explore

First read and understand the writable codebase: trace its baseline entry
points, data flow, input representation, model, training logic, evaluator, and
the integration shared by the frozen experiments. Then read the paper and the
selected `{{ idea_id }}` in the round idea artifact. Use the research brief,
experiment definitions, base plans, and frozen contracts to determine how the
idea can be added to the existing implementation.

#### Explore constraints

- Treat the completed replicate code and frozen contracts as authoritative; do
  not reassess or repair whether the baseline matches the paper.
- Use experiment definitions only for the IDs present in the frozen contracts;
  uncontracted statistical experiments are outside Auto Research.
- Distinguish method inputs from reported outputs. Never copy a paper or
  baseline result value into the implementation; results must be computed.
- Inspect only what is needed to understand and implement this idea. Do not
  modify the read-only base codebase or source data.
- Treat replication intermediates as unavailable by default. The completed
  replicate may preserve the codebase, logs, aggregate evidence, and explicitly
  supplied artifacts, but it does not preserve cohort tables, feature tables,
  split files, caches, checkpoints, temporary output roots, or model state.
  The refinement must not depend on any such base-run path. When it needs
  deterministic preprocessing from the fixed raw inputs, implement that work in
  the refinement-owned execution path without invoking a baseline entry point.
- On a repair attempt, diagnose every failed audit check before changing the
  implementation.

### 2. Plan

Choose the smallest implementation that fits the existing computational stack
and makes the refinement independently selectable. Before editing code, write
`{{ implementation_plan_path }}`:

```json
{
  "idea_id": "{{ idea_id }}",
  "summary": "specific standalone refinement",
  "refinement_types": ["training_strategy"],
  "refinement_description": "mechanism, implementation, and executable interface",
  "refine_file_list": [
    {
      "file_path": "contract-declared/existing_file.py",
      "change": "minimal change and how it integrates the refinement while preserving baseline behavior"
    }
  ],
  "new_file_list": [
    {
      "file_path": "relative/path/to/new_refinement.py",
      "change": "new file responsibility, implementation, and interface"
    }
  ]
}
```

Every `file_path` above is relative to `{{ codebase_dir }}`. Files in
`refine_file_list` are existing files in this idea's independent writable copy;
files in `new_file_list` are created in that same copy. Never write to or modify
the previous read-only codebase at `{{ base_codebase_dir }}`.

Codegen does not run full experiments. The later plan and experiment stages
must execute only the newly added refinement variant for each frozen experiment;
they must not rerun any old existing or baseline experiment entry point.

#### Plan constraints

- List each applicable refinement type once. Allowed values are
  `input_representation`, `model`, and `training_strategy`.
- Put every existing file that will change in `refine_file_list`. These paths
  may come only from the contract-declared `input_representation_paths`,
  `training_paths`, or `integration_paths` across the frozen experiments.
- Put every file that will be added in `new_file_list`. A model refinement must
  add at least one new file and must not replace or mutate the baseline model.
- File paths must be unique and cannot appear in both lists. At least one list
  must be non-empty.
- Absolute paths, `..` traversal, and any path that resolves outside
  `{{ codebase_dir }}` are prohibited.
- Each `change` must state exactly how the existing file will change or what the
  new file will implement, including its role in integrating the refinement
  into the relevant frozen experiments while preserving baseline behavior.
- Account for every frozen experiment across the declared file changes. Do not
  plan a full experiment run.

### 3. Implement

Implement the plan module by module. Prefer the existing codebase's language,
framework, configuration, naming, and dependency conventions. Add standalone
refinement files where planned, then make only the minimum declared wiring or
scoped representation/training changes required to run the idea in every
experiment.

#### Implement constraints

- Modify only files in `refine_file_list` and add only files in `new_file_list`
  inside `{{ codebase_dir }}`. Keep the implementation plan synchronized with
  the final code; never use a plan update to conceal an out-of-scope edit.
- Preserve baseline behavior and keep every baseline entry point runnable.
- Do not change the downstream dataset, cohort membership, train/validation/test
  assignment, prediction-time information availability, final prediction
  outcome or horizon, evaluator-facing output, metrics, or evaluation protocol.
- Input-representation changes may derive features or encodings only from the
  fixed prediction-time inputs, without outcome or split leakage.
- Training changes may alter training targets, loss/objective, sampling,
  balancing, augmentation, optimization, pretraining, or training logic only
  while preserving the final prediction task and evaluator compatibility.
  Validation and test information may be used only through the frozen protocol.
- Declare external pretraining as a training strategy. It must not alter the
  downstream dataset/cohort/split, expose evaluation examples, or introduce
  information unavailable at prediction time.
- Do not hardcode computed results, fabricate outputs, or run full training or
  evaluation. Full experiments belong to the later experiment stage.

### 4. Auto Research self-audit

Re-read the frozen contracts and final implementation plan, then inspect the
actual diff between the base and idea codebases. Repair any mismatch before
finishing. Perform lightweight, non-experimental checks such as imports,
parsing, or entry-point help when useful.

#### Self-audit constraints

- Confirm the implementation exactly matches the plan: all declared changes
  exist, no undeclared file changed, new files are refinement-owned, and every
  frozen experiment has a working refinement entry point.
- Audit every experiment across `data`, `prediction_target`,
  `input_representation`, `output`, `training`, and `evaluation`. Confirm that
  permitted representation or training changes stay within their frozen Auto
  Research boundaries and introduce no leakage.
- Re-scan numerical constants and configuration: methodological inputs may be
  configured, but paper-reported, baseline, or target results must be computed.
- Check imports and dependencies affected by the refinement without running the
  methodology end to end.
- On a repair attempt, confirm every required fix from the failed audit is
  implemented and that the repair introduced no new contract violation.
- Do not modify the base codebase or source data, and do not execute baseline or
  full refinement experiments during self-audit.
