"""Bootstrap script to create the three requested specialist agents."""
from __future__ import annotations

import json
from pathlib import Path

from .factory_agent import AgentFactory
from .schemas import AgentBlueprint


def create_requested_agents(output_dir: Path | str = "generated_agents") -> list[dict]:
    root = Path(__file__).resolve().parent
    factory = AgentFactory(output_root=output_dir)

    requests = [
        {
            "blueprint": AgentBlueprint(
                name="OutlookEmailManager",
                description="Manages Outlook email workflows: triage, routing, drafting, and follow-ups.",
                topic="Outlook Email Operations",
                task_type="classification",
            ),
            "dataset": root / "examples" / "outlook_email_manager" / "training.csv",
            "knowledge": [root / "examples" / "outlook_email_manager" / "knowledge"],
        },
        {
            "blueprint": AgentBlueprint(
                name="LandDealUnderwriter",
                description="Uses proforma-style logic to underwrite land acquisition deals and estimate max offer price.",
                topic="Land Acquisition Underwriting",
                task_type="regression",
            ),
            "dataset": root / "examples" / "land_underwriter" / "training.csv",
            "knowledge": [root / "examples" / "land_underwriter" / "knowledge"],
        },
        {
            "blueprint": AgentBlueprint(
                name="HousingMarketResearcher",
                description="Researches housing markets and classifies market momentum conditions.",
                topic="Housing Market Research",
                task_type="classification",
            ),
            "dataset": root / "examples" / "housing_market_researcher" / "training.csv",
            "knowledge": [root / "examples" / "housing_market_researcher" / "knowledge"],
        },
    ]

    created = []
    for item in requests:
        agent_dir = factory.create_specialist_agent(
            blueprint=item["blueprint"],
            dataset_path=item["dataset"],
            knowledge_paths=item["knowledge"],
        )
        specialist = factory.load_specialist_agent(agent_dir)
        metadata = specialist.describe()
        created.append(
            {
                "name": metadata["blueprint"]["name"],
                "topic": metadata["blueprint"]["topic"],
                "task_type": metadata["blueprint"]["task_type"],
                "agent_dir": str(agent_dir.resolve()),
                "metric_name": metadata["training"]["metric_name"],
                "metric_value": metadata["training"]["metric_value"],
            }
        )
    return created


def main() -> None:
    created = create_requested_agents()
    print(json.dumps(created, indent=2))


if __name__ == "__main__":
    main()
