from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .config import AppConfig
from .repository import Neo4jAlertRepository
from .sample_data import SAMPLE_ALERTS
from .workflow import run_triage

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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = AppConfig.from_env()
    repository = Neo4jAlertRepository(config=config)

    if args.check_neo4j:
        repository.verify_connection()
        print(json.dumps({"neo4j": "ok", "connection": repository.describe_connection()}, indent=2))
        return

    if args.seed_neo4j:
        loaded = repository.load_seed_file(Path(args.seed_file))
        print(json.dumps({"seed_file": args.seed_file, "statements_executed": loaded}, indent=2))
        return

    alert = SAMPLE_ALERTS["alert-001"]
    state = run_triage(alert, repository)
    print(json.dumps({
        "alert_id": state.alert.alert_id,
        "status": state.investigation_status,
        "disposition": state.recommendation.disposition if state.recommendation else None,
        "rationale": state.recommendation.rationale if state.recommendation else None,
        "evidence_count": len(state.evidence),
    }, indent=2))


if __name__ == "__main__":
    main()
