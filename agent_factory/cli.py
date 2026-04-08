"""Command-line interface for the agent factory system."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .factory_agent import AgentFactory
from .schemas import AgentBlueprint


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-factory",
        description="Create and run machine-learning specialist agents.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser(
        "create-agent",
        help="Train and create a new specialist agent from a dataset and topic docs.",
    )
    create_parser.add_argument("--name", required=True, help="Agent name.")
    create_parser.add_argument("--description", required=True, help="Agent purpose.")
    create_parser.add_argument("--topic", required=True, help="Knowledge topic.")
    create_parser.add_argument(
        "--task-type",
        required=True,
        choices=["classification", "regression"],
        help="Task model type.",
    )
    create_parser.add_argument("--dataset", required=True, help="CSV training dataset path.")
    create_parser.add_argument(
        "--knowledge",
        required=True,
        nargs="+",
        help="One or more knowledge file/folder paths.",
    )
    create_parser.add_argument("--input-column", default="input", help="Input column name.")
    create_parser.add_argument("--target-column", default="target", help="Target column name.")
    create_parser.add_argument(
        "--output-dir",
        default="generated_agents",
        help="Folder where generated agents are stored.",
    )

    predict_parser = subparsers.add_parser("predict", help="Run a specialist agent task prediction.")
    predict_parser.add_argument("--agent-dir", required=True, help="Generated agent directory path.")
    predict_parser.add_argument("--input", required=True, help="Task input text.")

    ask_parser = subparsers.add_parser("ask", help="Ask a specialist agent a topic question.")
    ask_parser.add_argument("--agent-dir", required=True, help="Generated agent directory path.")
    ask_parser.add_argument("--question", required=True, help="Question text.")
    ask_parser.add_argument("--top-k", type=int, default=3, help="How many knowledge excerpts to return.")

    describe_parser = subparsers.add_parser("describe", help="Show metadata for a generated agent.")
    describe_parser.add_argument("--agent-dir", required=True, help="Generated agent directory path.")

    list_parser = subparsers.add_parser("list", help="List registered generated agents.")
    list_parser.add_argument(
        "--output-dir",
        default="generated_agents",
        help="Folder where generated agents are stored.",
    )

    return parser


def _handle_create(args: argparse.Namespace) -> None:
    blueprint = AgentBlueprint(
        name=args.name,
        description=args.description,
        topic=args.topic,
        task_type=args.task_type,
        input_column=args.input_column,
        target_column=args.target_column,
    )
    factory = AgentFactory(output_root=args.output_dir)
    agent_dir = factory.create_specialist_agent(
        blueprint=blueprint,
        dataset_path=Path(args.dataset),
        knowledge_paths=[Path(path) for path in args.knowledge],
    )
    specialist = factory.load_specialist_agent(agent_dir)
    print(
        json.dumps(
            {
                "created_agent_dir": str(agent_dir.resolve()),
                "blueprint": specialist.describe()["blueprint"],
                "training": specialist.describe()["training"],
            },
            indent=2,
        )
    )


def _handle_predict(args: argparse.Namespace) -> None:
    specialist = AgentFactory().load_specialist_agent(Path(args.agent_dir))
    result = specialist.predict(args.input)
    print(json.dumps(result, indent=2))


def _handle_ask(args: argparse.Namespace) -> None:
    specialist = AgentFactory().load_specialist_agent(Path(args.agent_dir))
    result = specialist.ask_topic_question(args.question, top_k=args.top_k)
    print(json.dumps(result, indent=2))


def _handle_describe(args: argparse.Namespace) -> None:
    specialist = AgentFactory().load_specialist_agent(Path(args.agent_dir))
    print(json.dumps(specialist.describe(), indent=2))


def _handle_list(args: argparse.Namespace) -> None:
    factory = AgentFactory(output_root=args.output_dir)
    print(json.dumps(factory.list_registered_agents(), indent=2))


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "create-agent":
        _handle_create(args)
    elif args.command == "predict":
        _handle_predict(args)
    elif args.command == "ask":
        _handle_ask(args)
    elif args.command == "describe":
        _handle_describe(args)
    elif args.command == "list":
        _handle_list(args)
    else:
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
