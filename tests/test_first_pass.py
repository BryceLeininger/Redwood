"""Regression tests for deterministic first-pass fact extraction."""

from __future__ import annotations

import unittest
from pathlib import Path

from land_due_diligence_agent.analysis.first_pass import build_issue_registry
from land_due_diligence_agent.deal_models import ClassificationResult, ManifestEntry, ProcessedDocument
from land_due_diligence_agent.models import DocumentRecord, ExtractedChunk


def _processed_document(
    relative_path: str,
    text: str,
    *,
    category: str,
    ocr_pages: list[int] | None = None,
    warnings: list[str] | None = None,
    page_count: int = 1,
) -> ProcessedDocument:
    path = Path(relative_path)
    document = DocumentRecord(
        source_path=path,
        relative_path=path,
        extension=path.suffix or ".txt",
        title=path.stem.replace("_", " ").title(),
        raw_text=text,
        normalized_text=text,
        metadata={"page_count": page_count},
        warnings=list(warnings or []),
        ocr_pages=list(ocr_pages or []),
        chunks=[
            ExtractedChunk(
                document_name=path.name,
                chunk_id="chunk-0001",
                text=text,
                page_number=1,
                ocr_used=bool(ocr_pages),
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

    def test_validation_filters_invalid_values_and_deduplicates_registry(self) -> None:
        processed_documents = [
            _processed_document(
                "purchase_agreement.txt",
                "APN: 123-456-78. Site acreage: 049 acres. Proposed 84 units total for the project.",
                category="Purchase / Sale / Contract",
            ),
            _processed_document(
                "title_report.txt",
                "Preliminary title report. APN: 123-456-78. Vesting owner: Diana Land Holdings LLC.",
                category="Title",
            ),
            _processed_document(
                "planning_notes.txt",
                "Current zoning: of seasonal moisture. Jurisdiction: Morgan HillTelephone. 2025 units.",
                category="Entitlement / Planning / Conditions",
            ),
        ]

        registry = build_issue_registry(
            processed_documents,
            [processed.manifest_entry for processed in processed_documents],
        )

        facts_by_type = {}
        for fact in registry.facts:
            facts_by_type.setdefault(fact.fact_type, []).append(fact)

        self.assertEqual(len(facts_by_type["apn"]), 1)
        self.assertEqual(len(facts_by_type["apn"][0].sources), 2)
        self.assertEqual(facts_by_type["site_acreage"][0].normalized_value, "49")
        self.assertEqual([fact.normalized_value for fact in facts_by_type["unit_count"]], ["84"])
        self.assertEqual(facts_by_type["owner_name"][0].value, "Diana Land Holdings LLC")
        self.assertNotIn("zoning", facts_by_type)
        self.assertNotIn("jurisdiction", facts_by_type)
        self.assertFalse(any(conflict.fact_type == "unit_count" for conflict in registry.conflicts))
        self.assertGreaterEqual(registry.validation_stats.filtered_count, 3)
        self.assertGreaterEqual(registry.validation_stats.deduplicated_count, 1)

    def test_owner_name_requires_title_or_vesting_source(self) -> None:
        processed_documents = [
            _processed_document(
                "purchase_agreement.txt",
                "Seller: Redwood Sponsor LLC. Buyer shall close within thirty days.",
                category="Purchase / Sale / Contract",
            )
        ]

        registry = build_issue_registry(
            processed_documents,
            [processed.manifest_entry for processed in processed_documents],
        )

        owner_values = [fact.value for fact in registry.facts if fact.fact_type == "owner_name"]
        self.assertEqual(owner_values, [])
        self.assertTrue(any("title report or vesting document" in entry.reason for entry in registry.validation_log))

    def test_ocr_only_fact_is_excluded_from_first_pass_registry(self) -> None:
        processed_documents = [
            _processed_document(
                "scanned_title_report.txt",
                "Vesting owner: Redwood Owner LLC.",
                category="Title",
                ocr_pages=[1],
                page_count=1,
            )
        ]

        registry = build_issue_registry(
            processed_documents,
            [processed.manifest_entry for processed in processed_documents],
        )

        self.assertEqual([fact for fact in registry.facts if fact.fact_type == "owner_name"], [])
        self.assertEqual(registry.validation_stats.low_confidence_excluded_count, 1)


if __name__ == "__main__":
    unittest.main()