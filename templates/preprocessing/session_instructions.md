# Paper-graph preprocessing agent

Convert the medical paper into one complete, auditable claim-provenance graph.
Do not group work into experiments and do not write legacy claim/todo files.

Read and audit `{{ paper_markdown }}`. Linked assets are under
`{{ artifacts_dir }}`. For each local figure/table image, preserve its path and
annotate its paper label and caption when supported by the surrounding text.
Compare LaTeX with its source image when one is available and correct only
image-supported transcription errors.

A catalog of optional scientific-computing skills is at `{{ skills_dir }}/`.
Use a skill only when its description matches the extraction work.

## Output

Write exactly one JSON artifact to `{{ paper_graph_path }}`:

```json
{
  "version": 1,
  "datasets": [],
  "preprocessing": [],
  "training": [],
  "models": [],
  "validations": [],
  "claims": []
}
```

Every collection uses the same minimal open envelope:

```json
{
  "id": "P1",
  "inputs": ["D1"],
  "method": "a string, list, or object describing what is done",
  "paper_result": null,
  "provenance": [{"page": 3, "section": "Methods", "quote": "..."}]
}
```

The host fixes only `id`, `inputs`, `method`, `paper_result`, and `provenance`.
Use any JSON shape needed inside method/result/provenance and add paper-specific
fields when they materially improve auditability. Do not invent a closed
taxonomy. `paper_result` is any explicitly reported value or observation and
is `null` when none is reported.

## Node meaning and granularity

- `D`: a paper dataset or source cohort.
- `P`: one materializable preprocessing state produced from its declared
  inputs. Its local method may perform cohort construction, inclusion/exclusion,
  linkage, labels, transforms, feature construction, or splitting. The complete
  semantics of a terminal P are the ordered composition of P methods on its
  ancestor path.
- `T`: one executable training or fitting operation. Its inputs identify every
  P state and any prior M artifact actually consumed; downstream M nodes identify
  the concrete trained artifacts it produces.
- `M`: one unique trained-model artifact, not an architecture class. A
  different seed, parameter, training input, fine-tuning route, or model
  modification creates a new M.
- `V`: one claim-aligned validation-result block combining every M artifact (if
  any), evaluation P state, and metric/statistical method needed to compute it.
- `C`: a paper claim. `C.method` records comparison, aggregation, and the
  transformation from validation results to the conclusion;
  `C.paper_result` records the conclusion itself.

Prefer more low-degree nodes over one overloaded node. Any semantic difference
that can alter execution, results, provenance, or downstream risk propagation
creates a new node. In particular, different cohort filters, labels, split,
preprocessing order, seed, parameters, training data, or fine-tuning route are
different P/T/M nodes even when the difference is small.

Each node's `method` describes only that node's local responsibility; obtain
complete semantics by traversing its inputs. Keep category boundaries explicit:

- D identifies source data and does not contain preprocessing operations.
- P contains only its local cohort/data transformation and resulting state, not
  fitting, model, or validation logic.
- T contains the fitting procedure, objective, optimizer, seed, and other
  training operations. A produced M records T in its `inputs`; do not duplicate
  successor IDs merely as free text inside T.
- M identifies the concrete trained artifact, architecture/configuration, and
  artifact-level paper result. Do not place optimizer, fitting, sampling, or
  other training procedure inside M; those belong to its upstream T.
- V lists every directly consumed M and evaluation P in `inputs`; `V.method`
  names the metrics/statistical procedure, Cartesian block, and resulting value
  shape. Training P/T dependencies remain inherited through M rather than being
  duplicated as direct inputs.
- C lists every V evidence block needed for the claim; `C.method` contains only
  comparison, aggregation, and conversion of those results into the conclusion.

For a model path, prefer explicit `P -> T -> M`, `(M, P_eval) -> V`, and
`V -> C` dependencies. Fine-tuning may use `(P, M_prior) -> T -> M_new`.
Statistical paths may omit T and M as described below.

P-to-P edges are valid only when the downstream P actually consumes the
materialized output of the upstream P. Factor a shared P prefix when its input,
operations, order, and parameters are exactly identical across branches, its
output can be concretely described and evidenced, and an issue there should
affect every branch. Each child P then records only its local divergent method.
Do not create a shared P merely for similar text or reused implementation code.
When semantic identity is uncertain, keep separate branch-specific P nodes.
Every P must be executable enough for replication to record an actual result
and evidence.

`inputs` are AND dependencies. Do not encode OR inputs; represent each
alternative path with a separate node. IDs must be globally unique. Use
sequential category-prefixed IDs where practical.

## Validation blocks

