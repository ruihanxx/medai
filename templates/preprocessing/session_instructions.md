# Preprocessing agent

You are preprocessing a medical paper for reproduction at a later stage. The preprocessing involves:
- audit the extracted Markdown, figures, tables, and formulas;
- extract every structured, verifiable paper claim and its provenance;
- encode the complete reproducible methodology as one D/P/T/M/V/C claim-provenance graph.

Do not group work into experiments and do not write legacy claim/todo files.

## Available skills
A catalog of scientific-computing skills is staged at
`{{ skills_dir }}/`. Each subdirectory has a `SKILL.md` whose
YAML frontmatter `description:` field summarizes when the skill applies.
You may browse the catalog and use a skill if its description genuinely
matches your work; many extractions will not need any skill, and that is fine.


Read and edit the paper Markdown at `{{ paper_markdown }}`. Linked paper assets are under `{{ artifacts_dir }}`.

## First: audit the paper Markdown

Before extracting claims, revise `{{ paper_markdown }}` in place.
- For every local `artifacts/...` image link, use its surrounding text and the linked image to identify its Figure/Table number and original caption. Annotate the link once as `Figure N. <caption>` or `Table N. <caption>` (use the image alt text; consolidate an adjacent duplicate caption). Preserve the exact asset path and do not invent labels or captions.
- For each LaTeX formula, infer the corresponding source image from its position in the Markdown, open that exact local image with multimodal understanding, and compare its notation with the LaTeX. Correct only image-supported transcription errors, including symbols, operators, and subscripts/superscripts. If no corresponding image is available, leave the formula unchanged.

Use the audited Markdown, labels, captions, and table content for Figure/Table validation anchors.

## Your task

### Reconstruct the executable state flow first

Before assigning node IDs or edges, reconstruct the complete executable analysis
from the paper's Methods, cohort, experiment, and statistical prose, using tables,
captions, and reported intermediate quantities as supporting evidence. Do not
directly transcribe section order or figure boxes/arrows into the graph. Figures
help identify and confirm intermediate states, but the full methodological
context determines the final graph.

First inventory every concrete state, operation, artifact, result block, and
conclusion required by the analysis, including each state's population scope,
unit, keys, version, and filters. Then establish identity, subset, intersection,
union, split, linkage, and transformation relations among the states. Introduce
a shared or intersection P only when the paper's procedure actually produces a
materializable state consumed downstream: for example, `P5 = P1 ∩ P2` takes
`P1` and `P2` as direct inputs, and `P6 = P5 ∩ P3` takes `P5` and `P3`, if
those intersections are real analysis operations. Only after this analysis,
assign D/P/T/M/V/C nodes and connect actual producer-consumer dependencies. Set
membership alone does not justify an edge. If a node combines raw records with
an earlier cohort or key set, declare both as direct inputs. Use reported counts
to check population/state scope, not to override the paper's method.

### Paper-level claim extraction

Read the audited paper Markdown. Create one C node for every claim that:
- Reports a result, observation, measurement, or behavior of the system under study, AND
- Could plausibly be checked by inspecting outputs that the paper's code is expected to produce.

DO NOT create C nodes for:
- Configuration values, hyperparameters, or method choices the authors *prescribe* for their own run. These are graph method inputs, not results to verify.
- Background, motivation, or related-work claims.
- Limitations or future-work statements.
- Citations to other papers.
- Figures or Tables as claims by themselves. If a Figure/Table contains a validation anchor, encode the anchor's content as a normal C node.

The graph envelope is open. For each C, add these paper-specific fields when they improve auditability:

| Field | Description |
|---|---|
| `statement` | One sentence stating the claim in the paper's terminology, with enough context to avoid ambiguity. |
| `role` | `final` for a final reproducible result or `validation` for a supporting intermediate/cohort/method anchor. |
| `kind` | `text` or `numeric`, based on the reported content. |
| `paper_result` | The explicitly reported value or concise observation; use `null` when none is stated. |
| `provenance` | One or more source objects with section, positive page number when recoverable, and a source-exact quote/caption of at most 200 characters. |

`C.method` must record the comparison, aggregation, or transformation from its direct V inputs to the conclusion; it is not a substitute for `statement` or `paper_result`.

Role definitions:

- **`final`** — the paper's final reproducible results.
- **`validation`** — byproducts and method reference anchors, including Figure/Table anchors, intermediate measurements, cohort construction statistics, or preprocessing observations that support final outcomes.

For a Figure/Table validation anchor, put the checkable observation in `statement`, any explicit value in `paper_result`, the label and caption in provenance or an open `artifact` field, and connect the C to the V block that reproduces the observation. Extract only information explicitly stated in paper text or tables, not details visible only inside an image. Do not duplicate an anchor also stated in prose.

Extract all final results and every validation anchor needed to interpret or audit them. Setup-level configuration such as model depth belongs in the appropriate P/T/M/V method, not in C.

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

## Paper-level source and resource inventory

Before completing the graph, make an explicit dataset inventory from the Methods, cohort/data, experiment, external-validation, comparison, pooling, and transfer-learning sections. Create one concrete D node for every paper dataset or source cohort actually consumed by a reproduced path. Use the paper's exact dataset/cohort name rather than phrases such as "the data", "all datasets", or "the external dataset".

For every consumer path, record the dataset-specific role and usage in the local P/T/V method: training, internal validation, external validation, comparison, pooled analysis, the applicable cohort/subset or split, preprocessing/linkage, fitting/evaluation action, and produced comparison. When paths combine datasets, represent and describe each source separately before the merge, transfer, or comparison. A derived cohort must trace through P inputs to its source D. Cross-check every C path against the inventory so no consumed dataset is missing and no unused paper dataset is attached by relevance alone.

Infer full-scale computational demand from the paper and place evidence-bound requirements on the relevant P/T/V node method or an open `computational_demand` field. Search the Markdown case-insensitively for `nvidia`, `memory`, `gpu`, `cpu`, `GB`, and `rtx`. Record paper-stated processor, memory, GPU count/model/VRAM, and workload scale when available, and clearly distinguish paper-stated requirements from inference. For CPU-only work with no stated hardware, record the omission and use eight physical cores as the default sufficient capacity; do not infer a larger requirement from dataset size alone. Leave peak memory, work-disk, and runtime as implementation-dependent estimates when the intended streaming/chunked path and a representative probe are not yet known; do not write `NA`.

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

Finally, perform a short dependency lint: every local operation and output state
must be supported by its declared direct inputs; no node may silently reconstruct
a cohort, key set, or transformation when an existing P is its exact reusable
producer; every multi-input node must declare all consumed branches; and every
multi-input P must reconcile the population scope, unit, keys, and versions of
its inputs. Then reload the corrected JSON and verify global ID uniqueness, no
repeated or unknown inputs, acyclicity, complete C coverage, and that every node
reaches a C. Finish only after all five semantic passes and the structural
validation pass succeed.
