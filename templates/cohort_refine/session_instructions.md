# Cohort refine agent

Handle every issue in the scientific audit, implement justified preprocessing
corrections, and record all dispositions before the next independent audit.
The paper graph is immutable.
{% if resuming %}This is a technical retry of the same refinement round. Preserve valid fixes,
finish incomplete work, and repeat any uncertain verification.{% endif %}

## Inputs

- Paper Markdown: `{{ paper_markdown }}`
- Immutable paper graph: `{{ paper_graph_path }}`
- Approved execution scope: `{{ execution_scope_path }}`
- Authoritative codebase (read-only baseline): `{{ codebase_dir }}`
- Host-created candidate and working directory: `{{ candidate_codebase }}`
- Candidate-only scratch, probes, caches, and results: `{{ candidate_scratch }}`
- Code-generation plan (entirely read-only): `{{ codegen_plan_path }}`
- Current node overlay (read-only): `{{ node_state_path }}`
- Write node updates to: `{{ node_updates_path }}`
- Put evidence scripts in `{{ candidate_scratch }}/scripts/` and aggregate
  results/logs in `{{ candidate_scratch }}/results/`. The host retains these
  directories and `node_updates.json` at `{{ retained_evidence_dir }}`. Cite
  evidence using that final path; all other candidate scratch is discarded.
- Editable file paths, relative to candidate (additions/deletions included):
{% for path in editable_paths %}
  - `{{ path }}`
{% else %}
  - None; investigate and record dispositions without changing source files.
{% endfor %}
- Failed audit report: `{{ audit_report_path }}`
- Refinement round: {{ refine_round }}
{% if remote_working_dir %}
- Cloud datasets: {% for dataset in cloud_datasets %}`{{ dataset }}`{% if not loop.last %}, {% endif %}{% endfor %} (drive provider: `{{ drive_provider }}`)
- Remote dataset (read-only): `{{ remote_dataset_dir }}`
- Remote working directory: `{{ remote_working_dir }}`
- Remote candidate scratch: `{{ remote_candidate_dir }}`
- Remote-compute state: `{{ remote_compute_state_path }}`
- Selected provider reference: `{{ computation_provider_reference|default("<selected-provider-reference>") }}`
- Selected drive reference: `{{ drive_reference|default("<selected-drive-reference>") }}`
{% else %}
- Local input data root (read-only): `{{ data_dir }}`; selected paths: {% for path in data_paths|default([data_dir]) %}`{{ path }}`{% if not loop.last %}, {% endif %}{% endfor %}
{% endif %}

## Available skills

Scientific-computing skills are staged at `{{ skills_dir }}/`. Read only a
genuinely relevant skill. {% if remote_working_dir %}Use the selected
`computation-provider` reference only to reuse the existing instance; do not
rent, release, reauthorize, or rematerialize data.{% else %}Do not use remote
compute or the `computation-provider` skill.{% endif %}

## Permissions

- The host already created the candidate. Never recreate it, create another
  baseline copy, move its parent directory, or edit the authoritative codebase.
  All local edits and probe outputs belong inside the candidate, with non-source
  work under the supplied scratch directory. These boundaries apply throughout
  the session and every resume. Never edit transcripts or host checkpoints.
  The host alone validates paths, promotes code, merges node updates, and deletes
  the candidate after successful completion.
- Within the audit's editable paths, modify only cohort
  construction, data loading, preprocessing, and their directly related data
  configuration.
- Do not modify any part of `codegen_plan.json`, including its old node updates.
  Write this round's updates only to `{{ node_updates_path }}`. Do not expand the
  audit's editable path list.
- Do not edit `{{ paper_graph_path }}`, the execution scope, or
  `graph/node_state.json`. Preserve every graph node's ID and meaning.
- Do not modify model definitions, training, tuning, evaluation, or generated
  results.
{% if remote_working_dir %}
- Keep remote raw and row-level data remote. Transfer only the necessary
  preprocessing code and retrieve only aggregate verification output and logs.
  Reuse the plan's existing remote working/data directories. Stage and test the
  preprocessing code only in `{{ remote_candidate_dir }}` without modifying
  authoritative remote code. Stage baseline code from the authoritative local
  codebase, run baseline probes, then stage the local candidate and repeat them
  while retaining aggregate comparisons. The host owns final remote code
  synchronization and scratch cleanup. Do not create another instance or data copy.
{% endif %}
- Do not hide an audit failure.
- Do not invent fallback data or outcome-matching methods. Record evidenced
  limitations and their follow-up when they cannot be removed.

## Workflow

### Delegation

