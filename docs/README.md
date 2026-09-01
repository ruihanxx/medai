# Documentation Router

Before changing the repository, always read `coding_style.md` and
`change_scope.md`, then read only the contract files whose routing conditions
match the change:

| Change area | Read |
| --- | --- |
| Host launcher, CLI flags, initialization, provider configuration, MinerU, mounts, Docker isolation, or orchestration-owned remote lifecycle and cleanup | `execution.md` |
| Base replication stages, failure behavior, checkpoints, resume, or manifest state | `replication.md` |
| Auto Research eligibility, validation setup, idea graphs, audit, assessment, routing, or campaign state | `autoresearch.md` |
| Canonical run paths, artifact fields, validation rules, evidence, or report structure | `artifacts.md` |
| Prompt locations, agent information/mutation boundaries, transcripts, invocation handoffs, or the runtime-skill interface | `agents.md` |
| Revising project files after feedback | `proportional_revision.md` |
| Required local checks or mocked external boundaries | `acceptance.md` |

For a cross-cutting change, read each matching row. Do not load unrelated
contract files by default.

## Ownership

- `../AGENTS.md`: repository-wide operating rules.
- `coding_style.md`: coding style maintained by the project owner; do not duplicate it elsewhere.
- `change_scope.md`: target-state minimality, complete removal, minimal
  additions, and proportional recurrence prevention.
- `execution.md`: public host execution, isolation, and orchestration-owned remote-lifecycle contract.
- `replication.md`: base replication workflow contract.
- `autoresearch.md`: Auto Research workflow contract.
- `artifacts.md`: persistent path and artifact-validation contract.
- `agents.md`: agent, prompt, invocation, and runtime-skill interface boundaries.
- `proportional_revision.md`: proportional revision rules for project files after feedback.
- `acceptance.md`: repository acceptance checks.
- `../scripts/`: operator-maintained API guides and helpers for external
  services; these are not runtime skills or agent instructions.
- `../templates/skills/`: runtime skill contracts; metadata-selected provider
  references are the canonical documentation for provider-specific procedures.

Put each rule in one canonical file. Link to it elsewhere instead of restating it.
