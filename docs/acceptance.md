# Acceptance Checks

Run:

```bash
pytest
ruff check .
python -m medai --help
python -m medai.cli --help
```

Tests mock MinerU, agent, SSH, drive, and computation-provider boundaries and
never rent hardware.

Graph coverage includes open node/provenance fields, arbitrary method/result
JSON, global ID collisions, unknown/repeated inputs, cycles, orphan nodes,
P→V→C statistical paths, trained-model paths, and claim-aligned Cartesian V
blocks. Prompt coverage pins the five-pass paper-completeness, reverse-edge,
concrete-product, identity-separation, and category-responsibility self-audit.
No test should require a closed scientific payload enumeration.

Availability coverage includes exact direct D→P requirements, shared P-prefix
branching, independent P variants on one D, forward blocker and unknown propagation, maximal runnable
claim subgraphs, graph/report/scope hashes, FULL/PARTIAL/NONE verdicts, and
scope-bound decisions. Forced-remote coverage pins provider configuration,
launcher forwarding, manifest/resume binding, and mandatory remote-location
validation.

Overlay coverage includes idempotent `(source,node_id)` merge, attempt source
retention, stage invalidation, replication rollback cleanup, real-ancestor-only
collection, shared issue deduplication, multiple origin-to-target paths, and
queries at intermediate nodes.

Base replication coverage includes graph extraction prompts, runnable-only
codegen/audit/refinement/planning, empty-codebase repository-isolated codegen,
paper-verbatim HTTPS Git discovery, pinned/deduplicated/failure-tolerant frozen
snapshots, conditional repository calibration, exact adopted candidate deltas,
ambiguity adoption/integrity/suspicion rules, exact setup-plus-topological-layer plan
structure and coverage of all active nodes, failure on
missing actual result or evidence, node-level resume with predecessor
invalidation and preserved snapshots, per-claim report checkpoints/resume,
claim-keyed Smart Replicate logs, final report agent handoff, repository report
coverage/uniqueness/classification/suspicion sorting, and
path-relevant issues only. Plan prompt coverage pins per-node predecessor
artifact descriptions and the mandatory reverse C-to-D artifact-flow audit.
Direct-Codex tests also cover structured terminal
results, bounded same-session artifact repair, appended transcripts, and cleanup
after success or terminal failure. Provider-handoff coverage requires
availability to execute create, materialization, and remote-inspection commands
locally between turns of one session and rejects a successful Codex exit with an
unfinished command.

Auto Research coverage includes claim-driven eligible-V selection, zero-weight
sparsification, positive normalization, zero-weight exclusion from contract/run/
score, base-node immutability, new M/V creation, full refinement-graph
validation, free audit check names with per-positive-V evidence, refinement-only
plan/log coverage, baseline non-execution, numeric deltas/scoring, and mixed
statistical/prediction papers.

Compatibility coverage parametrizes manifest v1–v6 and asserts that resume and
Auto Research base loading fail before any byte is changed. Error text directs
the operator to a new output directory.

Remote mocks retain provider-authorized drive selection, bounded inventory and
polling, secret non-persistence, safe replacement/reconciliation, no duplicate
billable action after uncertainty, SSH-readiness-gated creation, confined
downloads, direct-SSH creation, single-command cloud preparation, per-operation
power-off, resume recovery, and release after any unambiguous terminal outcome.
A real cloud E2E is manual and billable and must
use disposable data/resources with cleanup on every outcome.
