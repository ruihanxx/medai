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
authoritative. For every experiment it freezes the downstream data/cohort/split,
prediction outcome and horizon, evaluator-facing output, evaluation procedure,
metrics, primary metric, and direction. It also records the baseline input
representation, training target, loss, training procedure, and the existing
paths permitted for representation, training, and integration changes. Auto
Research does not reassess whether the replicate code agrees with the paper;
that would duplicate the completed replication workflow.

Each round generates exactly three standalone input-representation, model, or
training-strategy refinement ideas. The idea agent first develops six
paper- or experiment-evidenced problem candidates, reviews closely relevant
literature to revise their methods and rationale, and emits the three strongest
candidates in a validated JSON idea artifact. A campaign-wide candidate-pool JSON retains
unused candidates across rounds; each round replenishes it to six, and
orchestration removes the three selected candidates after validating them.
Representation refinements may reconstruct or encode only the fixed
prediction-time inputs. Training refinements may change
training targets, loss/objective, sampling and balancing, augmentation,
optimization, pretraining, and training logic. External pretraining must be
declared and must not alter or leak the downstream dataset/cohort/split. All
refinements preserve prediction-time information availability, final prediction
outcome and horizon, evaluator-facing output, metrics, evaluation protocol, and
baseline behavior. Every idea receives an independent copy of the completed
replicate codebase. The copies exclude Git metadata, virtual environments, and
caches;
changes never accumulate across ideas or flow back to the base run. Codegen
adds model refinements in new files and may add representation or training
refinement files. Its implementation plan separately declares existing files to
refine and files to add, with a change description for each, then codegen makes
only those minimal changes. Existing paths must come from the contract-recorded
representation, training, or integration boundary. A deterministic changed-file
check rejects edits outside the two lists. An independent audit then checks the
refinement scope plus each experiment's data, prediction target, representation,
evaluator-facing output, training, and evaluation boundary. One failed audit
permits one repair and re-audit; a second failure creates an invalid assessment
and skips planning and execution.

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
