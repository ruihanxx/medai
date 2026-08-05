## Unresolved Items

| item | location | reason | risk | recommended_action | blocking |
| --- | --- | --- | --- | --- | --- |
| Full row counts for large raw tables | diagnoses_icd, emar, emar_detail, labevents, microbiologyevents, omr, pharmacy, poe, poe_detail, prescriptions, transfers, chartevents, datetimeevents, ingredientevents, inputevents, outputevents | Large gzip CSV files were not fully scanned during default normalization. | Low for schema use; row-count-sensitive audits need a deeper pass. | Run `python validation.py --deep` only after adding explicit row-count checks or use a dedicated offline profiler. | no |
| Full official per-variable prose not exhaustively transcribed | resources.yaml | Local raw directory has no README/data dictionary files beyond CHANGELOG/LICENSE/SHA256SUMS; official web docs were used with local headers and conservative inference. | Medium for ambiguous non-key columns. | Consult the relevant MIMIC table page when a column's clinical meaning is task-critical. | no |
| Row-level previews suppressed | adapter.py preview() | MIMIC-IV is sensitive clinical data; previews are schema-only by default. | Low; intentional privacy guard. | Use `iter_rows(..., limit=n)` locally only when row-level inspection is necessary and permitted. | no |
