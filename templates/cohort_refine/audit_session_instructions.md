# Runnable graph scientific audit agent

Exhaustively audit the runnable preprocessing produced by code generation before
any replication plan is written. This is a scientific sanity check using the
real data, not model training and not a static code review. Accumulate every
issue discoverable within the audit scope and write one complete report only
after all feasible checks have run. Finding one failure is never a reason to
stop the audit.
{% if resuming %}

This audit is resuming after a technical interruption. Reuse valid scripts and
results already present in the audit working directory, rerun anything whose
completion is uncertain, and replace the report with a complete final report.
This retry does not represent another scientific refinement round.
{% endif %}

## Inputs
- Paper Markdown: `{{ paper_markdown }}`
- Immutable paper graph: `{{ paper_graph_path }}`
- Approved execution scope: `{{ execution_scope_path }}`
- Approved source-availability report: `{{ availability_report_path }}`
- Generated codebase (read-only for this audit): `{{ codebase_dir }}`
- Code-generation plan and node-local decisions/updates: `{{ codegen_plan_path }}`
{% if cloud_drive_enabled %}
- Cloud datasets: {% for dataset in cloud_datasets %}`{{ dataset }}`{% if not loop.last %}, {% endif %}{% endfor %} (drive provider: `{{ drive_provider }}`)
- Completed remote dataset (read-only): `{{ remote_dataset_dir }}`
- Codegen remote working directory: `{{ remote_working_dir }}`
- Independent remote audit directory: `{{ remote_audit_dir }}`
- Selected provider reference: `{{ computation_provider_reference|default("<selected-provider-reference>") }}`
- Selected drive reference: `{{ drive_reference|default("<selected-drive-reference>") }}`
{% else %}
- Local input data root (read-only): `{{ data_dir }}`; selected paths: {% for path in data_paths|default([data_dir]) %}`{{ path }}`{% if not loop.last %}, {% endif %}{% endfor %}
{% endif %}
- Local resource record: `{{ resources_path }}`
- Codegen attempt under audit: {{ codegen_attempt }}
- Audit working directory: `{{ audit_dir }}`
- Audit-only scripts: `{{ scripts_dir }}`
- Audit results and logs: `{{ results_dir }}`
- Required report: `{{ report_path }}`
{% if cloud_drive_enabled %}
- The active remote-compute state is `{{ remote_compute_state_path }}`. Use it
  through the selected computation-provider reference for this audit.
{% elif remote_compute_active %}
- A remote-compute state exists at `{{ remote_compute_state_path }}`. It remains
  active for later stages, but you must not connect to it or operate it.
{% else %}
- No remote-compute state exists. Run the complete preprocessing locally.
{% endif %}

## Available skills

A catalog of scientific-computing skills is staged at `{{ skills_dir }}/`.
Read a skill only when its description genuinely matches the audit.
{% if cloud_drive_enabled %}
Read the `computation-provider` skill, its selected provider reference, and the
selected cloud-drive document before remote operations. Reuse the existing
instance; do not rent, release, reauthorize, or rematerialize data in this stage.
{% else %}
Never use the `computation-provider` skill during this stage.
{% endif %}

## Permissions and prohibitions

- Treat `{{ paper_graph_path }}` and `{{ execution_scope_path }}` as immutable.
  Do not edit graph nodes, edges, IDs, or scope.
- Treat `{{ codebase_dir }}`{% if not cloud_drive_enabled %} and `{{ data_dir }}`{% endif %}
  as read-only. Do not edit, delete, rename, or generate files inside it.
{% if cloud_drive_enabled %}
- Treat `{{ remote_dataset_dir }}` and `{{ remote_working_dir }}` as read-only.
  Copy only the code needed for preprocessing into `{{ remote_audit_dir }}` and
  make audit-only instrumentation there. Never modify the codegen remote tree.
{% endif %}
- Write only beneath `{{ audit_dir }}`. Install dependencies only into an
  environment or target beneath that directory, and keep audit-only scripts,
  logs, caches, and results there.
- Do not train, tune, evaluate, or compare models. Do not use model performance
  to choose preprocessing.
{% if cloud_drive_enabled %}
- Do not download raw data, processed row-level data, model inputs, checkpoints,
  or other dataset derivatives locally. Download only aggregate statistics,
  command logs, and the audit report into `{{ results_dir }}` and
  `{{ report_path }}`.
{% else %}
- Do not connect to, query, stop, release, or otherwise operate a remote server.
{% endif %}
- Do not change scientific preprocessing to make the data look better.
- Apply the explicit cohort-size tolerance below; do not invent other fixed
  universal thresholds. Judge other basic statistics in the context of the
  paper's cohort, data type, and stated balancing procedure.

## Workflow

### 1. Establish the paper's preprocessing expectations

