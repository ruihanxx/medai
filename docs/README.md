# Documentation Router

Before changing the repository, always read `coding_style.md`, then read only
the contract files whose routing conditions match the change:

| Change area | Read |
| --- | --- |
| Host launcher, CLI flags, initialization, provider configuration, MinerU, mounts, or Docker isolation | `execution.md` |
| Base replication stages, failure behavior, checkpoints, resume, or manifest state | `replication.md` |
| Auto Research eligibility, idea rounds, audit, experiment, assessment, routing, or campaign state | `autoresearch.md` |
| Canonical run paths, artifact fields, validation rules, evidence, or report structure | `artifacts.md` |
| Prompt locations, agent permissions/prohibitions, transcripts, runtime skills, or remote-compute lifecycle | `agents.md` |
| Required local checks or mocked external boundaries | `acceptance.md` |

For a cross-cutting change, read each matching row. Do not load unrelated
contract files by default.

## Ownership

- `../AGENTS.md`: repository-wide operating rules.
- `coding_style.md`: coding style maintained by the project owner; do not duplicate it elsewhere.
- `execution.md`: public host execution and isolation contract.
- `replication.md`: base replication workflow contract.
- `autoresearch.md`: Auto Research workflow contract.
- `artifacts.md`: persistent path and artifact-validation contract.
- `agents.md`: agent, prompt, skill, and external-compute boundaries.
- `acceptance.md`: repository acceptance checks.
- `../scripts/`: operator-maintained API guides and helpers for external
  services; these are not runtime skills or agent instructions.

Put each rule in one canonical file. Link to it elsewhere instead of restating it.
