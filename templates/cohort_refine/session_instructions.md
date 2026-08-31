# Cohort refine agent

Fix every `preprocessing_fix` issue in the failed scientific audit before the
next audit runs, without changing the immutable paper graph.
{% if resuming %}This is a technical retry of the same refinement round. Preserve valid fixes,
finish incomplete work, and repeat any uncertain verification.{% endif %}

## Inputs

- Paper Markdown: `{{ paper_markdown }}`
- Immutable paper graph: `{{ paper_graph_path }}`
- Approved execution scope: `{{ execution_scope_path }}`
- Authoritative codebase: `{{ codebase_dir }}`
- Refinement workspace: `{{ refinement_workspace }}`
- Code-generation plan (only `node_updates` is writable): `{{ codegen_plan_path }}`
- Failed audit report: `{{ audit_report_path }}`
- Refinement round: {{ refine_round }}
{% if cloud_drive_enabled %}
- Cloud datasets: {% for dataset in cloud_datasets %}`{{ dataset }}`{% if not loop.last %}, {% endif %}{% endfor %} (drive provider: `{{ drive_provider }}`)
- Remote dataset (read-only): `{{ remote_dataset_dir }}`
- Remote working directory: `{{ remote_working_dir }}`
- Remote-compute state: `{{ remote_compute_state_path }}`
- Selected provider reference: `{{ computation_provider_reference|default("<selected-provider-reference>") }}`
- Selected drive reference: `{{ drive_reference|default("<selected-drive-reference>") }}`
{% else %}
- Local input data root (read-only): `{{ data_dir }}`; selected paths: {% for path in data_paths|default([data_dir]) %}`{{ path }}`{% if not loop.last %}, {% endif %}{% endfor %}
{% endif %}

## Available skills

Scientific-computing skills are staged at `{{ skills_dir }}/`. Read only a
genuinely relevant skill. {% if cloud_drive_enabled %}Use the selected
`computation-provider` reference only to reuse the existing instance; do not
rent, release, reauthorize, or rematerialize data.{% else %}Do not use remote
compute or the `computation-provider` skill.{% endif %}

## Permissions

- Treat `{{ codebase_dir }}` as the unchanged pre-refinement baseline until a
  candidate fix passes the semantic-delta self-audit below. First make complete
  `baseline_codebase` and `candidate_codebase` copies beneath
  `{{ refinement_workspace }}`, excluding only caches, environments, and other
  reproducible non-source artifacts. Never edit baseline source or
  configuration. Develop, execute, and revise the fix only in the candidate.
  Promote only the final verified patch to `{{ codebase_dir }}`.
- In both the candidate and the final promoted patch, modify only cohort
  construction, data loading, preprocessing, and their directly related data
  configuration.
- In `{{ codegen_plan_path }}`, modify only the `node_updates` list. Keep every
  other plan field unchanged. Make candidate plan updates in the copied plan
  and promote them only with the verified code patch.
- Do not edit `{{ paper_graph_path }}`, the execution scope, or
  `graph/node_state.json`. Preserve every graph node's ID and meaning.
- Do not modify model definitions, training, tuning, evaluation, or generated
  results.
{% if cloud_drive_enabled %}
- Keep remote raw and row-level data remote. Transfer only the necessary
  preprocessing code and retrieve only aggregate verification output and logs.
  Reuse the plan's existing remote working/data directories. Stage and test the
  preprocessing code in attempt-specific baseline and candidate scratch copies
  without modifying the authoritative code under `{{ remote_working_dir }}`;
  after the self-audit passes, apply the same verified patch to the
  corresponding authoritative remote code. Do not create another instance or
  data copy.
{% endif %}
- Do not hide an audit failure.
- Do not write fallback plan when you cannot solve an issue. Keep solving it.

## Workflow

1. Read the paper context, code-generation plan, and every issue in
   `{{ audit_report_path }}`. Work only on issues whose route is
   `preprocessing_fix`; orchestration handles `source_unavailable` by revising
   availability and scope. Treat `description` and `evidence` as the observed
   failure, `diagnosis` when present as its causal interpretation, and
   `required_fix` when present as the minimum correction contract. Confirm every
   issue's `node_id` is runnable.
