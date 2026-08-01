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
{"claims": [/* claim objects, see below */]}
```
Each claim object has these fields:

| Field | Required | Description |
|---|---|---|
| `claim_id` | yes | Short identifier, e.g. `"C1"`, `"C2"`. Sequential. |
| `statement` | yes | One sentence: what the claim asserts. Use the paper's own terminology and enough context to avoid ambiguity. |
| `role` | yes | One of: `final`, `validation`. |
| `kind` | yes | One of: `text`, `numeric`. Figure/Table anchors still use one of these based on their content. |
| `paper_result` | optional | The value or concise observation reported by the paper. Use `null` when no result value is stated. |
| `provenance` | yes | `{"section": "...", "page": <positive int>, "quote": "..."}` — where in the paper the claim appears. For a Figure/Table anchor, include its label in `section`, e.g. `"Methods; Figure 2"` or `"Table 1"`. `quote` is a verbatim snippet or caption of at most 200 characters. |

Role Definitions

- **`final`** — the paper's final reproducible results. 
- **`validation`** — byproducts and method reference anchors, including anchors found in Figures/Tables, such as intermediate measurements, cohort construction statistics, preprocessing observations, which are not final outcomes. This is mostly used to determine how closely the replication process aligns with the original paper.

For a Figure/Table validation anchor, keep the existing claim format: put the checkable observation in `statement`, any explicit value in `paper_result`, and the Figure/Table label in `provenance.section`. Extract only information explicitly stated in the paper text or table, not details visible only inside an image. Do not duplicate an anchor that is also stated in prose.

Example — a table reporting cohort construction after preprocessing (adapt every value to the paper; do not copy example values or placeholder text):
```json
{
    "claim_id": "C3",
    "statement": "The cohort counts and statistical characteristics after preprocessing are shown in Table 3.",
    "role": "validation",
    "kind": "numeric",
    "paper_result": {"<reported statistic>": "<reported value>"},
    "provenance": {
        "section": "Cohort construction; Table 3",
        "page": 6,
        "quote": "<Table 3 caption or supporting sentence, at most 200 characters>"
    }
}
```

Extract only final results and validation anchors that support those results. Setup-level configuration (e.g., "the model uses 12 layers") belongs in the replication plan, not in claims.

Save the JSON to `{{ claims_path }}`.

### experiment extraction

Read the paper (do not need to read images), identify all the experiments need to reproduce.

An 'experiment' refers to the entire end-to-end process from data preprocessing, model training to downstream task validation and comparative analysis. Training and downstream analysis should not be split into separate experiments. If the paper consists directly of statistical analysis on a dataset, divide it into 1–3 experiments based on the main claims in the abstract.

DO NOT extract:
- Configuration values, hyperparameters, or method choices the authors *prescribe* for their own run (these are inputs to the replication, not results to verify). They will be encoded in the replication plan separately.
- Background, motivation, or related-work claims.
- Limitations or future-work statements.
- Citations to other papers.
- Standalone experiments whose only purpose is a Figure/Table label. Record
  requested Figure/Table outputs in the enclosing experiment's `artifacts`.

Output a JSON object with this top-level shape:
```json
{"experiments": [/* experiment objects, see below */]}
```
Each experiment object has these fields:

| Field | Required | Description |
|---|---|---|
| `experiment_id` | yes | Short identifier, e.g. `"E1"`, `"E2"`. Sequential. |
| `description` | yes | One sentence: what the experiment is about. |
| `claims` | yes | the list of `claim_id` of all the claims extracted previously that is relevent to this experiment, including validation anchors. |
| `artifacts` | yes | All the Figure/Table result of this experiment, including Figure/Table sources of validation anchors, e.g. `"Table 2"`, `"Figure 3"`. |

Every extracted claim must belong to at least one experiment. When a Figure/Table supplies a validation anchor, include its claim ID in `claims` and its label in `artifacts`.

Save the JSON to `{{ experiments_path }}`.
