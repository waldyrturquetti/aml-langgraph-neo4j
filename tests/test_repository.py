from pathlib import Path

import pytest

from aml_alert_triage.config import AppConfig
from aml_alert_triage.repository import Neo4jAlertRepository


class _FakeResult:
    def __init__(self, records: list[dict[str, object]] | None = None, single_row: dict[str, object] | None = None):
        self._records = records or []
        self._single_row = single_row

    def __iter__(self):
        return iter(self._records)

    def single(self):
        return self._single_row


class _FakeSession:
    def __init__(self, run_handler):
        self._run_handler = run_handler

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def run(self, query: str, **params):
        return self._run_handler(query, **params)


class _FakeDriver:
    def __init__(self, run_handler):
        self._run_handler = run_handler
        self.closed = False

    def session(self, database: str):
        return _FakeSession(self._run_handler)

    def close(self):
        self.closed = True


def test_fetch_evidence_from_neo4j_matches_expected_shape() -> None:
    records = [
        {
            "kind": "transaction",
            "subject": "acct-001",
            "details": "Five deposits over three days",
            "source": "neo4j",
        }
    ]

    def run_handler(query: str, **params):
        assert "MATCH" in query
        assert params["customer_id"] == "cust-100"
        return _FakeResult(records=records)

    repository = Neo4jAlertRepository(config=AppConfig(), driver=_FakeDriver(run_handler))

    evidence = repository.fetch_evidence("cust-100", limit=5)

    assert len(evidence) == 1
    assert evidence[0].kind == "transaction"
    assert evidence[0].subject == "acct-001"
    assert evidence[0].details == "Five deposits over three days"
    assert evidence[0].source == "neo4j"


def test_fetch_evidence_raises_value_error_for_invalid_record_shape() -> None:
    records = [{"kind": "transaction", "subject": "acct-001", "source": "neo4j"}]

    def run_handler(query: str, **params):
        return _FakeResult(records=records)

    repository = Neo4jAlertRepository(config=AppConfig(), driver=_FakeDriver(run_handler))

    # fetch_evidence falls back to offline data on errors; call mapper directly to enforce shape contract.
    with pytest.raises(ValueError):
        repository._record_to_evidence_item(records[0])


def test_verify_connection_succeeds_with_expected_response() -> None:
    def run_handler(query: str, **params):
        assert "RETURN 1 AS ok" in query
        return _FakeResult(single_row={"ok": 1})

    repository = Neo4jAlertRepository(config=AppConfig(), driver=_FakeDriver(run_handler))

    repository.verify_connection()


def test_verify_connection_fails_when_driver_is_missing() -> None:
    repository = Neo4jAlertRepository(config=AppConfig(), driver=None)

    with pytest.raises(RuntimeError, match="driver is not available"):
        repository.verify_connection()


def test_load_seed_file_executes_all_statements(tmp_path: Path) -> None:
    executed: list[str] = []

    def run_handler(query: str, **params):
        executed.append(query.strip())
        return _FakeResult()

    seed_file = tmp_path / "seed.cypher"
    seed_file.write_text("MERGE (:X {id: 1});\nMERGE (:Y {id: 2});\n", encoding="utf-8")

    repository = Neo4jAlertRepository(config=AppConfig(), driver=_FakeDriver(run_handler))

    count = repository.load_seed_file(seed_file)

    assert count == 2
    assert len(executed) == 2
    assert executed[0].startswith("MERGE")


def test_app_config_from_env_uses_concrete_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_MAX_HOPS", raising=False)
    monkeypatch.delenv("AML_ALERT_EVIDENCE_LIMIT", raising=False)
    monkeypatch.delenv("AML_ALERT_LLM_ENABLED", raising=False)
    monkeypatch.delenv("AML_ALERT_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("AML_ALERT_LLM_MODEL", raising=False)

    config = AppConfig.from_env()

    assert config.neo4j_uri == "bolt://localhost:7687"
    assert config.neo4j_max_hops == 2
    assert config.evidence_limit == 10
    assert config.llm_enabled is False
    assert config.llm_provider == "rule-based"
    assert config.llm_model == "local-insight-summarizer"


def test_app_config_from_env_reads_llm_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AML_ALERT_LLM_ENABLED", "true")
    monkeypatch.setenv("AML_ALERT_LLM_PROVIDER", "demo-provider")
    monkeypatch.setenv("AML_ALERT_LLM_MODEL", "demo-model")
    monkeypatch.setenv("AML_ALERT_LLM_TIMEOUT_SECONDS", "30")

    config = AppConfig.from_env()

    assert config.llm_enabled is True
    assert config.llm_provider == "demo-provider"
    assert config.llm_model == "demo-model"
    assert config.llm_timeout_seconds == 30
