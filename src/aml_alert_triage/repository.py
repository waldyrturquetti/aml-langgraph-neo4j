from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .config import AppConfig
from .models import EvidenceItem
from .sample_data import SAMPLE_EVIDENCE


@dataclass(slots=True)
class Neo4jAlertRepository:
    config: AppConfig
    driver: object | None = None

    def __post_init__(self) -> None:
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
        return cls(config=config, driver=None)

    def fetch_evidence(self, customer_id: str, limit: int | None = None) -> list[EvidenceItem]:
        if self.driver is not None:
            try:
                return self._fetch_evidence_from_neo4j(customer_id, limit)
            except Exception:
                pass

        evidence = list(SAMPLE_EVIDENCE.get(customer_id, []))
        if limit is not None:
            return evidence[:limit]
        return evidence

    def _fetch_evidence_from_neo4j(self, customer_id: str, limit: int | None = None) -> list[EvidenceItem]:
        query_limit = limit or self.config.evidence_limit
        query = """
        MATCH (customer {customer_id: $customer_id})-[relationship]-(related)
        RETURN
            type(relationship) AS kind,
            coalesce(related.customer_id, related.account_id, related.alert_id, related.name, 'unknown') AS subject,
            coalesce(relationship.note, relationship.reason, relationship.description, 'Related graph evidence') AS details,
            'neo4j' AS source
        LIMIT $limit
        """

        with self.driver.session(database=self.config.neo4j_database) as session:
            records = session.run(query, customer_id=customer_id, limit=query_limit)
            return [self._record_to_evidence_item(record) for record in records]

    def _record_to_evidence_item(self, record: object) -> EvidenceItem:
        try:
            kind = str(record["kind"])
            subject = str(record["subject"])
            details = str(record["details"])
            source = str(record["source"])
        except Exception as exc:
            raise ValueError(
                "Neo4j evidence record is missing one of required fields: "
                "kind, subject, details, source"
            ) from exc

        return EvidenceItem(
            kind=kind,
            subject=subject,
            details=details,
            source=source,
        )

    def fetch_connected_context(self, customer_id: str) -> list[EvidenceItem]:
        return self.fetch_evidence(customer_id, self.config.evidence_limit)

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

        statements = [
            statement.strip()
            for statement in seed_file.read_text(encoding="utf-8").split(";")
            if statement.strip()
        ]
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
