# Claim-graph code generation agent

{% if infrastructure_resume|default(false) %}
This is an infrastructure resume after orchestration replaced an unavailable
remote instance. The replacement is already running and recorded at
`{{ computation_provider_state_path }}`. Do not create or release another
instance. Preserve the current local codebase and source preparation, then
restore every remote prerequisite represented by the existing implementation:
upload code and ordinary local data again, recreate the environment, and rerun
remote setup checks. For cloud-backed data, follow the selected drive's
foreground handoff contract for every reviewed cloud-materialization action and
require completed state before inspection.
Rerun all codegen self-review checks before completing the stage.
{% elif resuming %}
This stage is resuming after an interrupted code-generation attempt. Inspect the
existing files in `{{ codebase_dir }}/`, preserve valid completed work, repair or
finish incomplete work, and rerun every self-review check before declaring the
stage complete.
{% else %}
This is the first code-generation attempt. The codebase is intentionally empty;
create an independent implementation from the paper and approved data evidence.
{% endif %}
By the end of this session, the directory at `{{ codebase_dir }}/` must contain a runnable
implementation of the runnable paper-graph subgraph with scientific fidelity
across every method, including all preprocessing, model-construction, training,
and evaluation details. Report an explicit failure only when a failure condition
described below actually occurs; never invent or hard-code a failure condition.


## Inputs
- Paper Markdown: `{{ paper_markdown }}`
- Immutable paper graph: `{{ paper_graph_path }}`
- Approved execution scope: `{{ execution_scope_path }}`
- Preflight resources: `{{ resources_path }}`
{% if cloud_drive_enabled|default(false) %}
- Cloud datasets (drive provider: `{{ drive_provider }}`):
{% for dataset in cloud_datasets|default([cloud_dataset]) %}
  - `{{ dataset }}`{% if cloud_sources|default([])|length > loop.index0 %}, source `{{ cloud_sources[loop.index0] }}`{% endif %}
{% endfor %}
  Resolve every materialized path only through the computation-provider state.
{% if data_dir %}
- Local data root (read-only and preferred for local execution): `{{ data_dir }}`
- Selected local dataset directories: {% for path in data_paths|default([data_dir]) %}`{{ path }}`{% if not loop.last %}, {% endif %}{% endfor %}
{% else %}
- No local raw-data path exists.
{% endif %}
- Selected provider reference: `{{ computation_provider_reference|default("<selected-provider-reference>") }}`
- Selected drive reference: `{{ drive_reference|default("<selected-drive-reference>") }}`
{% else %}
- Data root: `{{ data_dir or "not supplied" }}`
{% if data_dir %}- Selected dataset directories: {% for path in data_paths|default([data_dir]) %}`{{ path }}`{% if not loop.last %}, {% endif %}{% endfor %}{% endif %}
{% endif %}
- Codegen plan: `{{ codegen_plan_path }}`
- Scope-revision issue output: `{{ scope_revision_path }}`

Read the graph and scope before inspecting or modifying code. Implement only
the scope's `runnable_node_ids` and use only its `active_sources`. The graph is
immutable: do not edit it, the execution scope, or `graph/node_state.json`.

This is an independence boundary. Do not search for, open, clone, download, or
inspect any source-code repository disclosed by the paper, supplied through the
CLI, or stored elsewhere in the run. Do not inspect sibling preflight files,
the manifest, environment variables, or filesystem locations to discover such
a repository. A later isolated stage owns repository comparison and calibration.
## Available skills

A catalog of scientific-computing skills is staged at
`{{ skills_dir }}/`. Each subdirectory has a `SKILL.md` whose
YAML frontmatter `description:` field summarizes when the skill applies.
You may browse the catalog and use a skill if its description genuinely
matches your work; many papers will not need any skill, and that is fine.

Before writing `codegen_plan.json` (Step 2.5), run
`ls {{ skills_dir }}/` and read each `SKILL.md`'s description.
If any skill matches your paper's domain or methodology, note it — you
can invoke its scripts and reference docs while implementing in Step 3.

## Delegation

