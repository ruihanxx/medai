---
name: explore-data
description: Inspect known or arbitrary local medical and scientific datasets during code generation. Use before writing codegen_plan.json to identify paths, formats, schemas, representative values, reader requirements, and explicit ambiguities without modifying raw data.
---

# Explore Data

Treat the supplied data directory as the raw root. Keep it read-only. Write the
result to the requested `data_inventory.json` before planning or implementing
the paper.

## Workflow

1. Identify the dataset from the paper and the supplied path.
2. For MIMIC-IV, read `metadata/mimic-iv.json`, select only the tables needed
   by the paper, and run:

   ```bash
   python adapter/mimic-iv_adapter.py RAW_ROOT \
     --output DATA_INVENTORY \
     --file hosp/admissions.csv.gz \
     --file icu/icustays.csv.gz
   ```

   Omitting `--file` writes the complete catalog without row samples. Selected
   files include up to five actual rows by default.
3. For every other dataset, including PTB-XL, run:

   ```bash
   python adapter/generic_adapter.py RAW_ROOT --output DATA_INVENTORY
   ```

   Use repeated `--file RELATIVE_PATH` arguments when the automatic
   representatives do not cover the paper's inputs.
4. Read the inventory. Rescan narrower paths when `scan.truncated` is true.
   Record unresolved formats, missing readers, and sampling limitations in the
   codegen plan instead of guessing.

Both adapters accept `--rows` and `--max-field-chars`. Their
`DatasetAdapter` classes also expose `list_resources()`, `sample()`,
`build_inventory()`, and `write_inventory()`.

## Format references

Load only the reference that matches the observed data:

- General tables, arrays, containers, archives, and waveforms:
  `references/general_scientific_formats.md`
- Genomics, sequence, alignment, and expression data:
  `references/bioinformatics_genomics_formats.md`
- DICOM, NIfTI, microscopy, and whole-slide images:
  `references/microscopy_imaging_formats.md`
- Proteomics and metabolomics:
  `references/proteomics_metabolomics_formats.md`

Search the selected reference by extension rather than loading every reference.
When an extension is ambiguous, use file signatures and the paper's domain and
record the remaining ambiguity.

## Safety and evidence

- Never write inside the raw root.
- Never extract archives during exploration.
- Never load pickle, joblib, model checkpoint, or another format that may
  execute code. Reference examples do not override this rule.
- Keep reads bounded. Preserve actual sampled values, truncation flags, reader
  errors, and missing dependencies in the inventory.
- Do not infer a schema or modality from an extension alone when content
  inspection disagrees.
