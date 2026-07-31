from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .config import AppConfig
from .llm import create_llm_adapter
from .models import TriageState
from .report import generate_alert_report
from .repository import Neo4jAlertRepository
from .snapshot_store import AlertSnapshotStore
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
        "--check-dynamodb",
        action="store_true",
        help="Verify connectivity to the configured DynamoDB (Local) instance and ensure the snapshot table exists.",
    )
    parser.add_argument(
        "--seed-dynamodb",
        action="store_true",
        help="Load alert snapshots for the pre-registered fictional alerts into DynamoDB.",
    )
    parser.add_argument(
        "--dynamodb-seed-file",
        default="data/dynamodb/seed.json",
        help="Path to the snapshot seed file used with --seed-dynamodb.",
    )
    parser.add_argument(
        "--prompt",
        default="Review this fictional customer and provide concise investigation insights.",
        help="User prompt context passed into the triage strategy.",
    )
    parser.add_argument(
        "--customer-id",
        default="cust-100",
        help="Which fictional customer to investigate (owns the accounts/transactions to enrich from Neo4j).",
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
        help="Checkpoint thread id for the LangGraph run. Defaults to the customer id.",
    )
    parser.add_argument(
        "--analyst-decision",
        default=None,
        help="Decision to resume with if the run pauses for human review, e.g. "
        "'confirm-escalation' or 'reject-escalation'. Also used as the linear-path "
        "human review outcome when set.",
    )
    parser.add_argument(
        "--report-alert-id",
        default=None,
        help="Generate a Markdown investigation report for this alert id from its persisted "
        "DynamoDB snapshot, instead of running a triage investigation.",
    )
    parser.add_argument(
        "--report-output",
        default=None,
        help="Output path for --report-alert-id. Defaults to reports/<alert_id>.md.",
    )
    return parser.parse_args()


def _run_linear(
    customer_id: str,
    repository: Neo4jAlertRepository,
    llm_adapter,
    config: AppConfig,
    snapshot_store: AlertSnapshotStore,
    args: argparse.Namespace,
) -> None:
    human_review_callback = (lambda state: args.analyst_decision) if args.analyst_decision else None
    state = run_triage(
        customer_id,
        repository,
        llm_adapter=llm_adapter,
        config=config,
        user_prompt=args.prompt,
        human_review_callback=human_review_callback,
        snapshot_store=snapshot_store,
    )
    print(json.dumps(build_triage_response(state), indent=2))


def _run_langgraph(
    customer_id: str,
    repository: Neo4jAlertRepository,
    llm_adapter,
    config: AppConfig,
    snapshot_store: AlertSnapshotStore,
    args: argparse.Namespace,
) -> None:
    graph = build_langgraph(repository, llm_adapter, config, snapshot_store)
    if graph is None:
        print(json.dumps({"error": "LangGraph is not installed; run `pip install -e .`."}, indent=2))
        return

    from langgraph.types import Command

    thread_id = args.thread_id or customer_id
    thread_config = {"configurable": {"thread_id": thread_id}}

    result = graph.invoke(TriageState(customer_id=customer_id, user_prompt=args.prompt), config=thread_config)

    if "__interrupt__" in result:
        interrupt_payload = [item.value for item in result["__interrupt__"]]
        print(json.dumps({"paused": True, "thread_id": thread_id, "interrupt": interrupt_payload}, indent=2))

        if args.analyst_decision:
            resumed = graph.invoke(Command(resume=args.analyst_decision), config=thread_config)
            print(json.dumps(build_triage_response(state_from_mapping(resumed)), indent=2))
        else:
            print(
                "\nRun paused for analyst review. Resume it (same process) with, for example:\n"
                f"  python -m aml_alert_triage.main --use-langgraph --customer-id {customer_id} "
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

    if args.check_neo4j:
        repository = Neo4jAlertRepository(config=config)
        repository.verify_connection()
        print(json.dumps({"neo4j": "ok", "connection": repository.describe_connection()}, indent=2))
        return

    if args.seed_neo4j:
        repository = Neo4jAlertRepository(config=config)
        loaded = repository.load_seed_file(Path(args.seed_file))
        print(json.dumps({"seed_file": args.seed_file, "statements_executed": loaded}, indent=2))
        return

    if args.check_dynamodb:
        snapshot_store = AlertSnapshotStore(config=config)
        snapshot_store.ensure_table()
        print(json.dumps({"dynamodb": "ok", "table": config.dynamodb_table_name}, indent=2))
        return

    if args.seed_dynamodb:
        snapshot_store = AlertSnapshotStore(config=config)
        snapshot_store.ensure_table()
        loaded = snapshot_store.load_seed_file(Path(args.dynamodb_seed_file))
        print(json.dumps({"seed_file": args.dynamodb_seed_file, "snapshots_loaded": loaded}, indent=2))
        return

    if args.report_alert_id:
        snapshot_store = AlertSnapshotStore(config=config)
        output_path = Path(args.report_output) if args.report_output else None
        report_path = generate_alert_report(args.report_alert_id, snapshot_store, output_path)
        print(json.dumps({"alert_id": args.report_alert_id, "report_path": str(report_path)}, indent=2))
        return

    repository = Neo4jAlertRepository(config=config)
    llm_adapter = create_llm_adapter(config)
    snapshot_store = AlertSnapshotStore(config=config)

    if args.use_langgraph:
        _run_langgraph(args.customer_id, repository, llm_adapter, config, snapshot_store, args)
    else:
        _run_linear(args.customer_id, repository, llm_adapter, config, snapshot_store, args)


if __name__ == "__main__":
    main()
