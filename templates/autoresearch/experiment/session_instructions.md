# Auto Research experiment agent

Execute the planned refinement experiments for `{{ idea_id }}`.

## Inputs

- Frozen experiment contracts: `{{ contracts_path }}`
- Experiment plan: `{{ experiment_plan_path }}`
- Implementation plan: `{{ implementation_plan_path }}`
- Passing audit: `{{ audit_path }}`
- Writable idea codebase: `{{ codebase_dir }}`
{% if cloud_drive_enabled %}
- Cloud dataset: `{{ cloud_dataset }}` (drive provider: `{{ drive_provider }}`),
  available only at the completed read-only target in provider state.
- Selected provider reference: `{{ computation_provider_reference }}`
- Selected drive reference: `{{ drive_reference }}`
{% else %}
- Data: `{{ data_dir or "not supplied" }}`
{% endif %}
- Existing baseline log and environment: `{{ base_replication_log }}`,
  `{{ base_evidence_summary }}`
- Remote-compute state: `{{ computation_provider_state_path }}`

## Task

Execute every experiment and its steps in order. Run only the newly added,
audited refinement variant through its refinement-only entry point. Never run an
old existing experiment entry point or rerun or alter the replicated baseline.
Preserve actual outputs. If execution fails, record the failure without editing
the already audited code.

Treat replication intermediates as unavailable unless this prompt explicitly
lists them. Do not look for or require base-run cohort or feature tables, split
files, caches, checkpoints, temporary output roots, or model state. The audited
refinement must use the fixed raw input and its own execution path instead.

{% if cloud_drive_enabled %}
Read `{{ skills_dir }}/computation_provider/SKILL.md`, the selected provider
reference, and the selected drive reference. Reuse only the pool member selected
through the supplied campaign state and the completed `remote_dataset_dir` from the plan.
Upload only the audited idea code. Download only experiment models, metrics,
logs, and aggregate evidence needed by the local artifacts. Never download raw
or row-level dataset content, reauthorize or rematerialize the drive, create a
second instance, or release the instance.
{% endif %}

{% if command_handoff %}
## Command handoff protocol

Before returning the first command, create the local mother-environment
directory `{{ local_environment_dir }}` with both:

- `setup.sh`: an idempotent Bash program accepting the remote environment path
  as `$1` and the synchronized remote codebase path as `$2`. It must create or
  validate the complete runtime at `$1` from local dependency definitions and
  must not read the dataset or run an experiment.
- `environment.json`: a non-empty JSON object describing the selected language,
  runtime, dependency inputs, and material divergences from the plan or base
  evidence. Neither file may contain credentials or copied environment secrets.

Derive this definition from the experiment plan and the validated base evidence
listed above. Prefer the base run's proven runtime when it satisfies the audited
dependencies; record any necessary divergence instead of assuming an unavailable
paper-version executable.

Use only `{{ remote_environment_dir }}` as the experiment runtime. Local
orchestration synchronizes the audited local codebase and this mother-environment
definition to every selected campaign instance, then runs `setup.sh` before each
foreground command. Commands must therefore treat the synchronized remote code
and environment as authoritative and must not create an unrecorded environment
elsewhere.

Return exactly one JSON object with one non-empty field:
`{"command":"<foreground bash command>"}`. Do not directly run or monitor a
remote experiment or provider command in this agent turn. Local orchestration
will select a usable campaign instance, execute and stream the command from the
idea codebase, save its combined log and terminal result, power that instance
off, then resume this session. Use each resumed result to continue or debug
until all local experiment artifacts validate.

Every returned command must remain in the foreground. Do not use `nohup`, `&`,
or a detached remote launcher. Use only the provider adapter's reviewed upload,
exec, and download operations. Do not include power-on, power-off, release, or
instance-creation actions; those lifecycle transitions belong to orchestration.
{% endif %}

## Output

After every completed step, rewrite `{{ experiment_log_path }}`:

```json
{
  "experiments": [
    {
      "experiment_id": "E1",
      "step_outcomes": [
        {
          "step_id": 1,
          "description": "step description",
          "command_executed": "actual refinement-only command",
          "exit_code": 0,
          "stdout": "captured output",
          "stderr": "captured error output",
          "output_files": ["actual output paths"],
          "duration_seconds": 1.0,
          "fixes_applied": [],
          "code_modified": false,
          "notes": "observations"
        }
      ]
    }
  ]
}
```

Write `{{ evidence_summary_path }}` using the existing evidence-summary schema.

## Constraints

- Store experiment artifacts inside `{{ codebase_dir }}` or `{{ experiment_dir }}`.
- Never execute a baseline entry point or overwrite base results.
- Never fabricate, hard-code, or overwrite computed refinement results.
- Do not modify any code; every `code_modified` value must be false and every
  `fixes_applied` list must be empty.
- Do not modify the base run or source data.
{% if cloud_drive_enabled %}
- Keep the remote dataset read-only and ensure every cited output has been
  downloaded into the local idea codebase or experiment directory.
{% endif %}
