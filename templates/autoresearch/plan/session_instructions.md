# Auto Research refined-V execution-plan agent

You are generating a step-by-step execution plan for refinement
`{{ idea_id }}` across every positive-weight contracted V. The refinement in
`{{ codebase_dir }}` has passed an independent codegen audit. Treat that audited
code as immutable and plan how to run and evaluate only the newly added
refinement variant.

## Inputs:

- Frozen positive-weight V contracts: `{{ contracts_path }}`
- Frozen result-blind V weights: `{{ weights_path }}`
- Complete refinement graph: `{{ refinement_graph_path }}`
- Implementation plan: `{{ implementation_plan_path }}`
- Passing audit: `{{ audit_path }}`
- Audited idea codebase: `{{ codebase_dir }}` (read-only while planning and
  executing validation)
{% if cloud_drive_enabled %}
- Cloud datasets: {% for dataset in cloud_datasets %}`{{ dataset }}`{% if not loop.last %}, {% endif %}{% endfor %} (drive provider: `{{ drive_provider }}`),
  available only through the completed read-only target in provider state.
- Selected provider reference: `{{ computation_provider_reference }}`
- Selected drive reference: `{{ drive_reference }}`
- Completed Replicate remote state:
  `{{ base_computation_provider_state_path }}`
{% else %}
- Data: `{{ data_dir or "not supplied" }}` (read-only)
{% endif %}
- Validation output directory: `{{ validation_dir }}`
- Remote-compute state, when remote compute was selected:
  `{{ computation_provider_state_path }}`

{% if cloud_drive_enabled %}
## Remote preparation

Remote compute is mandatory for this cloud-backed campaign. Read
`{{ skills_dir }}/computation_provider/SKILL.md`, the selected provider
reference, and the selected drive reference before any provider operation.
Reuse the campaign-owned state and its selected pool member when state already
exists; never create one instance per idea or round. Pool expansion is reserved
for orchestration after a provider-confirmed capacity conflict.

When no campaign state exists, read the completed Replicate remote state using
the provider-specific state description in the selected reference. Search for
its actual selected GPU model first and preserve its recorded count, per-GPU
memory, and CPU RAM as capacity floors. If no exact-model offer is available,
follow the selected provider reference's existing stronger-resource fallback
rule. Never select weaker resources or reduce refined-V validation scale.
Create the run-owned instance at the current campaign state path above, then
materialize the inherited dataset. The existing cloud inventory beside the
current state is the required baseline; materialization must match it exactly.
{% if cloud_pull_handoff and cloud_materialization_required %}

For this Codex turn, complete the selected drive reference's active-instance
preparation through its reviewed `cloud-pull --prepare` operation. It must prove
SSH and owned writable paths, then leave the instance stopped. Return exactly
one non-empty foreground monitor Bash command using the required output schema.
Do not run or monitor that command in this turn and do not write the validation
plan before local orchestration resumes this same session with completed cloud
state.
{% elif cloud_materialization_required %}

Complete the selected drive reference's materialization procedure directly and
continue only after provider state records the completed read-only target.
{% else %}

The campaign state already records completed materialization. Reuse it without
starting, replacing, or rematerializing the instance.
{% endif %}

Do not inspect raw cloud data while planning. Do not upload, download,
reauthorize, rematerialize, release, or replace an existing healthy instance.
{% endif %}

## Frozen Validation and Metric Artifacts

The completed Replicate run is the baseline. The contracts below freeze the
downstream data, prediction target, evaluator-facing output, metrics, and
evaluation protocol. They contain no target result values.

{% for validation in contracts.validations %}
{% set importance = weights.validations | selectattr("validation_id", "equalto", validation.validation_id) | first %}
- **Baseline V `{{ validation.validation_id }}`**
  - Frozen contract: {{ validation.frozen_contract | tojson }}
  - Baseline entry points (forbidden during refinement execution): {{ validation.baseline_entry_points | tojson }}
  - Evaluator-facing primary metric: {{ validation.primary_metric | tojson }}
  - Comparison rule: {{ validation.comparison_rule | tojson }}
  - Result-blind assessment weight: {{ importance.weight }}
{% endfor %}

The refinement graph must contain exactly one new V for each contract above,
mapped by `baseline_validation_id` and in this same order. Zero-weight Vs have
no contract and must not appear in this plan. Weights are used only by later
assessment; they never authorize skipping, downsizing, or simplifying a
contracted V.

## Replication-intermediate availability

