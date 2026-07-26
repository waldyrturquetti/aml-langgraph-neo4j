from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(slots=True)
class AppConfig:
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "test-password"
    neo4j_database: str = "neo4j"
    neo4j_auth: str = "neo4j/test-password"
    neo4j_max_hops: int = 2
    evidence_limit: int = 10

    @classmethod
    def from_env(cls) -> "AppConfig":
        defaults = cls()
        return cls(
            neo4j_uri=os.getenv("NEO4J_URI", defaults.neo4j_uri),
            neo4j_user=os.getenv("NEO4J_USER", defaults.neo4j_user),
            neo4j_password=os.getenv("NEO4J_PASSWORD", defaults.neo4j_password),
            neo4j_database=os.getenv("NEO4J_DATABASE", defaults.neo4j_database),
            neo4j_auth=os.getenv("NEO4J_AUTH", defaults.neo4j_auth),
            neo4j_max_hops=int(os.getenv("NEO4J_MAX_HOPS", str(defaults.neo4j_max_hops))),
            evidence_limit=int(os.getenv("AML_ALERT_EVIDENCE_LIMIT", str(defaults.evidence_limit))),
        )