2. Before editing, create the baseline and candidate copies required above.
   Keep probe scripts and outputs under `{{ refinement_workspace }}` and run
   focused probes against the baseline copy, never the authoritative codebase.
   Cover every affected P boundary and shared consumer far enough to
   characterize the original cohort behavior. Capture, as applicable, cohort
   membership keys, inclusion and exclusion counts, mapped values, derived
   features, missingness, duplicates, labels, split assignments, schemas, and
   branch-specific artifacts. If the reported defect prevents complete
   baseline execution, retain every comparison available before the failure
   and use focused probes around the failed boundary; do not bypass the defect
   in the baseline.
3. In the candidate only, fix every diagnosed issue exactly as required while
   preserving all out-of-scope behavior. Do not fix only a shared symptom while
   leaving a reported root cause unresolved. When changing a shared P
   implementation, trace every runnable consumer first and preserve branches
   not named by the issue unless the same evidenced root cause applies to them.
4. If a fix exposes a new paper-underspecified cohort or preprocessing decision,
   first reread the relevant paper text and confirm the paper truly does not
   specify it. Never replace a paper decision with a library default, weaken a
   cohort rule, substitute a source, or tune toward a paper result.
   Treat every graph `paper_result` as an observed reference output, never as a
   runtime assertion, reconciliation gate, success criterion, or exception
   condition. Preserve any discrepancy between computed and paper results in
   audit metadata and downstream evidence. Only source, method, schema, and
   artifact-integrity conditions may make preprocessing fail.
5. Resolve each confirmed ambiguity using applicable medical expertise and
   standard medical-research methods. Record the question, confirmed paper
   omission, evidence-based assumption, exact semantic effect, and code/config
   location in the exact origin node's open `node_updates` payload. Preserve
   unrelated existing updates. Do not copy an issue or resolution into
   descendants; orchestration assigns this refinement attempt's source and
   merges it into node state.
6. Run focused preprocessing checks on the candidate that verify every fix
   against its reported evidence on the supplied data and against the concrete
   artifact contract of the affected P node. Keep raw data read-only and verify
   direct predecessor artifacts, counts, distributions, mappings, split
   behavior, and downstream schema as applicable.
7. Before promoting any file, self-audit the complete candidate delta against
   the untouched baseline copy. Inspect the source/configuration diff and run
   the same baseline and candidate probes. Account for every changed cohort
   member, filter outcome, mapped or derived value, label, split, schema, and
   runnable P branch that the patch can affect, including effects not named in
   the audit report. Where a path cannot execute, trace its control flow, data
   flow, and shared consumers to predict those effects explicitly rather than
   assuming no change. Classify each semantic delta as:

   - directly required to correct a reported root cause;
   - an unavoidable downstream consequence of that correction; or
   - unrelated to the reported issues.

   For every effect outside the report's explicit failure location, reread the
   paper's corresponding cohort and preprocessing description. Revert every
   unrelated delta. An unavoidable consequence may remain only when it follows
   from the required correction and is consistent with the paper, graph, and
   declared artifact contracts. If any extra effect contradicts the paper,
   changes an unnamed branch unnecessarily, or cannot be causally justified by
   a reported issue, revise the candidate and repeat both the fix verification
   and this semantic-delta self-audit. Do not treat closeness to a paper result
   as evidence of consistency.
8. Only after the candidate passes that review, apply exactly the verified
   scoped patch and candidate `node_updates` to `{{ codebase_dir }}` and, when
   applicable, the corresponding authoritative remote code. Rerun the focused
   checks on the promoted code and confirm that its outputs match the verified
   candidate. Do not promote temporary probes, caches, environments, or
   candidate-only instrumentation.
9. Exit successfully only when every reported issue is fixed and verified. If
   any issue cannot be fixed or verified, exit nonzero instead of proceeding.
   Also exit nonzero rather than promoting when the baseline/candidate semantic
   comparison cannot be completed reliably. Before finishing, reload
   `codegen_plan.json`, verify that all updated node IDs are runnable, every
   required fix is reflected in code and node-local update metadata, all
   unrelated plan fields are unchanged, and the codebase is ready for the next
   independent audit attempt.

Begin cohort refinement now.
