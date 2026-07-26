from __future__ import annotations

import json
import logging

from .config import AppConfig
from .repository import Neo4jAlertRepository
from .sample_data import SAMPLE_ALERTS
from .workflow import run_triage

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def main() -> None:
    config = AppConfig.from_env()
    repository = Neo4jAlertRepository(config=config)
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
