---
name: context-delegation
description: Delegate bounded investigation, implementation, or verification work under a stage's delegation rules to reduce accumulated context while preserving scientific coverage and evidence.
---

# Context-aware delegation

Keep scientific fidelity, complete coverage, and traceability ahead of context
or token savings. The stage prompt defines which work may be delegated and
which decisions remain with its owner. Subtasks are internal work assignments;
they do not create scientific graph nodes, pipeline stages, or new completion
criteria.

## Choose a useful boundary

Read the stage task, constraints, and necessary indexes before broad exploration.
Delegate substantial work when its inputs are narrower than the whole task and
it can return a compact, independently checkable answer. Good boundaries are a
source path, a scientific question, a failure diagnosis, or a verification target.
Keep shared scientific decisions and tightly coupled changes with one owner.
Group shared dependencies so workers do not independently rediscover or execute
the same upstream work. Handle small queries directly.

Use the runtime's native subagent tools when the stage calls for delegation.
If unavailable, complete the work directly with bounded reads; do not enable
features, install tools, or launch nested agent CLIs to bypass that limitation.
Use only as many children as independent work justifies and do not recursively
delegate. Choose concurrency separately from context isolation.

## Give each worker a task contract

Supply the question, relevant node/claim/validation IDs, exact input paths or
source excerpts, shared definitions, allowed reads/writes, required result, and
acceptance checks. Include applicable stage prohibitions, result-blindness, and
execution restrictions even when omitting the rest of the parent history.
Default to read-only work; source edits require explicit permission in the stage
rule and exclusive ownership of the assigned paths. Only the parent writes the
stage's canonical graph, plan, report, or result unless that stage explicitly
assigns a particular output to a worker.

Prefer a fresh or minimally seeded worker context where supported. Do not copy
the full conversation, paper, graph, source tree, or transcript when references
and a scoped task suffice. Do not first load large inputs into the parent merely
to prepare delegation. If history inheritance would expose information forbidden
to the worker, do not use that fork. A worker needing more context requests the
specific missing definition or evidence rather than silently widening its task.

## Bound investigation and return usable evidence

Inspect file sizes and indexes first. Use searches, field selection, aggregates,
and bounded excerpts. Save large command output in an allowed location before
returning a short status, result fields, and evidence paths. Apply this to remote
adapter output too: extract the needed result rather than printing a nested
response with full stdout. Preserve the complete diagnostic evidence on its
permitted host. Never transfer raw data across a stage's data boundary.

Return findings, exact evidence locations (path plus line/section/JSON key),
inspected scope, unresolved questions or contradictions, and necessary next
actions. Aim for roughly 500–1,000 tokens for an investigation summary; keep
longer detail in permitted files when needed. Preserve decision-critical values,
units, populations, splits, parameters, and source wording. State incomplete
coverage explicitly. Do not claim absence from a narrow search or turn a
hypothesis into a verified fact. Do not return raw logs or the exploration diary.

Use only existing stage-permitted scratch/evidence locations for worker files,
with exclusive paths; if none is allowed, return findings in the worker response.
Do not add a required delegation artifact or put coordination notes in scientific
source files. Cite durable evidence rather than disposable scratch paths.

## Coordinate and integrate

Delegation never expands permissions or overrides serial commands, foreground
handoffs, remote lifecycle ownership, or candidate-editing rules. Where command
execution is serial, allow at most one command-capable worker at a time and do
not run parent commands or edits until it returns with all executions terminal.
Give concurrent readers a stable source version; finish their inspection before
mutating those inputs. Settle every worker and its commands before a parent
handoff, final result, or session rollover; no worker may outlive the turn to
continue an experiment or operate shared state.

The parent checks coverage and cross-task dependencies, resolves conflicting
findings against primary evidence, and verifies decisive evidence and proposed
deltas before accepting them. Avoid rereading the entire investigation. Reuse
resolved findings while their source version remains unchanged; invalidate only
affected findings after an input or code change. Persist accepted decisions in
the stage's existing artifacts for resume. Preserve the required final output
schema and all existing artifact validation; a worker's success or summary alone
does not complete a stage. Keep coordination out of the final scientific report.
