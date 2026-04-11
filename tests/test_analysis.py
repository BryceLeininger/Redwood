"""Tests for the analysis pipeline."""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from land_due_diligence_agent.analysis.autonomous_agent import AutonomousLearningAgent, load_autonomous_learning_records
from land_due_diligence_agent.analysis.front_end import _document_staleness, apply_front_end_assessment
from land_due_diligence_agent.analysis.heuristics import aggregate_risks, analyze_document
from land_due_diligence_agent.analysis.issue_registry import (
    build_canonical_issue_registry,
    build_overall_read_draft,
    build_recommendation_from_registry,
    build_section_selections,
)
from land_due_diligence_agent.analysis.service import run_analysis
from land_due_diligence_agent.analysis.web_research import WebResearchAgent
from land_due_diligence_agent.llm.base import LLMProvider
from land_due_diligence_agent.llm.heuristic_provider import HeuristicProvider
from land_due_diligence_agent.models import (
    CanonicalIssue,
    CanonicalIssueRegistry,
    Citation,
    ContradictionFinding,
    DocumentAnalysis,
    DocumentRecord,
    ExtractedChunk,
    OmissionAssessment,
    RiskFinding,
    WebResearchResult,
)
from land_due_diligence_agent.output.docx_writer import _location_text, _scale_text
from land_due_diligence_agent.utils.text import normalize_text


def _document(relative_path: str, text: str) -> DocumentRecord:
    path = Path(relative_path)
    return DocumentRecord(
        source_path=path,
        relative_path=path,
        extension=path.suffix,
        title=path.stem.replace("_", " ").title(),
        raw_text=text,
        normalized_text=normalize_text(text),
    )


