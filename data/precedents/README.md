# Precedent Store

This folder holds local outcome records used to calibrate canonical issues against prior deals.

## File

- `issue_memory.jsonl`

Each line is one JSON object with this shape:

```json
{
  "precedent_id": "anon-west-deal:title-access-clearance",
  "issue_id": "title-access-clearance",
  "issue_type": "title-access-clearance",
  "canonical_title": "Title and access clearance is not closed",
  "category": "Title / Access Concerns",
  "deal_id": "anon-west-deal",
  "deal_name": "Anon West Deal",
  "deal_metadata": {
    "stage": "acquisition-dd",
    "geography": "west",
    "product": "multifamily"
  },
  "description": "Preliminary title exceptions conflicted with the access layout shown in the plan set.",
  "evidence_basis": "direct_unresolved_risk",
  "issue_strength": "strong",
  "real_issue": true,
  "materiality": "high",
  "decision_relevant": true,
  "actual_outcome": "delay",
  "false_positive_flag": false,
  "resolved_by": "seller",
  "notes": "Cleared through survey reconciliation, title endorsements, and a revised access exhibit."
}
```

## How To Capture Real Deal Outcomes

1. After each live deal, open the latest `11_issue_registry_debug.md` and `12_reviewer_feedback_template.json`.
2. Fill in reviewer feedback on the JSON template:
   - `real_issue`
   - `false_positive_flag`
   - `duplicate_of`
   - `materiality`
   - `decision_relevant`
   - `actual_outcome`
   - `resolved_by`
   - `notes`
3. The next CLI run for that deal will ingest any annotated feedback files and upsert them into `issue_memory.jsonl`.
4. Record the actual outcome as the primary commercial effect:
   - `cost`
   - `delay`
   - `redesign`
   - `none`
   - `unknown`
5. Mark `false_positive_flag` as `true` only when the issue surfaced but later proved immaterial, duplicative, or routine.
6. Use `resolved_by` to capture who actually carried the fix:
   - `seller`
   - `buyer`
   - `unknown`
7. Keep `notes` short and factual. Focus on what actually closed the issue.
8. Prefer consistent `issue_id` / `issue_type` values from the canonical registry so retrieval stays stable over time.

## Practical Capture Standard

- Use one record per canonical issue per deal outcome.
- Add records only after the team knows how the issue actually resolved.
- If the issue changed category but was still the same underlying problem, keep the original `issue_id` / `issue_type` and explain the nuance in `notes`.
- If no geography or product is known, leave those fields blank rather than guessing.