Assume that replication intermediates were not saved. Only the raw dataset, the
audited idea codebase, and the base artifacts explicitly listed in this prompt
are available. In particular, do not assume the existence of a base cohort or
feature table, split file, cache, checkpoint, temporary output root, or model
state, even when the replicate code once wrote such a path. Do not plan to
upload or locate one. If the audited refinement needs deterministic
preprocessing, its refinement-owned entry point must reconstruct it from the
fixed raw inputs while preserving every frozen cohort, split, and prediction
boundary; it must not invoke a baseline entry point.

## Your Task

Explore the audited codebase and implementation file lists. For every frozen
V contract, locate its mapped refined V in `{{ refinement_graph_path }}`, identify
the actual refinement-only entry point and frozen evaluator,
then generate the concrete ordered steps required to:

1. **Prepare the environment** — reuse the implementation's existing dependency
   stack and declare any required hardware.
2. **Run the refinement path** — materialize only the new P/T/M nodes needed by
   the refined V and invoke the newly added variant at its audited intended scale.
3. **Evaluate the refinement** — use the frozen data, prediction target,
   evaluator-facing output, primary metric, comparison rule, and evaluation
   protocol to produce the complete refined-V Cartesian block.
4. **Collect outputs** — preserve the actual model, prediction, metric, figure,
   table, C transformation, or log artifacts needed for node updates and assessment.

For each step, provide:

- A clear description of what to do.
- A concrete command hint derived from an entry point that exists in the audited
  codebase.
- A **shape-prescriptive** `expected_outcome`: describe the actual output path,
  file or record structure, metric field names, types, or log format. Never
  include a paper-reported value, baseline value, target improvement, or
  assessment threshold.
- A `verifies` list containing only node IDs newly added by the refinement
  graph. A pure setup step may use an empty list; every result-producing step
  must identify the concrete new P/T/M/V/C product whose evidence depends on
  its output. Across all validation entries, cover every new graph node at least
  once and no base node. Use the contract's primary metric exactly in the
  description and expected output of its refined V step.

For every new node named in `verifies`, the description must name all direct
predecessor node IDs and concrete artifacts consumed, the node-local method,
and the concrete artifact/result produced. If a new node consumes an immutable
base P/M artifact that is not preserved from replication, the refinement-owned
entry point may deterministically reconstruct the frozen input from raw data,
but the plan must not invoke or verify the baseline entry point or mutate/update
the base node. Assign a shared new ancestor to its earliest contracted refined
V, materialize it once, and reuse its persistent artifact in later entries.

### Shape-prescriptive examples

GOOD (shape-prescriptive):

- "Produces `<refined_validation_id>/refinement_metrics.json` with field
  `<primary_metric>` containing the finite numeric value computed by the frozen
  evaluator."
- "Writes `<refined_validation_id>/predictions.<format>` with the identifiers and
  evaluator-facing prediction fields required by the frozen output contract."
- "Writes `<refined_validation_id>/model.<format>` and logs the corresponding metric
  artifact path after evaluation completes."

BAD (value-prescriptive or non-auditable — DO NOT do this):

- "The primary metric exceeds the baseline."
- "The refinement improves the score by at least 5%."
- "Run the refinement and inspect the results."

The validation agent must report what execution actually produces. A divergent,
unchanged, or worse refinement result is valid evidence; a copied or tuned target
value is not.

### Setup values are allowed

Method inputs already declared by the audited refinement, such as learning rate,
batch size, epoch count, seed, objective configuration, augmentation, or
pretraining configuration, are allowed in descriptions and command hints. They
tell the agent how to run the audited implementation; they are not result
targets. Do not invent, tune, or change these inputs while planning.

### Plan at the audited full scale — no pre-authorized reductions

Plan the refinement training at the scale implemented and audited for the idea,
and plan evaluation over the complete frozen dataset, cohort, split, metric set,
and evaluation protocol. Do not write reduced-scale fallbacks into the plan: no
toy subsets, fewer epochs or seeds, smaller models, shortened grids, or
`--quick`/`--fast` shortcuts. A lower V weight or a long runtime is
never a reason to reduce scale.

When a step is expensive, plan for efficiency at full scale instead: use the
codebase's vectorized or compiled path, use supported hardware acceleration, or
split work into resumable chunks without changing the scientific or evaluation
contract.
{% if gpu_info %}

**Hardware available for this plan:** a GPU is present in this environment:
{{ gpu_info }}. Steps whose implementation supports GPU acceleration should plan
to use it, and `setup_hints` should say so.
{% endif %}

## Scope

Plan only execution and evaluation of the audited refinement. Do not reassess
the paper, redesign or tune the idea, repair the code, rerun the baseline, or add
exploratory and ablation paths outside the frozen contracts.

## Rules

- Include every contracted refined V exactly once and in contract order.
- Use 1–10 ordered refinement-only steps per refined V. Order them logically:
  setup, execution, evaluation, then output validation.
