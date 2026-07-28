from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .config import AppConfig
from .graph_dataset import DATASET
from .graph_engine import evidence_for_customer, format_transaction_details
from .models import EvidenceItem

# Cypher variable-length patterns can't take a parameter for the hop bound,
# so the configured cycle_max_hops is clamped to this range and interpolated
# as a literal. It is an internal config value, never user input.
_CYCLE_HOPS_RANGE = (2, 12)


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

    def __post_init__(self) -> None:
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
        )

        if limit is not None:
            return evidence[:limit]
        return evidence

    def _fetch_evidence_from_neo4j(
        self, customer_id: str, limit: int | None, hop_radius: int
    ) -> list[EvidenceItem]:
        query_limit = limit or self.config.evidence_limit

        evidence = self._fetch_direct_evidence(customer_id, query_limit)
        if hop_radius >= 2:
            evidence.extend(self._fetch_second_hop_evidence(customer_id, query_limit))

        # Targeted typology queries: cheap, pattern-specific graph traversals
        # that run independently of the general-neighbor hop radius, since a
        # laundering cycle or a fan-out/fan-in pattern is either present in
        # the graph or it isn't.
        evidence.extend(self._fetch_cycle_evidence(customer_id))
        evidence.extend(self._fetch_structuring_evidence(customer_id))
        return evidence

    def _fetch_direct_evidence(self, customer_id: str, limit: int) -> list[EvidenceItem]:
        # Rooted at the customer's own account(s) and only ever traverses
        # TRANSFERRED_TO edges, so this never touches the administrative OWNS
        # (customer->account) or TARGETS (alert->customer) edges in the first
        # place - a customer with no external money movement genuinely
        # produces empty evidence here, which is what drives the
        # widen-search retry loop in workflow.py.
        query = """
        MATCH (customer {customer_id: $customer_id})-[:OWNS]->(account)-[relationship:TRANSFERRED_TO]-(related)
        RETURN
            relationship.channel AS channel,
            relationship.amount AS amount,
            relationship.currency AS currency,
            related.account_id AS counterparty,
            CASE WHEN startNode(relationship) = account THEN 'to' ELSE 'from' END AS direction
        LIMIT $limit
        """

        with self.driver.session(database=self.config.neo4j_database) as session:
            records = session.run(query, customer_id=customer_id, limit=limit)
            return [self._record_to_transaction_evidence(record) for record in records]

    def _fetch_second_hop_evidence(self, customer_id: str, limit: int) -> list[EvidenceItem]:
        # Pivots through the customer's own account and one counterparty
        # ("mid") to describe that counterparty's *other* transactions -
        # `related <> account` excludes reporting the customer's own
        # transaction back to itself as if it were new second-hop evidence.
        query = """
        MATCH (customer {customer_id: $customer_id})-[:OWNS]->(account)-[:TRANSFERRED_TO]-(mid)
              -[relationship:TRANSFERRED_TO]-(related)
        WHERE related <> account
        RETURN DISTINCT
            relationship.channel AS channel,
            relationship.amount AS amount,
            relationship.currency AS currency,
            related.account_id AS counterparty,
            CASE WHEN startNode(relationship) = mid THEN 'to' ELSE 'from' END AS direction
        LIMIT $limit
        """

        with self.driver.session(database=self.config.neo4j_database) as session:
            records = session.run(query, customer_id=customer_id, limit=limit)
            return [self._record_to_transaction_evidence(record) for record in records]

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