class AnalysisTests(unittest.TestCase):
    def test_second_pass_builds_acquisition_judgment(self) -> None:
        def document_with_chunk(relative_path: str, text: str) -> DocumentRecord:
            document = _document(relative_path, text)
            document.chunks = [
                ExtractedChunk(
                    document_name=document.title,
                    chunk_id=f"chunk-{Path(relative_path).stem}",
                    text=document.normalized_text,
                    page_number=1,
                )
            ]
            return document

        documents = [
            document_with_chunk(
                "planning_staff_report.txt",
                (
                    "Planning Commission staff report. City of Exampleville. "
                    "Current zoning is R-1. The project proposes 84 lots and 84 single family homes. "
                    "Tentative map approved subject to conditions of approval before final map and grading permit."
                ),
            ),
            document_with_chunk(
                "title_report.txt",
                "Preliminary title report states title is vested in Example Land Holdings LLC. Easement exception remains open.",
            ),
            document_with_chunk(
                "grading_memo.txt",
                "Geotechnical memo states grading scope and drainage improvements remain unresolved before permit release.",
            ),
        ]

        synthesis = run_analysis(
            deal_name="IC Judgment Deal",
            documents=documents,
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-acquisition-judgment"),
        )

        controlling = {fact.fact_type: fact for fact in synthesis.acquisition_judgment.controlling_facts}
        self.assertEqual(controlling["lot_count"].controlling_value, "84 lots")
        self.assertEqual(controlling["unit_count"].controlling_value, "84 units")
        self.assertIn("R-1", controlling["zoning"].controlling_value)
        self.assertIn("Exampleville", controlling["jurisdiction"].controlling_value)
        self.assertIn("Example Land Holdings LLC", controlling["owner_name"].controlling_value)
        self.assertTrue(
            any(
                item.bucket in {"Primary Deal Driver", "Secondary Drivers", "Supporting Risks"}
                for item in synthesis.acquisition_judgment.risk_items
            )
        )
        self.assertTrue(any(item.cost_impact for item in synthesis.acquisition_judgment.risk_items))
        self.assertTrue(any(item.primary_lever for item in synthesis.acquisition_judgment.risk_items))
        self.assertTrue(synthesis.acquisition_judgment.investment_decision.primary_driver)
        self.assertTrue(synthesis.acquisition_judgment.investment_decision.close_requirements)
        self.assertEqual(synthesis.acquisition_judgment.investment_decision.deal_stage, "approved horizontal land")
        self.assertEqual(synthesis.acquisition_judgment.investment_decision.posture, "Needs Targeted Confirmation")
        self.assertEqual(synthesis.acquisition_judgment.investment_decision.true_blockers, [])
        self.assertTrue(any(step.target == "Final Map" for step in synthesis.acquisition_judgment.critical_path))

    def test_second_pass_applies_sanity_corrections(self) -> None:
        def document_with_chunk(relative_path: str, text: str) -> DocumentRecord:
            document = _document(relative_path, text)
            document.chunks = [
                ExtractedChunk(
                    document_name=document.title,
                    chunk_id=f"chunk-{Path(relative_path).stem}",
                    text=document.normalized_text,
                    page_number=1,
                )
            ]
            return document

        documents = [
            document_with_chunk(
                "planning_staff_report.txt",
                (
                    "Planning Commission staff report. City of Exampleville. "
                    "Current zoning is R-1. General plan land use is High Density Residential. "
                    "The project proposes 84 lots and 84 single family homes. "
                    "Tentative map approved subject to conditions of approval before final map."
                ),
            ),
            document_with_chunk(
                "design_review_notes.txt",
                "Design review packet notes Building A has 12 units. Owner: Existing Conditions Plan.",
            ),
            document_with_chunk(
                "title_report.txt",
                "Preliminary title report states title is vested in Example Land Holdings LLC.",
            ),
        ]

        synthesis = run_analysis(
            deal_name="Sanity Correction Deal",
            documents=documents,
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-sanity-corrections"),
        )

        corrections = {item.fact_type: item for item in synthesis.acquisition_judgment.sanity_corrections}
        self.assertIn("unit_count", corrections)
        self.assertEqual(corrections["unit_count"].corrected_value, "84 units")
        self.assertIn("owner_name", corrections)
        self.assertIn("Example Land Holdings LLC", corrections["owner_name"].corrected_value)
        self.assertIn("zoning", corrections)
        self.assertIn("R-1", corrections["zoning"].corrected_value)

    def test_second_pass_rejects_ocr_fact_fragments_and_docx_summary_uses_controlling_facts(self) -> None:
        def document_with_chunk(relative_path: str, text: str, *, ocr_used: bool = False) -> DocumentRecord:
            document = _document(relative_path, text)
            document.chunks = [
                ExtractedChunk(
                    document_name=document.title,
                    chunk_id=f"chunk-{Path(relative_path).stem}",
                    text=document.normalized_text,
                    page_number=1,
                    ocr_used=ocr_used,
                )
            ]
            return document

        documents = [
            document_with_chunk(
                "planning_staff_report.txt",
                (
                    "Planning Commission staff report. City of Morgan Hill. "
                    "Current zoning is R-1. The project proposes 84 lots and 84 single family homes."
                ),
            ),
            document_with_chunk(
                "ocr_utility_fragment.txt",
                (
                    "City of Morgan HillGas And Electric provides utility service. "
                    "Current zoning laws; land use and development standards apply generally. "
                    "Owner: Ship has not changed since the time of the disaster."
                ),
                ocr_used=True,
            ),
            document_with_chunk(
                "title_report.txt",
                "Preliminary title report states title is vested in Morgan Hill Development LLC.",
            ),
        ]

        synthesis = run_analysis(
            deal_name="OCR Fragment Deal",
            documents=documents,
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-ocr-fragment-filter"),
        )

        controlling = {fact.fact_type: fact for fact in synthesis.acquisition_judgment.controlling_facts}
        self.assertEqual(controlling["jurisdiction"].controlling_value, "Morgan Hill")
        self.assertIn("R-1", controlling["zoning"].controlling_value)
        self.assertEqual(controlling["owner_name"].controlling_value, "Morgan Hill Development LLC")
        self.assertNotIn("Morgan HillGas And Electric", controlling["jurisdiction"].controlling_value)
        self.assertNotIn("Zoning laws; land use and", controlling["zoning"].controlling_value)
        self.assertNotIn("Ship has not changed since the time of the disaster", controlling["owner_name"].controlling_value)
        self.assertEqual(_location_text({}, synthesis), controlling["jurisdiction"].controlling_value)

    def test_second_pass_conflicting_counts_fall_back_and_scale_summary_caps_candidates(self) -> None:
        def document_with_chunk(relative_path: str, text: str) -> DocumentRecord:
            document = _document(relative_path, text)
            document.chunks = [
                ExtractedChunk(
                    document_name=document.title,
                    chunk_id=f"chunk-{Path(relative_path).stem}",
                    text=document.normalized_text,
                    page_number=1,
                )
            ]
            return document

        documents = [
            document_with_chunk(
                "planning_staff_report_a.txt",
                (
                    "Planning Commission staff report. City of Exampleville. "
                    "Current zoning is R-1. The project proposes 84 lots and 84 single family homes."
                ),
            ),
            document_with_chunk(
                "planning_staff_report_b.txt",
                (
                    "Planning Commission staff report. City of Exampleville. "
                    "Current zoning is R-1. The project proposes 96 lots and 96 single family homes."
                ),
            ),
        ]

        synthesis = run_analysis(
            deal_name="Conflicting Count Deal",
            documents=documents,
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-conflicting-count-filter"),
        )

        controlling = {fact.fact_type: fact for fact in synthesis.acquisition_judgment.controlling_facts}
        self.assertEqual(controlling["lot_count"].controlling_value, "No reliable controlling value extracted")
        self.assertEqual(controlling["unit_count"].controlling_value, "No reliable controlling value extracted")
        self.assertLessEqual(len(controlling["lot_count"].rejected_alternatives), 3)
        self.assertLessEqual(len(controlling["unit_count"].rejected_alternatives), 3)
        self.assertTrue(any("84 lots" in candidate for candidate in controlling["lot_count"].rejected_alternatives))
        self.assertTrue(any("96 lots" in candidate for candidate in controlling["lot_count"].rejected_alternatives))

        scale_summary = _scale_text({}, synthesis)
        self.assertEqual(scale_summary, "Not reliably established from provided documents")

    def test_finished_lot_stage_does_not_promote_routine_title_items_to_true_blockers(self) -> None:
        def document_with_chunk(relative_path: str, text: str) -> DocumentRecord:
            document = _document(relative_path, text)
            document.chunks = [
                ExtractedChunk(
                    document_name=document.title,
                    chunk_id=f"chunk-{Path(relative_path).stem}",
                    text=document.normalized_text,
                    page_number=1,
                )
            ]
            return document

        documents = [
            document_with_chunk(
                "recorded_final_map.txt",
                "Recorded final map for 52 finished lots. Final map recorded and lot closure calculations complete.",
            ),
            document_with_chunk(
                "closure_calculations.txt",
                "Finished lot closure calculations confirm 52 finished lots and improvement acceptance sequencing.",
            ),
            document_with_chunk(
                "title_commitment.txt",
                "Current title commitment states title is vested in Finished Lot Seller LLC. Standard easement exceptions remain listed.",
            ),
        ]

        synthesis = run_analysis(
            deal_name="Finished Lot Deal",
            documents=documents,
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-finished-lot-stage"),
        )

        decision = synthesis.acquisition_judgment.investment_decision
        self.assertEqual(decision.deal_stage, "finished lot / near-finished lot")
        self.assertNotEqual(decision.posture, "Do Not Advance")
        self.assertEqual(decision.true_blockers, [])

    def test_normalize_text_repairs_common_mojibake(self) -> None:
        text = "The dealâ€™s geotech scopeâ€”and cost basisâ€”need review."
        self.assertEqual(
            normalize_text(text),
            "The deal's geotech scope-and cost basis-need review.",
        )

    def test_normalize_text_repairs_cp1252_utf8_mojibake(self) -> None:
        text = 'There are no publicly available sources that confirm whether an offsite improvement scope confirmation for the â€œharkenâ€ package has been produced in a current, projectâ€‘specific form.'
        self.assertEqual(
            normalize_text(text),
            'There are no publicly available sources that confirm whether an offsite improvement scope confirmation for the "harken" package has been produced in a current, project-specific form.',
        )

    def test_generates_key_risks_and_questions(self) -> None:
        documents = [
            _document(
                "environmental_report.txt",
                (
                    "Phase I environmental site assessment identified a recognized environmental condition. "
                    "Wetlands and floodplain constraints affect a portion of the site. "
                    "Utility capacity remains pending and a will serve letter has not been issued."
                ),
            ),
            _document(
                "zoning_memo.txt",
                (
                    "Current zoning is not approved and rezoning required before final plat approval. "
                    "Title review notes an access easement exception. "
                    "The city backlog may delay the schedule and create a long lead entitlement path."
                ),
            ),
        ]

        synthesis = run_analysis(
            deal_name="Test Deal",
            documents=documents,
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-analysis"),
        )

        categories = {risk.category for risk in synthesis.key_risks}
        self.assertIn("Environmental Risks", categories)
        self.assertIn("Flood / Drainage Issues", categories)
        self.assertIn("Entitlement Status", categories)
        self.assertIn("Title / Access Concerns", categories)
        self.assertIn("Schedule Risks", categories)
        self.assertTrue(synthesis.seller_questions)
        self.assertTrue(any("ALTA" in item for item in synthesis.missing_items))
        self.assertTrue(all(risk.citations for risk in synthesis.key_risks))

    def test_layout_legend_noise_does_not_create_utility_risk(self) -> None:
        document = _document(
            "joint_trench_plans.txt",
            (
                'JT JT JT SD SD SD 12" W 8" SS FIRE SERVICE WITH METER AND BFP TYP '
                "DOMESTIC SERVICE WITH MASTER METER AND BFP TYP PROJECT NUMBER SHEET "
                "DRAWN BY CHECKED BY SCALE 1 20 TRANSFORMER PAD RIM 24.5 INV 11.5."
            ),
        )

        analysis = analyze_document(document)

        self.assertFalse(any(risk.category == "Utilities / Infrastructure Issues" for risk in analysis.risks))

    def test_market_language_does_not_misclassify_access_or_will_serve(self) -> None:
        document = _document(
            "market_study.txt",
            (
                "Access to ground floor retail and restaurants supports buyer demand. "
                "Lupine Hills Elementary, Hercules Middle, and Hercules High will serve the subject."
            ),
        )

        analysis = analyze_document(document)
        categories = {risk.category for risk in analysis.risks}

        self.assertNotIn("Title / Access Concerns", categories)
        self.assertNotIn("Utilities / Infrastructure Issues", categories)

    def test_detects_cross_document_tensions(self) -> None:
        documents = [
            _document(
                "title_report.txt",
                "Preliminary title report lists an access easement exception affecting the current site layout.",
            ),
            _document(
                "design_permit_plans.txt",
                "The vehicular project entry is located along the Diana Avenue frontage and private access drive.",
            ),
            _document(
                "conditions_of_approval.txt",
                "At improvement plan stage, the project shall confirm if the Diana Avenue frontage was dedicated to the City.",
            ),
            _document(
                "stormwater_plan.txt",
                "Diana Avenue frontage is already improved.",
            ),
            _document(
                "geotechnical_report.txt",
                "Liquefaction triggering and foundation recommendations apply to the site and must be incorporated into design.",
            ),
            _document(
                "site_budget.txt",
                "Budgetary pricing only. Preliminary proposal with allowances and unresolved contingencies.",
            ),
        ]

        synthesis = run_analysis(
            deal_name="Contradiction Deal",
            documents=documents,
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-contradictions"),
        )

        self.assertTrue(synthesis.contradictions)
        self.assertTrue(synthesis.issue_analyses)
        self.assertTrue(synthesis.priority_assessment.top_deal_shaping_issues)
        self.assertTrue(synthesis.challenge_findings)
        self.assertTrue(any("frontage" in finding.description.lower() or "access" in finding.description.lower() for finding in synthesis.contradictions))
        self.assertTrue(all(finding.citations for finding in synthesis.contradictions))

    def test_structured_facts_filter_low_confidence_ocr_sources(self) -> None:
        path = Path("scanned_environmental_report.txt")
        document = DocumentRecord(
            source_path=path,
            relative_path=path,
            extension=".txt",
            title="Scanned Environmental Report",
            raw_text="Recognized environmental condition remains open and remediation scope is unresolved.",
            normalized_text="Recognized environmental condition remains open and remediation scope is unresolved.",
            metadata={"page_count": 1},
            ocr_pages=[1],
            chunks=[
                ExtractedChunk(
                    document_name=path.name,
                    chunk_id="chunk-0001",
                    text="Recognized environmental condition remains open and remediation scope is unresolved.",
                    page_number=1,
                    ocr_used=True,
                )
            ],
        )

        synthesis = run_analysis(
            deal_name="OCR Fact Filter",
            documents=[document],
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-ocr-fact-filter"),
        )

        self.assertEqual(synthesis.structured_facts, [])
        self.assertGreaterEqual(synthesis.fact_validation_stats.filtered_count, 1)
        self.assertGreaterEqual(synthesis.fact_validation_stats.low_confidence_excluded_count, 1)

    def test_document_staleness_uses_short_dates_from_title(self) -> None:
        analysis = DocumentAnalysis(
            document=_document(
                "dd/Reciprocal Easement Agreement and Budget 6-24-24.pdf",
                "Recorded easement agreement dated 2010 governs the underlying rights and reimbursement mechanics.",
            ),
            summary="",
            risks=[],
            seller_questions=[],
            reading_priority=0,
            reading_reason="",
            confidence="high",
            confidence_reason="",
            focus_areas=["Offsite Obligations"],
        )

        status, reason = _document_staleness(analysis)

        self.assertEqual(status, "present and adequate")
        self.assertIn("No obvious staleness signal", reason)

    def test_fast_mode_limits_analysis_depth_and_llm_calls(self) -> None:
        class CountingProvider(LLMProvider):
            provider_name = "openai"

            def __init__(self) -> None:
                self.model = "fake-openai"
                self.document_calls = 0
                self.executive_calls = 0

            def refine_document_summary(
                self,
                document: DocumentRecord,
                draft_summary: str,
                risks: list[RiskFinding],
                missing_items: list[str],
            ) -> str:
                self.document_calls += 1
                return draft_summary

            def refine_executive_summary(
                self,
                deal_name: str,
                draft_summary: str,
                category_rollup: dict[str, str],
                key_risks: list[RiskFinding],
                contradictions: list[ContradictionFinding],
                missing_items: list[str],
            ) -> str:
                self.executive_calls += 1
                return draft_summary

        documents = [
            _document(
                "title_report.txt",
                "Preliminary title report lists an access easement exception affecting the current site layout.",
            ),
            _document(
                "design_permit_plans.txt",
                "The vehicular project entry is located along the Diana Avenue frontage and private access drive.",
            ),
            _document(
                "conditions_of_approval.txt",
                "At improvement plan stage, the project shall confirm if the Diana Avenue frontage was dedicated to the City.",
            ),
            _document(
                "stormwater_plan.txt",
                "Diana Avenue frontage is already improved.",
            ),
        ]

        provider = CountingProvider()
        synthesis = run_analysis(
            deal_name="Fast Deal",
            documents=documents,
            llm_provider=provider,
            logger=logging.getLogger("test-fast-mode"),
            mode="fast",
        )

        self.assertEqual(provider.document_calls, 0)
        self.assertEqual(provider.executive_calls, 1)
        self.assertEqual(synthesis.llm_calls_attempted, 1)
        self.assertFalse(synthesis.contradictions)
        self.assertLessEqual(len(synthesis.key_risks), 3)
        self.assertLessEqual(len(synthesis.seller_questions), 6)

    def test_canonical_registry_merges_overlapping_utility_signals(self) -> None:
        risks = [
            RiskFinding(
                category="Utilities / Infrastructure Issues",
                severity="high",
                summary="Utility capacity remains pending and will-serve support is not in the file.",
                issue="Utility capacity and provider confirmation remain open.",
                why_it_matters="Provider commitment is still required before the utility path is reliable.",
                likely_implication="Schedule and offsite utility scope remain exposed.",
                source_documents=["Utility Memo"],
            ),
            RiskFinding(
                category="Schedule Risks",
                severity="medium",
                summary="Provider coordination remains open and keeps the schedule path exposed.",
                issue="Utility-related schedule risk remains open.",
                why_it_matters="The critical path still depends on provider coordination.",
                likely_implication="Schedule slips remain likely until utility assumptions are confirmed.",
                source_documents=["Schedule Memo"],
            ),
            RiskFinding(
                category="Budget / Cost Reliability",
                severity="medium",
                summary="Joint trench and dry-utility scope still reads as budgetary.",
                issue="Offsite utility risk is not fully priced.",
                why_it_matters="Basis remains exposed if utility work is larger than assumed.",
                likely_implication="Cost can move if utility scope is repriced.",
                source_documents=["Budget Memo"],
            ),
        ]
        omissions = [
            OmissionAssessment(
                item="Utility availability / will-serve documentation",
                category="Utilities / Infrastructure Issues",
                status="not found",
                rationale="No current will-serve letter is in the package.",
            )
        ]
        registry = build_canonical_issue_registry(
            key_risks=risks,
            contradictions=[],
            omission_assessments=omissions,
            document_analyses=[],
        )

        utility_issue = next((issue for issue in registry.issues if issue.issue_id == "utility-capacity"), None)
        self.assertIsNotNone(utility_issue)
        self.assertGreaterEqual(len(utility_issue.merged_fragment_ids), 3)
        self.assertEqual(utility_issue.decision_action, "condition closing")
        self.assertEqual(utility_issue.title, "Utility capacity confirmation unresolved")

    def test_standardized_titles_use_controlled_vocabulary_and_length_limits(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Utilities / Infrastructure Issues",
                    severity="high",
                    summary="Utility provider coordination remains open.",
                    issue="Potential utility coordination issues may impact schedule.",
                    why_it_matters="Provider commitment is still required.",
                    likely_implication="Schedule remains exposed.",
                    source_documents=["Utility Memo"],
                ),
                RiskFinding(
                    category="Offsite Obligations",
                    severity="high",
                    summary="Frontage scope still sits with the buyer.",
                    issue="Frontage improvements and offsite work requirements remain undefined.",
                    why_it_matters="Scope owner remains open.",
                    likely_implication="Buyer-facing cost remains exposed.",
                    source_documents=["Offsite Memo"],
                ),
                RiskFinding(
                    category="Geotechnical Risks",
                    severity="high",
                    summary="Soils recommendations still control grading and foundation scope.",
                    issue="Geotechnical recommendations still need to be carried into plan and budget.",
                    why_it_matters="Design assumptions remain exposed.",
                    likely_implication="Cost and design remain exposed.",
                    source_documents=["Geotech Memo"],
                ),
                RiskFinding(
                    category="Title / Access Concerns",
                    severity="high",
                    summary="Title exceptions still affect the current access layout.",
                    issue="Title exceptions could potentially affect access.",
                    why_it_matters="Closability remains exposed.",
                    likely_implication="Closing remains conditional.",
                    source_documents=["Title Memo"],
                ),
            ],
            contradictions=[],
            omission_assessments=[],
            document_analyses=[],
        )

        issue_by_id = {issue.issue_id: issue for issue in registry.issues}
        self.assertEqual(issue_by_id["utility-capacity"].title, "Utility capacity confirmation unresolved")
        self.assertEqual(issue_by_id["offsite-frontage"].title, "Offsite improvement scope buyer-facing")
        self.assertEqual(issue_by_id["geotechnical-scope"].title, "Geotechnical recommendations not incorporated")
        self.assertEqual(issue_by_id["title-access-clearance"].title, "Title access clearance unresolved")
        for issue in registry.issues:
            self.assertLessEqual(len(issue.title.split()), 10)
            self.assertNotRegex(issue.title.lower(), r"\b(risk|issue|concern|potentially|possibly)\b")

    def test_title_normalization_preserves_raw_titles_for_debug(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Utilities / Infrastructure Issues",
                    severity="high",
                    summary="Provider confirmation remains missing.",
                    issue="Utility confirmation missing.",
                    why_it_matters="Provider commitment is still required.",
                    likely_implication="Schedule remains exposed.",
                    source_documents=["Utility Memo"],
                ),
                RiskFinding(
                    category="Schedule Risks",
                    severity="medium",
                    summary="Utility path remains open.",
                    issue="Utility capacity not confirmed.",
                    why_it_matters="The utility path still depends on provider coordination.",
                    likely_implication="Schedule remains provisional.",
                    source_documents=["Schedule Memo"],
                ),
            ],
            contradictions=[],
            omission_assessments=[
                OmissionAssessment(
                    item="Utility availability / will-serve documentation",
                    category="Utilities / Infrastructure Issues",
                    status="not found",
                    rationale="No current will-serve letter is in the package.",
                )
            ],
            document_analyses=[],
        )

        utility_issue = next(issue for issue in registry.issues if issue.issue_id == "utility-capacity")
        self.assertEqual(utility_issue.title, "Utility capacity confirmation unresolved")
        self.assertTrue(any("Utility confirmation missing" in title for title in utility_issue.merged_fragment_titles))
        self.assertTrue(any("Utility capacity not confirmed" in title for title in utility_issue.merged_fragment_titles))

    def test_normalized_titles_are_unique_and_category_prefixed(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Environmental Risks",
                    severity="high",
                    summary="Environmental follow-up remains open.",
                    issue="Environmental follow-up is not fully closed.",
                    why_it_matters="Environmental scope still affects underwriting confidence.",
                    likely_implication="Mitigation cost remains open.",
                    source_documents=["Phase I"],
                ),
                RiskFinding(
                    category="Budget / Cost Reliability",
                    severity="medium",
                    summary="Pricing still reads as budgetary.",
                    issue="Cost package is still budgetary.",
                    why_it_matters="Basis remains provisional.",
                    likely_implication="Basis can move if pricing tightens.",
                    source_documents=["Budget"],
                ),
                RiskFinding(
                    category="Schedule Risks",
                    severity="medium",
                    summary="The critical path still depends on unconfirmed assumptions.",
                    issue="Critical path still relies on unconfirmed assumptions.",
                    why_it_matters="Timing remains provisional.",
                    likely_implication="Map timing remains open.",
                    source_documents=["Schedule"],
                ),
            ],
            contradictions=[],
            omission_assessments=[],
            document_analyses=[],
        )

        titles = [issue.title for issue in registry.issues]
        self.assertEqual(len(titles), len(set(titles)))
        self.assertTrue(any(title.startswith("Environmental") for title in titles))
        self.assertTrue(any(title.startswith("Cost") for title in titles))
        self.assertTrue(any(title.startswith("Schedule") for title in titles))

    def test_registry_ranking_and_output_selection_are_stable(self) -> None:
        documents = [
            _document(
                "title_report.txt",
                "Preliminary title report lists an access easement exception affecting the current site layout.",
            ),
            _document(
                "budget.txt",
                "Budgetary pricing only. Preliminary proposal with allowances and unresolved contingencies.",
            ),
        ]
        synthesis = run_analysis(
            deal_name="Ranking Deal",
            documents=documents,
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-ranking"),
        )
        registry = synthesis.canonical_issue_registry
        self.assertTrue(registry.issues)
        self.assertEqual(registry.issues[0].issue_id, "title-access-clearance")

        recommendation = build_recommendation_from_registry(registry)
        selections = build_section_selections(registry, recommendation, analysis_mode="full")
        executive_ids = [selection.issue_id for selection in selections if selection.output_name == "01_executive_summary.md"]
        key_risk_ids = [selection.issue_id for selection in selections if selection.output_name == "02_key_risks.md"]
        self.assertEqual(len(executive_ids), len(set(executive_ids)))
        self.assertEqual(len(key_risk_ids), len(set(key_risk_ids)))
        self.assertTrue(set(executive_ids).issubset(set(key_risk_ids)))

    def test_omission_only_issue_is_downgraded_when_not_critical(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[],
            contradictions=[],
            omission_assessments=[
                OmissionAssessment(
                    item="Agency correspondence log",
                    category="Entitlement Status",
                    status="unclear whether present",
                    rationale="No clean correspondence log is in the package.",
                )
            ],
            document_analyses=[],
        )

        issue = next(issue for issue in registry.issues if issue.issue_id == "entitlement-conditions")
        self.assertEqual(issue.evidence_basis, "routine_missing_support")
        self.assertEqual(issue.issue_strength, "weak")
        self.assertFalse(issue.top_line_eligible)
        self.assertIn("normal process friction", issue.top_line_filter_reasons)

    def test_strong_direct_evidence_issue_stays_top_line_eligible(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Title / Access Concerns",
                    severity="high",
                    summary="Preliminary title report lists an access easement exception affecting the site layout.",
                    issue="Title and access clearance is not closed.",
                    why_it_matters="This goes directly to closability and lenderability.",
                    likely_implication="Closing should not be treated as clean until the exception is cured or endorsed.",
                    source_documents=["Title Report"],
                    citations=[Citation(document_name="Title Report", chunk_id="page-0001", page_number=1)],
                    gating_flags=["Closing", "Underwriting confidence"],
                )
            ],
            contradictions=[],
            omission_assessments=[],
            document_analyses=[],
        )

        issue = registry.issues[0]
        self.assertIn(issue.evidence_basis, {"direct_confirmed_risk", "direct_unresolved_risk"})
        self.assertEqual(issue.issue_strength, "strong")
        self.assertTrue(issue.top_line_eligible)

    def test_output_selection_filters_weak_routine_issue(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Environmental Risks",
                    severity="high",
                    summary="Phase I ESA identifies follow-up work.",
                    issue="Environmental follow-up is not fully closed.",
                    why_it_matters="Environmental scope still affects underwriting confidence.",
                    likely_implication="Mitigation cost remains open.",
                    source_documents=["Phase I ESA"],
                    gating_flags=["Underwriting confidence"],
                )
            ],
            contradictions=[],
            omission_assessments=[
                OmissionAssessment(
                    item="Agency correspondence log",
                    category="Entitlement Status",
                    status="unclear whether present",
                    rationale="No clean correspondence log is in the package.",
                )
            ],
            document_analyses=[],
        )
        recommendation = build_recommendation_from_registry(registry)
        selections = build_section_selections(registry, recommendation, analysis_mode="full")

        executive_ids = [selection.issue_id for selection in selections if selection.output_name == "01_executive_summary.md"]
        self.assertIn("environmental-followup", executive_ids)
        self.assertNotIn("entitlement-conditions", executive_ids)

    def test_front_end_flag_grading_distinguishes_real_flags_document_gaps_and_routine_items(self) -> None:
        synthesis = run_analysis(
            deal_name="Front End Flags",
            documents=[
                _document(
                    "title_report_2026.txt",
                    "Preliminary title report lists an access easement exception affecting the current site layout.",
                )
            ],
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-front-end-flags"),
        )

        issue_by_id = {issue.issue_id: issue for issue in synthesis.canonical_issue_registry.issues}
        self.assertIn(issue_by_id["title-access-clearance"].front_end_flag, {"red flag", "yellow flag"})
        self.assertEqual(issue_by_id["entitlement-conditions"].front_end_flag, "document gap")

        registry = CanonicalIssueRegistry(
            issues=[
                CanonicalIssue(
                    issue_id="routine-check",
                    title="Routine process follow-up",
                    category="Schedule Risks",
                    status="open",
                    why_it_matters="This is normal coordination work.",
                    likely_implication="No concentrated project-specific concern is visible.",
                    evidence_basis="direct_confirmed_risk",
                    materiality="low",
                    normal_friction_flag=True,
                    decision_relevant=False,
                    false_positive_risk="high",
                )
            ]
        )
        apply_front_end_assessment(
            registry=registry,
            document_analyses=[],
            omission_assessments=[],
            contradictions=[],
        )
        self.assertEqual(registry.issues[0].front_end_flag, "routine item")

    def test_front_end_separates_missing_stale_and_conflict_signals(self) -> None:
        synthesis = run_analysis(
            deal_name="Signal Separation",
            documents=[
                _document(
                    "stormwater_plan.txt",
                    "Diana Avenue frontage is already improved.",
                ),
                _document(
                    "conditions_of_approval.txt",
                    "At improvement plan stage, the project shall confirm if the Diana Avenue frontage was dedicated to the City.",
                ),
                _document(
                    "2019_fee_schedule.txt",
                    "2019 fee schedule. Impact fees and capacity fees shown for planning purposes.",
                ),
            ],
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-front-end-separation"),
        )

        issue_by_id = {issue.issue_id: issue for issue in synthesis.canonical_issue_registry.issues}
        self.assertEqual(issue_by_id["offsite-frontage"].front_end_flag, "conflict / contradiction concern")
        stale_omissions = [
            assessment
            for assessment in synthesis.omission_assessments
            if assessment.front_end_status == "stale and potentially unreliable"
        ]
        self.assertTrue(stale_omissions)
        missing_important = [
            assessment
            for assessment in synthesis.omission_assessments
            if assessment.front_end_status == "missing and important"
        ]
        self.assertTrue(missing_important)

    def test_reading_order_and_roadmap_are_front_end_oriented(self) -> None:
        synthesis = run_analysis(
            deal_name="Reading Deal",
            documents=[
                _document(
                    "title_report.txt",
                    "Preliminary title report lists an access easement exception affecting the current site layout.",
                ),
                _document(
                    "conditions_of_approval.txt",
                    "At improvement plan stage, the project shall confirm if the Diana Avenue frontage was dedicated to the City.",
                ),
                _document(
                    "memo_summary.txt",
                    "Executive memo summarizing the package.",
                ),
            ],
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-reading-roadmap"),
        )

        self.assertTrue(synthesis.recommended_reading_order)
        self.assertEqual(synthesis.recommended_reading_order[0].bucket, "must read personally")
        self.assertTrue(synthesis.recommended_reading_order[0].rationale_factors)
        self.assertTrue(synthesis.further_diligence_roadmap.top_documents_to_read_first)
        self.assertTrue(synthesis.further_diligence_roadmap.recommended_next_steps)
        self.assertTrue(
            synthesis.further_diligence_roadmap.top_real_flags
            or synthesis.further_diligence_roadmap.top_contradictions_to_resolve
        )

    def test_front_end_assigns_acquisition_severity_and_gating_outputs(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Title / Access Concerns",
                    severity="high",
                    summary="An access easement exception still burdens the planned entry condition.",
                    issue="Title access clearance unresolved.",
                    why_it_matters="Legal access control is not yet closed for the current entry configuration.",
                    likely_implication="Closing and site plan reliability remain exposed until access is cleared or redesigned.",
                    source_documents=["Title Report"],
                    citations=[Citation(document_name="Title Report", chunk_id="page-0001", page_number=1)],
                    gating_flags=["Closing", "Underwriting confidence"],
                )
            ],
            contradictions=[],
            omission_assessments=[
                OmissionAssessment(
                    item="ALTA or boundary survey",
                    category="Title / Access Concerns",
                    status="not found",
                    rationale="No current survey was found in the package.",
                )
            ],
            document_analyses=[],
        )

        _reading_order, roadmap = apply_front_end_assessment(
            registry=registry,
            document_analyses=[],
            omission_assessments=registry.omission_assessments,
            contradictions=[],
        )

        issue = next(issue for issue in registry.issues if issue.issue_id == "title-access-clearance")
        self.assertEqual(issue.acquisition_severity, "CRITICAL")
        self.assertTrue(issue.gating_item)
        self.assertIn("legal/title risk", issue.affects)
        self.assertTrue(issue.practical_impact)
        self.assertEqual(issue.deal_impact_type, "legal/title risk")
        self.assertEqual(issue.deal_impact_magnitude, "deal-shaping")
        self.assertTrue(issue.deal_impact_mechanism)
        self.assertTrue(issue.cost_exposure_band)
        self.assertTrue(issue.timing_exposure_band)
        self.assertTrue(issue.fixability_classification)
        self.assertIn("closing", issue.downside_if_wrong.lower())
        self.assertTrue(issue.reality_vs_noise)
        self.assertTrue(roadmap.deal_killers_or_gating_items)
        self.assertTrue(roadmap.recommended_next_steps)

        recommendation = build_recommendation_from_registry(registry)
        self.assertEqual(recommendation.posture, "pause")

    def test_omission_only_coordination_issue_stays_routine(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[],
            contradictions=[],
            omission_assessments=[
                OmissionAssessment(
                    item="Agency correspondence log",
                    category="Entitlement Status",
                    status="unclear whether present",
                    rationale="No clean correspondence log is in the package.",
                )
            ],
            document_analyses=[],
        )
        apply_front_end_assessment(
            registry=registry,
            document_analyses=[],
            omission_assessments=registry.omission_assessments,
            contradictions=[],
        )

        issue = next(issue for issue in registry.issues if issue.issue_id == "entitlement-conditions")
        self.assertEqual(issue.normality_classification, "routine")
        self.assertTrue(issue.process_friction_flag)
        self.assertEqual(issue.why_now, "likely routine unless contradicted")

    def test_contradiction_driven_issue_is_treated_as_unusual(self) -> None:
        synthesis = run_analysis(
            deal_name="Contradiction Timing",
            documents=[
                _document("stormwater_plan.txt", "Diana Avenue frontage is already improved."),
                _document(
                    "conditions_of_approval.txt",
                    "At improvement plan stage, the project shall confirm if the Diana Avenue frontage was dedicated to the City.",
                ),
            ],
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-contradiction-unusual"),
        )

        issue = next(issue for issue in synthesis.canonical_issue_registry.issues if issue.issue_id == "offsite-frontage")
        self.assertIn(issue.normality_classification, {"elevated", "unusual"})
        self.assertEqual(issue.front_end_flag, "conflict / contradiction concern")
        self.assertEqual(issue.why_now, "investigate now")

    def test_generic_title_issue_is_suppressed_without_site_specific_trigger(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Title / Access Concerns",
                    severity="medium",
                    summary="Title review is part of standard diligence.",
                    issue="Title exceptions exist.",
                    why_it_matters="Standard title review is still underway.",
                    likely_implication="Normal diligence follow-up may still be needed.",
                    source_documents=["Title Report"],
                )
            ],
            contradictions=[],
            omission_assessments=[],
            document_analyses=[],
        )
        apply_front_end_assessment(
            registry=registry,
            document_analyses=[],
            omission_assessments=registry.omission_assessments,
            contradictions=[],
        )

        issue = next(issue for issue in registry.issues if issue.issue_id == "title-access-clearance")
        self.assertEqual(issue.specificity_level, "generic")
        self.assertEqual(issue.abnormality_basis, "routine category only")
        self.assertEqual(issue.site_specific_trigger, "")
        self.assertGreater(issue.genericity_penalty, 0)
        self.assertFalse(issue.top_line_eligible)
        self.assertIn("site-specificity gate: generic category presence only", issue.top_line_filter_reasons)

    def test_generic_soils_issue_is_suppressed_without_specific_condition(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Geotechnical Risks",
                    severity="medium",
                    summary="A geotechnical report is in the package.",
                    issue="Geotechnical report recommends further review.",
                    why_it_matters="Geotechnical review remains part of normal diligence.",
                    likely_implication="Routine design follow-up may still occur.",
                    source_documents=["Geotech Report"],
                )
            ],
            contradictions=[],
            omission_assessments=[],
            document_analyses=[],
        )
        apply_front_end_assessment(
            registry=registry,
            document_analyses=[],
            omission_assessments=registry.omission_assessments,
            contradictions=[],
        )

        issue = next(issue for issue in registry.issues if issue.issue_id == "geotechnical-scope")
        self.assertEqual(issue.specificity_level, "generic")
        self.assertEqual(issue.normality_classification, "routine")
        self.assertFalse(issue.top_line_eligible)
        self.assertIn("site-specificity gate: generic category presence only", issue.top_line_filter_reasons)

    def test_generic_access_issue_is_suppressed_without_specific_uncertainty(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Title / Access Concerns",
                    severity="medium",
                    summary="Site access should be reviewed as part of diligence.",
                    issue="Site access review remains open.",
                    why_it_matters="Connectivity review is still underway.",
                    likely_implication="Routine diligence follow-up may still be needed.",
                    source_documents=["Access Memo"],
                )
            ],
            contradictions=[],
            omission_assessments=[],
            document_analyses=[],
        )
        apply_front_end_assessment(
            registry=registry,
            document_analyses=[],
            omission_assessments=registry.omission_assessments,
            contradictions=[],
        )

        issue = next(issue for issue in registry.issues if issue.issue_id == "title-access-clearance")
        self.assertEqual(issue.specificity_level, "generic")
        self.assertEqual(issue.site_specific_trigger, "")
        self.assertFalse(issue.top_line_eligible)
        self.assertIn("site-specificity gate: generic category presence only", issue.top_line_filter_reasons)

    def test_specific_abnormal_trigger_keeps_issue_elevated(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Geotechnical Risks",
                    severity="high",
                    summary="The geotechnical report identifies undocumented fill beneath the proposed pad.",
                    issue="Undocumented fill affects pad design and foundation scope.",
                    why_it_matters="Pad design and grading assumptions are not reliable until the fill condition is incorporated.",
                    likely_implication="Foundation scope and sitework cost can move if the recommendation is not carried through.",
                    source_documents=["Geotech Report"],
                    gating_flags=["Underwriting confidence"],
                )
            ],
            contradictions=[],
            omission_assessments=[],
            document_analyses=[],
        )
        apply_front_end_assessment(
            registry=registry,
            document_analyses=[],
            omission_assessments=registry.omission_assessments,
            contradictions=[],
        )

        issue = next(issue for issue in registry.issues if issue.issue_id == "geotechnical-scope")
        self.assertNotEqual(issue.specificity_level, "generic")
        self.assertIn(issue.abnormality_basis, {"direct abnormal finding", "unresolved constraint"})
        self.assertTrue(issue.site_specific_trigger)
        self.assertTrue(issue.top_line_eligible)
        self.assertIn(issue.front_end_flag, {"red flag", "yellow flag"})

    def test_top_line_outputs_prefer_site_specific_issues_over_generic_category_presence(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Title / Access Concerns",
                    severity="medium",
                    summary="Title review is part of standard diligence.",
                    issue="Title exceptions exist.",
                    why_it_matters="Standard title review is still underway.",
                    likely_implication="Normal diligence follow-up may still be needed.",
                    source_documents=["Title Report"],
                ),
                RiskFinding(
                    category="Utilities / Infrastructure Issues",
                    severity="high",
                    summary="The provider has not issued a will-serve letter for the required offsite utility extension.",
                    issue="Utility capacity is not confirmed for the offsite extension.",
                    why_it_matters="The offsite utility path remains unresolved for the current plan.",
                    likely_implication="Improvement timing and underwriting confidence remain exposed until the provider confirms service.",
                    source_documents=["Utility Memo"],
                    gating_flags=["Underwriting confidence"],
                ),
            ],
            contradictions=[],
            omission_assessments=[],
            document_analyses=[],
        )
        apply_front_end_assessment(
            registry=registry,
            document_analyses=[],
            omission_assessments=registry.omission_assessments,
            contradictions=[],
        )

        recommendation = build_recommendation_from_registry(registry)
        selections = build_section_selections(registry, recommendation, analysis_mode="full")
        key_risk_ids = [selection.issue_id for selection in selections if selection.output_name == "02_key_risks.md"]

        self.assertIn("utility-capacity", key_risk_ids)
        self.assertNotIn("title-access-clearance", key_risk_ids)

    def test_document_analysis_suppresses_generic_joint_trench_presence_signal(self) -> None:
        analysis = analyze_document(
            _document(
                "joint_trench_plans.txt",
                (
                    "JOINT TRENCH COMPOSITE 1\" = 30' SCALE PROJECT MANAGER CHECKED BY DRAWN BY "
                    "PROJECT NUMBER SHEET OF LAST UPDATED 03-20-2024 UTILITY DESIGN CONSULTANTS & ENGINEERS."
                ),
            )
        )

        self.assertFalse(
            any(
                risk.category == "Utilities / Infrastructure Issues" and not risk.generic_signal_only
                for risk in analysis.risks
            )
        )

    def test_document_analysis_keeps_specific_title_exception_signal(self) -> None:
        analysis = analyze_document(
            _document(
                "title_report.txt",
                (
                    "Schedule B Exception 12 grants a reciprocal access easement across Lot 2. "
                    "The current vehicular entry shown on the site plan relies on that easement."
                ),
            )
        )

        risk = next(risk for risk in analysis.risks if risk.category == "Title / Access Concerns")
        self.assertFalse(risk.generic_signal_only)
        self.assertGreaterEqual(risk.specificity_score, 6)
        self.assertIn("easement", risk.specificity_basis.lower())
        self.assertIn("access", risk.specificity_basis.lower())

    def test_aggregate_risks_prefers_specific_basis_over_generic_category_presence(self) -> None:
        generic_utility = analyze_document(
            _document(
                "joint_trench_plans.txt",
                (
                    "JOINT TRENCH COMPOSITE 1\" = 30' SCALE PROJECT MANAGER CHECKED BY DRAWN BY "
                    "PROJECT NUMBER SHEET OF LAST UPDATED 03-20-2024 UTILITY DESIGN CONSULTANTS & ENGINEERS."
                ),
            )
        )
        specific_utility = analyze_document(
            _document(
                "utility_memo.txt",
                (
                    "The provider has not issued a will-serve letter for the offsite water extension. "
                    "Utility capacity remains unconfirmed for the current plan."
                ),
            )
        )

        utility_risk = next(
            risk
            for risk in aggregate_risks([generic_utility, specific_utility])
            if risk.category == "Utilities / Infrastructure Issues"
        )
        self.assertIn("will-serve", utility_risk.issue.lower())
        self.assertFalse(utility_risk.generic_signal_only)

    def test_package_quality_classification_is_deterministic(self) -> None:
        thin_synthesis = run_analysis(
            deal_name="Thin Package",
            documents=[
                _document("memo_summary.txt", "Executive memo summarizing the package."),
            ],
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-package-thin"),
        )
        self.assertIn(thin_synthesis.canonical_issue_registry.package_quality, {"thin", "mixed"})
        self.assertIn(thin_synthesis.canonical_issue_registry.confidence_in_initial_read, {"low", "medium"})

        selective_synthesis = run_analysis(
            deal_name="Selective Package",
            documents=[
                _document("memo_summary.txt", "Executive memo summarizing the package."),
                _document("stormwater_plan.txt", "Diana Avenue frontage is already improved."),
                _document(
                    "conditions_of_approval.txt",
                    "At improvement plan stage, the project shall confirm if the Diana Avenue frontage was dedicated to the City.",
                ),
            ],
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-package-selective"),
        )
        self.assertEqual(selective_synthesis.canonical_issue_registry.package_quality, "selectively presented")
        self.assertEqual(selective_synthesis.canonical_issue_registry.confidence_in_initial_read, "low")

    def test_roadmap_and_reading_order_use_unusualness_and_timing(self) -> None:
        synthesis = run_analysis(
            deal_name="Priority Deal",
            documents=[
                _document(
                    "title_report.txt",
                    "Preliminary title report lists an access easement exception affecting the current site layout.",
                ),
                _document(
                    "conditions_of_approval.txt",
                    "At improvement plan stage, the project shall confirm if the Diana Avenue frontage was dedicated to the City.",
                ),
                _document("memo_summary.txt", "Executive memo summarizing routine next steps."),
            ],
            llm_provider=HeuristicProvider(),
            logger=logging.getLogger("test-roadmap-priority"),
        )

        self.assertTrue(synthesis.further_diligence_roadmap.investigate_immediately)
        self.assertTrue(synthesis.further_diligence_roadmap.read_personally)
        self.assertTrue(synthesis.further_diligence_roadmap.likely_routine_unless_changed)
        self.assertEqual(synthesis.recommended_reading_order[0].title, "Title Report")
        self.assertEqual(synthesis.recommended_reading_order[0].bucket, "must read personally")

    def test_evaluator_output_is_stable_and_flags_routine_issue(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Title / Access Concerns",
                    severity="high",
                    summary="Preliminary title report lists an access easement exception affecting the site layout.",
                    issue="Title and access clearance is not closed.",
                    why_it_matters="This goes directly to closability and lenderability.",
                    likely_implication="Closing should not be treated as clean until the exception is cured or endorsed.",
                    source_documents=["Title Report"],
                    citations=[Citation(document_name="Title Report", chunk_id="page-0001", page_number=1)],
                    gating_flags=["Closing", "Underwriting confidence"],
                ),
                RiskFinding(
                    category="Environmental Risks",
                    severity="high",
                    summary="Phase I follow-up remains open.",
                    issue="Environmental follow-up is not fully closed.",
                    why_it_matters="Environmental scope still affects underwriting confidence.",
                    likely_implication="Mitigation cost remains open.",
                    source_documents=["Phase I ESA"],
                    citations=[Citation(document_name="Phase I ESA", chunk_id="page-0001", page_number=1)],
                    gating_flags=["Underwriting confidence"],
                ),
                RiskFinding(
                    category="Utilities / Infrastructure Issues",
                    severity="high",
                    summary="Will-serve support remains outstanding.",
                    issue="Utility capacity and provider confirmation remain open.",
                    why_it_matters="Provider commitment is still required before the utility path is reliable.",
                    likely_implication="Schedule and offsite utility scope remain exposed.",
                    source_documents=["Utility Memo"],
                    citations=[Citation(document_name="Utility Memo", chunk_id="page-0001", page_number=1)],
                    gating_flags=["Underwriting confidence", "Vertical start"],
                ),
            ],
            contradictions=[],
            omission_assessments=[
                OmissionAssessment(
                    item="Agency correspondence log",
                    category="Entitlement Status",
                    status="unclear whether present",
                    rationale="No clean correspondence log is in the package.",
                )
            ],
            document_analyses=[],
        )

        evaluation = registry.evaluator_result
        self.assertGreaterEqual(evaluation.ranking_quality, 60)
        self.assertIn("title-access-clearance", evaluation.top_issues_should_be[:2])
        self.assertIn("environmental-followup", evaluation.top_issues_should_be[:3])
        self.assertIn("utility-capacity", evaluation.top_issues_should_be[:3])
        self.assertIn("entitlement-conditions", evaluation.issues_to_remove)

    def test_registry_issue_ids_remain_stable_with_evaluator_enabled(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Title / Access Concerns",
                    severity="high",
                    summary="Preliminary title report lists an access easement exception affecting the site layout.",
                    issue="Title and access clearance is not closed.",
                    why_it_matters="This goes directly to closability and lenderability.",
                    likely_implication="Closing should not be treated as clean until the exception is cured or endorsed.",
                    source_documents=["Title Report"],
                    citations=[Citation(document_name="Title Report", chunk_id="page-0001", page_number=1)],
                    gating_flags=["Closing"],
                )
            ],
            contradictions=[],
            omission_assessments=[
                OmissionAssessment(
                    item="ALTA or boundary survey",
                    category="Title / Access Concerns",
                    status="not found",
                    rationale="No survey file is present in the package.",
                )
            ],
            document_analyses=[],
        )

        self.assertEqual([issue.issue_id for issue in registry.issues], ["title-access-clearance"])

    def test_dependency_assignment_and_blocker_classification_are_deterministic(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Utilities / Infrastructure Issues",
                    severity="high",
                    summary="Utility capacity remains pending and will-serve support is not in the file.",
                    issue="Utility capacity and provider confirmation remain open.",
                    why_it_matters="Provider commitment is still required before the utility path is reliable.",
                    likely_implication="Schedule and offsite utility scope remain exposed.",
                    source_documents=["Utility Memo"],
                    citations=[Citation(document_name="Utility Memo", chunk_id="page-0001", page_number=1)],
                    gating_flags=["Underwriting confidence", "Vertical start"],
                ),
                RiskFinding(
                    category="Offsite Obligations",
                    severity="high",
                    summary="Frontage and offsite obligations remain buyer-facing.",
                    issue="Offsite and frontage scope is still buyer-facing.",
                    why_it_matters="Scope owner and timing triggers remain open.",
                    likely_implication="Buyer-facing hard cost and schedule remain exposed.",
                    source_documents=["Offsite Memo"],
                    citations=[Citation(document_name="Offsite Memo", chunk_id="page-0001", page_number=1)],
                    gating_flags=["Underwriting confidence", "Vertical start"],
                ),
                RiskFinding(
                    category="Schedule Risks",
                    severity="medium",
                    summary="The critical path still depends on unconfirmed agency and procurement assumptions.",
                    issue="Critical path still relies on unconfirmed assumptions.",
                    why_it_matters="The execution path still depends on unresolved agency and procurement sequencing.",
                    likely_implication="The current map and vertical timing are still provisional.",
                    source_documents=["Schedule Memo"],
                    citations=[Citation(document_name="Schedule Memo", chunk_id="page-0001", page_number=1)],
                    gating_flags=["Vertical start"],
                ),
            ],
            contradictions=[],
            omission_assessments=[],
            document_analyses=[],
        )

        utility_issue = next(issue for issue in registry.issues if issue.issue_id == "utility-capacity")
        schedule_issue = next(issue for issue in registry.issues if issue.issue_id == "schedule-path")
        self.assertEqual(utility_issue.dependency_type, "utility")
        self.assertIn("offsite-frontage", [link.issue_id for link in utility_issue.downstream_dependencies])
        self.assertIn("schedule-path", [link.issue_id for link in utility_issue.downstream_dependencies])
        self.assertEqual(utility_issue.schedule_impact_classification, "pre-final-map blocker")
        self.assertTrue(utility_issue.blocking_flag)
        self.assertTrue(utility_issue.critical_path_flag)
        self.assertEqual(utility_issue.blocker_classification, "blocking issue")
        self.assertEqual(schedule_issue.blocker_classification, "sequencing issue")
        self.assertTrue(schedule_issue.critical_path_flag)

    def test_cluster_grouping_identifies_root_causes(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Utilities / Infrastructure Issues",
                    severity="high",
                    summary="Utility capacity remains pending and will-serve support is not in the file.",
                    issue="Utility capacity and provider confirmation remain open.",
                    why_it_matters="Provider commitment is still required before the utility path is reliable.",
                    likely_implication="Schedule and offsite utility scope remain exposed.",
                    source_documents=["Utility Memo"],
                    citations=[Citation(document_name="Utility Memo", chunk_id="page-0001", page_number=1)],
                    gating_flags=["Underwriting confidence", "Vertical start"],
                ),
                RiskFinding(
                    category="Offsite Obligations",
                    severity="high",
                    summary="Frontage and offsite obligations remain buyer-facing.",
                    issue="Offsite and frontage scope is still buyer-facing.",
                    why_it_matters="Scope owner and timing triggers remain open.",
                    likely_implication="Buyer-facing hard cost and schedule remain exposed.",
                    source_documents=["Offsite Memo"],
                    citations=[Citation(document_name="Offsite Memo", chunk_id="page-0001", page_number=1)],
                    gating_flags=["Underwriting confidence", "Vertical start"],
                ),
                RiskFinding(
                    category="Schedule Risks",
                    severity="medium",
                    summary="The critical path still depends on unconfirmed agency and procurement assumptions.",
                    issue="Critical path still relies on unconfirmed assumptions.",
                    why_it_matters="The execution path still depends on unresolved agency and procurement sequencing.",
                    likely_implication="The current map and vertical timing are still provisional.",
                    source_documents=["Schedule Memo"],
                    citations=[Citation(document_name="Schedule Memo", chunk_id="page-0001", page_number=1)],
                    gating_flags=["Vertical start"],
                ),
            ],
            contradictions=[],
            omission_assessments=[],
            document_analyses=[],
        )

        cluster_labels = [cluster.label for cluster in registry.issue_clusters]
        self.assertIn("utility/offsite readiness", cluster_labels)
        self.assertEqual(registry.issue_clusters[0].root_issue_id, "utility-capacity")
        self.assertEqual(registry.fragility_classification, "fragile sequencing")

    def test_overall_read_uses_causal_pattern_language(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Utilities / Infrastructure Issues",
                    severity="high",
                    summary="Utility capacity remains pending and will-serve support is not in the file.",
                    issue="Utility capacity and provider confirmation remain open.",
                    why_it_matters="Provider commitment is still required before the utility path is reliable.",
                    likely_implication="Schedule and offsite utility scope remain exposed.",
                    source_documents=["Utility Memo"],
                    citations=[Citation(document_name="Utility Memo", chunk_id="page-0001", page_number=1)],
                    gating_flags=["Underwriting confidence", "Vertical start"],
                ),
                RiskFinding(
                    category="Offsite Obligations",
                    severity="high",
                    summary="Frontage and offsite obligations remain buyer-facing.",
                    issue="Offsite and frontage scope is still buyer-facing.",
                    why_it_matters="Scope owner and timing triggers remain open.",
                    likely_implication="Buyer-facing hard cost and schedule remain exposed.",
                    source_documents=["Offsite Memo"],
                    citations=[Citation(document_name="Offsite Memo", chunk_id="page-0001", page_number=1)],
                    gating_flags=["Underwriting confidence", "Vertical start"],
                ),
            ],
            contradictions=[],
            omission_assessments=[],
            document_analyses=[],
        )

        recommendation = build_recommendation_from_registry(registry)
        overall_read = build_overall_read_draft(
            deal_name="Dependency Deal",
            registry=registry,
            recommendation=recommendation,
            entitlement_status="Status still conditional.",
            challenge_findings=[],
        )

        self.assertIn("real critical path", overall_read.lower())
        self.assertIn("fragile sequencing", overall_read.lower())
        self.assertIn("utility/offsite readiness", overall_read.lower())

    def test_ambiguous_merge_arbiter_is_used(self) -> None:
        arbiter_calls: list[tuple[str, str]] = []

        def _arbiter(left_fragment, right_fragment):
            arbiter_calls.append((left_fragment.fragment_id, right_fragment.fragment_id))
            return "same_issue", "Utility scope and schedule exposure should be treated as one issue."

        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Budget / Cost Reliability",
                    severity="high",
                    summary="The site-development cost package is still budgetary and allowance-driven.",
                    issue="Cost package is still budgetary.",
                    why_it_matters="Basis remains exposed if the current cost stack is not auditable.",
                    likely_implication="Land basis remains provisional until pricing is locked.",
                    source_documents=["Cost Memo"],
                    gating_flags=["Underwriting confidence"],
                ),
                RiskFinding(
                    category="Fee / Exaction Burden",
                    severity="medium",
                    summary="Impact fee assumptions are still preliminary in the same underwriting package.",
                    issue="Fee stack is not locked.",
                    why_it_matters="The same underwriting package still depends on estimated fee assumptions.",
                    likely_implication="Land basis can move if the fee stack resets.",
                    source_documents=["Cost Memo"],
                    gating_flags=["Underwriting confidence"],
                ),
            ],
            contradictions=[],
            omission_assessments=[],
            document_analyses=[],
            merge_arbiter=_arbiter,
        )

        self.assertTrue(arbiter_calls)
        self.assertTrue(registry.arbitration_records)
        self.assertTrue(registry.arbitration_records[0].used_arbiter)

    def test_autonomous_learning_agent_generates_conservative_pseudo_labels(self) -> None:
        registry = build_canonical_issue_registry(
            key_risks=[
                RiskFinding(
                    category="Title / Access Concerns",
                    severity="high",
                    summary="Access easement exception burdens the planned entry condition.",
                    issue="Title access clearance unresolved.",
                    why_it_matters="This affects access control and closability.",
                    likely_implication="The entry condition remains provisional until the burden is cleared or endorsed.",
                    source_documents=["Title Report"],
                    citations=[Citation(document_name="Title Report", chunk_id="page-0001", page_number=1)],
                    gating_flags=["Closing", "Underwriting confidence"],
                )
            ],
            contradictions=[],
            omission_assessments=[
                OmissionAssessment(
                    item="Drainage calculations",
                    category="Flood / Drainage Issues",
                    status="not found",
                    rationale="No current drainage calculations were found.",
                )
            ],
            document_analyses=[],
        )
        apply_front_end_assessment(
            registry=registry,
            document_analyses=[],
            omission_assessments=[],
            contradictions=[],
        )

        records, summary = AutonomousLearningAgent().build_records(
            deal_name="Autonomous Deal",
            registry=registry,
        )

        self.assertGreaterEqual(summary.records_generated, 1)
        self.assertTrue(any(record.label_source == "autonomous" for record in records))
        self.assertTrue(any(record.real_issue is True for record in records))

    def test_run_analysis_attaches_web_research_results_from_fake_agent(self) -> None:
        class _FakeWebResearchAgent(WebResearchAgent):
            def __init__(self) -> None:
                pass

            def research(self, *, deal_name: str, registry: CanonicalIssueRegistry, document_analyses):
                return [
                    WebResearchResult(
                        issue_id="entitlement-conditions",
                        title="Entitlement conditions unresolved",
                        question="What public approval condition still controls this site?",
                        query=f"{deal_name} entitlement conditions site development",
                        status="answered",
                        answer="Public planning materials show outstanding conditions still tied to improvement-plan approval.",
                        confidence="high",
                        source_titles=["City Planning Conditions"],
                        source_urls=["https://example.gov/planning-conditions"],
                        note="Public-web result is supportive only; confirm with the current approval package.",
                    )
                ]

        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "autonomous_issue_memory.jsonl"
            synthesis = run_analysis(
                deal_name="Web Research Deal",
                documents=[
                    _document(
                        "conditions_of_approval.txt",
                        "At improvement plan stage, the project shall satisfy remaining frontage dedication and utility confirmation conditions.",
                    )
                ],
                llm_provider=HeuristicProvider(),
                logger=logging.getLogger("test-web-research"),
                mode="full",
                autonomous_learning_enabled=True,
                autonomous_store_path=store_path,
                web_researcher=_FakeWebResearchAgent(),
            )

            self.assertTrue(synthesis.web_research_results)
            self.assertEqual(synthesis.web_research_results[0].status, "answered")
            self.assertIn("planning materials", synthesis.web_research_results[0].answer.lower())
            self.assertTrue(synthesis.autonomous_learning_summary.enabled)
            self.assertTrue(store_path.exists())
            self.assertTrue(load_autonomous_learning_records(store_path))


if __name__ == "__main__":
    unittest.main()
