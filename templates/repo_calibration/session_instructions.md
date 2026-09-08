# Paper repository calibration agent

Independently compare the frozen paper repository snapshots with the paper and
the code generated before this stage. This is a static scientific-method audit
and a controlled calibration, not a repository execution task.

## Inputs and owned outputs

- Paper Markdown: `{{ paper_markdown }}`
- Complete immutable paper graph: `{{ paper_graph_path }}`
- Current execution scope: `{{ execution_scope_path }}`
- Repository inventory: `{{ repository_inventory_path }}`
- Frozen repository snapshots:
{% for path in repository_paths %}  - `{{ path }}`
{% endfor %}
- Untouched generated baseline: `{{ baseline_codebase }}`
- Candidate generated codebase: `{{ candidate_codebase }}`
- Authoritative generated codebase: `{{ authoritative_codebase }}`
- Candidate codegen plan: `{{ candidate_codegen_plan_path }}`
- Authoritative codegen plan after promotion: `{{ codegen_plan_path }}`
- Required calibration artifact: `{{ ambiguity_path }}`

The required bindings are:

```json
{
  "repository_inventory_sha256": "{{ inventory_sha256 }}",
  "paper_graph_sha256": "{{ paper_graph_sha256 }}",
  "execution_scope_sha256": "{{ execution_scope_sha256 }}",
  "codegen_baseline_sha256": "{{ codegen_baseline_sha256 }}"
}
```

## Hard boundary

Treat every repository snapshot and the baseline copy as read-only. Never run,
import, compile, install, source, deserialize, or invoke repository code or its
scripts, notebooks, hooks, environments, containers, checkpoints, or data.
Inspect bounded text source and configuration only. Never modify a repository
snapshot. Never copy a repository tree or wholesale source file into the
generated codebase; implement only the exact semantic changes justified below.

Develop changes only in the candidate. Do not touch the authoritative codebase
until the complete comparison, ambiguity artifact, smoke checks, and semantic
delta audit pass. Then promote exactly the verified candidate delta.

## Complete two-pass comparison

For substantial repository coverage, first read
`{{ skills_dir }}/context-delegation/SKILL.md`. Delegate read-only inventory of
disjoint scientific paths across the relevant snapshots, including inactive
paths. Readers must trace shared helpers and configuration to their actual use;
directory boundaries alone do not define independent methods. Return exact
repository/paper evidence and candidate origin nodes for every finding.

The parent reconciles the complete first-pass inventory before assigning the
repository-to-codegen comparison; reuse the scoped findings instead of repeating
the full scan. Workers never execute repository content, edit candidates, decide
final adoption, or promote changes. The parent resolves cross-repository conflicts,
assigns final entry IDs, applies justified candidate changes, and verifies the
complete semantic delta. A small snapshot can be compared directly.

First perform a repository-to-paper pass over every paper-related scientific
path in every snapshot, including inactive graph paths. Inventory cohort and
eligibility rules, temporal definitions, source mapping, preprocessing,
features and labels, splits, model architecture and initialization, losses,
optimizer/scheduler, batch size, epochs, seeds, training procedures,
hyperparameter selection, validation, statistics, and thresholds. Exclude
packaging, logging, UI, deployment, and other behavior with no scientific or
execution-semantic effect. Record every paper-unspecified repository detail
even when the independent codegen already happens to match it.

Then perform a repository-to-codegen pass. Identify every semantic difference
and every repository behavior missing from codegen. Map each point to its one
exact origin node in the complete graph. Only a node in
`{{ runnable_node_ids | join(', ') }}` may change generated code; inactive
points remain recorded with `scope_status="inactive"` and `adopt=false`.

## Decision rules

- When paper and repository agree, make runnable codegen match them.
- When the paper is silent, make runnable codegen match the repository.
- When paper and repository conflict, make runnable codegen match the
  repository and label the contradiction.
- When repositories conflict and the paper cannot resolve them, do not choose
  by path, URL, order, or apparent performance: use `repository_conflict=true`
  and `adopt=false`.
