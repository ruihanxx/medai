# Final reproduction report agent

Write the final evidence-bound Markdown report to `{{ report_path }}`. The
per-claim agents have already completed the scientific comparisons. Preserve
their conclusions exactly and build a concise index over the run; do not redo,
weaken, strengthen, or reconcile their assessments.

## Inputs

- Run root: `{{ run_dir }}`
- Paper Markdown: `{{ paper_markdown }}`
- Extracted paper figures/tables: `{{ paper_artifacts }}`
- Immutable paper graph: `{{ paper_graph_path }}`
- Node overlay: `{{ node_state_path }}`
- Execution scope: `{{ execution_scope_path }}`
- Replication log: `{{ replication_log_path }}`
- Replication outputs: paths in `replication_log.json["step_outcomes"]`
- Per-claim reports: `{{ claims_dir }}`

The claim index below fixes graph order, claim type, paper result, and the
per-claim report path. `type` must be copied from the claim node's `role` and is
expected to be exactly `final` or `validation`.

```json
{{ claim_index_json }}
```

The node issue index below fixes graph order and contains every issue attached
to each node update. Preserve the source and description of every issue. An
empty `issues` list means that no issue was recorded for that node.

```json
{{ node_issue_index_json }}
```

## Evidence rules

Read every per-claim report. In the claim table, copy the claim's `Assessment:`
value exactly; it must remain one of `close`, `not close`, or `not assessable`.
Use the paper result from the claim index, presenting structured values
compactly without dropping components.

Inventory every explicitly named paper artifact (Figure, Table, Supplementary
Figure, Supplementary Table, or equivalent named artifact) found in the paper
Markdown, extracted paper assets, or graph provenance. List each paper artifact
once in paper order, including artifacts that have no runnable claim or no
reproduced counterpart. Use its exact paper label and title when available.

For each paper artifact, inspect the claim reports and real replication output
files to identify the corresponding reproduced artifact path or paths. Report
paths relative to the run root so the report remains portable. Never list a
directory, command, transcript, claim report, or summary JSON as a reproduced
Figure/Table unless it is genuinely the corresponding reproduced artifact. If
no counterpart was produced, write `not produced`. A reproduced data table
(CSV/JSON) may correspond to a paper Figure when it contains the plotted values;
state that relationship briefly in the assessment.

Assess each paper artifact itself as exactly one of `close`, `not close`, or
`not assessable`. A path alone is not evidence of successful reproduction.
`close` requires that the artifact's checkable content and structure agree with
the paper within the claim report's stated comparison rule. Use `not close`
when a real counterpart exists but materially differs, and `not assessable`
when the paper artifact, reproduced counterpart, or required evidence is
missing. Add one short evidence-bound reason after the verdict.

The final node table must include every graph node exactly once in graph order.
For a node with issues, include every issue as `[source] description`, separated
with `<br>`. For a node without issues, write `none`. Do not propagate an
ancestor issue onto a descendant.

## Output

Write exactly these four sections after the title, in this order. Do not append
per-claim narratives or any other section; the claim-path table links to the
detailed evidence.

```markdown
# Reproduction Report

## Claim comparison

| C_i | Type | Paper result | Agent comparison |
| --- | --- | --- | --- |
| C1 | validation | ... | close |

## Artifact reproduction

| Paper artifact | Reproduced artifact path | Assessment |
| --- | --- | --- |
| Figure 1. ... | replication/... | not close — ... |

## Claim report paths

| C_i | Path |
| --- | --- |
| C1 | report/claims/C1.md |

## Node issues

| Node | Issues |
| --- | --- |
| D1 | none |
```

Escape Markdown table pipes inside values and replace embedded newlines with
`<br>`. Before finishing, reread the report and verify: all four sections occur
once and in order; every claim occurs once in both claim tables and follows
graph order; every paper artifact occurs once in paper order; every reproduced
path exists relative to the run root or is `not produced`; every graph node
occurs once; every supplied issue appears only on its origin node; and the node
issues table is the last content in the file.
