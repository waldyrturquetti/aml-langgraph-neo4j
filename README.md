# AML Alert Triage Agent

This study project demonstrates a fictional AML alert triage workflow built with LangGraph and Neo4j. The repository includes a Docker Compose setup for running Neo4j locally so the graph-backed workflow can be exercised without manual database installation.

## Local Neo4j Setup

1. Copy `.env.example` to `.env` and adjust the password if needed.
2. Start Neo4j with Docker Compose:

```bash
docker compose up -d
```

3. Open Neo4j Browser at http://localhost:7474.
4. Use the credentials from `.env` to connect.

5. Verify application connectivity:

```bash
python -m aml_alert_triage.main --check-neo4j
```

6. Load fictional seed data:

```bash
python -m aml_alert_triage.main --seed-neo4j --seed-file data/neo4j/seed.cypher
```

## Running the Demo

The application code is organized under `src/aml_alert_triage/`. The triage workflow can run in offline mode against the bundled fictional dataset or against the Neo4j container when the driver settings are configured.

## Project Scope

- All data is fictional.
- All code, comments, logs, and docs are in English.
- The repository is intended for learning and experimentation only.
