"""Regression tests for deterministic first-pass fact extraction."""

from __future__ import annotations

import unittest
from pathlib import Path

from land_due_diligence_agent.analysis.first_pass import build_issue_registry
from land_due_diligence_agent.deal_models import ClassificationResult, ManifestEntry, ProcessedDocument
from land_due_diligence_agent.models import DocumentRecord, ExtractedChunk


def _processed_document(relative_path: str, text: str, *, category: str) -> ProcessedDocument:
    path = Path(relative_path)
    document = DocumentRecord(
        source_path=path,
        relative_path=path,
        extension=path.suffix or ".txt",
        title=path.stem.replace("_", " ").title(),
        raw_text=text,
        normalized_text=text,
        chunks=[
            ExtractedChunk(
                document_name=path.name,
                chunk_id="chunk-0001",
                text=text,
                page_number=1,
            )
        ],
    )
    classification = ClassificationResult(
        category=category,
        document_type_guess="memo",
        confidence="high",
    )
    manifest_entry = ManifestEntry(
        file_path=str(path),
        relative_path=path.as_posix(),
        file_name=path.name,
        extension=path.suffix or ".txt",
        size_bytes=len(text.encode("utf-8")),
        last_modified="2026-04-08T00:00:00+00:00",
        supported=True,
        document_type_guess="memo",
        category=category,
        classification_confidence="high",
        ocr_used=False,
        extraction_status="success",
    )
    return ProcessedDocument(
        document=document,
        classification=classification,
        manifest_entry=manifest_entry,
    )


class FirstPassRegistryTests(unittest.TestCase):
    def test_filters_fragment_noise_and_interprets_count_conflicts(self) -> None:
        processed_documents = [
            _processed_document(
                "planning_notes.txt",
                "Zoning: setbacks, development standards. Proposed 93 units total for the project.",
                category="Entitlement / Planning / Conditions",
            ),
            _processed_document(
                "concept_plan.txt",
                "Building A contains 5 units. The full development totals 127 units.",
                category="Map / Plat / Improvement Plans",
            ),
            _processed_document(
                "vesting_notes.txt",
                "Owner: ship fees, leases.",
                category="Vesting / Legal",
            ),
        ]

        registry = build_issue_registry(
            processed_documents,
            [processed.manifest_entry for processed in processed_documents],
        )

        zoning_values = [fact.value.lower() for fact in registry.facts if fact.fact_type == "zoning"]
        owner_values = [fact.value.lower() for fact in registry.facts if fact.fact_type == "owner_name"]

        self.assertEqual(zoning_values, [])
        self.assertEqual(owner_values, [])

        unit_conflict = next(conflict for conflict in registry.conflicts if conflict.fact_type == "unit_count")
        self.assertIn("93 to 127", unit_conflict.description)
        self.assertNotIn("5", unit_conflict.description)
        self.assertIn("controlling unit program", unit_conflict.uncertainty.lower())


if __name__ == "__main__":
    unittest.main()