# Auto Research refinement-codegen agent

Implement standalone refinement `{{ idea_id }}` in the writable idea codebase
and integrate it into every positive-weight frozen validation contract. Ignore
zero-weight V nodes and uncontracted statistical paths in the paper and base
codebase.
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
- Frozen positive-weight V contracts: `{{ contracts_path }}`
- Immutable base paper graph: `{{ paper_graph_path }}`
- Base codegen and replication plans: `{{ base_codegen_plan_path }}`,
  `{{ base_replicate_plan_path }}`
- Implementation plan to write: `{{ implementation_plan_path }}`
- Complete merged refinement graph to write: `{{ refinement_graph_path }}`
{% if repair_audit_path %}
- Failed audit to repair: `{{ repair_audit_path }}`
{% endif %}

## Workflow

### Delegation

For substantial exploration or implementation, read
`{{ skills_dir }}/context-delegation/SKILL.md`. Delegate scoped tracing of the
idea's integration points or review of a contracted refined-V path. Establish
the shared refinement method and interfaces, then write the implementation plan
before assigning any source edits. An implementation worker may exclusively own
existing files listed in `refine_file_list` and contract `editable_paths`, or
refinement-owned additions listed in `new_file_list`, under the plan constraints
below. Keep shared configuration and integration changes with the parent and
preserve the frozen evaluator.

All workers preserve immutable base code/nodes, frozen contracts, positive-V
scope, and refinement-only entry points. None may run a baseline entry point,
repair the baseline, or use another idea's workspace. The parent owns new graph
IDs and the complete merged refinement graph, checks every contracted path and
full V block after integration, and handles all required fixes on the one audit
repair. Worker review does not replace the later independent audit. Keep a
small or tightly coupled refinement in one agent.

Follow these five steps in order.

### 1. Explore

First read and understand the writable codebase: trace its baseline entry
points, data flow, input representation, model, training logic, evaluator, and
the integration shared by the contracted baseline V nodes. Then read the paper
and the selected `{{ idea_id }}` in the round idea artifact. Use the research
brief, base paper graph, base plans, and frozen contracts to determine how the
idea can be added to the existing implementation.

#### Explore constraints

- Treat the completed replicate code and frozen contracts as authoritative; do
  not reassess or repair whether the baseline matches the paper.
- Work only on baseline V IDs present in the contracts. The contract list is
  already the positive-weight set; zero-weight and uncontracted V nodes are
  outside this idea's implementation and later execution.
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
- Treat every base graph node ID and payload as immutable. Changed cohort,
  preprocessing, training, fitted artifact, seed, parameterization,
  fine-tuning route, model, or evaluation semantics require new graph nodes;
  never edit or recategorize a base node in place.
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
  "method": {
    "mechanism": "paper-specific refinement semantics",
    "implementation": "how it integrates with each contracted refined V",
    "executable_interface": "refinement-only entry points"
  },
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

Codegen does not run full validation. The later plan and validation stages must
execute only newly added refinement paths for each contracted V; they must not
rerun any old existing or baseline entry point.

#### Plan constraints

- Put every existing file that will change in `refine_file_list`. These paths
  may come only from contract-declared `editable_paths` across the positive-
  weight V contracts.
- Put every file that will be added in `new_file_list`. New files must be
  refinement-owned and must not replace or mutate the baseline model or another
  base artifact.
- File paths must be unique and cannot appear in both lists. At least one list
  must be non-empty.
- Absolute paths, `..` traversal, and any path that resolves outside
  `{{ codebase_dir }}` are prohibited.
- Each `change` must state exactly how the existing file will change or what the
  new file will implement, including its role in integrating the refinement
  into the relevant contracted refined V paths while preserving baseline behavior.
- Account for every positive-weight V contract across the declared file
  changes. Do not plan a full validation run.
- If a direct implementation could materially increase computation, plan and
  implement a compute-efficient version with the smallest methodological
  deviation. Prefer semantics-preserving vectorization, batching, concurrency,
  or reuse of shared computation. When an exact implementation would use
  unreasonable resources, an optimized approximation is allowed only if it
  preserves the idea's core mechanism and every frozen boundary; disclose the
  deviation in `method` and the relevant `change` fields. Never reduce frozen
  validation scale or omit required evaluation as a compute
  optimization.

