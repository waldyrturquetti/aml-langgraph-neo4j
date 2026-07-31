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


def _account_ids_response(account_id: str) -> _FakeResult:
    return _FakeResult(records=[{"account_id": account_id}])


def test_fetch_evidence_from_neo4j_matches_expected_shape() -> None:
    def run_handler(query: str, **params):
        if "RETURN account.account_id AS account_id" in query:
            assert params["customer_id"] == "cust-100"
            return _account_ids_response("acct-100")
        if "b.account_id AS counterparty" in query:
            assert params["frontier"] == ["acct-100"]
            return _FakeResult(
                records=[
                    {"counterparty": "acct-108", "channel": "pix", "amount": 640.0, "currency": "BRL", "direction": "to"}
                ]
            )
        return _FakeResult(records=[], single_row=None)

    repository = Neo4jAlertRepository(config=AppConfig(), driver=_FakeDriver(run_handler))

    evidence = repository.fetch_evidence("cust-100", limit=5, hop_radius=1)

    assert len(evidence) == 1
    assert evidence[0].kind == "pix"
    assert evidence[0].subject == "acct-108"
    assert evidence[0].details == "PIX transfer of 640.00 BRL to acct-108."
    assert evidence[0].source == "neo4j"


def test_fetch_evidence_raises_value_error_for_invalid_record_shape() -> None:
    record = {"channel": "pix", "subject": "acct-001", "source": "neo4j"}  # missing amount/currency/counterparty/direction

    repository = Neo4jAlertRepository(config=AppConfig(), driver=_FakeDriver(lambda query, **params: _FakeResult()))

    with pytest.raises(ValueError):
        repository._record_to_transaction_evidence(record)


def test_verify_connection_succeeds_with_expected_response() -> None:
    def run_handler(query: str, **params):
        assert "RETURN 1 AS ok" in query
        return _FakeResult(single_row={"ok": 1})

    repository = Neo4jAlertRepository(config=AppConfig(), driver=_FakeDriver(run_handler))

    repository.verify_connection()


def test_verify_connection_fails_when_driver_is_missing() -> None:
    # force_offline guarantees no driver is created even if a real Neo4j
    # instance happens to be reachable in the local environment.
    repository = Neo4jAlertRepository.offline(config=AppConfig())

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


def test_load_seed_file_tolerates_semicolons_inside_string_literals(tmp_path: Path) -> None:
    # A naive `text.split(";")` breaks the moment any property value in the
    # seed contains a semicolon - this regression-tests the quote-aware
    # statement splitter against exactly that case.
    executed: list[str] = []

    def run_handler(query: str, **params):
        executed.append(query.strip())
        return _FakeResult()

    seed_file = tmp_path / "seed.cypher"
    seed_file.write_text(
        "// a comment; with a semicolon too\n"
        "MERGE (:Alert {description: 'Multiple transfers; review needed.'});\n"
        "MERGE (:Y {id: 2});\n",
        encoding="utf-8",
    )

    repository = Neo4jAlertRepository(config=AppConfig(), driver=_FakeDriver(run_handler))

    count = repository.load_seed_file(seed_file)

    assert count == 2
    assert "Multiple transfers; review needed." in executed[0]


def test_fetch_evidence_offline_merges_evidence_up_to_hop_radius() -> None:
    # cust-100 has exactly one direct (hop-1) transaction; widening to hop-2
    # pulls in that counterparty's other activity too.
    repository = Neo4jAlertRepository.offline(AppConfig())

    thin = repository.fetch_evidence("cust-100", hop_radius=1)
    widened = repository.fetch_evidence("cust-100", hop_radius=2)

    assert len(thin) == 1
    assert len(widened) > len(thin)
    assert thin[0] in widened

    # Regression: hop-2 items must describe the pivot's *other* counterparty,
    # not the pivot account itself repeated for every item, nor a bounce
    # back to the original account.
    hop2_items = [item for item in widened if item not in thin]
    assert hop2_items
    hop2_subjects = {item.subject for item in hop2_items}
    assert "acct-100" not in hop2_subjects


def test_fetch_cycle_evidence_reports_detected_cycle() -> None:
    def run_handler(query: str, **params):
        if "TRANSFERRED_TO*2.." in query:
            return _FakeResult(single_row={"hops": 4})
        if "RETURN account.account_id AS account_id" in query:
            return _account_ids_response("acct-300")
        return _FakeResult(records=[], single_row=None)

    repository = Neo4jAlertRepository(config=AppConfig(), driver=_FakeDriver(run_handler))

    evidence = repository.fetch_evidence("cust-300")

    cycle_items = [item for item in evidence if item.kind == "cycle"]
    assert len(cycle_items) == 1
    assert "4 hop" in cycle_items[0].details


def test_fetch_structuring_evidence_reports_fanout_and_fanin() -> None:
    def run_handler(query: str, **params):
        if "TRANSFERRED_TO]->(counterparty)" in query:
            return _FakeResult(single_row={"counterparties": 6, "sample": ["acct-401", "acct-402"]})
        if "<-[:TRANSFERRED_TO]-(counterparty)" in query:
            return _FakeResult(single_row={"counterparties": 5, "sample": ["acct-601", "acct-602"]})
        if "RETURN account.account_id AS account_id" in query:
            return _account_ids_response("acct-400")
        return _FakeResult(records=[], single_row=None)

    repository = Neo4jAlertRepository(config=AppConfig(), driver=_FakeDriver(run_handler))

    evidence = repository.fetch_evidence("cust-400")

    kinds = {item.kind for item in evidence}
    assert "structuring-fanout" in kinds
    assert "structuring-fanin" in kinds


