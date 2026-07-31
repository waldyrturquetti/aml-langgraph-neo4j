import json
from pathlib import Path

from aml_alert_triage.config import AppConfig
from aml_alert_triage.models import EvidenceItem, RiskAssessment
from aml_alert_triage.snapshot_store import AlertSnapshot, AlertSnapshotStore


class _FakeWaiter:
    def wait(self, **kwargs) -> None:
        pass


class _FakeDynamoClient:
    def __init__(self) -> None:
        self.tables: set[str] = set()
        self.items: dict[str, dict] = {}
        self.create_table_calls = 0

    def list_tables(self) -> dict:
        return {"TableNames": sorted(self.tables)}

    def create_table(self, TableName: str, **kwargs) -> None:
        self.create_table_calls += 1
        self.tables.add(TableName)

    def get_waiter(self, name: str) -> _FakeWaiter:
        return _FakeWaiter()

    def put_item(self, TableName: str, Item: dict) -> None:
        self.items[Item["alert_id"]["S"]] = Item

    def get_item(self, TableName: str, Key: dict) -> dict:
        item = self.items.get(Key["alert_id"]["S"])
        return {"Item": item} if item is not None else {}


def _make_snapshot(alert_id: str = "alert-auto-cust-214") -> AlertSnapshot:
    return AlertSnapshot(
        alert_id=alert_id,
        customer_id="cust-214",
        reason="structuring-fanin-detected",
        description="Five distinct incoming transfers.",
        evidence=[EvidenceItem(kind="structuring-fanin", subject="cust-214", details="5 sources.", source="neo4j")],
        risk=RiskAssessment(level="high", rationale="Structural pattern detected.", typologies=["structuring-fanin"]),
        insight_mode="static",
        insight_summary="High risk pattern found.",
        insight_key_observations=["5 distinct sources converged."],
        alert_reason="Structuring fan-in detected.",
        created_at="2026-07-30T00:00:00+00:00",
    )


def test_ensure_table_creates_when_missing() -> None:
    client = _FakeDynamoClient()
    store = AlertSnapshotStore(config=AppConfig(), client=client)

    store.ensure_table()

    assert client.create_table_calls == 1
    assert AppConfig().dynamodb_table_name in client.tables


def test_ensure_table_skips_when_already_present() -> None:
    client = _FakeDynamoClient()
    client.tables.add(AppConfig().dynamodb_table_name)
    store = AlertSnapshotStore(config=AppConfig(), client=client)

    store.ensure_table()

    assert client.create_table_calls == 0


def test_save_and_get_snapshot_round_trip() -> None:
    client = _FakeDynamoClient()
    store = AlertSnapshotStore(config=AppConfig(), client=client)
    snapshot = _make_snapshot()

    store.save_snapshot(snapshot)
    loaded = store.get_snapshot(snapshot.alert_id)

    assert loaded is not None
    assert loaded.alert_id == snapshot.alert_id
    assert loaded.customer_id == snapshot.customer_id
    assert loaded.risk.level == "high"
    assert loaded.risk.typologies == ["structuring-fanin"]
    assert loaded.evidence[0].kind == "structuring-fanin"
    assert loaded.insight_key_observations == snapshot.insight_key_observations


def test_get_snapshot_returns_none_when_absent() -> None:
    client = _FakeDynamoClient()
    store = AlertSnapshotStore(config=AppConfig(), client=client)

    assert store.get_snapshot("does-not-exist") is None


def test_load_seed_file_loads_all_snapshots(tmp_path: Path) -> None:
    client = _FakeDynamoClient()
    store = AlertSnapshotStore(config=AppConfig(), client=client)

    seed_file = tmp_path / "seed.json"
    seed_file.write_text(
        json.dumps(
            [
                {
                    "alert_id": "alert-auto-cust-200",
                    "customer_id": "cust-200",
                    "reason": "cycle-detected",
                    "description": "desc",
                    "evidence": [{"kind": "cycle", "subject": "cust-200", "details": "d", "source": "neo4j"}],
                    "risk": {"level": "high", "rationale": "r", "typologies": ["cycle"]},
                    "insight_mode": "static",
                    "insight_summary": "s",
                    "insight_key_observations": ["o"],
                    "alert_reason": "ar",
                    "created_at": "2026-07-30T00:00:00+00:00",
                }
            ]
        ),
        encoding="utf-8",
    )

    loaded_count = store.load_seed_file(seed_file)

    assert loaded_count == 1
    assert store.get_snapshot("alert-auto-cust-200") is not None
