# Auto Research Workflow Contract

Auto Research has its own manifest, checkpoints, and dynamic stages below the
base run. Preflight records hardware resources and fingerprints the canonical
base artifacts and codebase. It also requires
`templates/skills/idea-generation/SKILL.md`; this repository contract does not
provide that skill, so absence fails before agent execution. A paper-only
eligibility agent admits supervised machine-learning tasks with a defined
prediction target and records a concise research brief: problem, scientific
context, proposed method, and datasets. It does not infer experiment contracts.
An ineligible campaign writes its decision, records status `ineligible`, and
stops.

Before idea generation, a result-blind agent reads only the paper and experiment
definitions, assigns every experiment a positive importance weight summing to
one. A separate contract agent treats the completed replicate code and plans as
authoritative and records every experiment's entry points, model and integration
paths, input/target/output contracts, training and evaluation procedures, and
metrics. It also freezes the actual primary metric and direction used by each
evaluator. Auto Research does not reassess whether the replicate code agrees
with the paper; that would duplicate the completed replication workflow.

Each round generates exactly three standalone model-upgrade ideas. Ideas may not
change data, preprocessing, targets, loss, optimizer, training loops, inference
strategy, augmentation, or evaluation. Every idea receives an independent copy
of the completed replicate codebase. The copies exclude Git metadata, virtual
environments, and caches; changes never accumulate across ideas or flow back to
the base run. Codegen first adds the new model in new files, then makes only the
minimal declared wiring changes needed to embed it into every frozen experiment.
A deterministic changed-file check rejects edits outside the new model and
contract-declared integration files. An independent audit then checks the
model-only scope plus each experiment's input, target, output, training, and
evaluation contracts. One failed audit permits one repair and re-audit; a second
failure creates an invalid assessment and skips planning and execution.

The Auto Research plan and log group refinement-only steps by experiment. The
experiment stage never reruns the replicated baseline and cannot modify the
audited source code; execution failures remain explicit. Assessment compares
each frozen primary metric with existing baseline evidence. It computes
`relative_delta = (refined - baseline) / abs(baseline)`, reverses the sign for a
lower-is-better metric, multiplies by the frozen experiment weight, and sums the
contributions. A complete weighted score strictly above
`--assessment-threshold` is `valid`; a complete score at or below it is
`invalid`. Missing or unmappable values and zero baselines are `inconclusive`.
The program derives each round summary from the three assessments. All three
ideas finish before routing: any valid idea ends iteration, otherwise a new
round begins until `max_iter` is reached. Later rounds receive prior ideas,
audit/assessment verdicts, and failure-reason paths.

Dynamic stages are named `round_001.idea_01.<stage>`. Completed stages are
skipped only after their artifacts reload and validate; retries retain provider
transcripts. The campaign manifest records the base fingerprint, resolved
provider configuration, maximum iterations, attempts, checkpoints, and one of
`running`, `completed`, `failed`, or `ineligible`. Final reporting includes
every candidate, including skipped, failed, and inconclusive ideas. Multiple
valid ideas are shown side by side without ranking, merging, or modifying the
base codebase. Two deterministic PNGs show baseline/refinement metrics and the
round-by-idea verdict grid, with missing results displayed as N/A.
