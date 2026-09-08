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

Repository acquisition coverage, including unavailable and incomplete sources:

```json
{{ repository_coverage_json }}
```

Repository behaviors that contradict explicit paper text:

```json
{{ repository_conflicts_json }}
```

Paper-unspecified repository details, already sorted high to low suspicion:

```json
{{ repository_unspecified_json }}
```

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

## Delegation

Assemble the report directly by default; the claim-level scientific work is
already partitioned. If locating a large paper-artifact inventory requires
substantial independent reading, use
`{{ skills_dir }}/context-delegation/SKILL.md` for read-only label/path/content
lookup on assigned artifacts. Readers return evidence, not rewritten claim
assessments or separately authored report sections. The parent still reads
every claim fragment, preserves its assessment, verifies artifact mappings,
and checks complete ordered coverage of claims, nodes, issues, and calibration
entries. Do not reopen experiments or browse full transcripts to fill gaps.

## Evidence rules

Read every per-claim report. In the claim table, copy both the
`Reproduced result:` content and the `Assessment:` value from that claim's
fragment. Present the reproduced result compactly but preserve every component
needed to understand the comparison; use `not produced` when that is the
fragment's result. The assessment must remain exactly one of `close`,
`not close`, or `not assessable`. Use the paper result from the claim index,
presenting structured values compactly without dropping components.

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

Write exactly these five sections after the title, in this order. Do not append
per-claim narratives or any other section; the claim-path table links to the
detailed evidence. The repository section must remain last.

```markdown
# Reproduction Report

## Claim comparison

| C_i | Type | Paper result | Replication result | Agent comparison |
| --- | --- | --- | --- | --- |
| C1 | validation | ... | ... | close |

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

## Paper–repository calibration

Repository acquisition: R001 available at commit ..., R002 unavailable (...).

### Repository–paper contradictions

- [PRC-001] P1 — concise behavior and evidence; adopt=true — rationale.

### Paper-unspecified repository details

- [high] [PRC-002] T1 — concise behavior and evidence; adopt=false — rationale.
```

Escape Markdown table pipes inside values and replace embedded newlines with
`<br>`. Use `- none` when either repository list is empty. Mention every
repository inventory ID and its acquisition status in the coverage line. Copy
each supplied calibration ID exactly once into its designated subsection and
include the exact lowercase `adopt=true` or `adopt=false` value on the same
bullet. Preserve the supplied order of paper-unspecified details; it is the
required high-to-medium-to-low suspicion order. Do not add `supports_repo`
entries to either list.

Before finishing, reread the report and verify: all five sections occur
once and in order; every claim occurs once in both claim tables and follows
graph order; every claim row contains its paper result, reproduced result, and
unchanged assessment; every paper artifact occurs once in paper order; every
reproduced path exists relative to the run root or is `not produced`; every
graph node occurs once; every supplied issue appears only on its origin node;
and the repository calibration section is the last content in the file.