### 3. Implement

Implement the plan module by module. Prefer the existing codebase's language,
framework, configuration, naming, and dependency conventions. Add standalone
refinement files where planned, then make only the minimum declared wiring or
scoped representation/training changes required to run the idea in every
contracted refined V path.

#### Implement constraints

- Modify only files in `refine_file_list` and add only files in `new_file_list`
  inside `{{ codebase_dir }}`. Keep the implementation plan synchronized with
  the final code; never use a plan update to conceal an out-of-scope edit.
- Preserve baseline behavior and keep every baseline entry point runnable.
- Keep each contract's `frozen_contract`, evaluator-facing output, primary
  metric, and comparison rule unchanged. In particular, do not change its
  downstream dataset, cohort membership, train/validation/test assignment,
  prediction-time information availability, final prediction outcome/horizon,
  metric, or evaluation protocol.
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
  evaluation. Full refined-V execution belongs to the later validation stage.

### 4. Build the complete refinement graph

Write a complete merged `PaperGraph` to `{{ refinement_graph_path }}`. Copy
every base D/P/T/M/V/C node unchanged with the same ID, category, payload, and
order, then append only the nodes needed by this idea:

- Do not add a D node. Source data and frozen downstream boundaries cannot
  change in Auto Research.
- Create a new P for every changed cohort, split, preprocessing, feature, or
  input-representation state. Reuse a base P only when its materialized product
  and local semantics are exactly unchanged.
- Create new T nodes for changed fitting/training procedures and new M nodes for
  every changed model artifact. Any seed, parameter, training input,
  fine-tuning route, architecture, or model modification produces a new M;
  connect it through the exact new or reused P/T/M inputs it consumes.
- Add exactly one new V for each contracted positive-weight baseline V, in
  contract order. Each new V must contain `baseline_validation_id` equal to its
  contract V ID, preserve the frozen metric/data/evaluator boundary, and
  explicitly describe its complete model/data/metric Cartesian block.
- Add narrowly scoped refined C transformation endpoints as needed so every new
  path reaches a claim. Each new C must contain `baseline_claim_id` naming the
  corresponding base C. A refined C is an idea-assessment endpoint, not a new
  assertion attributed to the paper.

Prefer fine-grained new nodes over overloaded nodes. Every new node must denote
a concrete product that later validation can update with a nonempty actual
result and real evidence. The full merged graph must retain globally unique
IDs, reference only known inputs, remain acyclic, and keep every node connected
to a C. Do not edit the idea node-state overlay; orchestration creates it only
after validating this graph.

### 5. Auto Research self-audit

Re-read the frozen contracts and final implementation plan, then inspect the
actual diff between the base and idea codebases. Repair any mismatch before
finishing. Perform lightweight, non-experimental checks such as imports,
parsing, or entry-point help when useful.

#### Self-audit constraints

- Confirm the implementation exactly matches the plan: all declared changes
  exist, no undeclared file changed, new files are refinement-owned, and every
  contracted V has a working refinement-only entry point.
- Audit every contract's open `frozen_contract`, evaluator-facing output,
  primary metric, and comparison rule. Confirm that permitted representation,
  model, or training changes stay within those frozen Auto Research boundaries
  and introduce no leakage.
- Compare the base and refinement graphs node-by-node. Confirm every base node
  is semantically unchanged, no D was added, all changed semantics use new
  P/T/M nodes, contracted Vs map one-to-one in order, every refined V retains
  its complete Cartesian block, every new C maps to a base C, and every new
  node reaches a C.
- Re-scan numerical constants and configuration: methodological inputs may be
  configured, but paper-reported, baseline, or target results must be computed.
- Check imports and dependencies affected by the refinement without running the
  methodology end to end.
- On a repair attempt, confirm every required fix from the failed audit is
  implemented and that the repair introduced no new contract violation.
- Do not modify the base codebase or source data, and do not execute baseline or
  full refined-V validation during self-audit.
