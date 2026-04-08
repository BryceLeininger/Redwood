# Sample Deal Input Structure

Use this folder as a template for organizing a real diligence package before the first test run. The CLI will recurse through subfolders, so the grouping is for operator clarity rather than a hard technical requirement.

```text
sample_deal_input/
|-- 01_overview/
|-- 02_entitlements/
|-- 03_environmental/
|-- 04_civil_and_geotech/
|-- 05_utilities/
|-- 06_title_and_survey/
|-- 07_schedule_and_budget/
`-- 08_misc_correspondence/
```

Suggested contents:

- `01_overview/`
  - offering memorandum
  - seller summary memo
  - site plan
  - aerial exhibits
- `02_entitlements/`
  - zoning letters
  - entitlement matrix
  - annexation materials
  - tentative or final plat exhibits
- `03_environmental/`
  - Phase I ESA
  - wetlands report
  - biological or cultural constraints memo
  - drainage or FEMA correspondence
- `04_civil_and_geotech/`
  - geotechnical report
  - grading concept
  - civil engineering memo
  - stormwater study
- `05_utilities/`
  - will-serve letters
  - utility maps
  - offsite sewer or water exhibits
  - infrastructure cost assumptions
- `06_title_and_survey/`
  - title commitment
  - exception documents
  - ALTA survey
  - access exhibits
- `07_schedule_and_budget/`
  - milestone schedule
  - fee schedule
  - offsite cost summary
  - reimbursement or participation agreements
- `08_misc_correspondence/`
  - seller Q&A
  - jurisdiction emails
  - consultant notes

Recommended filename style:

- Start with a date when available: `2026-03-14_phase1_esa.pdf`
- Use lowercase words with underscores
- Keep filenames descriptive enough to scan in a file list

For a real run, place one deal under `data/input/<deal-folder>/` using this structure, then point the CLI at that deal folder.
