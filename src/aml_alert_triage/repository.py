from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
import logging

from .config import AppConfig
from .graph_dataset import ALERTS, DATASET
from .graph_engine import evidence_for_customer, format_transaction_details
from .models import AlertRecord, EvidenceItem

logger = logging.getLogger(__name__)

# Cypher variable-length patterns can't take a parameter for the hop bound,
# so the configured cycle_max_hops/alert_proximity_max_hops are clamped to
# these ranges and interpolated as literals. Internal config values only,
# never user input.
_CYCLE_HOPS_RANGE = (2, 12)
_PROXIMITY_HOPS_RANGE = (1, 12)


def _split_cypher_statements(code: str) -> list[str]:
    """Splits a script into individual statements on top-level `;` only.

    A naive `code.split(";")` breaks the moment any string literal in the
    script contains a semicolon (e.g. a description field with "a; b").
    This tracks quote state (and `\\`-escapes within a quoted string) so a
    `;` inside 'single' or "double" quotes is never treated as a separator.
    """
    statements: list[str] = []
    current: list[str] = []
    quote_char: str | None = None
    i = 0
    length = len(code)
    while i < length:
        char = code[i]
        if quote_char:
            current.append(char)
            if char == "\\" and i + 1 < length:
                current.append(code[i + 1])
                i += 2
                continue
            if char == quote_char:
                quote_char = None
        elif char in ("'", '"'):
            quote_char = char
            current.append(char)
        elif char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)
        i += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


