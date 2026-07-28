from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .config import AppConfig
from .llm import create_llm_adapter
from .models import TriageState
from .repository import Neo4jAlertRepository
from .sample_data import SAMPLE_ALERTS
from .workflow import build_langgraph, build_triage_response, run_triage, state_from_mapping

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AML triage demo tasks.")
    parser.add_argument(
        "--check-neo4j",
        action="store_true",
        help="Verify connectivity to the configured Neo4j instance.",
    )
    parser.add_argument(
        "--seed-neo4j",
        action="store_true",
        help="Load fictional seed graph data into the configured Neo4j instance.",
    )
    parser.add_argument(
        "--seed-file",
        default="data/neo4j/seed.cypher",
        help="Path to the Cypher seed file used with --seed-neo4j.",
    )
    parser.add_argument(
        "--prompt",
        default="Review this fictional AML alert and provide concise investigation insights.",
        help="User prompt context passed into the triage strategy.",
    )
    parser.add_argument(
        "--alert-id",
        default="alert-001",
        choices=sorted(SAMPLE_ALERTS),
        help="Which fictional sample alert/typology to triage.",
    )
    parser.add_argument(
        "--use-langgraph",
        action="store_true",
        help="Run the workflow as a compiled LangGraph graph (with retry loop and human-review "
        "interrupt) instead of the plain linear call chain.",
    )
    parser.add_argument(
        "--thread-id",
        default=None,
        help="Checkpoint thread id for the LangGraph run. Defaults to the alert id.",
    )
    parser.add_argument(
        "--analyst-decision",
        default=None,
        help="Decision to resume with if the run pauses for human review, e.g. "
        "'confirm-escalation' or 'reject-escalation'. Also used as the linear-path "
        "human review outcome when set.",
    )
    return parser.parse_args()


def _run_linear(alert, repository, llm_adapter, config: AppConfig, args: argparse.Namespace) -> None:
    human_review_callback = (lambda state: args.analyst_decision) if args.analyst_decision else None
    state = run_triage(
        alert,
        repository,
        llm_adapter=llm_adapter,
        config=config,
        user_prompt=args.prompt,
        human_review_callback=human_review_callback,
    )
    print(json.dumps(build_triage_response(state), indent=2))


def _run_langgraph(alert, repository, llm_adapter, config: AppConfig, args: argparse.Namespace) -> None:
    graph = build_langgraph(repository, llm_adapter, config)
    if graph is None:
        print(json.dumps({"error": "LangGraph is not installed; run `pip install -e .`."}, indent=2))
        return

    from langgraph.types import Command

    thread_id = args.thread_id or alert.alert_id
    thread_config = {"configurable": {"thread_id": thread_id}}

    result = graph.invoke(TriageState(alert=alert, user_prompt=args.prompt), config=thread_config)

    if "__interrupt__" in result:
        interrupt_payload = [item.value for item in result["__interrupt__"]]
        print(json.dumps({"paused": True, "thread_id": thread_id, "interrupt": interrupt_payload}, indent=2))

        if args.analyst_decision:
            resumed = graph.invoke(Command(resume=args.analyst_decision), config=thread_config)
            print(json.dumps(build_triage_response(state_from_mapping(resumed)), indent=2))
        else:
            print(
                "\nRun paused for analyst review. Resume it (same process) with, for example:\n"
                f"  python -m aml_alert_triage.main --use-langgraph --alert-id {alert.alert_id} "
                f"--thread-id {thread_id} --analyst-decision confirm-escalation\n"
                "\nNote: the built-in checkpointer is in-memory only, so resuming only works "
                "within the same process/run - a durable checkpointer (e.g. SqliteSaver) would "
                "be needed to resume across separate CLI invocations."
            )
        return

    print(json.dumps(build_triage_response(state_from_mapping(result)), indent=2))


def main() -> None:
    args = parse_args()
    config = AppConfig.from_env()
    repository = Neo4jAlertRepository(config=config)
    llm_adapter = create_llm_adapter(config)

    if args.check_neo4j:
        repository.verify_connection()
        print(json.dumps({"neo4j": "ok", "connection": repository.describe_connection()}, indent=2))
        return

    if args.seed_neo4j:
        loaded = repository.load_seed_file(Path(args.seed_file))
        print(json.dumps({"seed_file": args.seed_file, "statements_executed": loaded}, indent=2))
        return

    alert = SAMPLE_ALERTS[args.alert_id]

    if args.use_langgraph:
        _run_langgraph(alert, repository, llm_adapter, config, args)
    else:
        _run_linear(alert, repository, llm_adapter, config, args)


if __name__ == "__main__":
    main()