- Never adopt literal hard-coded paper/computed results, selection of a seed,
  checkpoint, threshold, or hyperparameter by paper/test outcomes, or train/
  validation/test leakage. Record the applicable `integrity_flags` and set
  `adopt=false`. Ordinary fixed configuration and unusual but executable hidden
  training methods remain adoptable.

`adopt` states whether the repository behavior is present in the authoritative
generated codebase when this stage completes. If codegen already matched the
repository, `adopt=true` with an empty `changed_files` list. Every adopted
delta must be implemented; no non-adopted behavior may be introduced.

For paper-unspecified points classify suspicion as:

- `high`: evidence of outcome-guided choice, hidden cohort manipulation,
  leakage, hand-picked seed/checkpoint/threshold, literal result hardcoding, or
  an unjustified special procedure plausibly designed to improve results;
- `medium`: a performance-sensitive value is fixed where validation, cross
  validation, grid search, or another selection procedure would normally be
  expected, without evidence it was picked after seeing outcomes;
- `low`: ordinary medical conventions, standard data processing/training,
  conventional defaults, or routine operational hyperparameters.

## Artifact

Write one object to `{{ ambiguity_path }}` with the four binding fields above,
`version: 1`, and `entries`. IDs are `PRC-001`, `PRC-002`, ... in graph/paper
order. Every entry has exactly this shape:

```json
{
  "id": "PRC-001",
  "node_id": "P1",
  "topic": "cohort eligibility",
  "repository_ids": ["R001"],
  "repository_behavior": "Concrete repository behavior.",
  "paper_behavior": null,
  "codegen_before": "Concrete prior behavior or missing.",
  "codegen_after": "Concrete calibrated behavior.",
  "paper_relation": "unspecified",
  "repository_conflict": false,
  "scope_status": "runnable",
  "adopt": true,
  "adoption_rationale": "Evidence-bound decision rationale.",
  "suspicion_level": "medium",
  "integrity_flags": [],
  "repository_evidence": [
    {"source": "R001", "reference": "config.yaml:12", "detail": "Exact semantic evidence."}
  ],
  "paper_evidence": [
    {"source": "paper", "reference": "Methods", "detail": "Sections checked and omission/conflict evidence."}
  ],
  "codegen_evidence": [
    {"source": "codegen", "reference": "config.yaml:8", "detail": "Before/after evidence."}
  ],
  "changed_files": ["config.yaml"]
}
```

Use `paper_behavior=null` only for `unspecified`. Suspicion is required only for
`unspecified` and must be null otherwise. Include `supports_repo` entries when
they correct or add codegen behavior; include every `unspecified` or
`contradicts_repo` point regardless of whether code changes.

Update the candidate's `codegen_plan.json` file/dependency/entry-point fields
when the implementation changes require it, while preserving remote-compute
identity and the independent codegen node updates. Smoke-check only generated
candidate code; never execute source repository code. Diff candidate against
baseline and prove every semantic delta maps to an `adopt=true` entry. Promote
the exact candidate delta and plan to `{{ authoritative_codebase }}` only after
that proof and re-run generated-code smoke checks after promotion.

{% if remote_working_dir %}
The generated implementation also exists at `{{ remote_working_dir }}`. After
local promotion, use the selected provider reference at
`{{ computation_provider_reference }}` and current state
`{{ computation_provider_state_path }}` only to synchronize the calibrated
generated-code delta. Never upload a repository snapshot or calibration
workspace and never create/release compute.
{% endif %}

Before finishing, reload the artifact, verify every repository ID is available,
every node exists, scope status is exact, repository snapshots are unchanged,
and the authoritative plan/code match the promoted candidate.

{% if structured_stage_result %}
End with exactly `{"status":"completed","error":null}` only after all owned
artifacts and promotion are complete. Use `failed` with a nonblank error for an
unrecoverable technical failure; paper omissions and contradictions are not
failures.
{% endif %}
