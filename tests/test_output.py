"""Tests for markdown output generation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from land_due_diligence_agent.models import (
    CanonicalIssue,
    CanonicalIssueRegistry,
    ChallengeFinding,
    Citation,
    ContradictionFinding,
    DealMetadata,
    DealSynthesis,
    DocumentAnalysis,
    DocumentRecord,
    FileProcessingResult,
    IssueAnalysis,
    IssuePriorityScore,
    LLMCallFailure,
    OmissionAssessment,
    OutputIssueSelection,
    PrecedentReference,
    PrecedentSummary,
    PriorityAssessment,
    PriorityCallout,
    ReadingRecommendation,
    RecommendationDecision,
    RiskFinding,
    RunSummary,
    StructuredFact,
)
from land_due_diligence_agent.output.markdown_writer import write_markdown_outputs


class OutputWriterTests(unittest.TestCase):
    def test_writes_expected_markdown_files(self) -> None:
        document = DocumentRecord(
            source_path=Path("memo.txt"),
            relative_path=Path("memo.txt"),
            extension=".txt",
            title="Memo",
            raw_text="memo",
            normalized_text="memo",
            ocr_pages=[1],
            ocr_recovered_pages=[1],
        )
        analysis = DocumentAnalysis(
            document=document,
            summary="Summary text.",
            risks=[
                RiskFinding(
                    category="Environmental Risks",
                    severity="high",
                    summary="Risk summary.",
                    evidence=["Memo: evidence"],
                    issue="The Phase I ESA (Memo) leaves environmental follow-up open.",
                    why_it_matters="This affects underwriting certainty.",
                    likely_implication="Mitigation cost remains open.",
                    anchor="The Phase I ESA (Memo)",
                    priority_tier="primary",
                    gating_flags=["Underwriting confidence"],
                    citations=[Citation(document_name="Memo", chunk_id="page-0001", page_number=1)],
                )
            ],
            seller_questions=["What remediation is still outstanding?"],
            reading_priority=5,
            reading_reason="Contains high-priority environmental indicators.",
            confidence="high",
            confidence_reason="Text extraction was strong with no OCR-related warnings.",
            focus_areas=["Environmental Risks"],
        )
        structured_fact = StructuredFact(
            category="Environmental Risks",
            statement="Memo: Phase I ESA indicates environmental follow-up remains open.",
            document_name="Memo",
            confidence="high",
            citations=[Citation(document_name="Memo", chunk_id="page-0001", page_number=1)],
        )
        issue_analysis = IssueAnalysis(
            category="Environmental Risks",
            label="Environmental",
            core_facts=[structured_fact],
            unresolved_questions=["What remediation scope remains open and who is paying for it?"],
            why_it_matters="This affects underwriting certainty.",
            likely_implication="Mitigation cost remains open.",
            confidence="high",
            citations=[Citation(document_name="Memo", chunk_id="page-0001", page_number=1)],
            source_documents=["Memo"],
            priority_score=95,
            decision_summary="The Phase I ESA leaves environmental follow-up open and cost certainty exposed.",
        )
        challenge_finding = ChallengeFinding(
            heading="Optimism Check",
            concern="The package can overstate cost certainty if remediation is treated as closed when the Phase I still leaves follow-up open.",
            why_it_matters="Environmental scope can expand after deal approval if the follow-up assumptions are wrong.",
            likely_pushback="IC will ask why remediation reserve is not better evidenced before approval.",
            citations=[Citation(document_name="Memo", chunk_id="page-0001", page_number=1)],
            source_documents=["Memo"],
            priority=80,
        )
        priority_callout = PriorityCallout(
            label="Environmental",
            statement="The Phase I ESA leaves environmental follow-up open and cost certainty exposed.",
            why_it_matters="Environmental scope still affects underwriting confidence.",
            citations=[Citation(document_name="Memo", chunk_id="page-0001", page_number=1)],
            category="Environmental Risks",
        )
        canonical_issue = CanonicalIssue(
            issue_id="environmental-followup",
            title="Environmental follow-up is not fully closed",
            category="Environmental Risks",
            status="open",
            issue_type="environmental-followup",
            core_facts=["Phase I ESA still leaves remediation scope unresolved."],
            best_evidence=["Memo: Phase I ESA indicates environmental follow-up remains open."],
            why_it_matters="Environmental scope still affects underwriting confidence.",
            likely_implication="Mitigation cost remains open.",
            what_would_resolve_it="Provide the current environmental closure path, cost owner, and any remaining mitigation obligation.",
            open_questions=["What remediation scope remains open and who is paying for it?"],
            confidence="high",
            severity="high",
            likelihood="high",
            timing_sensitivity="medium",
            cost_sensitivity="medium",
            fixability="medium",
            decision_action="verify",
            citations=[Citation(document_name="Memo", chunk_id="page-0001", page_number=1)],
            source_documents=["Memo"],
            gating_flags=["Underwriting confidence"],
            merged_fragment_ids=["risk-01-environmental"],
            merged_fragment_titles=["Environmental follow-up is not fully closed"],
            priority_score=IssuePriorityScore(
                total=104,
                cost_exposure=3,
                schedule_exposure=3,
                likelihood=5,
                evidence_confidence=5,
                ic_sensitivity=4,
                precedent_adjustment=6,
            ),
            precedent_references=[
                PrecedentReference(
                    precedent_id="anon-west-007",
                    title="Anon West Multifamily G: Environmental follow-up is not fully closed",
                    issue_type="environmental-followup",
                    category="Environmental Risks",
                    deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="multifamily"),
                    similarity_score=0.781,
                    category_match=True,
                    stage_match=True,
                    real_issue=True,
                    materiality="high",
                    actual_outcome="cost",
                    resolution_notes="Closed after confirming the remediation scope, seller credit, and agency sign-off path.",
                    relevance="same issue type, same stage",
                )
            ],
            precedent_summary=PrecedentSummary(
                historical_frequency=2,
                real_rate=0.5,
                outcome_stats={"cost": 1, "none": 1},
                false_positive_rate=0.5,
                typical_impact="cost",
                resolution_pattern="Closed after confirming the remediation scope, seller credit, and agency sign-off path.",
                confidence_adjustment="neutral",
                score_adjustment=6,
                sample_size=2,
                sparse_data=False,
                reasoning="Historical outcomes are mixed, so the current issue should stay anchored to the cited deal evidence first.",
            ),
            output_bucket="executive",
        )
        synthesis = DealSynthesis(
            deal_name="Demo Deal",
            executive_summary="Executive summary text.",
            entitlement_status="Status unclear.",
            key_risks=analysis.risks,
            recommended_reading_order=[
                ReadingRecommendation(
                    title="Memo",
                    relative_path="memo.txt",
                    priority=5,
                    reason="Contains high-priority environmental indicators.",
                    confidence="high",
                    focus_areas=["Environmental Risks"],
                )
            ],
            seller_questions=analysis.seller_questions,
            missing_items=["ALTA or boundary survey"],
            category_rollup={"Environmental Risks": "One document flagged environmental signals."},
            document_analyses=[analysis],
            structured_facts=[structured_fact],
            omission_assessments=[
                OmissionAssessment(
                    item="ALTA or boundary survey",
                    category="Title / Access Concerns",
                    status="not found",
                    rationale="No survey file is present in the package.",
                )
            ],
            issue_analyses=[issue_analysis],
            canonical_issue_registry=CanonicalIssueRegistry(
                fragments=[],
                issues=[canonical_issue],
                merge_decisions=[],
                omission_assessments=[],
                output_selections=[
                    OutputIssueSelection("01_executive_summary.md", "environmental-followup", 1, "Highest weighted decision priority"),
                    OutputIssueSelection("02_key_risks.md", "environmental-followup", 1, "Top ranked issue"),
                    OutputIssueSelection("09_investment_committee_brief.md", "environmental-followup", 1, "Board-level decision driver"),
                    OutputIssueSelection("10_issue_analysis.md", "environmental-followup", 1, "Appendix coverage"),
                ],
                deal_metadata=DealMetadata(stage="acquisition-dd", region="west", product="multifamily"),
            ),
            challenge_findings=[challenge_finding],
            priority_assessment=PriorityAssessment(
                top_deal_shaping_issues=[priority_callout],
                top_cost_risk=priority_callout,
            ),
            recommendation=RecommendationDecision(
                posture="proceed with conditions",
                rationale="Environmental follow-up still needs to be closed before basis is treated as reliable.",
                reasons=["Environmental follow-up remains open in the Phase I ESA."],
                conditions=["Provide the current environmental closure path, cost owner, and any remaining mitigation obligation."],
            ),
            contradictions=[
                ContradictionFinding(
                    description="Memo p. 1 shows environmental follow-up, but the pricing package still reads as preliminary.",
                    why_it_matters="That tension weakens cost certainty.",
                    citations=[Citation(document_name="Memo", chunk_id="page-0001", page_number=1)],
                    source_documents=["Memo"],
                    related_categories=["Environmental Risks", "Budget / Cost Reliability"],
                    priority=90,
                )
            ],
            llm_failures=[
                LLMCallFailure(
                    stage="document_summary",
                    target="memo.txt",
                    model="gpt-4.1",
                    detail="RuntimeError: example failure detail",
                )
            ],
        )
        run_summary = RunSummary(
            run_id="20260328_120000",
            deal_name="Demo Deal",
            input_folder="data/input/demo-deal",
            output_folder="data/output/demo-deal/20260328_120000",
            llm_provider="heuristic",
            started_at="2026-03-28T12:00:00-07:00",
            completed_at="2026-03-28T12:01:00-07:00",
            analysis_mode="full",
            files_found=1,
            files_parsed_successfully=1,
            files_failed=0,
            file_results=[FileProcessingResult(relative_path="memo.txt", status="parsed")],
            llm_model="gpt-4.1",
        )
        run_summary.file_results[0].ocr_pages = [1]
        run_summary.file_results[0].ocr_recovered_pages = [1]
        run_summary.file_results[0].warnings = ["Page 1 required OCR fallback (no text) and text was recovered."]

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "run.log").write_text("log", encoding="utf-8")
            written = write_markdown_outputs(output_dir, run_summary=run_summary, synthesis=synthesis)

            self.assertEqual(len(written), 13)
            self.assertTrue((output_dir / "00_run_summary.md").exists())
            self.assertTrue((output_dir / "08_error_report.md").exists())
            self.assertTrue((output_dir / "01_executive_summary.md").exists())
            self.assertTrue((output_dir / "09_investment_committee_brief.md").exists())
            self.assertTrue((output_dir / "10_issue_analysis.md").exists())
            self.assertTrue((output_dir / "11_issue_registry_debug.md").exists())
            self.assertTrue((output_dir / "12_reviewer_feedback_template.json").exists())
            content = (output_dir / "01_executive_summary.md").read_text(encoding="utf-8")
            self.assertIn("Demo Deal", content)
            self.assertIn("heuristic", content)
            self.assertIn("Decision Framing", content)
            self.assertIn("Top Decision Drivers", content)
            self.assertIn("Decision Readiness", content)
            self.assertIn("Status:", content)
            self.assertIn("Executive Call", content)
            self.assertIn("Known Limitations Of This Run", content)
            self.assertIn("Recommendation Posture", content)
            key_risk_content = (output_dir / "02_key_risks.md").read_text(encoding="utf-8")
            self.assertIn("Ranked Issues", key_risk_content)
            self.assertIn("Why It Matters", key_risk_content)
            self.assertIn("What Would Resolve It", key_risk_content)
            self.assertIn("Gating Impact", key_risk_content)
            self.assertIn("Source: Memo p. 1", key_risk_content)
            self.assertIn("Potential Contradictions / Tensions", key_risk_content)
            synthesis_content = (output_dir / "07_deal_synthesis.md").read_text(encoding="utf-8")
            self.assertIn("Risk Pattern", synthesis_content)
            self.assertIn("Gating Issues", synthesis_content)
            self.assertIn("Potential Contradictions / Tensions", synthesis_content)
            self.assertIn("Adversarial Challenge", synthesis_content)
            ic_content = (output_dir / "09_investment_committee_brief.md").read_text(encoding="utf-8")
            self.assertIn("Recommendation", ic_content)
            self.assertIn("Reasons", ic_content)
            self.assertIn("Conditions / Asks", ic_content)
            self.assertIn("Decision Readiness", ic_content)
            self.assertIn("Likely IC Pushback", ic_content)
            issue_content = (output_dir / "10_issue_analysis.md").read_text(encoding="utf-8")
            self.assertIn("Issue Analysis", issue_content)
            self.assertIn("Environmental follow-up is not fully closed", issue_content)
            self.assertIn("Core Facts", issue_content)
            debug_content = (output_dir / "11_issue_registry_debug.md").read_text(encoding="utf-8")
            self.assertIn("Issue Registry Debug", debug_content)
            self.assertIn("Canonical Issue Registry", debug_content)
            self.assertIn("environmental-followup", debug_content)
            self.assertIn("Evidence Basis", debug_content)
            self.assertIn("Top-Line Eligible", debug_content)
            self.assertIn("Deal Metadata", debug_content)
            self.assertIn("Precedent Summary", debug_content)
            self.assertIn("Retrieved Precedent Matches", debug_content)
            self.assertIn("precedent=+6", debug_content)
            self.assertIn("## Evaluator", debug_content)
            feedback_rows = json.loads((output_dir / "12_reviewer_feedback_template.json").read_text(encoding="utf-8"))
            self.assertEqual(feedback_rows[0]["issue_id"], "environmental-followup")
            self.assertEqual(
                set(feedback_rows[0]),
                {
                    "issue_id",
                    "canonical_title",
                    "category",
                    "deal_id",
                    "deal_name",
                    "deal_metadata",
                    "evidence_basis",
                    "issue_strength",
                    "false_positive_risk",
                    "model_materiality",
                    "model_decision_relevant",
                    "model_action",
                    "real_issue",
                    "false_positive_flag",
                    "materiality",
                    "decision_relevant",
                    "duplicate_of",
                    "overstated",
                    "understated",
                    "actual_outcome",
                    "resolved_by",
                    "correct_action",
                    "notes",
                },
            )
            summary_content = (output_dir / "00_run_summary.md").read_text(encoding="utf-8")
            self.assertIn("Files found: 1", summary_content)
            self.assertIn("run.log", summary_content)
            self.assertIn("09_investment_committee_brief.md", summary_content)
            self.assertIn("10_issue_analysis.md", summary_content)
            self.assertIn("11_issue_registry_debug.md", summary_content)
            self.assertIn("12_reviewer_feedback_template.json", summary_content)
            self.assertIn("LLM Model: `gpt-4.1`", summary_content)
            self.assertIn("Analysis Mode: `full`", summary_content)
            self.assertIn("OCR fallback was required on 1 file(s) across 1 page(s).", summary_content)
            self.assertIn("OCR pages 1", summary_content)
            error_content = (output_dir / "08_error_report.md").read_text(encoding="utf-8")
            self.assertIn("OCR Fallback Activity", error_content)
            self.assertIn("OCR pages 1", error_content)
            self.assertIn("LLM Refinement Failures", error_content)
            self.assertIn("example failure detail", error_content)

    def test_writes_fast_mode_output_subset(self) -> None:
        document = DocumentRecord(
            source_path=Path("memo.txt"),
            relative_path=Path("memo.txt"),
            extension=".txt",
            title="Memo",
            raw_text="memo",
            normalized_text="memo",
            ocr_pages=[1],
            ocr_recovered_pages=[1],
        )
        analysis = DocumentAnalysis(
            document=document,
            summary="Summary text.",
            risks=[
                RiskFinding(
                    category="Environmental Risks",
                    severity="high",
                    summary="Risk summary.",
                    evidence=["Memo: evidence"],
                    issue="The Phase I ESA (Memo) leaves environmental follow-up open.",
                    why_it_matters="This affects underwriting certainty.",
                    likely_implication="Mitigation cost remains open.",
                    anchor="The Phase I ESA (Memo)",
                    priority_tier="primary",
                    gating_flags=["Underwriting confidence"],
                    citations=[Citation(document_name="Memo", chunk_id="page-0001", page_number=1)],
                )
            ],
            seller_questions=["What remediation is still outstanding?"],
            reading_priority=5,
            reading_reason="Contains high-priority environmental indicators.",
            confidence="high",
            confidence_reason="Text extraction was strong with no OCR-related warnings.",
            focus_areas=["Environmental Risks"],
        )
        canonical_issue = CanonicalIssue(
            issue_id="environmental-followup",
            title="Environmental follow-up is not fully closed",
            category="Environmental Risks",
            status="open",
            why_it_matters="Environmental scope still affects underwriting certainty.",
            likely_implication="Mitigation cost remains open.",
            what_would_resolve_it="Provide the current environmental closure path and remaining mitigation obligations.",
            confidence="high",
            citations=[Citation(document_name="Memo", chunk_id="page-0001", page_number=1)],
            source_documents=["Memo"],
            priority_score=IssuePriorityScore(total=104, likelihood=5, evidence_confidence=5),
        )
        synthesis = DealSynthesis(
            deal_name="Fast Deal",
            executive_summary="Executive summary text.",
            entitlement_status="Status unclear.",
            key_risks=analysis.risks,
            recommended_reading_order=[],
            seller_questions=analysis.seller_questions,
            missing_items=[],
            category_rollup={"Environmental Risks": "One document flagged environmental signals."},
            document_analyses=[analysis],
            canonical_issue_registry=CanonicalIssueRegistry(
                issues=[canonical_issue],
                output_selections=[
                    OutputIssueSelection("01_executive_summary.md", "environmental-followup", 1, "Highest weighted decision priority"),
                    OutputIssueSelection("02_key_risks.md", "environmental-followup", 1, "Top ranked issue"),
                ],
            ),
            recommendation=RecommendationDecision(
                posture="proceed with conditions",
                rationale="Environmental follow-up remains open.",
                reasons=["Environmental follow-up remains open."],
                conditions=["Provide the current environmental closure path and remaining mitigation obligations."],
            ),
            analysis_mode="fast",
            llm_calls_attempted=1,
        )
        run_summary = RunSummary(
            run_id="20260328_120000",
            deal_name="Fast Deal",
            input_folder="data/input/fast-deal",
            output_folder="data/output/fast-deal/20260328_120000",
            llm_provider="openai",
            started_at="2026-03-28T12:00:00-07:00",
            completed_at="2026-03-28T12:01:00-07:00",
            analysis_mode="fast",
            llm_calls_made=1,
            files_found=1,
            files_parsed_successfully=1,
            files_failed=0,
            file_results=[FileProcessingResult(relative_path="memo.txt", status="parsed")],
            llm_model="gpt-4.1",
        )
        run_summary.file_results[0].ocr_pages = [1]
        run_summary.file_results[0].ocr_recovered_pages = [1]
        run_summary.file_results[0].warnings = ["Page 1 required OCR fallback (no text) and text was recovered."]

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "run.log").write_text("log", encoding="utf-8")
            written = write_markdown_outputs(output_dir, run_summary=run_summary, synthesis=synthesis)

            self.assertEqual(len(written), 5)
            self.assertTrue((output_dir / "01_executive_summary.md").exists())
            self.assertTrue((output_dir / "02_key_risks.md").exists())
            self.assertTrue((output_dir / "04_seller_questions.md").exists())
            self.assertFalse((output_dir / "03_recommended_reading_order.md").exists())
            self.assertFalse((output_dir / "05_document_summaries.md").exists())
            self.assertFalse((output_dir / "07_deal_synthesis.md").exists())
            self.assertFalse((output_dir / "09_investment_committee_brief.md").exists())
            self.assertFalse((output_dir / "11_issue_registry_debug.md").exists())
            self.assertFalse((output_dir / "12_reviewer_feedback_template.json").exists())
            content = (output_dir / "01_executive_summary.md").read_text(encoding="utf-8")
            self.assertIn("Mode:** fast", content)
            self.assertNotIn("Decision Framing", content)
            key_risk_content = (output_dir / "02_key_risks.md").read_text(encoding="utf-8")
            self.assertIn("Ranked Issues", key_risk_content)
            self.assertIn("What Would Resolve It", key_risk_content)
            self.assertNotIn("Potential Contradictions / Tensions", key_risk_content)
            summary_content = (output_dir / "00_run_summary.md").read_text(encoding="utf-8")
            self.assertIn("Analysis Mode: `fast`", summary_content)
            self.assertIn("Approximate LLM Calls: 1", summary_content)
            self.assertIn("OCR fallback was required on 1 file(s) across 1 page(s).", summary_content)

    def test_writes_summary_and_error_report_without_synthesis(self) -> None:
        run_summary = RunSummary(
            run_id="20260328_120000",
            deal_name="Broken Deal",
            input_folder="data/input/broken-deal",
            output_folder="data/output/broken-deal/20260328_120000",
            llm_provider="heuristic",
            started_at="2026-03-28T12:00:00-07:00",
            completed_at="2026-03-28T12:01:00-07:00",
            files_found=2,
            files_parsed_successfully=0,
            files_failed=2,
            file_results=[
                FileProcessingResult(relative_path="bad.pdf", status="failed", error_message="PdfReadError: corrupt"),
                FileProcessingResult(relative_path="scan.pdf", status="failed", error_message="RuntimeError: no text"),
            ],
            run_errors=["No documents could be parsed successfully."],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "run.log").write_text("log", encoding="utf-8")
            written = write_markdown_outputs(output_dir, run_summary=run_summary)

            self.assertEqual(len(written), 2)
            error_content = (output_dir / "08_error_report.md").read_text(encoding="utf-8")
            self.assertIn("bad.pdf", error_content)
            self.assertIn("No documents could be parsed successfully.", error_content)


if __name__ == "__main__":
    unittest.main()
