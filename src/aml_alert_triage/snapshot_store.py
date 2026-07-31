"""Immutable per-alert evidence/insight snapshot store, backed by DynamoDB.

Persisted separately from the live Neo4j graph so an alert investigation
report can always show "why this was flagged" as it looked at the moment
the alert was created, even if the graph changes later. See design.md
(decision 10) for the rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json

from .config import AppConfig
from .models import EvidenceItem, RiskAssessment


@dataclass(slots=True)
class AlertSnapshot:
    alert_id: str
    customer_id: str
    reason: str
    description: str
    evidence: list[EvidenceItem]
    risk: RiskAssessment
    insight_mode: str  # "static" | "anthropic" | "openai"
    insight_summary: str
    insight_key_observations: list[str] = field(default_factory=list)
    alert_reason: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


def _evidence_to_item(evidence: EvidenceItem) -> dict[str, str]:
    return {"kind": evidence.kind, "subject": evidence.subject, "details": evidence.details, "source": evidence.source}


def _item_to_evidence(item: dict[str, object]) -> EvidenceItem:
    return EvidenceItem(
        kind=str(item["kind"]), subject=str(item["subject"]), details=str(item["details"]), source=str(item["source"])
    )


@dataclass(slots=True)
class AlertSnapshotStore:
    """Lazy `boto3` DynamoDB client, mirroring the lazy-driver pattern used
    by `Neo4jAlertRepository` and the LLM adapters elsewhere in this
    project. A client can be injected for testing."""

    config: AppConfig
    client: object | None = None

    def _get_client(self) -> object:
        if self.client is not None:
            return self.client

        import boto3

        self.client = boto3.client(
            "dynamodb",
            endpoint_url=self.config.dynamodb_endpoint_url,
            region_name=self.config.dynamodb_region,
            aws_access_key_id="local",
            aws_secret_access_key="local",
        )
        return self.client

    def ensure_table(self) -> None:
        client = self._get_client()
        existing = client.list_tables().get("TableNames", [])
        if self.config.dynamodb_table_name in existing:
            return

        client.create_table(
            TableName=self.config.dynamodb_table_name,
            KeySchema=[{"AttributeName": "alert_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "alert_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        waiter = client.get_waiter("table_exists")
        waiter.wait(TableName=self.config.dynamodb_table_name)

    def save_snapshot(self, snapshot: AlertSnapshot) -> None:
        client = self._get_client()
        item = {
            "alert_id": {"S": snapshot.alert_id},
            "customer_id": {"S": snapshot.customer_id},
            "reason": {"S": snapshot.reason},
            "description": {"S": snapshot.description},
            "insight_mode": {"S": snapshot.insight_mode},
            "insight_summary": {"S": snapshot.insight_summary},
            "insight_key_observations": {"L": [{"S": obs} for obs in snapshot.insight_key_observations]},
            "alert_reason": {"S": snapshot.alert_reason},
            "created_at": {"S": snapshot.created_at},
            "risk_level": {"S": snapshot.risk.level},
            "risk_rationale": {"S": snapshot.risk.rationale},
            "risk_typologies": {"L": [{"S": t} for t in snapshot.risk.typologies]},
            "evidence": {
                "L": [
                    {
                        "M": {
                            "kind": {"S": item["kind"]},
                            "subject": {"S": item["subject"]},
                            "details": {"S": item["details"]},
                            "source": {"S": item["source"]},
                        }
                    }
                    for item in (_evidence_to_item(e) for e in snapshot.evidence)
                ]
            },
        }
        client.put_item(TableName=self.config.dynamodb_table_name, Item=item)

    def load_seed_file(self, seed_file: Path) -> int:
        """Loads snapshots for pre-registered alerts (see
        scripts/generate_dataset.py) that were never created via
        `register_alert`, so `--report-alert-id` works for them too."""
        payload = json.loads(seed_file.read_text(encoding="utf-8"))
        for entry in payload:
            self.save_snapshot(
                AlertSnapshot(
                    alert_id=entry["alert_id"],
                    customer_id=entry["customer_id"],
                    reason=entry["reason"],
                    description=entry["description"],
                    evidence=[_item_to_evidence(item) for item in entry["evidence"]],
                    risk=RiskAssessment(**entry["risk"]),
                    insight_mode=entry["insight_mode"],
                    insight_summary=entry["insight_summary"],
                    insight_key_observations=list(entry["insight_key_observations"]),
                    alert_reason=entry["alert_reason"],
                    created_at=entry["created_at"],
                )
            )
        return len(payload)

    def get_snapshot(self, alert_id: str) -> AlertSnapshot | None:
        client = self._get_client()
        response = client.get_item(TableName=self.config.dynamodb_table_name, Key={"alert_id": {"S": alert_id}})
        item = response.get("Item")
        if item is None:
            return None

        evidence = [
            _item_to_evidence({k: v["S"] for k, v in entry["M"].items()}) for entry in item["evidence"]["L"]
        ]
        risk = RiskAssessment(
            level=item["risk_level"]["S"],
            rationale=item["risk_rationale"]["S"],
            typologies=[t["S"] for t in item["risk_typologies"]["L"]],
        )
        return AlertSnapshot(
            alert_id=item["alert_id"]["S"],
            customer_id=item["customer_id"]["S"],
            reason=item["reason"]["S"],
            description=item["description"]["S"],
            evidence=evidence,
            risk=risk,
            insight_mode=item["insight_mode"]["S"],
            insight_summary=item["insight_summary"]["S"],
            insight_key_observations=[o["S"] for o in item["insight_key_observations"]["L"]],
            alert_reason=item["alert_reason"]["S"],
            created_at=item["created_at"]["S"],
        )
