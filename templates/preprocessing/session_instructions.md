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
- `P`: complete cohort construction, inclusion/exclusion, linkage, labels,
  transforms, feature construction, and train/validation/test splitting.
- `T`: a training or fitting operation.
- `M`: one unique trained-model artifact, not an architecture class. A
  different seed, parameter, training input, fine-tuning route, or model
  modification creates a new M.
- `V`: a claim-aligned validation block combining its model set (if any), data
  set, and metrics/statistical method.
- `C`: a paper claim. `C.method` records comparison, aggregation, and the
  transformation from validation results to the conclusion;
  `C.paper_result` records the conclusion itself.

Prefer more low-degree nodes over one overloaded node. Any semantic difference
that can alter execution, results, provenance, or downstream risk propagation
creates a new node. In particular, different cohort filters, labels, split,
preprocessing order, seed, parameters, training data, or fine-tuning route are
different P/T/M nodes even when the difference is small.

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

Before finishing, reload the JSON and verify global ID uniqueness, no repeated
inputs, no unknown inputs, acyclicity, complete C coverage, and that every node
reaches a C.
