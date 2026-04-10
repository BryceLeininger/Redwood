"""Tests for markdown output generation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from land_due_diligence_agent.models import (
    AutonomousLearningSummary,
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
    FurtherDiligenceRoadmap,
    IssueAnalysis,
    IssueCluster,
    IssueDependencyLink,
    IssuePriorityScore,
    LearningSummary,
    LLMCallFailure,
    OmissionAssessment,
    OutputIssueSelection,
    PrecedentReference,
    PrecedentSummary,
    PriorityAssessment,
    PriorityCallout,
    ReadingRecommendation,
    ResearchAgendaItem,
    RecommendationDecision,
    RiskFinding,
    RunSummary,
    StructuredFact,
    WebResearchResult,
)
from land_due_diligence_agent.output.markdown_writer import (
    _compress_statement,
    _output_discipline_snapshot,
    write_markdown_outputs,
)


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
            document_takeaway="This is a control document for residual environmental scope and cost owner.",
            key_points=[
                "Phase I ESA leaves environmental follow-up open.",
                "Residual remediation scope is still unresolved.",
            ],
            open_loops=[
                "This file does not by itself close the environmental follow-up scope or cost owner.",
            ],
            document_role="primary",
            staleness_status="present and adequate",
            staleness_reason="No obvious staleness signal was isolated.",
            contradiction_count=1,
            reading_bucket="must read personally",
            reading_rationale_factors=["primary source document", "legal significance", "other conclusions depend on it"],
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
                learning_adjustment=4,
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
            learning_summary=LearningSummary(
                sample_size=4,
                real_issue_rate=0.75,
                false_positive_rate=0.25,
                material_issue_rate=0.75,
                decision_relevant_rate=0.75,
                impact_rate=0.5,
                matched_features=[
                    "issue_id=environmental-followup (n=4)",
                    "category=Environmental Risks (n=5)",
                    "stage=acquisition-dd (n=7)",
                ],
                confidence_adjustment="up",
                score_adjustment=4,
                reasoning="Reviewer-labeled history says this issue usually proves real and decision-relevant when it appears in similar deals.",
            ),
            dependency_type="legal",
            critical_path_flag=True,
            blocking_flag=True,
            blocker_classification="blocking issue",
            schedule_impact_classification="pre-underwriting blocker",
            blocking_reason="Labeled blocking because it is a pre-underwriting blocker and currently blocks underwriting confidence.",
            critical_path_reason="On the critical path because it directly controls the underwriting basis.",
            likely_cost_effect="Mitigation, remediation, or agency follow-up can add direct cost and reserve requirements.",
            likely_schedule_effect="Sampling, agency review, or mitigation closeout can delay underwriting and sometimes permit timing.",
            likely_yield_or_product_effect="Buffers, mitigation areas, or cleanup limits can reduce buildable area or product flexibility.",
            likely_closing_effect="Material environmental exposure can push the deal back to a conditional or paused closing posture.",
            likely_structure_effect="May require seller indemnity, credit, escrow, or post-close remediation allocation.",
            likely_underwriting_effect="Basis and timing remain provisional until residual environmental scope and cost owner are clear.",
            front_end_flag="red flag",
            front_end_flag_reason="Direct evidence shows this issue is both real and close enough to the critical path that it should stand out in screening.",
            information_status="present and adequate",
            information_status_reason="This issue is supported by current direct evidence rather than by a missing-document inference.",
            missing_confirmation="Provide the current environmental closure path, cost owner, and any remaining mitigation obligation.",
            research_agenda=[
                ResearchAgendaItem(
                    issue_id="environmental-followup",
                    title="Environmental follow-up is not fully closed",
                    verify_what="What remediation scope remains open and who is paying for it?",
                    request_item="Provide the current environmental closure path, cost owner, and any remaining mitigation obligation.",
                    likely_source="environmental consultant and agency file review",
                    timing="now",
                )
            ],
            downstream_dependencies=[
                IssueDependencyLink(
                    issue_id="budget-reliability",
                    title="Cost package is still budgetary",
                    dependency_type="cost",
                    mechanism="Residual mitigation scope belongs in the basis.",
                    effect="Underwriting remains exposed until cost ownership is explicit.",
                )
            ],
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
                    reason="Must Read Personally because this document carries primary source document, legal significance, other conclusions depend on it. Confidence is high.",
                    confidence="high",
                    focus_areas=["Environmental Risks"],
                    bucket="must read personally",
                    document_role="primary",
                    rationale_factors=["primary source document", "legal significance", "other conclusions depend on it"],
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
                    front_end_status="missing and important",
                    importance="important",
                    recommended_request="a current, readable alta or boundary survey",
                    front_end_reason="The package does not contain current, readable support for a normally expected diligence item.",
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
                blocker_issue_ids=["environmental-followup"],
                critical_path_issue_ids=["environmental-followup"],
                central_risk_pattern="Risk is concentrated around environmental closure path, with environmental follow-up acting as the root issue that drives downstream underwriting and schedule exposure.",
                cluster_pattern="Most of the important issues cluster around one or two root causes rather than behaving independently.",
                fragility_classification="fragile sequencing",
                critical_path_summary="The real critical path runs through environmental follow-up is not fully closed.",
                confidence_unlocks=["Provide the current environmental closure path, cost owner, and any remaining mitigation obligation."],
                package_quality="selectively presented",
                package_quality_reason="The package has material conflicts and does not include enough current controlling support to cleanly resolve them.",
                front_end_known_points=[
                    "Environmental follow-up is not fully closed: Phase I ESA still leaves remediation scope unresolved."
                ],
                front_end_unresolved_points=[
                    "ALTA or boundary survey: missing and important.",
                    "Memo p. 1 shows environmental follow-up, but the pricing package still reads as preliminary.",
                ],
                front_end_routine_points=["No routine-only item was worth calling out separately."],
                front_end_deeper_work=[
                    "Environmental follow-up is not fully closed: verify What remediation scope remains open and who is paying for it?; request Provide the current environmental closure path, cost owner, and any remaining mitigation obligation.; use environmental consultant and agency file review (now)."
                ],
                issue_clusters=[
                    IssueCluster(
                        cluster_id="cluster-01-environmental-closure-path",
                        label="environmental closure path",
                        tier="Primary",
                        root_issue_id="environmental-followup",
                        issue_ids=["environmental-followup"],
                        downstream_effects=[
                            "Sampling, agency review, or mitigation closeout can delay underwriting and sometimes permit timing.",
                            "Mitigation, remediation, or agency follow-up can add direct cost and reserve requirements.",
                        ],
                        key_unresolved_confirmations=[
                            "Provide the current environmental closure path, cost owner, and any remaining mitigation obligation."
                        ],
                        decision_implication="Basis and timing remain provisional until residual environmental scope and cost owner are clear.",
                        critical_path_issue_ids=["environmental-followup"],
                    )
                ],
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
            further_diligence_roadmap=FurtherDiligenceRoadmap(
                top_real_flags=[
                    "Environmental follow-up is not fully closed: red flag. Why it matters: Environmental scope still affects underwriting confidence. What it blocks: cost package is still budgetary."
                ],
                top_missing_items_to_request=[
                    "ALTA or boundary survey: missing and important. Request a current, readable alta or boundary survey."
                ],
                top_contradictions_to_resolve=[
                    "Memo p. 1 shows environmental follow-up, but the pricing package still reads as preliminary. Resolve by identifying which source controls and updating the underwriting assumption to that source."
                ],
                top_stale_materials_to_refresh=[],
                top_public_consultant_internal_research=[
                    "Environmental follow-up is not fully closed: verify What remediation scope remains open and who is paying for it? via environmental consultant and agency file review; request Provide the current environmental closure path, cost owner, and any remaining mitigation obligation. (now)."
                ],
                top_documents_to_read_first=[
                    "Memo (memo.txt): Must Read Personally because this document carries primary source document, legal significance, other conclusions depend on it. Confidence is high."
                ],
                follow_up_order=[
                    "Read Memo first because other conclusions depend on it.",
                    "Request a current, readable alta or boundary survey now.",
                ],
            ),
            web_research_results=[
                WebResearchResult(
                    issue_id="environmental-followup",
                    title="Environmental follow-up is not fully closed",
                    question="What remediation scope remains open and who is paying for it?",
                    query="Demo Deal Environmental follow-up is not fully closed environmental review remediation",
                    status="partial",
                    answer="Public agency materials suggest environmental review remains active, but the package still needs deal-specific closure support.",
                    confidence="medium",
                    source_titles=["City Environmental Review"],
                    source_urls=["https://example.gov/environmental-review"],
                    source_snippets=["Environmental review remains active for the project area."],
                    note="Public-web result is supportive only; confirm with current deal-specific support before relying on it.",
                )
            ],
            autonomous_learning_summary=AutonomousLearningSummary(
                records_generated=1,
                positive_records=1,
                negative_records=0,
                skipped_issues=0,
                reasoning="Autonomous learning stored one conservative positive pseudo-label from strong internal consensus.",
            ),
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

            self.assertEqual(len(written), 15)
            self.assertTrue((output_dir / "00_run_summary.md").exists())
            self.assertTrue((output_dir / "08_error_report.md").exists())
            self.assertTrue((output_dir / "01_executive_summary.md").exists())
            self.assertTrue((output_dir / "09_investment_committee_brief.md").exists())
            self.assertTrue((output_dir / "10_issue_analysis.md").exists())
            self.assertTrue((output_dir / "11_issue_registry_debug.md").exists())
            self.assertTrue((output_dir / "12_reviewer_feedback_template.json").exists())
            self.assertTrue((output_dir / "13_further_diligence_roadmap.md").exists())
            self.assertTrue((output_dir / "14_web_research.md").exists())
            content = (output_dir / "01_executive_summary.md").read_text(encoding="utf-8")
            self.assertIn("Demo Deal", content)
            self.assertIn("heuristic", content)
            self.assertIn("## Conclusions", content)
            self.assertIn("Deal Impact Summary", content)
            self.assertIn("Underwrite Confidence", content)
            self.assertIn("If Wrong, What Happens?", content)
            self.assertIn("Biggest Flags", content)
            self.assertIn("Biggest Blind Spots", content)
            self.assertIn("Read First", content)
            self.assertIn("Known Limitations Of This Run", content)
            self.assertIn("Recommendation Posture", content)
            self.assertNotIn("Why It Matters", content)
            key_risk_content = (output_dir / "02_key_risks.md").read_text(encoding="utf-8")
            self.assertIn("Ranked Issues", key_risk_content)
            self.assertIn("Flag:", key_risk_content)
            self.assertIn("Why It Matters", key_risk_content)
            self.assertIn("Basis:", key_risk_content)
            self.assertIn("Deal Impact:", key_risk_content)
            self.assertIn("Exposure:", key_risk_content)
            self.assertIn("If Wrong:", key_risk_content)
            self.assertIn("Next:", key_risk_content)
            self.assertIn("Source: Memo p. 1", key_risk_content)
            self.assertIn("Potential Contradictions / Tensions", key_risk_content)
            document_summary_content = (output_dir / "05_document_summaries.md").read_text(encoding="utf-8")
            self.assertIn("Document Summaries", document_summary_content)
            self.assertIn("Front-End Read", document_summary_content)
            self.assertIn("What It Establishes", document_summary_content)
            self.assertIn("What It Still Leaves Open", document_summary_content)
            self.assertIn("Linked Deal Issues", document_summary_content)
            self.assertIn("Document-Specific Signals", document_summary_content)
            self.assertIn("Next Questions", document_summary_content)
            synthesis_content = (output_dir / "07_deal_synthesis.md").read_text(encoding="utf-8")
            self.assertIn("Sanity Check / Corrections", synthesis_content)
            self.assertIn("Primary Drivers of Price", synthesis_content)
            self.assertIn("Treated as solved", synthesis_content)
            self.assertIn("Initial Judgment", synthesis_content)
            self.assertIn("Routine Vs Elevated", synthesis_content)
            self.assertIn("Critical Path", synthesis_content)
            self.assertIn("What Changes Confidence", synthesis_content)
            self.assertNotIn("### 1.", synthesis_content)
            ic_content = (output_dir / "09_investment_committee_brief.md").read_text(encoding="utf-8")
            self.assertIn("Recommendation", ic_content)
            self.assertIn("Package Read", ic_content)
            self.assertIn("Sanity Check / Corrections", ic_content)
            self.assertIn("What has to be true", ic_content)
            self.assertIn("Deal Impact Summary", ic_content)
            self.assertIn("Underwrite Confidence", ic_content)
            self.assertIn("If Wrong, What Happens?", ic_content)
            self.assertIn("Top 3 Gating Issues", ic_content)
            self.assertIn("Biggest Blind Spots", ic_content)
            self.assertIn("Decision Readiness", ic_content)
            self.assertIn("What I Would Verify Personally", ic_content)
            issue_content = (output_dir / "10_issue_analysis.md").read_text(encoding="utf-8")
            self.assertIn("Issue Analysis", issue_content)
            self.assertIn("Environmental follow-up is not fully closed", issue_content)
            self.assertIn("Front-End Read", issue_content)
            self.assertIn("Core Facts", issue_content)
            self.assertIn("Missing Document / Confirmation", issue_content)
            self.assertIn("Suggested Next Research Step", issue_content)
            self.assertIn("Dependency Read", issue_content)
            self.assertIn("Downstream Consequences", issue_content)
            self.assertIn("Deal Impact", issue_content)
            self.assertIn("If Wrong, What Happens?", issue_content)
            self.assertIn("Learned Read", issue_content)
            self.assertIn("Public Web Check", issue_content)
            debug_content = (output_dir / "11_issue_registry_debug.md").read_text(encoding="utf-8")
            self.assertIn("Issue Registry Debug", debug_content)
            self.assertIn("Canonical Issue Registry", debug_content)
            self.assertIn("environmental-followup", debug_content)
            self.assertIn("Evidence Basis", debug_content)
            self.assertIn("Top-Line Eligible", debug_content)
            self.assertIn("Deal Metadata", debug_content)
            self.assertIn("Front-End Flag", debug_content)
            self.assertIn("Information Status", debug_content)
            self.assertIn("Normality Classification", debug_content)
            self.assertIn("Why Now", debug_content)
            self.assertIn("Deal Impact Type", debug_content)
            self.assertIn("Deal Impact Magnitude", debug_content)
            self.assertIn("Cost Exposure Band", debug_content)
            self.assertIn("If Wrong", debug_content)
            self.assertIn("Specificity Level", debug_content)
            self.assertIn("Abnormality Basis", debug_content)
            self.assertIn("Site-Specific Trigger", debug_content)
            self.assertIn("Genericity Penalty", debug_content)
            self.assertIn("Original Extracted Title", debug_content)
            self.assertIn("Normalized Title", debug_content)
            self.assertIn("Title Normalized", debug_content)
            self.assertIn("Title Similarity Cluster", debug_content)
            self.assertIn("Package Quality Inputs", debug_content)
            self.assertIn("Reading Priority Debug", debug_content)
            self.assertIn("Autonomous Learning", debug_content)
            self.assertIn("Web Research Debug", debug_content)
            self.assertIn("Omission Front-End Classification", debug_content)
            self.assertIn("Output Discipline", debug_content)
            self.assertIn("Repeated Phrases Across Sections", debug_content)
            self.assertIn("Average Sentence Length", debug_content)
            self.assertIn("Compression Score", debug_content)
            self.assertIn("Precedent Summary", debug_content)
            self.assertIn("Learning Summary", debug_content)
            self.assertIn("Learning Features", debug_content)
            self.assertIn("Retrieved Precedent Matches", debug_content)
            self.assertIn("precedent=+6", debug_content)
            self.assertIn("learning=+4", debug_content)
            self.assertIn("Dependency Graph", debug_content)
            self.assertIn("Causal Clusters", debug_content)
            self.assertIn("## Evaluator", debug_content)
            roadmap_content = (output_dir / "13_further_diligence_roadmap.md").read_text(encoding="utf-8")
            self.assertIn("Further Diligence Roadmap", roadmap_content)
            self.assertIn("Investigate Immediately", roadmap_content)
            self.assertIn("Read Personally", roadmap_content)
            self.assertIn("Likely Routine Unless Other Evidence Changes View", roadmap_content)
            self.assertNotIn("Top Real Flags To Investigate", roadmap_content)
            self.assertNotIn("Top Missing Items To Request", roadmap_content)
            self.assertNotIn("Top Documents To Read First", roadmap_content)
            self.assertNotIn("Why it matters", roadmap_content)
            self.assertNotIn("What it blocks", roadmap_content)
            web_research_content = (output_dir / "14_web_research.md").read_text(encoding="utf-8")
            self.assertIn("Web Research Fallback", web_research_content)
            self.assertIn("Partial", web_research_content)
            self.assertIn("City Environmental Review", web_research_content)
            self.assertNotIn(
                "Environmental scope still affects underwriting confidence.",
                content,
            )
            self.assertNotIn(
                "Environmental scope still affects underwriting confidence.",
                synthesis_content,
            )
            self.assertNotIn(
                "Environmental scope still affects underwriting confidence.",
                roadmap_content,
            )
            snapshot = _output_discipline_snapshot(
                {
                    "01_executive_summary.md": content,
                    "02_key_risks.md": key_risk_content,
                    "07_deal_synthesis.md": synthesis_content,
                    "13_further_diligence_roadmap.md": roadmap_content,
                }
            )
            self.assertLessEqual(snapshot["repeated_phrase_count"], 1)
            self.assertLessEqual(snapshot["avg_sentence_length"], 18)
            self.assertLessEqual(snapshot["hedge_density"], 1.0)
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
            self.assertIn("13_further_diligence_roadmap.md", summary_content)
            self.assertIn("14_web_research.md", summary_content)
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
            self.assertIn("Next:", key_risk_content)
            self.assertNotIn("Potential Contradictions / Tensions", key_risk_content)
            summary_content = (output_dir / "00_run_summary.md").read_text(encoding="utf-8")
            self.assertIn("Analysis Mode: `fast`", summary_content)
            self.assertIn("Approximate LLM Calls: 1", summary_content)
            self.assertIn("OCR fallback was required on 1 file(s) across 1 page(s).", summary_content)

    def test_compression_helper_limits_hedges_and_length(self) -> None:
        text = "This could potentially indicate a possible risk to schedule and could possibly delay approvals."
        compressed = _compress_statement(text, max_words=10)

        self.assertLessEqual(len(compressed.split()), 12)
        self.assertNotIn("potentially", compressed.lower())
        self.assertNotIn("possibly", compressed.lower())
        hedge_count = sum(word in {"may", "could", "might"} for word in compressed.lower().split())
        self.assertLessEqual(hedge_count, 1)

    def test_compression_helper_avoids_dangling_stopwords(self) -> None:
        text = "Replace estimated fees with a current city-confirmed fee matrix and quantify any exposure if schedule slips."
        compressed = _compress_statement(text, max_words=14)

        self.assertNotRegex(compressed, r"\b(if|the|and|or|to|with)\.$")
        self.assertTrue(compressed.endswith((".", "!", "?", "...")))

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
