# Plan agent

You are generating a step-by-step replication plan for testing whether a paper's code reproduces the paper's reported results.  The codebase at `{{ codebase_dir }}` was just written from the paper by an earlier phase and may be rough.

## Inputs:
- Paper Markdown: `{{ paper_markdown }}`
- Data: `{{ data_dir or "not supplied" }}` (read-only)
- Previously extracted reproduction informations, which include:
   - Claims: `{{ claims_path }}`
   - Experiments to reproduce: `{{ experiments_path }}`
- Remote computation state, when remote compute was selected: `{{ computation_provider_state_path }}`

## Available skills

A catalog of scientific-computing skills is staged at
`{{ skills_dir }}/`. Each subdirectory has a `SKILL.md` whose
YAML frontmatter `description:` field summarizes when the skill applies.
You may browse the catalog and reference relevant skills in planning steps if
a skill genuinely matches; many plans will not need any skill, and that
is fine.

If remote computation was selected, read
`{{ skills_dir }}/computation_provider/SKILL.md` and then the selected
provider reference named by that skill before planning remote operations.


## Paper Claims and Experiment artifacts

The following validation claims were extracted from the paper as reference
anchors for methodology and cohort construction. Some anchors may originate
from a Figure/Table while retaining the same claim format.

{% for claim in claims.claims %}
{% if claim.role == "validation" %}
- **{{ claim.claim_id }}** ({{ claim.role }}): {{ claim.statement }}
  - Source: {{ claim.provenance.section }}
{% if claim.paper_result is not none %}
  - Anchor value: {{ claim.paper_result | tojson }}
{% endif %}
{% endif %}
{% endfor %}

The following experiments were extracted from the paper. Every claim and
artifact associated with each experiment must be reproduced.

{% for experiment in experiments.experiments %}
- **{{ experiment.experiment_id }}**: {{ experiment.description }}
  - Claims:
{% for claim_id in experiment.claims %}
{% set claim = claims.claims | selectattr("claim_id", "equalto", claim_id) | first %}
    - **{{ claim.claim_id }}** ({{ claim.role }}): {{ claim.statement }}
{% endfor %}
  - Artifacts:
{% for artifact in experiment.artifacts %}
    - {{ artifact }}
{% endfor %}
{% endfor %}


Each plan step should produce evidence relevant to one or more claims/artifacts (except for pure setup steps); use the claim IDs (e.g. `C1`, `C2`) or artifacts index (e.g. Figure 2, Table 3) in the `verifies` field of each step. Reproduce experiment one after another.
For a Figure/Table-sourced validation anchor, plan evidence for both its claim ID and its Figure/Table artifact label.

## Your Task

Explore the repository and generate a replication plan — a sequence of concrete steps that an agent should execute to produce evidence for the claims above. The plan should cover:

1. **Remote server setup** (if required) - how to connect, upload code files and dataset
2. **Environment setup** — what to install, any system requirements
3. **Running the code** — training scripts, experiments, evaluations
4. **Collecting outputs** — what files / metrics each step produces
5. **Remote server termination** (if required) - terminate instance to avoid additional charge.

For each step, provide:
- A clear description of what to do
- A command hint (the likely command to run)
- A **shape-prescriptive** `expected_outcome`: describe the structure of the expected output (file path, JSON field names, figure file location, log message format) — DO NOT include the paper's reported result values.
- A `verifies` list of claim IDs or artifacts index whose verification depends on this step's output. Empty list is allowed for pure-setup steps (e.g. installing dependencies).

### Shape-prescriptive examples

GOOD (shape-prescriptive):
- "Produces `output/metrics.json` with field `accuracy` (float in [0,1])."
- "Writes `figures/HRD.pdf` showing the HR diagram for all three binaries."
- "Logs to stdout in the format `[step] X done, time=Y s`."

BAD (value-prescriptive — DO NOT do this):
- "Accuracy reaches ~92%."
- "Figure shows three peaks at 100, 200, 300 Hz."
- "Loss converges below 0.5."

The replication agent never sees the paper's reported result values. Including them in `expected_outcome` would leak ground truth to the agent and defeat the verification step.

### Setup values from the paper ARE allowed

