# Repository Instructions

## Purpose

Maintain a reproducible, evidence-bound system that converts a medical paper, an optional code repository, and optional local data into executable experiments, audited replication runs, and claim/artifact-level reports.

This repository is a scientific orchestration system. Scientific fidelity, traceability, and explicit failure take precedence over producing a successful-looking run.

## Required reading

Before changing the repository:

1. Read `docs/README.md`.
2. Read `docs/coding_style.md`.
3. Read only the additional document(s) routed by `docs/README.md`.
4. Inspect the relevant implementation and tests.

Do not load every document, generated artifact, log, or prior agent trajectory by default.

## Documentation maintenance

Repository documentation is part of the implementation contract.

When a change occurs, update the corresponding file under `docs/` in the same change:

- repository structure or canonical paths;
- CLI inputs or provider support;
- workflow stages or stage responsibilities;
- persistent artifact names, fields, or validation rules;
- agent inputs, outputs, permissions, or prohibitions;
- skills or external execution boundaries;
- acceptance checks or failure conditions.

When there is no document that records the description of this project under `docs/`, you are allowed to write one. Remember to update `docs/README.md`.

The goal is to help your maintain this repository next time, understand it faster and save token used. So there is a tradeoff between the granularity and token consumption incurred. So keep the document compact and never write unnecessary content.

Do not update documentation for a purely internal change that preserves all documented behavior and interfaces.

Add less test. Do not add test if the change is required to be a "minimal change".

## Working with Codex

- **Commit during implementation; never push.** Run `git add` and `git commit` at each semantic boundary so the git log reflects the change's structure. Never run `git push`, `git push --force`, or any remote-modifying command—the user pushes manually after reviewing the branch.