When several issues require substantial investigation, read
`{{ skills_dir }}/context-delegation/SKILL.md`. Group issues sharing P semantics
or editable files, then delegate read-only confirmation of root causes against
the baseline and saved probe evidence. After candidate edits, a scoped reviewer
can check the changed semantics and affected shared consumers. Give reviewers
the exact audit issues, frozen editable paths, and stable code/evidence versions.

The parent owns candidate edits, baseline/candidate probes, remote staging,
cross-issue decisions, and every issue disposition. Workers may propose fixes
but may not mutate candidate code, expand editable paths, create extra baseline
copies, or promote/synchronize code. Reuse aggregate probes across related issues
and wait for readers before changing their inputs. Handle a small coupled fix
directly; on resume, reuse valid findings and investigate only remaining or
invalidated questions while retaining complete issue coverage.

1. Read the paper context, code-generation plan, and every issue in
   `{{ audit_report_path }}`. Implement corrections only for `preprocessing_fix`;
   for `source_unavailable`, record the evidence and availability/scope follow-up
   without fabricating data or revising scope yourself. Treat `description` and `evidence` as the observed
   failure, `diagnosis` when present as a causal hypothesis to confirm, and
   `required_fix` as the required observable outcome, not an implementation
   prescription. Confirm every issue's `node_id` is runnable.
2. Before editing, run baseline probes against the unchanged host-created
   candidate. Keep probe scripts and outputs under `{{ candidate_scratch }}`,
   never in the authoritative codebase.
   Cover every affected P boundary and shared consumer far enough to
   characterize the original cohort behavior. Capture, as applicable, cohort
   membership keys, inclusion and exclusion counts, mapped values, derived
   features, missingness, duplicates, labels, split assignments, schemas, and
   branch-specific artifacts. If the reported defect prevents complete
   baseline execution, retain every comparison available before the failure
   and use focused probes around the failed boundary; do not bypass the defect
   in the baseline behavior. Confirm, refine, or correct each reported diagnosis from
   this baseline evidence before choosing a solution.
3. In the candidate only, choose and implement the smallest evidence-supported
   correction for each confirmed defect while preserving all
   out-of-scope behavior. Do not fix only a shared symptom while leaving a
   confirmed root cause unresolved. When changing a shared P
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
   location in the exact origin node's open issue payload. For internal paper
   contradictions, implement the best-supported coherent interpretation and
   record the conflict, alternatives, and rationale. If a finding is refuted,
   record why no change is needed. If actual source content is missing or a
   limitation cannot be removed, record evidence, experiment impact, and the
   required follow-up. Recording missing data does not make it available.
   Paper omissions and contradictions require reasoned decisions, not blocking.
   Do not copy previous stage updates or copy an issue or resolution into
   descendants; orchestration assigns this refinement attempt's source and
   merges it into node state.
6. Run focused preprocessing checks on the candidate that verify every fix
   against its reported evidence on the supplied data and against the concrete
   artifact contract of the affected P node. Keep raw data read-only and verify
   direct predecessor artifacts, counts, distributions, mappings, split
   behavior, and downstream schema as applicable.
7. Before returning, self-audit the complete candidate delta against
   the read-only authoritative baseline. Inspect the source/configuration diff and run
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
   from the required correction and is consistent with the adopted paper
   interpretation and declared artifact contracts. If any extra effect contradicts
   that documented interpretation,
   changes an unnamed branch unnecessarily, or cannot be causally justified by
   a reported issue, revise the candidate and repeat both the fix verification
   and this semantic-delta self-audit. Do not treat closeness to a paper result
   as evidence of consistency.
8. Write `{{ node_updates_path }}` as a JSON list of objects with exactly
   `node_id` and `issues`. Issues use the same open schema as node state:

   ```json
   [{"node_id": "P1", "issues": [{
     "description": "The original issue and resulting finding.",
     "audit_issue": 1,
     "resolution": "Concrete correction, assumption, coherent interpretation, refutation, or evidenced limitation and follow-up.",
     "evidence": ["paper Methods", "retained aggregate evidence path"],
     "implementation_location": "changed code/configuration location, if applicable"
   }]}]
   ```

   `audit_issue` is the one-based position in the input report's `issues` array.
   Record exactly one disposition for every input issue at its original node.
   Multiple issues at one node share one node update. Additional local findings
   may omit `audit_issue`; scientific fields remain open. The host assigns the
   round's source and preserves other node-state sources.
9. Reload the audit report and node updates. Check that every input issue was
   actually handled with a concrete disposition and evidence. If an issue was
   omitted or merely acknowledged, return to its handling step in this same
   session. This coverage review never triggers failure exit and does not
   require every scientific limitation to disappear. Record verification limits
   when execution or comparison is unavailable, and retain valid independent
   corrections. Finish once all issues have been handled. Do not promote files
   yourself; host validation errors return to this session for correction in
   the existing candidate before the next independent audit.

Begin cohort refinement now.
