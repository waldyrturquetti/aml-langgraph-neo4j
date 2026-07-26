from __future__ import annotations

from dataclasses import dataclass
import os


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class AppConfig:
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "test-password"
    neo4j_database: str = "neo4j"
    neo4j_auth: str = "neo4j/test-password"
    neo4j_max_hops: int = 2
    evidence_limit: int = 10
    llm_enabled: bool = False
    llm_provider: str = "rule-based"
    llm_model: str = "local-insight-summarizer"
    llm_timeout_seconds: int = 15

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
            llm_enabled=_env_flag("AML_ALERT_LLM_ENABLED", defaults.llm_enabled),
            llm_provider=os.getenv("AML_ALERT_LLM_PROVIDER", defaults.llm_provider),
            llm_model=os.getenv("AML_ALERT_LLM_MODEL", defaults.llm_model),
            llm_timeout_seconds=int(
                os.getenv("AML_ALERT_LLM_TIMEOUT_SECONDS", str(defaults.llm_timeout_seconds))
            ),
        )
