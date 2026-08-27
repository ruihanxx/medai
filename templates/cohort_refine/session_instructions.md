# Cohort refine agent

Fix every `preprocessing_fix` issue in the failed scientific audit before the
next audit runs, without changing the immutable paper graph.
{% if resuming %}This is a technical retry of the same refinement round. Preserve valid fixes,
finish incomplete work, and repeat any uncertain verification.{% endif %}

## Inputs

- Paper Markdown: `{{ paper_markdown }}`
- Immutable paper graph: `{{ paper_graph_path }}`
- Approved execution scope: `{{ execution_scope_path }}`
- Writable codebase: `{{ codebase_dir }}`
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

- Modify only cohort construction, data loading, preprocessing, and their
  directly related data configuration inside `{{ codebase_dir }}`.
- In `{{ codegen_plan_path }}`, modify only the `node_updates` list. Keep every
  other plan field unchanged.
- Do not edit `{{ paper_graph_path }}`, the execution scope, or
  `graph/node_state.json`. Preserve every graph node's ID and meaning.
- Do not modify model definitions, training, tuning, evaluation, or generated
  results.
{% if cloud_drive_enabled %}
- Keep remote raw and row-level data remote. Transfer only the necessary
  preprocessing code and retrieve only aggregate verification output and logs.
  Reuse the plan's existing remote working/data directories and apply the same
  scoped preprocessing fix to the corresponding code under
  `{{ remote_working_dir }}`; do not create another instance or data copy.
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
2. Fix every diagnosed issue exactly as required, preserving all out-of-scope
   behavior. Do not fix only a shared symptom while leaving a reported root
   cause unresolved. When changing a shared P implementation, trace every
   runnable consumer first and preserve branches not named by the issue unless
   the same evidenced root cause applies to them.
3. If a fix exposes a new paper-underspecified cohort or preprocessing decision,
   first reread the relevant paper text and confirm the paper truly does not
   specify it. Never replace a paper decision with a library default, weaken a
   cohort rule, substitute a source, or tune toward a paper result.
4. Resolve each confirmed ambiguity using applicable medical expertise and
   standard medical-research methods. Record the question, confirmed paper
   omission, evidence-based assumption, exact semantic effect, and code/config
   location in the exact origin node's open `node_updates` payload. Preserve
   unrelated existing updates. Do not copy an issue or resolution into
   descendants; orchestration assigns this refinement attempt's source and
   merges it into node state.
5. Run focused preprocessing checks that verify every fix against its reported
   evidence on the supplied data and against the concrete artifact contract of
   the affected P node. Keep raw data read-only and verify direct predecessor
   artifacts, counts, distributions, mappings, split behavior, and downstream
   schema as applicable.
6. Exit successfully only when every reported issue is fixed and verified. If
   any issue cannot be fixed or verified, exit nonzero instead of proceeding.
   Before finishing, reload `codegen_plan.json`, verify that all updated node IDs
   are runnable, every required fix is reflected in code and node-local update
   metadata, all unrelated plan fields are unchanged, and the codebase is ready
   for the next independent audit attempt.

Begin cohort refinement now.
