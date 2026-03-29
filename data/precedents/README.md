# Precedent Store

This folder holds local outcome records used to calibrate canonical issues against prior deals.

## File

- `issue_memory.jsonl`

Each line is one JSON object with this shape:

```json
{
  "precedent_id": "anon-west-001",
  "deal_name": "Anon West Deal",
  "issue_type": "title-access-clearance",
  "canonical_title": "Title and access clearance is not closed",
  "category": "Title / Access Concerns",
  "description": "Preliminary title exceptions conflicted with the access layout shown in the plan set.",
  "deal_metadata": {
    "stage": "acquisition-dd",
    "region": "west",
    "product": "multifamily"
  },
  "real_issue": true,
  "materiality": "high",
  "actual_outcome": "delay",
  "false_positive_flag": false,
  "resolution_notes": "Cleared through survey reconciliation, title endorsements, and a revised access exhibit."
}
```

## How To Capture Real Deal Outcomes

1. After each live deal, open the latest `11_issue_registry_debug.md` and `12_reviewer_feedback_template.json`.
2. Mark which canonical issues were real, duplicated, overstated, understated, or not decision-relevant.
3. After closing, retrade, or kill, add one JSON line per canonical issue to `issue_memory.jsonl`.
4. Record the actual outcome as the primary commercial effect:
   - `cost`
   - `delay`
   - `redesign`
   - `none`
5. Mark `false_positive_flag` as `true` only when the issue surfaced but later proved immaterial or routine.
6. Keep `resolution_notes` short and factual. Focus on what actually closed the issue.
7. Prefer consistent `issue_type` values from the canonical registry so retrieval stays stable over time.

## Practical Capture Standard

- Use one record per canonical issue per deal outcome.
- Add records only after the team knows how the issue actually resolved.
- If the issue changed category but was still the same underlying problem, keep the original `issue_type` and explain the nuance in `resolution_notes`.
- If no region or product is known, leave those fields blank rather than guessing.