Setup values that the paper *prescribes* (hyperparameters, dataset sizes, version pins, simulation initial conditions like initial masses or metallicity) ARE allowed in step descriptions and command hints. They tell the agent how to run, not what answer to produce.

GOOD:
- "Run the training with learning rate 2e-5, batch size 32, 3 epochs (paper §3.1)."

This is a setup value, not a result.

### Plan at the paper's scale — no pre-authorized reductions

Plan every result-producing step at the full scale the methodology prescribes — problem size, resolution, iteration count, dataset, and seed count. Do NOT write reduced-scale fallbacks into the plan — no "if intractable, shrink the problem" clauses, no `--quick`/`--fast`-style shortcut flags, no downsized parameter grids. There is no hidden time budget to plan around: a heavy step may legitimately run for hours or multiple days if that is what the methodology needs — runtime alone is never a reason to plan a smaller step. If the plan offers a reduced-scale escape hatch, the executing agent will take it and the run will produce numbers at the wrong scale.

When a step is genuinely expensive, plan for *efficiency at full scale* instead: prefer the repo's compiled/vectorized code paths, use the GPU when one is available and the method supports it, or split the computation into resumable chunks. Whether to reduce scale is the executing agent's runtime decision, made only under a genuine resource limit and recorded explicitly — never a plan provision.
{% if gpu_info %}

**Hardware available for this plan:** a GPU is present in this environment: {{ gpu_info }}. Steps whose method benefits from GPU acceleration should plan to use it, and `setup_hints` should say so, rather than assuming a CPU-only path.
{% endif %}

## Scope

Focus on the paper's **headline and supporting claims**. Do not attempt to reproduce setup-only assertions, ablation studies, or appendix-only results unless they are essential to a headline claim.

## Rules

- Order steps logically: setup first, then execution, then verification
- Include 3-10 steps (enough to cover the headline claims, not exhaustive)
- The agent executing this plan will work on a writable copy of the repo at `{{ codebase_dir }}/`
- The agent may fix issues in the code to keep replication going (deprecated APIs, missing imports, configuration problems)
- If you find multiple entry points or experiments, prioritize the one that targets the headline claim
- Every result-producing step MUST have at least one claim ID or artifacts index in `verifies`. Setup-only steps may have an empty `verifies` list. Prefer 1-3 steps dedicated to one single experiment.
- Step outputs produced by the planned commands must be written under `{{ codebase_dir }}/`. Do not write them beside the pipeline-managed plan artifact at `{{ replicate_plan_path }}` or into any other pipeline stage directory.
- NEVER include the paper's reported numerical result values in `expected_outcome`.

## Output

Save the plan to `{{ replicate_plan_path }}` with this format:

```json
{
    "environment": {
        "language": "the language(s) the implementation actually uses",
        "key_dependencies": ["list", "of", "main", "packages"],
        "setup_hints": "Toolchains to install and hardware to use (e.g. which steps should run on the GPU). Never pre-authorize reduced-scale runs here."
    },
    "steps": [
        {
            "id": 1,
            "description": "What this step does",
            "command_hint": "the command to run",
            "expected_outcome": "Shape of expected output (NOT the paper's reported values)",
            "verifies": ["C1", "C2"]
        }
    ]
}
```
If replication requires remote compute, add this top-level object alongside
`environment` and `steps`:

```json
{
    "remote_compute": {
        "state_path": "{{ computation_provider_state_path }}",
        "remote_working_dir": "<provider-reference-defined-run-directory>",
        "remote_dataset_dir": "<provider-reference-defined-read-only-dataset-directory>",
        "provider": "<selected-provider>",
        "setup_hints": [
            "Use the selected provider reference and the local state at {{ computation_provider_state_path }} to resolve the current connection and connect to the remote server.",
            "Upload the code from {{ codebase_dir }}/ and the experiment's required input data to the run-owned locations defined by the selected provider reference."
        ]
    }
}
```
Only `state_path`, `remote_working_dir`, and `remote_dataset_dir` are required
and statically validated. Additional provider and execution fields are allowed.
Also add a step in `"steps"` to terminate and release the instance.

Begin your analysis now.