def test_fetch_alert_proximity_evidence_reports_linked_customer() -> None:
    def run_handler(query: str, **params):
        if "TRANSFERRED_TO*1.." in query:
            assert params["customer_id"] == "cust-129"
            return _FakeResult(
                records=[{"linked_customer_id": "cust-200", "linked_alert_id": "alert-auto-cust-200", "hops": 2}]
            )
        if "RETURN account.account_id AS account_id" in query:
            return _account_ids_response("acct-129")
        return _FakeResult(records=[], single_row=None)

    repository = Neo4jAlertRepository(config=AppConfig(), driver=_FakeDriver(run_handler))

    evidence = repository.fetch_evidence("cust-129")

    proximity_items = [item for item in evidence if item.kind == "alert-proximity"]
    assert len(proximity_items) == 1
    assert "cust-200" in proximity_items[0].details
    assert "2 hop" in proximity_items[0].details


def test_fetch_evidence_hop_query_widens_frontier_when_hop_radius_increases() -> None:
    queries_seen: list[tuple[str, list[str]]] = []

    def run_handler(query: str, **params):
        if "RETURN account.account_id AS account_id" in query:
            return _account_ids_response("acct-100")
        if "b.account_id AS counterparty" in query:
            queries_seen.append((query, params["frontier"]))
            if params["frontier"] == ["acct-100"]:
                return _FakeResult(
                    records=[
                        {"counterparty": "acct-108", "channel": "pix", "amount": 100.0, "currency": "BRL", "direction": "to"}
                    ]
                )
            return _FakeResult(records=[])
        return _FakeResult(records=[], single_row=None)

    repository = Neo4jAlertRepository(config=AppConfig(), driver=_FakeDriver(run_handler))

    repository.fetch_evidence("cust-100", hop_radius=1)
    assert len(queries_seen) == 1

    queries_seen.clear()
    repository.fetch_evidence("cust-100", hop_radius=2)
    assert len(queries_seen) == 2
    assert queries_seen[0][1] == ["acct-100"]
    assert queries_seen[1][1] == ["acct-108"]


def test_find_alert_for_customer_from_neo4j() -> None:
    def run_handler(query: str, **params):
        assert params["customer_id"] == "cust-200"
        return _FakeResult(
            single_row={"alert_id": "alert-auto-cust-200", "reason": "cycle-detected", "description": "..."}
        )

    repository = Neo4jAlertRepository(config=AppConfig(), driver=_FakeDriver(run_handler))

    record = repository.find_alert_for_customer("cust-200")

    assert record is not None
    assert record.alert_id == "alert-auto-cust-200"


def test_find_alert_for_customer_offline_uses_seed_data() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())

    record = repository.find_alert_for_customer("cust-200")

    assert record is not None
    assert record.alert_id == "alert-auto-cust-200"


def test_find_alert_for_customer_offline_returns_none_when_absent() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())

    assert repository.find_alert_for_customer("cust-101") is None


def test_create_alert_writes_to_neo4j_when_driver_available() -> None:
    executed = []

    def run_handler(query: str, **params):
        executed.append((query, params))
        return _FakeResult()

    repository = Neo4jAlertRepository(config=AppConfig(), driver=_FakeDriver(run_handler))

    record = repository.create_alert("cust-214", reason="structuring-fanin-detected", description="...")

    assert record.alert_id == "alert-auto-cust-214"
    assert any("MERGE (a:Alert" in query for query, _ in executed)


def test_create_alert_offline_is_idempotent_and_process_local() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())

    first = repository.create_alert("cust-214", reason="structuring-fanin-detected", description="desc")
    second = repository.find_alert_for_customer("cust-214")

    assert second is not None
    assert second.alert_id == first.alert_id == "alert-auto-cust-214"


def test_app_config_from_env_uses_concrete_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_MAX_HOPS", raising=False)
    monkeypatch.delenv("AML_ALERT_EVIDENCE_LIMIT", raising=False)
    monkeypatch.delenv("AML_ALERT_LLM_ENABLED", raising=False)
    monkeypatch.delenv("AML_ALERT_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("AML_ALERT_LLM_MODEL", raising=False)
    monkeypatch.delenv("AML_ALERT_PROXIMITY_MAX_HOPS", raising=False)

    config = AppConfig.from_env()

    assert config.neo4j_uri == "bolt://localhost:7687"
    assert config.neo4j_max_hops == 2
    assert config.evidence_limit == 10
    assert config.llm_enabled is False
    assert config.llm_provider == "anthropic"
    assert config.llm_model == "local-insight-summarizer"
    assert config.alert_proximity_max_hops == 3


def test_app_config_from_env_reads_llm_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AML_ALERT_LLM_ENABLED", "true")
    monkeypatch.setenv("AML_ALERT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("AML_ALERT_LLM_MODEL", "demo-model")
    monkeypatch.setenv("AML_ALERT_LLM_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("AML_ALERT_LLM_REASONING_EFFORT", "high")

    config = AppConfig.from_env()

    assert config.llm_enabled is True
    assert config.llm_provider == "openai"
    assert config.llm_model == "demo-model"
    assert config.llm_timeout_seconds == 30
    assert config.llm_reasoning_effort == "high"