Read the Methods, cohort/data, preprocessing, and relevant table/figure text.
List the checkable cohort criteria, units, feature definitions, sample or
sequence structure, target/group expectations, missing-data handling,
deduplication, splitting, and any stated balancing such as SMOTE. Treat paper
values as sanity context, never as numbers to hard-code or tune toward.

Read `{{ paper_graph_path }}` and `{{ execution_scope_path }}` and build an audit
checklist containing every runnable P node and every one of its direct D/P
inputs. Do not audit inactive graph paths. Trace shared P prefixes and distinct
P branches separately; every graph input is an AND dependency. For each D→P
source boundary, check the graph's exact source identity, role, required
content, and generated loading/preprocessing path against the paper. A missing
source path, a source used in the wrong role, a generic loader that cannot
distinguish required D nodes, or a P implementation that does not consume every
declared direct input is an explicit issue.

Inspect downstream T/M/V consumers only far enough to establish the exact
artifact contract that each runnable P must produce. Confirm that every
model-based V declares and can receive all M/P_eval inputs for its complete
model/data/metric Cartesian block, and that every statistical V can receive all
declared P inputs. Do not train, fit, tune, or evaluate models, and do not audit
independent T/M/V scientific logic in this stage. Do not mark the audit complete
until every runnable P and direct D→P requirement has either been executed
through its applicable preprocessing boundary or recorded as a diagnosed issue.

### 2. Identify and run the complete preprocessing

Inspect the codebase and its entry points without modifying it. Run
preprocessing through the final input immediately before model computation.
Execute every runnable P path in dependency order and retain separately
attributable aggregate evidence for each concrete P product; do not let a
successful shared branch stand in for an unexecuted sibling.
Instrument the preprocessing boundaries before execution so a crash still
leaves enough aggregate evidence to audit earlier boundaries and independently
check mappings, units, filtering, and feature propagation.

A generated-code exception is one issue to diagnose, not a signal to end the
audit. Trace it to its causal preprocessing or data-contract violation instead
of reporting only the terminal exception. After a crash, continue every check
that remains independently executable, including focused aggregate probes of
the failed boundary. Do not patch the generated code to bypass the failure.

{% if cloud_drive_enabled %}
Use the exact remote data-reading and preprocessing implementation from
codegen. In `{{ remote_audit_dir }}`, make only small audit instrumentation
changes needed to record counts, retention, distributions, missingness, and
other aggregate checks. Execute the complete dataset preprocessing remotely.
Training, hyperparameter tuning, inference evaluation, and model-performance
comparison are forbidden. A failure in the generated remote preprocessing is an
explicit issue to accumulate and diagnose. A provider or audit-infrastructure
failure that prevents the complete audit must exit nonzero for a same-attempt
retry; do not write a local CPU, streaming, small-batch, or sampled substitute.
Capture remote commands, status, aggregate outputs, and logs, then retrieve only
those audit artifacts locally.
{% else %}
Set up the local environment and run the complete local dataset preprocessing.

When no remote-compute state exists, use the complete local dataset and run the
complete preprocessing. Do not replace it with a sample or toy path.

When a remote-compute state exists, still complete all locally feasible work:

- For tabular and time-series data, run full local preprocessing when it does
  not itself require the remote server's large compute resources.
- For multimodal data, process the complete metadata, modality pairing, label
  mapping, and file-availability inventory locally.
- If production preprocessing depends on GPU only for execution mechanics,
  write an equivalent CPU, streaming, or small-batch adapter under
  `{{ scripts_dir }}` and run it locally without changing scientific meaning.
  Reads large raw tables/dataframe in chunks or bounded batches, applies chunk-eligible
  preprocessing immediately after each chunk read, projects required columns,
  drops unrelated columns before retaining data, and defers full-data operations
  such as downsampling after chunk-processed compact data is merged.
- Leave genuinely remote-heavy computation unexecuted and identify its exact
  boundary in the report.
{% endif %}

Capture commands and outputs under `{{ results_dir }}`.

Keep aggregate results attributable to the exact D and P node IDs and their
paper-exact source names. When sources are linked or pooled, record the
pre-combination counts and checks separately for every direct input, then record
the linkage/pooling P result; one aggregate for the combined data is not
sufficient evidence that all graph inputs were used.

### 3. Perform basic statistical sanity checks

Maintain an issue accumulator while running the checks that apply to the paper
and data type. Complete the applicable checklist before deciding the verdict;
do not write the report when the first issue is found. At minimum check:

- counts and retention ratios before and after each preprocessing boundary;
- missing, duplicate, infinite, and obviously invalid values;
- target, major cohort group, and split distributions;
- paper-stated cohort criteria, sample counts, class balance, and the result of
  any stated balancing procedure;
- for every paper-required mapped concept or derived feature, aggregate source
  rows, mapped rows, normalized/accepted rows, and final nonzero or populated
  outputs so a silently dropped component cannot be treated as legitimate zero;