@dataclass(slots=True)
class Neo4jAlertRepository:
    config: AppConfig
    driver: object | None = None
    force_offline: bool = False
    _offline_alerts: dict[str, AlertRecord] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        for seed in ALERTS:
            self._offline_alerts[seed.customer_id] = AlertRecord(
                alert_id=seed.alert_id, reason=seed.reason, description=seed.description
            )

        if self.force_offline:
            self.driver = None
            return

        if self.driver is not None:
            return

        try:
            from neo4j import GraphDatabase
        except Exception:
            self.driver = None
            return

        try:
            self.driver = GraphDatabase.driver(
                self.config.neo4j_uri,
                auth=(self.config.neo4j_user, self.config.neo4j_password),
            )
        except Exception:
            self.driver = None

    @classmethod
    def offline(cls, config: AppConfig) -> "Neo4jAlertRepository":
        return cls(config=config, driver=None, force_offline=True)

    def fetch_evidence(
        self, customer_id: str, limit: int | None = None, hop_radius: int = 1
    ) -> list[EvidenceItem]:
        if self.driver is not None:
            try:
                return self._fetch_evidence_from_neo4j(customer_id, limit, hop_radius)
            except Exception:
                pass

        return self._offline_evidence(customer_id, limit, hop_radius)

    def _offline_evidence(
        self, customer_id: str, limit: int | None, hop_radius: int
    ) -> list[EvidenceItem]:
        # Reimplements the live Cypher query logic in pure Python over the
        # same canonical dataset (graph_dataset.py) - not a hand-maintained
        # set of fixtures, so offline/test behavior can't silently drift from
        # what the live queries below actually compute.
        evidence = evidence_for_customer(
            DATASET,
            customer_id,
            hop_radius,
            cycle_max_hops=self.config.cycle_max_hops,
            fanout_threshold=self.config.structuring_fanout_threshold,
            fanin_threshold=self.config.structuring_fanin_threshold,
            alert_proximity_max_hops=self.config.alert_proximity_max_hops,
            alerted_customer_ids=set(self._offline_alerts.keys()),
            alert_ids_by_customer={cid: rec.alert_id for cid, rec in self._offline_alerts.items()},
        )

        if limit is not None:
            return evidence[:limit]
        return evidence

    def _fetch_evidence_from_neo4j(
        self, customer_id: str, limit: int | None, hop_radius: int
    ) -> list[EvidenceItem]:
        query_limit = limit or self.config.evidence_limit

        evidence = self._fetch_hop_evidence(customer_id, hop_radius, query_limit)

        # Targeted typology queries: cheap, pattern-specific graph traversals
        # that run independently of the general-neighbor hop radius, since a
        # laundering cycle, a fan-out/fan-in pattern, or proximity to an
        # already-alerted customer is either present in the graph or it isn't.
        evidence.extend(self._fetch_cycle_evidence(customer_id))
        evidence.extend(self._fetch_structuring_evidence(customer_id))
        evidence.extend(self._fetch_alert_proximity_evidence(customer_id))
        return evidence

    def _fetch_account_ids(self, customer_id: str) -> set[str]:
        query = (
            "MATCH (customer {customer_id: $customer_id})-[:OWNS]->(account) "
            "RETURN account.account_id AS account_id"
        )
        with self.driver.session(database=self.config.neo4j_database) as session:
            records = session.run(query, customer_id=customer_id)
            return {str(record["account_id"]) for record in records}

    def _fetch_hop_evidence(self, customer_id: str, hop_radius: int, limit: int) -> list[EvidenceItem]:
        # Iterative frontier expansion: one simple, non-variable-length
        # Cypher query per hop against the current frontier, rather than a
        # single `TRANSFERRED_TO*1..N` pattern - avoids the "variable-length
        # bound can't be a bind parameter" constraint (see _CYCLE_HOPS_RANGE)
        # and lets each hop's evidence be framed relative to that hop's own
        # frontier, matching what the offline graph_engine.hop_evidence does.
        frontier = self._fetch_account_ids(customer_id)
        if not frontier:
            return []

        visited = set(frontier)
        evidence: list[EvidenceItem] = []
        for _ in range(max(hop_radius, 1)):
            query = """
            MATCH (a:Account)-[r:TRANSFERRED_TO]-(b:Account)
            WHERE a.account_id IN $frontier AND NOT b.account_id IN $visited
            RETURN DISTINCT
                b.account_id AS counterparty,
                r.channel AS channel,
                r.amount AS amount,
                r.currency AS currency,
                CASE WHEN startNode(r) = a THEN 'to' ELSE 'from' END AS direction
            LIMIT $limit
            """
            with self.driver.session(database=self.config.neo4j_database) as session:
                records = list(
                    session.run(query, frontier=list(frontier), visited=list(visited), limit=limit)
                )
            if not records:
                break

            new_frontier: set[str] = set()
            for record in records:
                evidence.append(self._record_to_transaction_evidence(record))
                new_frontier.add(str(record["counterparty"]))
            visited |= new_frontier
            frontier = new_frontier
        return evidence

    def _fetch_cycle_evidence(self, customer_id: str) -> list[EvidenceItem]:
        lower, upper = _CYCLE_HOPS_RANGE
        max_hops = max(lower, min(self.config.cycle_max_hops, upper))
        query = (
            "MATCH (customer {customer_id: $customer_id})-[:OWNS]->(account) "
            f"MATCH path = (account)-[:TRANSFERRED_TO*2..{max_hops}]->(account) "
            "RETURN length(path) AS hops "
            "ORDER BY hops ASC "
            "LIMIT 1"
        )

        with self.driver.session(database=self.config.neo4j_database) as session:
            row = session.run(query, customer_id=customer_id).single()

        if row is None:
            return []

        hops = row["hops"]
        return [
            EvidenceItem(
                kind="cycle",
                subject=customer_id,
                details=(
                    f"Detected a directed fund-transfer cycle spanning {hops} hop(s) that "
                    "returns to the originating account."
                ),
                source="neo4j",
            )
        ]

    def _fetch_structuring_evidence(self, customer_id: str) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []

        fanout = self._fetch_fan_pattern(
            customer_id, direction="out", threshold=self.config.structuring_fanout_threshold
        )
        if fanout is not None:
            count, sample = fanout
            items.append(
                EvidenceItem(
                    kind="structuring-fanout",
                    subject=customer_id,
                    details=(
                        f"Detected {count} distinct outgoing transfers (possible structuring/"
                        f"pulverization); sample beneficiaries: {sample}."
                    ),
                    source="neo4j",
                )
            )

        fanin = self._fetch_fan_pattern(
            customer_id, direction="in", threshold=self.config.structuring_fanin_threshold
        )
        if fanin is not None:
            count, sample = fanin
            items.append(
                EvidenceItem(
                    kind="structuring-fanin",
                    subject=customer_id,
                    details=(
                        f"Detected {count} distinct incoming transfers converging onto this "
                        f"account (possible mule/collector pattern); sample sources: {sample}."
                    ),
                    source="neo4j",
                )
            )

        return items

    def _fetch_fan_pattern(
        self, customer_id: str, direction: str, threshold: int
    ) -> tuple[int, list[str]] | None:
        relationship = "-[:TRANSFERRED_TO]->" if direction == "out" else "<-[:TRANSFERRED_TO]-"
        query = (
            "MATCH (customer {customer_id: $customer_id})-[:OWNS]->(account)"
            f"{relationship}(counterparty) "
            "WITH count(DISTINCT counterparty) AS counterparties, "
            "collect(DISTINCT coalesce(counterparty.account_id, 'unknown'))[0..5] AS sample "
            "WHERE counterparties >= $threshold "
            "RETURN counterparties, sample"
        )

        with self.driver.session(database=self.config.neo4j_database) as session:
            row = session.run(query, customer_id=customer_id, threshold=threshold).single()

        if row is None:
            return None
        return row["counterparties"], list(row["sample"])

    def _fetch_alert_proximity_evidence(self, customer_id: str) -> list[EvidenceItem]:
        lower, upper = _PROXIMITY_HOPS_RANGE
        max_hops = max(lower, min(self.config.alert_proximity_max_hops, upper))
        query = (
            "MATCH (customer {customer_id: $customer_id})-[:OWNS]->(account) "
            f"MATCH path = (account)-[:TRANSFERRED_TO*1..{max_hops}]-(other_account) "
            "MATCH (other_customer)-[:OWNS]->(other_account) "
            "MATCH (a:Alert)-[:TARGETS]->(other_customer) "
            "WHERE other_customer.customer_id <> $customer_id "
            "WITH other_customer, a, min(length(path)) AS hops "
            "RETURN other_customer.customer_id AS linked_customer_id, a.alert_id AS linked_alert_id, hops "
            "ORDER BY hops ASC "
            "LIMIT 5"
        )

        with self.driver.session(database=self.config.neo4j_database) as session:
            rows = list(session.run(query, customer_id=customer_id))

        return [
            EvidenceItem(
                kind="alert-proximity",
                subject=customer_id,
                details=(
                    f"Connected within {row['hops']} hop(s) to customer {row['linked_customer_id']}, "
                    f"who already has alert {row['linked_alert_id']}."
                ),
                source="neo4j",
            )
            for row in rows
        ]

    def _record_to_transaction_evidence(self, record: object) -> EvidenceItem:
        try:
            channel = str(record["channel"])
            amount = float(record["amount"])
            currency = str(record["currency"])
            counterparty = str(record["counterparty"])
            direction = str(record["direction"])
        except Exception as exc:
            raise ValueError(
                "Neo4j transaction record is missing one of required fields: "
                "channel, amount, currency, counterparty, direction"
            ) from exc

        return EvidenceItem(
            kind=channel,
            subject=counterparty,
            details=format_transaction_details(channel, amount, currency, direction, counterparty),
            source="neo4j",
        )

    def fetch_connected_context(self, customer_id: str, hop_radius: int = 1) -> list[EvidenceItem]:
        return self.fetch_evidence(customer_id, self.config.evidence_limit, hop_radius=hop_radius)

    def find_alert_for_customer(self, customer_id: str) -> AlertRecord | None:
        if self.driver is not None:
            try:
                return self._find_alert_from_neo4j(customer_id)
            except Exception:
                pass
        return self._offline_alerts.get(customer_id)

    def _find_alert_from_neo4j(self, customer_id: str) -> AlertRecord | None:
        query = (
            "MATCH (a:Alert)-[:TARGETS]->(c {customer_id: $customer_id}) "
            "RETURN a.alert_id AS alert_id, a.reason AS reason, a.description AS description "
            "LIMIT 1"
        )
        with self.driver.session(database=self.config.neo4j_database) as session:
            row = session.run(query, customer_id=customer_id).single()

        if row is None:
            return None
        return AlertRecord(
            alert_id=str(row["alert_id"]), reason=str(row["reason"]), description=str(row["description"])
        )

    def create_alert(self, customer_id: str, reason: str, description: str) -> AlertRecord:
        record = AlertRecord(alert_id=f"alert-auto-{customer_id}", reason=reason, description=description)

        if self.driver is not None:
            try:
                self._create_alert_in_neo4j(customer_id, record)
                return record
            except Exception:
                logger.warning("Failed to persist alert %s to Neo4j; tracking offline only.", record.alert_id)

        self._offline_alerts[customer_id] = record
        return record

    def _create_alert_in_neo4j(self, customer_id: str, record: AlertRecord) -> None:
        # MERGE on the deterministic alert_id makes this idempotent at the
        # database level too, on top of the application-level existence
        # check callers are expected to do via find_alert_for_customer first.
        query = (
            "MATCH (c {customer_id: $customer_id}) "
            "MERGE (a:Alert {alert_id: $alert_id}) "
            "SET a.reason = $reason, a.description = $description "
            "MERGE (a)-[:TARGETS]->(c)"
        )
        with self.driver.session(database=self.config.neo4j_database) as session:
            session.run(
                query,
                customer_id=customer_id,
                alert_id=record.alert_id,
                reason=record.reason,
                description=record.description,
            )

    def describe_connection(self) -> str:
        return f"{self.config.neo4j_uri} ({self.config.neo4j_database})"

    def verify_connection(self) -> None:
        if self.driver is None:
            raise RuntimeError(
                "Neo4j driver is not available. Install neo4j dependencies and start the Docker Compose service."
            )

        try:
            with self.driver.session(database=self.config.neo4j_database) as session:
                result = session.run("RETURN 1 AS ok")
                first = result.single()
                ok = first["ok"] if first is not None else None
        except Exception as exc:
            raise RuntimeError(
                f"Failed to connect to Neo4j at {self.describe_connection()}. "
                "Check .env settings and ensure Docker Compose Neo4j is running."
            ) from exc

        if ok != 1:
            raise RuntimeError(
                f"Unexpected Neo4j connectivity response from {self.describe_connection()}."
            )

    def load_seed_file(self, seed_file: Path) -> int:
        if self.driver is None:
            raise RuntimeError(
                "Neo4j driver is not available. Start the Neo4j container before loading seed data."
            )

        code_lines = [
            line for line in seed_file.read_text(encoding="utf-8").splitlines() if not line.strip().startswith("//")
        ]
        statements = _split_cypher_statements("\n".join(code_lines))
        with self.driver.session(database=self.config.neo4j_database) as session:
            for statement in statements:
                session.run(statement)
        return len(statements)

    def close(self) -> None:
        if self.driver is not None:
            self.driver.close()
            self.driver = None


def summarize_evidence(evidence: Iterable[EvidenceItem]) -> str:
    return "; ".join(item.details for item in evidence)
