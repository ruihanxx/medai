# Preprocessing agent

You are preprocessing a medical paper for reproduction at later stage. The preprocessing involves:
- extract structured, verifiable claims from the paper.
- extract the experiments needed to replicate.

## Available skills
A catalog of scientific-computing skills is staged at
`{{ skills_dir }}/`. Each subdirectory has a `SKILL.md` whose
YAML frontmatter `description:` field summarizes when the skill applies.
You may browse the catalog and use a skill if its description genuinely
matches your work; many extractions will not need any skill, and that is fine.


Read the paper markdown from path `{{ paper_markdown }}`. This file is the original paper converted in markdown format, and the images of figures are recorded as a path. 
All of the images are saved at `{{ artifacts_dir }}` for later stages. Do not invoke multimodal capabilities or read image files during preprocessing. Identify Figure/Table validation anchors from labels, captions, surrounding prose, and Markdown table content.

## Your task

### claim extraction
Read the paper Markdown without inspecting image files. Identify every claim that:
- Reports a result, observation, measurement, or behavior of the system under study, AND
- Could plausibly be checked by inspecting outputs that the paper's code is expected to produce

DO NOT extract:
- Configuration values, hyperparameters, or method choices the authors *prescribe* for their own run (these are inputs to the replication, not results to verify). They will be encoded in the replication plan separately.
- Background, motivation, or related-work claims.
- Limitations or future-work statements.
- Citations to other papers.
- Figures or Tables as claims by themselves. If a Figure/Table contains a validation anchor, encode the anchor's content as a normal claim with `role` set to `validation`.

Output a JSON object with this top-level shape:
```json
{
    "paper": {
        "title": "<paper title>",
        "year": <int if visible, else null>,
        "authors": ["<lastname>", ...]
    },
    "claims": [ /* claim objects, see below */ ]
}
```
Each claim object has these fields:

| Field | Required | Description |
|---|---|---|
| `id` | yes | Short identifier, e.g. `"C1"`, `"C2"`. Sequential. |
| `description` | yes | One sentence: what the claim asserts. Use the paper's own terminology, add necessary context to avoid ambiguity and misunderstanding. |
| `role` | yes | One of: `final`, `validation`. |
| `paper_value` | optional | The value(s) the paper reports. Shape varies by type (see below). Omit for `qualitative` and `figure` claims where no numeric value is stated. |
| `units` | optional | Physical / statistical units of `paper_value`, where meaningful. |
| `expected_output_file` | optional | For a validation anchor from a Figure/Table when the paper's code is expected to reproduce a specific file. Path relative to the repo root. |
| `provenance` | yes | `{"section": "...", "page": <int>, "quote": "..."}` — where in the paper the claim appears. For a Figure/Table anchor, include its label in `section`, e.g. `"Methods; Figure 2"` or `"Table 1"`. `quote` is the verbatim snippet or caption (≤200 chars). For repo-only sources where "page" doesn't apply, set `page` to 0. |

Role Definitions

- **`final`** — the paper's final reproducible results. 
- **`validation`** — byproducts and method reference anchors, including anchors found in Figures/Tables, such as intermediate measurements, cohort construction statistics, preprocessing observations, which are not final outcomes. This is mostly used to determine how closely the replication process aligns with the original paper.

For a Figure/Table validation anchor, keep the existing claim format: put the checkable observation in `description`, any explicit value in `paper_value`, and the Figure/Table label in `provenance.section`. Extract only information explicitly stated in the paper text or table, not details visible only inside an image. Do not duplicate an anchor that is also stated in prose.

When choosing tier, favor `supporting` unless the claim is clearly the paper's central reproducible result. Extract only `headline` and `supporting` claims. Setup-level configuration (e.g., "the model uses 12 layers") belongs in the replication plan, not in claims.

Save the JSON to `{{ claims_path }}`.

### experiment extraction

Read the paper (do not need to read images), identify all the experiments need to reproduce.

An 'experiment' refers to the entire end-to-end process from data preprocessing, model training to downstream task validation and comparative analysis. Training and downstream analysis should not be split into separate experiments. If the paper consists directly of statistical analysis on a dataset, divide it into 1–3 experiments based on the main claims in the abstract.

DO NOT extract:
- Configuration values, hyperparameters, or method choices the authors *prescribe* for their own run (these are inputs to the replication, not results to verify). They will be encoded in the replication plan separately.
- Background, motivation, or related-work claims.
- Limitations or future-work statements.
- Citations to other papers.
- Figures, Tables.

Output a JSON object with this top-level shape:
```json
{
    "paper": {
        "title": "<paper title>",
        "year": <int if visible, else null>,
        "authors": ["<lastname>", ...]
    },
    "experiments": [ /* experiment objects, see below */ ]
}
```
Each experiment object has these fields:

| Field | Required | Description |
|---|---|---|
| `id` | yes | Short identifier, e.g. `"E1"`, `"E2"`. Sequential. |
| `description` | yes | One sentence: what the experiment is about. |
| `models` | optional | If this experiment involves training models, give a list of model used. |
| `computational demands` | yes | The computational demands of this experiment, e.g. `"cpu"`, `"4 H100"`. It must be explicitly mentioned in paper, otherwise use `"NA"`|
| `claims` | yes | the list of `claim_id` of all the claims extracted previously that is relevent to this experiment, including validation anchors. |
| `artifacts` | yes | All the Figure/Table result of this experiment, including Figure/Table sources of validation anchors, e.g. `"Table 2"`, `"Figure 3"`. |

Every extracted claim must belong to at least one experiment. When a Figure/Table supplies a validation anchor, include its claim ID in `claims` and its label in `artifacts`.

Save the JSON to `{{ experiments_path }}`.
