# Auto Research refinement-codegen agent

Implement standalone refinement `{{ idea_id }}` in the writable idea codebase
and integrate it into every completed replication experiment.
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
- Distinguish method inputs from reported outputs. Never copy a paper or
  baseline result value into the implementation; results must be computed.
- Inspect only what is needed to understand and implement this idea. Do not
  modify the read-only base codebase or source data.
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

#### Plan constraints

- Include every frozen experiment exactly once and in contract order.
- List each applicable refinement type once. Allowed values are
  `input_representation`, `model`, and `training_strategy`.
- Declare every new refinement file and every existing file that will change.
  Existing-file changes may use only the matching contract-declared
  `input_representation_paths`, `training_paths`, or `integration_paths`, with
  aspect `input_representation`, `training_strategy`, or `integration`.
- A model refinement must use at least one new file and must not replace or
  mutate the baseline model. A representation- or training-only refinement may
  use no new file when its implementation fits entirely within declared paths.
- Record unchanged baseline entry points and distinct refinement-only entry
  points for every experiment. Do not plan a full experiment run.

### 3. Implement

Implement the plan module by module. Prefer the existing codebase's language,
framework, configuration, naming, and dependency conventions. Add standalone
refinement files where planned, then make only the minimum declared wiring or
scoped representation/training changes required to run the idea in every
experiment.

#### Implement constraints

- Modify only the declared new files and declared contract-eligible existing
  files inside `{{ codebase_dir }}`. Keep the implementation plan synchronized
  with the final code; never use a plan update to conceal an out-of-scope edit.
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
