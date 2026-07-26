# Neo4j Local Setup

This project uses Docker Compose to start Neo4j locally for development and learning.

## Start the service

```bash
docker compose up -d
```

## Stop the service

```bash
docker compose down
```

## Connection settings

Use the following defaults for local development:

- URI: `bolt://localhost:7687`
- User: `neo4j`
- Password: `test-password`

These values can be overridden in `.env`.

## Verify application connectivity

Run the connectivity check command after Neo4j is up:

```bash
python -m aml_alert_triage.main --check-neo4j
```

The command returns a JSON payload with the configured connection when the check succeeds.

## Load fictional seed data

Load the versioned fictional graph fixtures into the container:

```bash
python -m aml_alert_triage.main --seed-neo4j --seed-file data/neo4j/seed.cypher
```

This seed includes both a connected-evidence case (`cust-100`) and a disconnected case (`cust-200`).

## What this enables

The AML triage workflow can query connected entities, transactions, and prior alert history from the containerized graph database.
