## Why

AML analysts need a repeatable way to triage alerts faster without losing the reasoning trail behind each decision. This change introduces an agentic workflow that can review fictional alert cases, assemble supporting evidence, and guide analysts through a consistent investigation path.

## What Changes

- Add a LangGraph-based triage agent that coordinates alert intake, case enrichment, evidence review, and decision support.
- Persist alert and relationship data in Neo4j so the agent can reason over connected entities, transactions, and case history.
- Provide a Docker Compose-based Neo4j setup so the graph database can be started locally with the project.
- Add environment and connection configuration for the application to reach Neo4j through the containerized setup.
- Add a fictional Neo4j seed dataset and a repeatable load path so developers can insert demo graph data locally.
- Standardize the agent's outputs around transparent triage steps, evidence summaries, and recommended next actions.
- Add domain-specific prompts, state fields, and node names in English for the graph workflow.
- Include logging and documentation that explain the triage flow for learning purposes.

## Capabilities

### New Capabilities
- `aml-alert-triage`: End-to-end AML triage workflow for reviewing fictional alerts, enriching context, and producing analyst-ready recommendations.

### Modified Capabilities
- `aml-alert-triage`: Extend the workflow requirements to include local Neo4j startup and connection through Docker Compose.

## Impact

Affected areas include the Python application code, LangGraph orchestration, Neo4j data access layer, Docker Compose configuration, environment files, fictional graph seed files, domain prompts, logs, and project documentation. The change may also add tests and seed data for fictional AML scenarios, but it does not introduce real customer data or production compliance logic.