- for time series, sequence counts, length/sampling distributions, temporal
  ordering, and window counts;
- for multimodal data, modality coverage, pairing completeness, label
  correspondence, and file readability.
- for every shared P prefix and branch, artifact identity, row/key propagation,
  branch-specific operations, and proof that the downstream P consumes the
  declared upstream artifact rather than silently rebuilding another cohort;
- for every P consumed by V, the feature/label/split schema and endpoint
  coverage needed for the declared statistical or Cartesian validation block.

For each comparable paper-reported cohort or subgroup size, use the same
population, counting unit, and preprocessing boundary. When `N_paper > 0`, the
count comparison passes if `abs(N_actual - N_paper) / N_paper < 0.01`. Use
unrounded counts; exactly 1% is outside this tolerance. A discrepancy below 1%
must not create an issue or trigger refinement solely because the counts are
unequal. Apply this separately to each reported cohort/subgroup; agreement in
the total cannot cancel a subgroup discrepancy. When `N_paper = 0`, only an
actual zero matches; a missing or incomparable paper count cannot receive this
tolerance-based pass. Outside the tolerance, investigate and apply the
evidence-bound failure rules below rather than tuning the cohort to the count.
Retain the paper and actual counts, absolute difference, relative error when
defined, and paper reference in aggregate evidence under `{{ results_dir }}`,
including passing comparisons. This tolerance applies only to the count
comparison: eligibility, source identity, mappings, labels, splits, and other
methodological checks must still pass. Never implement the tolerance as a
generated-code runtime gate or change preprocessing to reach it.

Natural imbalance described by the paper is not by itself a failure. Decide
whether an observation is significant from the paper's methodology and the
data, and explain the reasoning. The count tolerance above does not provide a
universal cutoff for other statistics.

### 4. Decide and report

Use `PASS` when every runnable P path and direct D→P requirement has been
attempted and the required preprocessing has no significant methodological or
statistical sanity problem.{% if not cloud_drive_enabled %} A
PASS may leave genuinely remote-heavy work unexecuted only when the limitation
and boundary are clear.{% endif %}

Use `FAIL` when preprocessing cannot run because of generated preprocessing
code, the cohort collapses unexpectedly, a target/group disappears, mappings
or units are clearly wrong, or observed preprocessing is seriously
incompatible with the paper.

Decide `PASS` or `FAIL` only after the complete applicable checklist has been
attempted. Before writing a `FAIL`, review the accumulated findings once more
for related symptoms, shared root causes, and independently observable issues.
Report every distinct actionable root cause supported by this audit, not only
the first failure or its downstream symptoms. If an audit-infrastructure or
provider interruption prevents this complete pass, exit nonzero without a
scientific verdict so orchestration retries the same audit attempt.

Write only this compact JSON object to `{{ report_path }}`:

```json
{
  "verdict": "FAIL",
  "issues": [
    {
      "node_id": "P1",
      "description": "Concise evidence-bound statement of the local defect.",
      "route": "preprocessing_fix",
      "evidence": ["results/p1_counts.json", "paper Methods"],
      "diagnosis": "The evidence-bound causal preprocessing or data-contract defect, not merely a symptom.",
      "required_fix": "The testable corrected P behavior or artifact condition required for a future PASS."
    }
  ]
}
```

Use exactly the two top-level fields shown. `PASS` requires an empty `issues`
list. `FAIL` requires the complete accumulated set of distinct actionable
issues and at least one issue. Every issue must contain a runnable origin
`node_id`, a nonblank `description`, `route`, a nonblank evidence-bound
`diagnosis`, and a nonblank `required_fix`; add open paper-specific fields such
as `evidence`, source name, or affected direct inputs when they improve
auditability. Do not use a fixed kind or severity taxonomy.

Use `preprocessing_fix` only when generated cohort/loading/preprocessing logic
within refinement scope should change. Paper omissions, ambiguous scientific
definitions, and unsupported mappings remain preprocessing decisions; they are
not source unavailability.

Use `source_unavailable` only when new concrete source-level evidence disproves
an `available` direct D→P decision in the approved availability report. Inspect
the complete relevant inventory of configured source components, not only the
components selected by generated code, and make this inspection at least as
broad as the evidence supporting the approved decision. Technical/provider
failures are not source unavailability and must exit without a verdict.

Choose the route before defining its required outcome, and keep that outcome
within the selected route. Attach each issue exactly once to the node where it
originates; do not copy it to descendants or list all affected claims, because
orchestration computes lineage propagation later. Keep evidence observational,
diagnosis causal without unsupported speculation, and the required fix
testable. State the observable outcome required after correction, not how
refinement must implement it. Leave detailed commands and statistics in
`{{ results_dir }}` rather than copying them into the report. Before finishing,
reload the JSON and verify all issue IDs are runnable and all cited local
evidence exists.

Begin the preprocessing audit now.
