# Experiment report agent

Update the single Markdown report at `{{ report_path }}` for experiment
`{{ experiment_id }}`. This is an evidence audit, not a narrative summary.

Read:
- Paper claims: `{{ claims_path }}`
- Paper Markdown and figures: `{{ paper_markdown }}`, `{{ paper_artifacts }}`
- All experiment definitions: `{{ experiments_path }}`
- Approved execution scope: `{{ execution_scope_path }}`
- Replication plan: `{{ replicate_plan_path }}`
- Replication step log: `{{ replication_log_path }}`
- Replication environment summary: `{{ evidence_summary_path }}`
- Replication output files: paths listed in `replication_log.json["step_outcomes"]`;
  resolve relative paths against `{{ codebase_dir }}` and then `{{ replication_dir }}`
- Smart-replication audit logs when present: `{{ replication_dir }}/<experiment_id>/smart_replicate_log.json`
- Experiment definition: `{{ experiment_json }}`
- Code-generation decisions and ambiguities: `{{ codegen_plan_path }}`

The ambiguity records are also provided here to make their required coverage
explicit:

```json
{{ ambiguities_json }}
```

Create the report if absent. When it exists, preserve other experiments and
update the current experiment in place instead of appending a duplicate. Keep
exactly one copy of each validation anchor and ambiguity risk. Use these exact
top-level sections in this order:

```markdown
# Reproduction Report

## 1. Per-experiment reports
## 2. Validation claim assessment
## 3. Replication risk list
```

## 1. Per-experiment reports

Create one subsection for every experiment. In the current experiment's
subsection include:

If the current experiment is outside `runnable_experiment_ids`, prominently
mark it as skipped by the partial replication, cite its scope blockers, and use
`not produced` / `not assessable` for outputs and assessments. Do not search for
or infer execution evidence for a skipped experiment. The overall report must
prominently identify a partial replication whenever the scope verdict is
`PARTIAL`.

1. A claim comparison table with one row for every claim assigned to the
   experiment. Each row must contain the claim ID and role, the verbatim paper
   quote from `provenance.quote`, page/section, `paper_result`, the actual
   reproduced result derived from the execution log and its output files,
   evidence paths, and a direct comparison. Do not replace
   the quote with a paraphrase. If the paper result or evidence is absent,
   write `not reported` or `not produced`.
2. An artifact comparison table with one row for every requested artifact.
   Each row must contain the artifact label, the paper's original caption/table
   text and source path, the reproduced artifact path, and a content-level
   comparison. Locate originals through the paper Markdown and
   `{{ paper_artifacts }}`; inspect the original and reproduced files when the
   comparison requires it. A pair of paths alone is not a comparison. If an
   original or reproduced artifact cannot be found, say so explicitly.

Never invent paper text, values, artifact content, experimental outputs, or
evidence. Preserve discrepancies instead of explaining them away.

## 2. Validation claim assessment

Include one row for every claim whose `role` is `validation`. Each row must
identify its experiment(s), quote and paper anchor, reproduced anchor and
evidence, discrepancy, verdict, and rationale. The verdict must be exactly one
of:

- `close`: the anchor is reproduced within the paper's stated tolerance; when
  no tolerance is stated, a numeric anchor has relative error at most 5%, or a
  text/structural anchor matches all explicitly checkable key conditions.
- `not close`: evidence exists but fails that criterion.
- `not assessable`: the paper anchor, reproduced value, or necessary evidence
  is missing. Missing evidence is never `close`.

For a numeric anchor, show the absolute difference and relative error. If the
paper value is zero or a relative error is not meaningful, state the
domain-appropriate comparison used. For a structured numeric anchor, assess
every reported component and do not cherry-pick the closest component. For a
qualitative or artifact-backed anchor, enumerate the matched and unmatched
conditions. Judge each anchor independently; do not infer one anchor's success
from another claim.
If no validation claims were extracted, state
`No validation claims were extracted from the paper.`

## 3. Replication risk list

Create one risk row for every object in `codegen_plan.json["ambiguities"]`.
Copy its `question` and `assumption` verbatim, then state the mechanism by which
that assumption could change the replication, affected experiment/claim/
artifact IDs, severity (`low`, `medium`, or `high`) with a brief reason, and
what evidence would resolve or reduce the risk. Do not merge ambiguities. Do
not add generic risks that are not traceable to an ambiguity. If the ambiguity
list is empty, state `No ambiguities were recorded in codegen_plan.json.`

Before finishing, verify that the report includes all three required sections,
the current experiment ID, every assigned claim ID and artifact label, every
validation claim, and every ambiguity question verbatim.
