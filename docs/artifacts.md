# Persistent Artifact Contract

## Base replication

```text
runs/<run_id>/
├── manifest.json                         # manifest v6
├── preflight/resources.json
├── preprocessing/
│   ├── paper.md
│   ├── artifacts/
│   ├── paper_graph.json                  # immutable paper definition
│   ├── preprocessing_transcript.jsonl
│   ├── data_availability/attempt_<NNN>/
│   │   ├── data_availability.json
│   │   ├── data_availability_transcript.jsonl
│   │   └── results/
│   ├── execution_scope.json
│   └── partial_replication_decisions.json
├── graph/node_state.json                 # orchestration-owned run overlay
├── codegen/
│   ├── codebase/codegen_plan.json
│   ├── codegen_transcript.jsonl
│   ├── codegen_agent_result.json
│   ├── audit/attempt_<NNN>/{audit_report.json,audit_transcript.jsonl,scripts/,results/}
│   ├── cohort_refine/attempt_<NNN>/cohort_refine_transcript.jsonl
│   └── scope_revision_<scope-sha256>.json
├── plan/{replicate_plan.json,plan_transcript.jsonl}
├── replication/
│   ├── replication_log.json
│   ├── evidence_summary.json
│   ├── replication_transcript.jsonl
│   └── claims/<claim_id>/smart_replicate_log.json
├── report/
│   ├── reproduction_report.md
│   └── claims/<claim_id>{.md,_transcript.jsonl}
├── prompts/
├── resume_history/resume_<NNN>/
├── system_maintenance/{dataset/patch.json,skills/corrections.json}
└── remote_compute/instance.json
```

`preprocessing/paper_graph.json` has version 1 and six ordered collections:
`datasets`, `preprocessing`, `training`, `models`, `validations`, and `claims`.
Every node fixes only this envelope:

```json
{
  "id": "P1",
  "inputs": ["D1"],
  "method": "any JSON value",
  "paper_result": null,
  "provenance": [{"any_auditable_field": "value"}]
}
```

Nodes and provenance entries accept additional fields. Host validation is
limited to globally unique IDs, existing non-duplicate inputs, acyclicity, a
non-empty input list for every C, and reachability of every node to at least one
C. It deliberately does not close scientific method or result shapes.

Each P is a materializable preprocessing state whose method describes the local
transformation from its inputs. A terminal P's complete cohort, labels, split,
and preprocessing semantics are composed along its ancestor P path. An exact,
materializable common prefix may be shared through P→P edges; similarity or code
reuse alone is insufficient. Any path-affecting difference requires a new P. M identifies
one trained-model artifact; changes in seed, parameterization, training data,
fine-tuning, or implementation require a new M. A V is claim-aligned: its model,
data, and metric sets mean their full Cartesian product. Sparse endpoints are
separate smaller Vs. C.method owns comparison, aggregation, and conversion of
V results into the paper claim; C.paper_result holds the paper conclusion.
Statistical paths such as D→P→V→C are valid. Inputs are AND dependencies;
alternative paths use separate nodes.

`graph/node_state.json` is an overlay bound to the paper-graph SHA-256:

```json
{
  "paper_graph_sha256": "...",
  "updates": [
    {
      "source": "replicate_agent",
      "node_id": "V1",
      "result": {},
      "evidence": ["replication/results/v1.json"],
      "issues": [{"description": "..."}]
    }
  ]
}
```

An update fixes only `source` and `node_id`; an issue fixes only a nonblank
`description`. Both remain open. The orchestrator validates node IDs and merges
idempotently by `(source,node_id)`. Stages own distinct source names; audit and
refinement attempts remain distinguishable. Invalidation removes only the
invalidated sources. Replication rollback archives artifacts and removes the
old `replicate_agent` updates.

Replication must update every runnable node exactly once with a non-empty
actual result and at least one real evidence path. Results may be numeric,
structured, textual observations, or artifact descriptions. Issues remain at
their origin. `collect_lineage_issues(node_id)` follows only actual ancestors,
deduplicates equal content from the same origin, and returns its sources and
origin-to-target paths.

Availability covers each direct D→P source boundary; inherited P dependencies
are handled by graph propagation. `execution_scope.json` binds both paper-graph and availability-report hashes.
It records `runnable_node_ids`, `blocked_nodes`, blocker paths,
`active_sources`, execution location, and one orchestration lifecycle verdict:
`FULL`, `PARTIAL`, or `NONE`. Blocked nodes retain `source_blocked` versus
`unknown` evidence. A partial decision is valid for one scope hash only.

The replication plan's `verifies` fields collectively equal all runnable node
IDs. The final report contains each C exactly once in graph order. Every claim
fragment contains the paper result, reproduced result, upstream results, direct
comparison, scope blockers, exact lineage issues/paths, and exactly one of
`close`, `not close`, or `not assessable`.

## Auto Research

```text
runs/<run_id>/autoresearch/campaign_<NNN>/
├── manifest.json
├── preflight/{resources.json,base_fingerprint.json}
├── eligibility/{eligibility.json,eligibility_transcript.jsonl}
├── validation_setup/
│   ├── validation_weights.json
│   ├── validation_weighting_transcript.jsonl
│   ├── validation_contracts.json
│   └── validation_contracts_transcript.jsonl
├── research/candidate_pool.json
├── rounds/round_<NNN>/
│   ├── ideas.json
│   ├── round_summary.json
│   └── ideas/<idea_id>/
│       ├── codegen/{codebase/,implementation_plan.json,transcript.jsonl}
│       ├── graph/{refinement_graph.json,node_state.json}
│       ├── audit/{audit.json,transcript.jsonl}
│       ├── plan/{validation_plan.json,transcript.jsonl}
│       ├── validation/{validation_log.json,evidence_summary.json,transcript.jsonl,artifacts/,commands/}
│       └── assessment/{assessment.json,transcript.jsonl}
├── report/{autoresearch_report.md,report_transcript.jsonl}
├── visualization/{metric_comparison.png,idea_verdicts.png}
├── prompts/
└── remote_compute/instance.json
```

`validation_weights.json` lists every eligible V in paper-graph order. Zero is
allowed; positive weights sum to one and at least one is positive. A zero-weight
V receives no contract, execution, or score. `validation_contracts.json`
covers exactly the positive Vs and fixes only `validation_id`, non-empty
`baseline_entry_points`, non-empty `editable_paths`, `frozen_contract`,
`primary_metric`, and `comparison_rule`; contract payload remains open.

Each idea's refinement graph is a complete merge candidate: base node IDs and
payloads are unchanged, changed semantics use new P/T/M nodes, every positive
baseline V maps to a new V through `baseline_validation_id`, and new claim
transformation endpoints map through `baseline_claim_id`. The merged graph must
pass normal paper-graph structure validation. It has its own overlay.

The validation audit uses freely named checks and non-empty evidence while
covering every positive V. The plan/log are organized by refined V, execute only
new refinement nodes and the complete V Cartesian block, and never invoke a
baseline entry point. Assessment copies each frozen metric, comparison rule,
and weight; retains actual values and absolute/relative deltas; assigns an
evidence-bound integer score from -5 through 5; and computes the positive-weight
sum against the configured threshold.

## Compatibility

Manifest v6 is the only writable/resumable format. Directories with manifest
v1–v5 remain untouched and readable as historical output, but cannot be
resumed or used as a new Auto Research base. No graph is inferred from legacy
artifacts; rerun into a new output directory.
