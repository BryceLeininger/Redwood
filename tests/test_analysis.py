"""Tests for the analysis pipeline."""

from __future__ import annotations

import logging
import unittest
from pathlib import Path

from land_due_diligence_agent.analysis.front_end import apply_front_end_assessment
from land_due_diligence_agent.analysis.issue_registry import (
    build_canonical_issue_registry,
    build_overall_read_draft,
    build_recommendation_from_registry,
    build_section_selections,
)
from land_due_diligence_agent.analysis.service import run_analysis
from land_due_diligence_agent.llm.base import LLMProvider
from land_due_diligence_agent.llm.heuristic_provider import HeuristicProvider
from land_due_diligence_agent.models import (
    CanonicalIssue,
    CanonicalIssueRegistry,
    Citation,
    ContradictionFinding,
    DocumentRecord,
    OmissionAssessment,
    RiskFinding,
)
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
    def test_normalize_text_repairs_common_mojibake(self) -> None:
        text = "The dealâ€™s geotech scopeâ€”and cost basisâ€”need review."
        self.assertEqual(
            normalize_text(text),
            "The deal's geotech scope-and cost basis-need review.",
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
        self.assertTrue(
            synthesis.further_diligence_roadmap.top_real_flags
            or synthesis.further_diligence_roadmap.top_contradictions_to_resolve
        )

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


if __name__ == "__main__":
    unittest.main()
