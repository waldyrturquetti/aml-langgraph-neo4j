from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv

# Loads .env into the process environment on first import (does not override
# variables already set in the real environment). Without this, a .env file
# has no effect at all - AppConfig.from_env() only ever reads os.getenv.
load_dotenv()


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
    llm_provider: str = "anthropic"
    llm_model: str = "local-insight-summarizer"
    llm_timeout_seconds: int = 15
    llm_reasoning_effort: str | None = None
    max_enrichment_attempts: int = 2
    cycle_max_hops: int = 6
    structuring_fanout_threshold: int = 4
    structuring_fanin_threshold: int = 4
    min_evidence_for_conclusion: int = 2
    alert_proximity_max_hops: int = 3
    dynamodb_endpoint_url: str = "http://localhost:8000"
    dynamodb_table_name: str = "aml-alert-snapshots"
    dynamodb_region: str = "us-east-1"

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
            llm_reasoning_effort=os.getenv("AML_ALERT_LLM_REASONING_EFFORT", defaults.llm_reasoning_effort),
            max_enrichment_attempts=int(
                os.getenv("AML_ALERT_MAX_ENRICHMENT_ATTEMPTS", str(defaults.max_enrichment_attempts))
            ),
            cycle_max_hops=int(os.getenv("AML_ALERT_CYCLE_MAX_HOPS", str(defaults.cycle_max_hops))),
            structuring_fanout_threshold=int(
                os.getenv("AML_ALERT_STRUCTURING_FANOUT_THRESHOLD", str(defaults.structuring_fanout_threshold))
            ),
            structuring_fanin_threshold=int(
                os.getenv("AML_ALERT_STRUCTURING_FANIN_THRESHOLD", str(defaults.structuring_fanin_threshold))
            ),
            min_evidence_for_conclusion=int(
                os.getenv("AML_ALERT_MIN_EVIDENCE_FOR_CONCLUSION", str(defaults.min_evidence_for_conclusion))
            ),
            alert_proximity_max_hops=int(
                os.getenv("AML_ALERT_PROXIMITY_MAX_HOPS", str(defaults.alert_proximity_max_hops))
            ),
            dynamodb_endpoint_url=os.getenv("DYNAMODB_ENDPOINT_URL", defaults.dynamodb_endpoint_url),
            dynamodb_table_name=os.getenv("DYNAMODB_TABLE_NAME", defaults.dynamodb_table_name),
            dynamodb_region=os.getenv("DYNAMODB_REGION", defaults.dynamodb_region),
        )
