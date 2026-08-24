# eICU-CRD Dataset Graph

| Entity | Resource | Key field | Parent resource | Join field | Cardinality |
| --- | --- | --- | --- | --- | --- |
| Patient | `patient` | `uniquepid` | — | — | one patient to many hospital stays |
| Hospital stay | `patient` | `patienthealthsystemstayid` | `patient` | `uniquepid` | many hospital stays to one patient |
| ICU unit stay | `patient` | `patientunitstayid` | `patient` | `patienthealthsystemstayid` | many ICU unit stays to one hospital stay |
| Admission medication | `admissiondrug` | `admissiondrugid` | `patient` | `patientunitstayid` | many events to one ICU unit stay |
| Admission diagnosis | `admissiondx` | `admissiondxid` | `patient` | `patientunitstayid` | many events to one ICU unit stay |
| Infectious disease care plan | `careplaninfectiousdisease` | `cplinfectid` | `patient` | `patientunitstayid` | many events to one ICU unit stay |
| Diagnosis | `diagnosis` | `diagnosisid` | `patient` | `patientunitstayid` | many events to one ICU unit stay |
| Infusion medication | `infusiondrug` | `infusiondrugid` | `patient` | `patientunitstayid` | many events to one ICU unit stay |
| Medication order | `medication` | `medicationid` | `patient` | `patientunitstayid` | many events to one ICU unit stay |
| Microbiology result | `microlab` | `microlabid` | `patient` | `patientunitstayid` | many events to one ICU unit stay |
| Note | `note` | `noteid` | `patient` | `patientunitstayid` | many events to one ICU unit stay |
| Respiratory care | `respiratorycare` | `respcareid` | `patient` | `patientunitstayid` | many events to one ICU unit stay |
| Treatment | `treatment` | `treatmentid` | `patient` | `patientunitstayid` | many events to one ICU unit stay |
| Periodic vital signs | `vitalperiodic` | `vitalperiodicid` | `patient` | `patientunitstayid` | many events to one ICU unit stay |

All event offsets are measured in minutes relative to ICU unit admission. Link event files to `patient` with `patientunitstayid`; use `patienthealthsystemstayid` to group unit stays within one hospitalization and `uniquepid` to group hospitalizations for one patient.
