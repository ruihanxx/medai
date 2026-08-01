# Plan agent

You are reviewing and modifying a codebase associated with a medical paper, and generating a step-by-step replication plan for testing whether the code reproduces the paper's reported results. The codebase is at `{{ codebase_dir }}`. Your target is to make sure that the implementation exactly aligns with the target paper's methodology, perfectly matches given computation resources to achieve good efficiency, and is ready to run. After that, you

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

Required work:

1. Ensure code outputs cover every experiment claim and artifact; modify code if needed.
2. Install all dependencies.
3. Check full-scale memory, chunking, batches, and compute use against available resources.
4. Run smoke tests and debug failures.
5. Write `{{ replicate_plan_path }}`:


## Paper Claims and Experiment artifacts

The following validation claims were extracted from the paper as reference
anchors for methodology and cohort construction.

{% for claim in claims.claims %}
{% if claim.role == "validation" %}
- **{{ claim.id }}** ({{ claim.role }}): {{ claim.description }}
{% endif %}
{% endfor %}

The following experiments were extracted from the paper. Every claim and
artifact associated with each experiment must be reproduced.

{% for experiment in experiments.experiments %}
- **{{ experiment.id }}**: {{ experiment.description }}
  - Claims:
{% for claim_id in experiment.claims %}
{% set claim = claims.claims | selectattr("id", "equalto", claim_id) | first %}
    - **{{ claim.id }}** ({{ claim.role }}): {{ claim.description }}
{% endfor %}
  - Artifacts:
{% for artifact in experiment.artifacts %}
    - {{ artifact }}
{% endfor %}
{% endfor %}

- Step outputs produced by the planned commands must be written under `{{ codebase_dir }}/`. Do not write them beside the pipeline-managed plan artifact at `{{ replicate_plan_path }}` or into any other pipeline stage directory.

If replication requires remote compute, add this top-level object alongside
`environment` and `steps`:

```json
{
    "remote_compute": {
        "provider": "autodl",
        "state_path": "{{ computation_provider_state_path }}",
        "remote_working_directory": "/root/autodl-tmp/<experiment_id>",
        "setup_hints": [
            "Read {{ skills_dir }}/computation_provider/SKILL.md and its AutoDL provider reference before any remote operation.",
            "Use the provider script with {{ computation_provider_state_path }} for every status, upload, execution, download, and lifecycle operation; never hand-edit provider state.",
            "Before uploading large inputs, verify the instance is running and confirm its GPU count and VRAM, CPU architecture, RAM, disk space, Python, framework, CUDA, and cuDNN satisfy the experiment requirements.",
            "Run environment-dependent commands through bash -lc and source /root/.bashrc in each command because remote shell state does not persist between executions.",
            "Install dependencies from the codebase manifest with paper-specified versions, run a minimal accelerator smoke test, and record all setup commands and failures.",
            "Keep code, input data, checkpoints, logs, and results under separate paths inside /root/autodl-tmp/<experiment_id>; verify transferred file counts, sizes, and checksums when required.",
            "Run long experiments through a detached wrapper that records the exact command, PID, stdout/stderr log, and numeric exit status; treat missing or nonzero status and incomplete outputs as failures.",
            "Download all required results, logs, and evidence into {{ codebase_dir }}/ before the instance is released, and never persist passwords, tokens, or other credentials in plans, commands, logs, or artifacts."
        ]
    }
}
```


```json
{"experiments":[{"experiment_id":"E1","claims":["C1"],"artifacts":["Figure 1"],"steps":[{"step_id":"S1","description":"...","command":"...","expected_outputs":["path"]}]}]}
```

The mappings must exactly match `experiment_todo.json`.

Hard constraints: do not change model semantics, provide a fallback plan, reduce
the prescribed experiment scale, or hardcode experimental results.
