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

## What this enables

The AML triage workflow can query connected entities, transactions, and prior alert history from the containerized graph database.
