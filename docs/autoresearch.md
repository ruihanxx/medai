# Auto Research Workflow Contract

Each Auto Research campaign has its own manifest, checkpoints, and dynamic
stages. By default campaigns are numbered independently below the completed base
run's `autoresearch/` directory; an explicit campaign output may be resumed.
Preflight records hardware resources and fingerprints the canonical base
artifacts and codebase. A paper-only eligibility agent admits supervised
machine-learning tasks with a defined prediction target and records a concise
research brief: problem, scientific context, proposed method, and datasets. For
a paper that mixes prediction with statistical analysis, the decision and brief
cover only the strict prediction task. It does not infer experiment contracts.
An ineligible campaign writes its decision, records status `ineligible`, and
stops.

Before idea generation, a result-blind agent reads only the paper and experiment
definitions, selects only strict supervised prediction experiments, and assigns
each selected experiment a positive importance weight summing to one. Direct
statistical, association, causal, matching, and effect-estimation experiments
are excluded. A separate contract agent treats the completed replicate code and
plans as authoritative. For every selected experiment it freezes the downstream
data/cohort/split, prediction outcome and horizon, evaluator-facing output,
evaluation procedure, a compact agent-written metrics sentence, one numeric
primary metric, and its direction. It also records the baseline input
representation, training target, loss, training procedure, and the existing
paths permitted for representation, training, and integration changes. Auto
Research does not reassess whether the replicate code agrees with the paper;
that would duplicate the completed replication workflow.

Each round generates exactly three standalone input-representation, model, or
training-strategy refinement ideas. The idea agent first develops six
paper- or experiment-evidenced problem candidates, reviews closely relevant
literature to revise their methods and rationale, and emits the three strongest
candidates in a validated JSON idea artifact. Idea scope is bounded by the
paper's main contributions: every candidate's diagnosed limitation and proposed
mechanism must directly refine a main contribution. Supporting components may
serve only as controls or minimum integration dependencies, and unrelated
representation, model, or training changes cannot be candidates even when they
might improve performance. A campaign-wide candidate-pool JSON retains unused
candidates across rounds; each round revalidates carried candidates against
this boundary, replenishes the pool to six without out-of-scope padding, and
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

The Auto Research plan and log group refinement-only steps by selected
prediction experiment. The plan covers every frozen primary metric with
shape-prescriptive outputs, uses the audited refinement's full training scale
and complete frozen evaluation protocol, and prohibits pre-authorized
reductions. Result-blind weights do not permit selected experiments to be
skipped or downsized. Planned outputs stay inside the idea codebase or its
experiment directory. Auto Research treats all base-replication intermediates
as absent unless a prompt explicitly provides them: cohort and feature tables,
split files, caches, checkpoints, temporary output roots, and model state cannot
be assumed to exist. A refinement that needs deterministic preprocessing must
reconstruct it in its own execution path from the fixed raw input while
preserving every frozen data/cohort/split boundary; it cannot invoke a baseline
entry point. The experiment stage never reruns the replicated baseline and
cannot modify the audited source code; execution failures remain explicit.
Assessment compares each frozen primary metric with existing baseline evidence.
It copies the frozen experiment IDs, primary-metric names, directions, weights,
and campaign threshold exactly rather than renaming or decorating them. It retains
`relative_delta = (refined - baseline) / abs(baseline)` as objective comparison
evidence, then assigns each experiment an evidence-bound integer score from -5
through 5. Zero means no meaningful improvement, -5 means compelling evidence
that the idea made the result worse, and 5 means compelling evidence in the
replicated study's scientific context that the idea works well. The assessment
may use an audited original paper-versus-baseline effect from the base
reproduction report to calibrate what magnitude is scientifically meaningful,
but never as a refinement target or substitute result. Each experiment records
a score rationale. Its score is multiplied by the frozen experiment weight and
the contributions are summed without renormalization. A complete weighted score
strictly above `--assessment-threshold` is `valid`; a complete score at or below
it is `invalid`. Missing or unmappable values and zero baselines are
`inconclusive`.
The program derives each round summary from the three assessments. All three
ideas finish before routing: any valid idea ends iteration, otherwise a new
round begins until `max_iter` is reached. Later rounds receive prior ideas,
audit/assessment verdicts, and failure-reason paths.

For a cloud-backed base run, preflight requires completed drive state on an
already released base instance and a non-empty per-file inventory. The campaign
copies that inventory byte-for-byte, mounts no local data, and owns a distinct
remote state. The first audited idea that reaches planning creates the initial
campaign-pool member. The selected provider reference reads the base provider
state's actual selected resources, searches for the exact accelerator model
first, preserves its count and memory capacities as floors, and uses only its
documented stronger fallback when exact inventory is unavailable. Every later
idea and round must reuse the same state path, remote working directory, and
completed read-only dataset target across selected pool members.

When direct Codex and the selected drive support offline handoff, the planning
agent prepares the initial member and returns one foreground monitor command.
Local orchestration runs it without an active agent process, validates the
copied base inventory, powers off, then resumes the same planning session to
write the existing three-field `remote_compute` object. During experiments the
Codex agent returns one structured `remote_exec` or `download` operation at a
time. Orchestration selects and prepares a member immediately before each
operation. It runs inner foreground Bash from the synchronized remote codebase
through the provider adapter, exposes a persistent
`work/artifacts/<idea_id>/` result root, or downloads from that root into the
local idea `experiment/artifacts/` directory. It streams and persists the
result; a failed mother-environment setup is likewise persisted before the
unexecuted operation is returned to the same agent session for repair. It powers
the pool off in `finally`, validates the experiment log, evidence summary, and
declared local outputs, and only then either finishes or resumes that same
session. Agent, orchestration, and transfer permissions follow `agents.md`.
Other agent providers keep their single-turn experiment behavior.

An explicit resume reconciles the campaign state before workflow execution.
If an idea's local mother-environment definition has already passed remote setup,
resume reuses it unchanged by default. A persisted operation failure may justify
a minimal agent repair; changed definition hashes invalidate the prior revision,
and orchestration must synchronize and successfully rerun setup before use.
Remote command execution uses a provider-bounded campaign instance pool. It
tries retained members first and adds a member only after an unambiguous
capacity-unavailable response. Every newly selected member independently
materializes and verifies the copied base inventory, then receives the local
audited mother code and local idempotent environment definition before use.
Ambiguous creation, copy, inventory, or ownership state is terminal. A failed
campaign powers off but retains every member; only a validated final report and
completed campaign permit orchestration to release all members.

Dynamic stages are named `round_001.idea_01.<stage>`. Completed stages are
skipped only after their artifacts reload and validate; retries retain provider
transcripts. The campaign manifest records the base fingerprint, resolved
provider configuration, maximum iterations, attempts, checkpoints, and one of
`running`, `completed`, `failed`, or `ineligible`. Final reporting includes
every candidate, including skipped, failed, and inconclusive ideas. Multiple
valid ideas are shown side by side without ranking, merging, or modifying the
base codebase. Two deterministic PNGs show baseline/refinement metrics and the
round-by-idea verdict grid, with missing results displayed as N/A.
