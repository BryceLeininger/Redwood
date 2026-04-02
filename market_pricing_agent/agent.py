"""Orchestration entrypoint for the market pricing agent."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import load_project_config, load_sources_config
from .schemas import AnalysisResult, SourceStatus
from .tools.analysis import analyze_pricing
from .tools.extractors import extract_records
from .tools.fetcher import fetch_source
from .tools.logger import get_logger
from .tools.reporting import OutputArtifacts, write_outputs


@dataclass(frozen=True)
class RunArtifacts:
    run_dir: Path
    report_path: Path
    analysis_path: Path
    comps_path: Path


def run_pricing_agent(
    project_config_path: Path | str,
    sources_config_path: Path | str,
    *,
    output_dir: Path | str = "market_pricing_agent/outputs",
) -> tuple[AnalysisResult, RunArtifacts]:
    logger = get_logger()
    project = load_project_config(project_config_path)
    sources = load_sources_config(sources_config_path)

    logger.info("Loaded project '%s' with %d sources", project.name, len(sources))

    records = []
    status_entries: list[SourceStatus] = []

    for source in sources:
        try:
            fetched = fetch_source(source)
            extracted = extract_records(fetched)
            records.extend(extracted)
            status = "ok" if extracted else "warning"
            error = None if extracted else "No comparable records extracted"
            status_entries.append(
                SourceStatus(
                    name=source.name,
                    kind=source.kind,
                    location=source.location,
                    status=status,
                    records_extracted=len(extracted),
                    error=error,
                )
            )
            logger.info("Source '%s' produced %d records", source.name, len(extracted))
        except Exception as error:  # noqa: BLE001
            status_entries.append(
                SourceStatus(
                    name=source.name,
                    kind=source.kind,
                    location=source.location,
                    status="error",
                    records_extracted=0,
                    error=str(error),
                )
            )
            logger.warning("Source '%s' failed: %s", source.name, error)

    result = analyze_pricing(project, records, status_entries)
    artifact_paths: OutputArtifacts = write_outputs(result, output_dir)
    artifacts = RunArtifacts(
        run_dir=artifact_paths.run_dir,
        report_path=artifact_paths.report_path,
        analysis_path=artifact_paths.analysis_path,
        comps_path=artifact_paths.comps_path,
    )
    logger.info("Analysis complete: %s", artifacts.report_path)
    return result, artifacts