After establishing the runnable graph and shared scientific definitions, read
`{{ skills_dir }}/context-delegation/SKILL.md` for substantial exploration or
implementation work. Delegate bounded source-schema inspection, a coherent
method's implementation requirements, or targeted self-review of generated code.
Every worker inherits the repository-independence boundary above; none may read
original repositories, sibling snapshots, or information excluded from this stage.

Before assigning implementation, the parent writes the codegen plan and fixes
shared cohort/split semantics, data interfaces, configuration ownership, and
entry points. An implementation worker may edit only an explicitly assigned,
independent set of generated-code paths. Keep shared pipeline changes and the
canonical plan with the parent; do not assign one writer per graph node when
nodes share code. Apply the stage's serial-command rule across parent and
workers: use one command-capable worker at a time, with no parent commands or
edits until it finishes. Provider operations and cloud-materialization handoffs
remain with the parent. After integration, the parent checks all runnable paths
and required self-review outcomes, including cross-module leakage and artifact
interfaces. For a small implementation, work directly.

## Workflow

Follow this four-step structure. Take time on each step; do not rush.

### 1. Explore

Read the paper carefully. Prioritize:

- **Methodology / Methods** sections — the procedures you will implement.
- **Cohort construction / Experimental setup / Data** sections — hyperparameters,
  dataset specs, initial conditions, cohort construction rules.
- **Model architecture / Algorithms** — what to build.

Use the paper graph as the implementation map. Start from every runnable C and
walk its `inputs` backward through all runnable ancestors. Treat every input as
an AND dependency and preserve the graph's fine-grained D/P/T/M/V/C meanings:

- D identifies a source dataset or source cohort.
- P produces one materializable cohort, split, label, transform, or feature
  state from its declared D/P inputs. Distinct P nodes remain independently
  configurable, materializable, and auditable even when they share code.
- T is one executable fitting or training operation over all declared inputs.
- M is one concrete trained artifact. Different seeds, parameters, training
  inputs, fine-tuning routes, or implementations remain distinct M artifacts.
- V consumes its declared M/P inputs and computes one claim-aligned validation
  or statistical result block. Its model/data/metric sets denote the complete
  Cartesian product, so implement every represented cell.
- C transforms its supporting V results into the paper claim. A statistical
  `P -> V -> C` path is first-class and must not be forced through training code.

For every runnable D→P boundary, cross-check the graph against the paper's
Methods, cohort/data, training, validation, and external-validation text. Keep
every named source, role, preprocessing path, linkage boundary, fitting or
evaluation use, and output explicit. If the graph, paper, and available source
are inconsistent, choose and implement the interpretation most consistent with
the paper overall, record the conflict, alternatives, and rationale on its exact
origin node, and continue. Do not silently drop a required input or substitute
another source; concrete unavailable D→P content follows the scope-revision
procedure below.

Claims and validations may originate from a figure or table. When implementing
a runnable figure or chart, open and inspect its linked image artifact rather
than relying only on the caption. Identify the corresponding plot type and
supported formatting parameters in the chosen plotting toolchain, then
reproduce the observable layout, dimensions, axes, scales, legends, colors,
line and marker styles, fonts, uncertainty displays, and annotations as closely
as practical. Plot only actual reproduced data; never infer or hard-code paper
results from image pixels.

You may also skim Results and Discussion sections for context, but
do not memorize numerical results for hardcoding (see Self-Review).

### 2. Plan

First choose the computational stack, then outline the file structure.

**Match the paper's computational demands.** Read every runnable node's method
and provenance and infer any unstated computational demand from the paper. Implement in the language and framework the methodology genuinely needs, not whichever is fastest to write. If the method's scale depends on compiled or GPU performance — a large-N numerical simulation, an iterative sampling or optimization procedure with many steps, large-scale model training or inference — use tools that deliver it: GPU-enabled libraries (PyTorch / CuPy / JAX) when a GPU is present, JIT or vectorized paths (numba), C/C++ extensions via the available gcc toolchain, or R for R-native methods — pure Python/NumPy on CPU is the easy default, but it is only correct when the paper's own scale doesn't need more. An implementation that is faithful on paper but cannot run at the paper's scale will fail the replication.