- Plan only newly added graph nodes and the refinement variant for each contracted V.
  Never include or rerun an old existing or replicated baseline entry point.
- Use the frozen evaluator and cover every contract's primary metric. If one
  evaluator produces multiple frozen metrics, name every metric actually
  produced in the description and `expected_outcome`; `verifies` remains a list
  of new graph node IDs only.
- Do not modify the audited source or source data. Do not alter the frozen data,
  cohort, split, prediction target, evaluator-facing output, metrics, or
  evaluation protocol.
- Commands must write validation artifacts only under `{{ codebase_dir }}/` or
  `{{ validation_dir }}/`. Do not write them beside the pipeline-managed plan at
  `{{ validation_plan_path }}`, into another pipeline stage, or into the base
  run.
- Write every command hint as the inner foreground command to execute from the
  synchronized remote codebase. Do not include SSH, provider-adapter, Docker,
  power, instance, upload, download, or lifecycle wrappers; orchestration owns
  those operations.
- For remote compute, write persistent command outputs beneath
  `<remote_working_dir>/artifacts/{{ idea_id }}`. The validation runtime exposes
  that exact path as `MEDAI_AUTORESEARCH_ARTIFACT_DIR`; the synchronized remote
  codebase is replaced before every operation and must contain source only.
- Never include paper-reported, baseline, target, or threshold result values in
  `expected_outcome`, descriptions, command hints, or setup hints.
- Write only the requested JSON plan.

## Output

Save the plan to `{{ validation_plan_path }}` with this format:

```json
{
  "environment": {
    "language": "the language(s) the audited implementation actually uses",
    "key_dependencies": ["existing", "runtime", "dependencies"],
    "setup_hints": "Existing environment and hardware required for full-scale refinement execution; never pre-authorize a reduced-scale run"
  },
  "validations": [
    {
      "validation_id": "V_refined_1",
      "baseline_validation_id": "V1",
      "steps": [
        {
          "id": 1,
          "description": "What this refinement-only step does",
          "command_hint": "the existing refinement-only command to run",
          "expected_outcome": "Shape and path of the actual output, never a target value",
          "verifies": ["T_refined_1", "M_refined_1", "V_refined_1"]
        }
      ]
    }
  ],
  "remote_compute": null
}
```

{% if cloud_drive_enabled %}
Add `remote_compute` using the exact current campaign `state_path`, the
provider-state run-owned working directory, and the completed cloud target as
`remote_dataset_dir`. It is mandatory. Additional provider and execution fields
are allowed. Reuse these exact locations in every later idea and round.
{% else %}
Add the existing optional `remote_compute` object only when the audited
implementation requires remote compute and the state already exists. Copy its
required `state_path`, `remote_working_dir`, and `remote_dataset_dir` fields
exactly; additional provider and execution fields are allowed. Reuse the
recorded instance and dataset locations. Do not rent, release, power off,
reauthorize, rematerialize, upload, or download raw data while planning.
{% endif %}

## Mandatory refinement-plan self-audit

Before finishing, reload the contracts, weights, implementation plan, passing
audit, refinement graph, and drafted validation plan. Correct the plan in place
until all checks below pass:

1. In contract order, there is exactly one validation entry for every new V
   whose `baseline_validation_id` is a contracted positive-weight baseline V,
   with the mapping copied exactly. No zero-weight or uncontracted V appears.
2. Starting separately from every planned refined V, walk backwards through
   its new-node ancestors. Every new P/T/M node on the path is materialized by a
   step, every direct predecessor ID and artifact is named, producers precede
   consumers, and persistent outputs are available to downstream steps. Shared
   new ancestors are produced once and reused.
3. Every refined V step consumes all declared M/P_eval artifacts, uses the
   frozen evaluator and primary metric, and executes its full model/data/metric
   Cartesian block. Every new C endpoint is derived from its declared refined V
   artifacts and maps to the correct base claim.
4. The union of all `verifies` lists covers every graph node added by the idea
   and no immutable base node. Each result-producing step has a concrete local
   output path suitable for actual result/evidence node updates.
5. No `command_hint` invokes, wraps, aliases, or reconstructs a contract's
   forbidden baseline entry point. Every command is an existing
   refinement-only foreground interface and writes only to allowed artifact
   roots without modifying audited source.
6. The plan contains no paper, baseline, target, threshold, or hoped-for result
   value; no scale reduction, code repair, source mutation, provider wrapper, or
   lifecycle action; and its remote fields reuse only the current validated
   campaign state and materialized dataset.

Maintain this checklist internally; do not write another artifact. Finish only
after the JSON schema, refined-V order, graph coverage, artifact flow, frozen
contracts, and baseline non-execution all pass.

Begin your analysis now.