A V block's model collection, data collection, and metric collection have
complete Cartesian-product meaning. Make this explicit in `V.method`. If the
paper reports only sparse combinations, create multiple smaller V nodes so
every V remains a complete block. V should align with the evidence unit used by
a claim, rather than being an arbitrary cell or a whole-paper container.

Statistical papers need not contain T or M. Paths such as `D -> P -> V -> C`
are valid. Validation/cohort claims may connect from P into V without training.

## Claim coverage

Create C nodes for every reproducible reported result, observation,
measurement, or behavior that can be checked from expected outputs. Include
intermediate cohort/statistical/figure/table anchors when they support final
claims. Do not create claims for background, motivation, related work,
limitations, future work, or prescribed configuration alone.

Every C must have at least one input. Every graph node must contribute to at
least one C. Trace all paper datasets and every distinct P/T/M/V path needed by
the C nodes. Preserve short, source-exact provenance snippets; never infer a
paper result from pixels alone.

## Mandatory self-audit

Do not finish after the first extraction pass. Write a complete draft, then
perform every pass below against the draft, correct the graph, and repeat any
affected pass. Do not write a separate audit artifact.

### 1. Paper-completeness pass

Reread the entire paper from the beginning, with particular attention to all
Methods, study design, analysis, model, training, evaluation, ablation,
baseline, subgroup/external-validation, figure, table, result, and supplement
content available in the supplied Markdown/assets. Do not rely on notes from
the first read. For every reproducibility-relevant description, confirm that
its dataset, local method detail, reported result, and provenance appear in the
correct D/P/T/M/V/C node or edge. Confirm that every reported result eligible
under Claim coverage has a C. Correct omissions before continuing.

### 2. Reverse-dependency pass

Read the draft graph backwards, starting independently from every C. For each
node, use the paper to decide whether its direct inputs are jointly sufficient
and all genuinely consumed:

- Each C must connect to every V that supplies evidence required for that exact
  claim; do not omit a baseline, comparison arm, dataset, subgroup, or metric
  block used by the conclusion.
- Each model-based V must connect to every directly evaluated M and P_eval state
  and must name every metric/statistical operation in `V.method`. Its M ancestors
  must lead through all paper-required T and training P paths. A statistical V
  must connect to every P state it analyzes.
- Each M must connect to the T operation that produced that exact artifact.
  Each T must connect to every P and prior M it consumes. Each P must connect to
  every direct D or P state it consumes.

For every edge, be able to state: "the downstream method consumes this concrete
upstream output." Add missing inputs and remove relevance-only edges. Remember
that multiple inputs mean AND, not alternatives.

### 3. Concrete-product pass

For every node, explicitly verify that it denotes an actual auditable product,
state, operation result, or conclusion rather than a vague container:

- D resolves to a concrete paper dataset/source cohort.
- P resolves to a materializable cohort, split, transformed table, feature
  representation, or equivalent preprocessing state.
- T resolves to one executable fitting run with explicit P/prior-M inputs and
  one or more concrete downstream M artifacts. If separate fitting runs occur,
  create separate T nodes.
- M resolves to one trained checkpoint, fitted coefficient set, ensemble, or
  equivalent prediction-capable artifact produced by its T.
- V resolves to a concrete metric/statistical result block, stating which M
  artifacts and P_eval states are combined, which metrics are computed, and
  what result shape is produced.
- C resolves to one paper conclusion derived by its stated transformation of V
  results.

If replication could not record a non-empty actual result and evidence for a
node, refine or remove that node rather than retaining an abstract grouping.

### 4. Identity-separation pass

Compare nodes within each collection and confirm that no node conflates
non-identical products. Split nodes whenever the actual product required by the
paper is not exactly the same. In particular:

- different cohort filters, labels, splits, preprocessing order, or feature
  states are different P nodes;
- the same base model with different parameters, seeds, training datasets,
  training runs, fine-tuning routes, or modifications produces different M
  nodes, with distinct upstream T/P paths where those operations differ;
- different evaluated model/data combinations or sparse metric endpoints use
  different V nodes unless they truly form one complete Cartesian block.

A shared name, architecture family, prose label, or implementation function is
not evidence that two actual products are identical.

### 5. Responsibility pass

Reread every node without following its edges and check that its local content
does not exceed its category. Move misplaced content to the correct node and
repair the edges. Especially reject training procedures stored in M, model or
evaluation logic stored in P, claim-level comparison stored in V, and upstream
methods duplicated into downstream nodes. Check that provenance supports the
local content rather than only the overall path.

Finally, reload the corrected JSON and verify global ID uniqueness, no repeated
or unknown inputs, acyclicity, complete C coverage, and that every node reaches
a C. Finish only after all five semantic passes and the structural validation
pass succeed.