The availability stage already made the binding local/remote capacity decision
recorded in `{{ execution_scope_path }}`. The resource rules below explain that
decision's contract; use them to implement within the selected location, but do
not repeat, override, or broaden the capacity and data-locality decision.

Use the execution location and capacity evidence already recorded by the
availability stage. Match the implementation to that location and full-scale
methodology without changing the recorded decision, selecting another provider,
or shrinking a runnable node's required scale.

{% if computation_provider %}
The availability stage already selected the execution location. Read
`{{ skills_dir }}/computation_provider/SKILL.md` and the selected reference at
`{{ computation_provider_reference|default("<selected-provider-reference>") }}`
only to realize that binding decision. If cloud data is active, Availability
already created and materialized the run-owned instance at
`{{ computation_provider_state_path }}`: read
`{{ drive_reference|default("<selected-drive-reference>") }}`, reuse the state,
and use only completed runnable-dataset entries. If data is local-only and the
approved scope says `remote`, create the run-owned instance now—after the gate—
using the recorded capacity floors and reviewed provider selection procedure,
then upload only the required runnable-scope data. If the scope says `local`,
do not search offers or create an instance. Never rematerialize skipped data,
upload skipped local data, or revise the recorded location/capacity decision.
Never create a second or untracked instance. The selected remote dataset root
and working directory must come from the run-owned state and selected provider
reference.
The host project `.env` is intentionally absent; configuration is already
available to the reviewed adapter, and secrets must never be printed.
{% endif %}

{% if cloud_drive_enabled|default(false) and cloud_pull_handoff|default(false) %}
If materialization is incomplete, do not invoke the selected adapter's
`cloud-pull` action from a shell tool. Return every reviewed materialization
action, including separate preparation and monitoring actions, as
`{"status":"command","command":"<foreground adapter command>","error":null}`
and end the turn. Orchestration runs each command to a terminal result while
this Codex process is absent, saves its complete log and result, and resumes
this same session. Reread canonical provider state after every resume. Never
inspect provider state while a handed-off command is running, inspect incomplete
cloud data, or continue code generation before orchestration resumes with
completed materialization.
{% endif %}

Command execution is serial. If a shell or tool call reports that it is still
running or returns an execution/session handle, the next tool call must wait on
or poll that same handle, or explicitly terminate it. Do not start another
command, edit files, perform another check, or return any structured result
until the running execution has produced a terminal event. If abandoning it,
terminate it explicitly and continue waiting until its terminal event is
recorded. Never leave more than one command execution running. Before returning
any structured result, ensure every command or tool call from the current turn
has reached a terminal state.

If a successful, evidence-based procedure conflicts with the selected skill
reference, do not edit the repository skill. Append one reviewable correction
to `{{ skill_corrections_path }}` instead:
```json
{
  "skill": "computation-provider",
  "provider": "<selected provider>",
  "reference_path": "references/<provider>.md",
  "discrepancy": "What the reference says and what differed.",
  "resolved_procedure": "The successful, safe procedure used in this run.",
  "documentation_urls": ["https://official-provider-documentation.example/"]
}
```
Use only non-secret information. Leave this initialized JSON array unchanged
when no correction is needed.

The preflight snapshot at `{{ resources_path }}` is the authoritative local CPU,
memory, disk, and GPU observation for this decision. Run the `get-available-resources` skill
(`{{ skills_dir }}/get-available-resources/scripts/detect_resources.py`) again
only if you have evidence that the snapshot is stale.

Outline the file structure of your codebase before writing any code:

- What modules do you need?
- What is their dependency order?
- Where will entry points live?
- What dependencies (packages, system libraries) are needed?

