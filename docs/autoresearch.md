# Auto Research Workflow Contract

Auto Research requires a completed FULL base replication with manifest v6,
valid paper graph, scope, overlay, codebase, replication evidence, and report.
A partial base or a v1–v5 manifest is rejected without writeback. Each campaign
has an independent manifest, code copies, idea graphs, overlays, and remote
state.

Eligibility admits strict supervised prediction tasks. A mixed statistical and
prediction paper may be eligible, but only prediction-task V nodes can enter
validation setup. An ineligible campaign writes its decision and stops.

Validation setup is result-blind:

- The weighting agent reads the paper graph and paper, not code or results. It
  lists every identified eligible V, prioritizes Vs mapping to numeric results,
  assigns zero to low-importance Vs, and makes positive weights sum to one.
- Zero-weight Vs do not receive contracts and are never executed or scored.
- Contracts cover exactly positive Vs. They freeze the data/split/target,
  evaluator-facing output, metric and comparison rule while keeping scientific
  contract content open. Editable paths and baseline entry points are explicit.

Each round maintains a campaign-wide candidate pool and selects exactly three
paper-, base-validation-, or literature-grounded refinement ideas. Each idea
gets an isolated copy of the base code. Its implementation plan freely
describes the method but explicitly lists existing files to refine and new files
to add; changes outside those lists or contract-approved paths fail.

Every idea writes a full refinement graph. Base IDs and their payloads are
immutable. Any changed cohort/split/preprocessing, training method, trained
artifact, or parameterization creates a new P, T, or M. Each positive baseline
V has one new refined V with `baseline_validation_id`; its complete metric/data/
model Cartesian block is retained. New C transformation endpoints identify the
corresponding base claim through `baseline_claim_id`. The merged graph must be
acyclic, reference-valid, and claim-connected and receives an independent
node-state overlay.

The independent code audit uses freely named checks rather than a closed aspect
enumeration. It must supply at least one non-empty evidence group for every
positive baseline V, prove that only the declared refinement changed, and keep
its overall verdict consistent with all checks. One failed audit permits one
repair; a second failure records an invalid assessment and skips execution.

The validation plan/log are grouped by refined V. They execute only the
refinement path and every endpoint in that V's Cartesian block at full audited
scale. Baseline entry points are forbidden: assessment uses the completed base
overlay/evidence and never reruns the baseline. Validation cannot mutate audited
source and must update every newly added graph node with actual result and
evidence.

Assessment compares numeric baseline/refined values for every positive V. It
copies the frozen primary metric, comparison rule, and weight, stores actual
values, absolute delta, and `(refined-baseline)/abs(baseline)` when defined,
assigns an evidence-bound scientific score from -5 through 5, and stores its
weighted contribution. The total is the sum over already normalized positive
weights and is compared with `--assessment-threshold`. Missing or unmappable
numeric evidence is inconclusive; a zero baseline permits absolute comparison
but has no relative delta.

All three ideas finish before routing. Any valid idea ends iteration; otherwise
another round begins until `max_iter`. The report names claims and V IDs and its
comparison section is `Validation comparisons`. Visualizations show baseline
versus refined V metrics and the round-by-idea verdict grid; zero-weight Vs are
absent.

Cloud-backed campaigns copy the base inventory but own a separate provider
state and bounded instance pool. Planning may return one foreground monitor;
validation may return one `remote_exec` or confined `download` operation at a
time. Orchestration prepares a pool member, runs and persists the operation,
powers the pool off in `finally`, validates artifacts, then resumes the same
direct-Codex session if needed. Raw data is never downloaded. Ambiguous create,
copy, inventory, or ownership state is terminal. Failure retains powered-off
members; validated campaign completion permits release. See `execution.md` and
`agents.md` for lifecycle and permission details.

Dynamic stages use `round_<NNN>.idea_<NN>.<stage>`. Completed stages are skipped
only after artifact validation. The campaign manifest records the base
fingerprint, resolved configuration, maximum iterations, attempts, checkpoints,
and `running`, `completed`, `failed`, or `ineligible`.