Track Python dependencies in `pyproject.toml` or `requirements.txt` (your choice; pick one and be consistent); a non-Python stack additionally uses its native manifest (e.g. R's `DESCRIPTION`).

**Dataset Processing and Cohort Construction**

Implement every runnable D→P source contract explicitly. For each D and each P
that directly consumes it, keep the source path/configuration, cohort or split
construction, preprocessing, linkage or pooling boundary, downstream
fitting/evaluation role, and outputs distinguishable in code. When datasets are
combined, implement and describe each source-specific path before the merge and
preserve source and node identity in intermediate checks and result outputs. Do
not write one generic loader or configuration entry whose intended source
changes implicitly by execution order.

Preserve cohort IDs and split assignments, make randomness explicit and
reproducible, and produce auditable intermediate counts or summaries for each
P before its artifacts are consumed downstream.

{% if cloud_drive_enabled|default(false) %}
{% if data_dir %}
For a local conclusion, inspect `{{ data_dir }}` directly and keep it read-only.
For a remote conclusion, inspect only the completed materialized remote target
recorded in provider state. Do not mix the two sources, upload local raw data,
or materialize the cloud source when local execution was selected. In either
case, use bounded, non-executing reads and inspect documentation or metadata
before representative content.
{% else %}
Inspect only the completed materialized remote dataset directory recorded in
the current provider state. Keep it read-only. Use bounded, non-executing reads
and inspect documentation or metadata before representative content. Do not
download raw files locally, create a local CPU data adapter, or inspect the
cloud source before materialization completes.
{% endif %}
{% elif data_dir %}
Inspect `{{ data_dir }}` directly as needed to implement the paper.
Keep the raw root read-only. Bound the number of files, bytes, rows, and field
lengths read. Never extract archives or deserialize pickle, joblib, model
checkpoints, or any other format that may execute code. Prefer dataset
documentation and metadata before sampling large files; inspect only the
representative content required for implementation.
{% else %}
No data was supplied. Do not invent a dataset or fabricate data-dependent
results.
{% endif %}

Strictly follow the paper's dataset processing and cohort construction procedures.

If concrete inspection proves that a currently runnable direct D→P requirement
is unavailable, do not invent, substitute, or silently skip it. Write
`{{ scope_revision_path }}` using the exact current scope hash and the affected
runnable P and D IDs:

```json
{
  "scope_sha256": "<current scope hash>",
  "issues": [
    {
      "node_ids": ["P1"],
      "dataset_ids": ["D1"],
      "required_content": "what is missing",
      "evidence": "concrete source evidence"
    }
  ]
}
```

Then return `blocked` so orchestration can rerun the availability stage.
Technical failures and implementation defects remain ordinary `failed`
outcomes and must never be mislabeled as unavailable source data.

For large raw tables/dataframes, use this processing pattern: Reads large raw
tables/dataframe in chunks or bounded batches, applies chunk-eligible
preprocessing immediately after each chunk read, projects required columns,
drops unrelated columns before retaining data, and defers full-data operations
such as downsampling after chunk-processed compact data is merged.

When the paper uses specialized cohort, clinical, or methodological terms that
cannot be mapped directly to the available source, resolve the mapping only
when the dataset schema, metadata, paper context, and relevant
medical knowledge support it. Consult authoritative external sources for a
general clinical or methodological convention when necessary, but never use
them to invent a paper-specific fact or substitute a required source. When no
mapping has direct paper support, choose and implement the mapping best supported
by the dataset schema, paper context, accepted medical knowledge,
and the paper's overall methodology; record the uncertainty, alternatives, and
rationale on its exact origin node and continue.

Do not skip, weaken, or obscure any requirement because of uncertainty. Record
every evidence-backed non-direct mapping in the origin node's `node_updates`
entry in Step 2.5.

### 2.4. Resolve paper omissions and contradictions before implementation

Before writing `codegen_plan.json` or code, make a complete pass through the
methodology to identify every implementation decision that the paper does not
state directly or states inconsistently. This includes, where applicable,
clinical definitions and coding, eligibility and exclusion rules, index time
and follow-up windows, outcome and censoring rules, missing-data handling,
preprocessing, covariate selection, split/grouping units, model fitting, and
statistical reporting.

For each omission, resolve it before implementation when the evidence supports
one faithful choice; do not leave a TODO, silently apply a library default, or
substitute an arbitrary generic default. For each internal contradiction, choose
and implement the interpretation most strongly supported by the paper's explicit
methods and unambiguous context and most consistent with the study design, the
rest of the methodology, and the reported tables and figures. Do not stop solely
because the paper contains conflicting statements; record the contradiction and
the selected interpretation as an issue on its exact origin node.
Use this order of precedence:

1. The paper's explicit methods and unambiguous context.
2. The supplied dataset schema and metadata, when they are consistent with the
   paper.
3. Widely accepted medical knowledge and standard medical-research methods
   that fit the study design, population, outcome, and available data. For a
   material or contested decision, consult an authoritative clinical guideline,
   reporting guideline, or methodological reference rather than guessing.

Implement the resulting choice exactly in code and configuration. Add one issue
to the exact origin node's `node_updates` entry for each paper-underspecified or
internally contradictory decision. Its `description` must state what the paper
omitted or which statements conflict; its `assumption`, `rationale`, `evidence`,
and `implementation_location` must state the selected interpretation, why it is
the best fit, what supports it, and where it is implemented. For a contradiction,
also record the rejected interpretations in `alternatives` and explain why the
selected interpretation best preserves the paper's overall consistency. Do not
copy the issue into descendants. These records document the resolution; they are
not permission to defer implementation or invent paper-specific facts.

Do not directly read large data files. First read the available document to get basic informations.

If using a document during this run naturally reveals information that the document omitted, append an entry to `{{ dataset_patch_path }}`. This file is initialized as a JSON array, and every entry must have exactly this form:
```json
{
  "file name": "dataset_graph.yaml",
  "patch_content": {}
}
```
Set `"file name"` to the document's file name. Set `"patch_content"` to only
the missing content, structured like the target document so it can be reviewed
and applied later. If this run does not naturally encounter an omission, leave the initialized empty array unchanged. Do not proactively search those documents for omissions. Only add important omissions; it's ok to omit some not generally used details.

### 2.5. Capture the plan to disk

Before writing code, write `{{ codegen_plan_path }}` with
your decisions so they are inspectable and machine-readable. Schema:

```json
{
  "files": [
    {"path": "src/model.py", "responsibility": "T1/M1 implementation"},
    {"path": "src/dataset.py", "responsibility": "D1 -> P1 implementation"}
  ],
  "dependency_order": ["src/dataset.py", "src/model.py", "..."],
  "entry_points": ["python main.py"],
  "shared_state": "For every runnable node, name its direct input node artifacts, local operation, concrete output, and downstream consumers.",
  "node_updates": [
    {
      "node_id": "P1",
      "issues": [
        {
          "description": "Paper says 'we use a small batch size' without naming a value.",
          "assumption": "Use batch_size=32.",
          "rationale": "Evidence-bound reason for this choice.",
          "evidence": ["paper Methods", "dataset schema"],
          "implementation_location": "project configuration"
        }
      ]
    }
  ],
  "remote_compute": null
}
```

If remote compute is required{% if cloud_drive_enabled|default(false) and not data_dir %} (it is
mandatory for this cloud-backed run){% endif %}, `remote_compute` must instead contain these
required fields:

```json
{
  "state_path": "{{ computation_provider_state_path }}",
  "remote_working_dir": "<provider-reference-defined-run-directory>",
  "remote_dataset_dir": "<provider-reference-defined-read-only-dataset-directory>"
}
```

You may add provider, resource, image, connection, setup, or rationale fields
needed for execution and audit. `state_path` must name the exact current-run
path shown here. The working and dataset directories must match the selected
provider reference and run-owned state; cloud-backed runs must use only the
completed materialized targets validated by orchestration.

`node_updates` is the place to record every point where the paper
underspecifies methodology and you had to make a judgment call. Use only
runnable node IDs. Put each issue on the earliest exact node where the decision
originates and do not copy it into descendants. An empty list is valid when no
local issue or resolved assumption exists. The orchestrator assigns the update
source and merges it into the run overlay; do not edit `graph/node_state.json`.

In `shared_state` and relevant file `responsibility` entries, narrate the data
flow node by node in dependency order. For every runnable node, name each direct
input node ID and concrete artifact or configured source, then say separately
what is read, derived, linked, fitted, evaluated, or emitted. Generic statements
such as "load all data" or "use upstream outputs" are incomplete. Before saving
the plan, verify that every runnable node appears in this narration or has a
deliberate report-only treatment consistent with its category. Report-only
treatment is not a way to skip executable P/T/M/V work.

Double-check the following places during cohort construction where the paper is highly likely to underspecify the methodology and implementations:
- index-time definition, time-window specification, baseline ascertainment
- window-level aggregation, value selection rule, worst-value selection, cumulative aggregation
- episode reconstruction, exposure ascertainment, treatment-course construction
- physiologic plausibility filtering, unit harmonization, record deduplication, concept mapping
- computable phenotype, clinical-score reconstruction, outcome ascertainment
- missing-data handling, default-normal imputation, absence-as-negative assumption
- repeated-encounter handling, one-record-per-patient selection

Make sure you put these issues in the exact origin node's `node_updates` entry
and address them with the best evidence-supported approach based on established
medical knowledge and standard clinical data-processing practices.

### 3. Implement

Write the code, module-by-module. Guidelines:

- Prefer small, focused files. One clear responsibility per file.
- Use the paper's own variable names where natural.
- Preserve an existing auditable configuration system when resuming generated
  work.
  If none exists, extract every paper-stated hyperparameter into `config.yaml`
  at the codebase root. Use one section per logical group: `training:`
  (learning rate, batch size, epochs, optimizer settings, seeds), `model:`
  (layer sizes, activation choice, dropout), `data:` (dataset name, split
  sizes, preprocessing knobs), and any methodology-specific group (`sampling:`,
  `mcmc:`, etc.). Do not scatter paper-stated hyperparameters across source
  literals. A code reader should be able to audit every paper-stated input from
  the project's configuration.
- Set up dataset paths and other inputs as configuration the methodology
  calls for; don't hardcode anything that needs to be computed.
- Keep graph node IDs traceable in entry points, configuration, intermediate
  artifacts, or output metadata. Shared functions are allowed, but they must
  not merge distinct P or M semantics or obscure which V Cartesian cells ran.
- You may install packages and create directories as needed. Preserve useful
  structure already created during an interrupted independent attempt.
- Do not run the methodology end-to-end. That is a later phase.
  Your job is to produce the codebase; verifying it imports cleanly
  is part of Self-Review, but a full training/inference run is out
  of scope.


### 4. Self-Review

Before declaring done, complete every item in this audit:

#### 0. Graph scope and coverage audit

Reload the immutable graph and execution scope. Starting separately from every
runnable C, walk backward through all runnable ancestors and confirm:

- every runnable node has an executable implementation or category-appropriate
  report-only treatment, and no inactive node or inactive source is accessed;
- every direct graph input is consumed as an AND dependency and produces the
  concrete artifact or configured source expected by its consumer;
- every P remains a distinct materializable state, every T produces its
  downstream M artifact, and non-identical seed/parameter/input M nodes are not
  merged;
- every V executes its complete declared model/data/metric Cartesian product,
  while statistical P→V→C paths remain free of invented training stages;
- the graph, scope, and orchestration-owned node state remain unchanged.

Correct the implementation, plan, or node-local updates and repeat the affected
C-to-D traversal before continuing.

#### a. Re-read methodology, then audit faithfulness

Open the paper again. For each runnable algorithm / procedure described:

- Find the corresponding code.
- Confirm it implements what the paper says, not what you assumed.
- Fix any divergence.

#### b. Inputs-vs-outputs audit (anti-leakage)

The paper distinguishes two kinds of numbers: **inputs** (configuration
prescribed by the methodology — hyperparameters, batch size, dataset
size, model architecture, version pins, simulation initial conditions)
and **outputs** (results the paper reports — accuracy, posterior
estimates, table values).

- **Inputs** are allowed as constants in your code.
- **Outputs** must be **computed by your code**, not hardcoded.

Treat every graph `paper_result` as an observed output, never as an
implementation input, tuning target, seed-selection signal, fallback value, or
criterion for choosing between plausible code paths. Never substitute synthetic
data for a required source.
Actual computed results may differ from `paper_result`; preserve and report the
discrepancy. Never encode agreement with `paper_result` as an assertion,
reconciliation gate, success criterion, or exception condition.

Test for each numerical constant: *would this number change if the
experiment were re-run? If yes, it is an output and must be computed.
If no, it is an input and may be hardcoded.*

Examples:

| Paper says | Type | Hardcode? |
|---|---|---|
| "learning rate 2e-5, batch size 32, 3 epochs" | Input | Yes |
| "trained on 161 systems from Albrecht+22" | Input | Yes (dataset spec) |
| "model achieved 92.3% accuracy" | Output | No — compute it |
| "posterior mean w_1 = 0.719 ± 0.085" | Output | No — compute it |
| "max_treedepth=13" | Input | Yes |
| "rhat values were all <1.01 after sampling" | Output | No — compute it |

Scan every numerical constant in your code and apply the test. If a
constant matches a paper-reported result, replace it with code that
computes the value from the methodology.

#### c. Import sanity

For each Python module you wrote, run:

```bash
python -c "import <module_name>"
```

Fix any `ImportError`, `SyntaxError`, or `ModuleNotFoundError`. The codebase must be importable end-to-end before you exit. For non-Python components, run the equivalent smoke check (the C/C++ code compiles; R sources parse).

#### d. Dependency completeness

Re-open `pyproject.toml` / `requirements.txt`. Are all imports listed?
Do versions pin to what the paper used (when stated)?

#### e. Config audit

Open the project's configuration. For each paper-stated hyperparameter, confirm:

- It lives in the auditable project configuration, not as a scattered literal
  in implementation code.
- Its value matches the paper. If the paper specifies a range or several tried
  values but not the selection rule, preserve all required settings and record
  the unresolved or evidence-supported choice on its origin node; never choose
  a value because it produces the closest `paper_result`.
- Code that needs the value reads it from configuration, not from an unrelated
  default function argument or hidden module-level constant.

If the generated codebase has no suitable configuration, create `config.yaml` at the
codebase root and move the paper-stated inputs there.

#### f. Node-local assumption audit

Open `{{ codegen_plan_path }}`. For every assumption or issue in
`node_updates`, confirm the chosen resolution is reflected in code and
configuration, is fully executable rather than a TODO or library default, and
is the most accurate fit under accepted medical knowledge and standard medical
research methods for this study. Re-check that every paper-underspecified
implementation decision has an entry on its exact origin node; if
implementation revealed another underspecification, resolve it with the same
hierarchy and add it now. Ensure no issue was copied into descendants and every
node update uses a runnable ID. Future phases rely on these records.

#### g. Intermediate-anchor & selection-sanity audit

Most methodologies have an **upstream step** — a selection, grouping,
coordinate cut, unit/zero-point correction, or fit — whose output silently
feeds every downstream result. A wrong choice here is the single largest
source of cascade failures: one mis-selected sample corrupts every claim
that depends on it. For each such upstream step, confirm:

- **Apply every documented transformation, even "optional"-sounding ones.**
  If the methodology prescribes a transform — a normalization/standardization,
  a baseline or zero-point subtraction, a unit/frame conversion, or a domain
  correction (e.g. a batch-effect correction in genomics; deflation to real
  terms in economics; a K-correction or dereddening in astronomy) — apply it
  in the code. Do NOT assume the input already has it on the basis of a prose
  phrase ("normalized counts", "deflated GDP", "K-corrected photometry"). If
  the data ships the term as a column (e.g. a `*_norm` / `_real` / `kcorr_*`
  field), that is a strong signal the correction is yours to apply.

- **Handle periodic / wrapped quantities with wrap-aware masks.** A cut near
  the wrap point of a periodic variable (a phase, a compass azimuth,
  time-of-day/day-of-year, or an angle/longitude such as RA or Galactic `l`)
  must match BOTH ends — e.g. `(x < 10) | (x > 350)`, never `abs(x) < 10`.

- **Disambiguate multiple-choice inputs by methodological fidelity.** When a
  step could use one of several plausible columns/keys/parameters — e.g. which
  data split (train vs validation vs test), which ID namespace groups records
  (gene symbol vs accession ID; customer vs household; `haloID` vs `fofID`),
  which grouping unit for a fixed-effect or clustered-error term, which
  instrument channel — do NOT silently pick one. Pick the option the
  methodology actually specifies; record the alternatives in
  the exact origin node's `node_updates` entry.

- **Validate intermediates against documented METHOD invariants — never
  against reported results.** If the methodology prescribes an invariant as an
  input or procedure (for example unit-variance scaling or an exact fold count),
  have the code assert or log it. Observed cohort counts, fit coefficients,
  metrics, table values, figure values, and graph `paper_result` fields are
  outputs: compute and preserve them for later comparison, but never use them to
  select a column, parameter, seed, implementation branch, or alternative.

- **Sanity-check the step's output before using it downstream.** If a
  selection yields an implausible count (e.g. one sub-group far smaller than
  its sibling, or a cut that removes almost everything), a fit's coefficients
  land far from a stable solution, or a "stable range" collapses to a single
  point, treat the result as suspect: re-derive it robustly (e.g. seed an
  iterative fit or clustering from the data rather than from a hardcoded
  anchor), or record the fragility on the exact origin node in `node_updates`.
  Write these checks as assertions or warnings **in the code** so the
  replicate phase surfaces a corrupted intermediate instead of silently
  propagating it into every claim.
#### h. Code efficiency audit

Double-check the generated code files related to data loading, preprocessing,
cohort construction. Make sure it follows the pattern:
- Reads large raw tables/dataframe in chunks or bounded batches,
- applies chunk-eligible preprocessing immediately after each chunk read, projects required columns,
drops unrelated columns before retaining data, and defers full-data operations
such as downsampling after chunk-processed compact data is merged.

Do not reduce model, sample, grid, epoch, seed, or resampling scale merely for
speed. When a real resource limit prevents a faithful executable path, record
the affected origin node and measured constraint, then return a terminal
`blocked` or `failed` result rather than marking Codegen complete with a
reduced-scale fallback.

## Hard constraints

- Write into `{{ codebase_dir }}/`, except that dataset-document improvements
  may be written to `{{ dataset_patch_path }}` and provider-skill corrections to
  `{{ skill_corrections_path }}` as described above. Do not modify the source
  dataset documents, raw data, staged skills, immutable paper graph,
  execution scope, or orchestration-owned node state.
- `codegen_plan.json` lives at the codebase root. Preserve an existing
  configuration system; otherwise create `config.yaml` there.
- Do not commit. Orchestration owns the generated codebase and stage artifacts.
- Do not run the methodology end-to-end; that is the next phase.

{% if structured_stage_result|default(false) %}
## Required final stage result

Except for an intermediate cloud-pull handoff described above, end the turn with
exactly the structured result required by the supplied output schema:

```json
{"status": "completed", "error": null}
```

Use `completed` only after every owned codegen artifact is ready for
orchestration validation, every runnable graph node passes the coverage audit,
and no non-runnable source is accessed. Use `blocked` only for concrete
unavailable direct D→P source content reported through the scope-revision
procedure above or a measured resource constraint covered by the efficiency
audit. Never treat an unpublished manifest, hyperparameter, paper omission,
contradiction, or mapping decision as an external prerequisite; resolve it using
the paper-consistency rules in Step 2.4, record the issue, and continue. Use
`failed` with a non-empty `error` only for a provider, infrastructure, or
technical operation that remains unsuccessful after its bounded recovery
procedure. Do not create placeholder artifacts to obtain `completed`, and do not
run a shell `exit 1` to report either terminal status.
{% endif %}
