# aml-alert-triage Specification

## Purpose
TBD - created by archiving change aml-alert-triage-agent. Update Purpose after archive.
## Requirements
### Requirement: Local Neo4j Docker Compose setup
The system MUST provide a Docker Compose configuration that starts Neo4j locally for development and learning.

#### Scenario: Neo4j starts through Docker Compose
- **WHEN** a developer runs the project Docker Compose configuration
- **THEN** Neo4j SHALL start as a local container with the expected database ports available

#### Scenario: Local startup is documented
- **WHEN** a developer sets up the project from a clean checkout
- **THEN** the setup instructions SHALL explain how to start and stop Neo4j using Docker Compose

### Requirement: Application connects to containerized Neo4j
The system MUST read Neo4j connection settings from configuration so the triage workflow can connect to the Docker Compose instance.

#### Scenario: Connection settings target the container
- **WHEN** the application is configured for local development
- **THEN** it SHALL use Neo4j connection values that point to the Docker Compose service

#### Scenario: Missing connection settings are handled clearly
- **WHEN** the Neo4j connection settings are absent or invalid
- **THEN** the system SHALL fail with a clear configuration error that explains how to enable the local Neo4j service

### Requirement: AML alert triage workflow
The system MUST provide a LangGraph-based workflow that ingests a fictional AML alert, tracks triage state, and produces a structured recommendation.

#### Scenario: Workflow starts from an alert
- **WHEN** the system receives a fictional alert payload
- **THEN** it SHALL initialize triage state with the alert identifier, entity context, and investigation status
- **AND THEN** it SHALL route the alert through the triage workflow

#### Scenario: Workflow produces a structured result
- **WHEN** the workflow completes triage
- **THEN** it SHALL return a structured result containing the decision, rationale, and supporting evidence summary

### Requirement: Neo4j evidence enrichment
The system MUST enrich the alert with connected evidence from Neo4j, including related entities, transactions, and prior alert history when available.

#### Scenario: Fictional seed data can be inserted for local validation
- **WHEN** a developer prepares a local environment for the workflow
- **THEN** the project SHALL provide a repeatable way to load fictional AML graph data into the Neo4j container
- **AND THEN** the dataset SHALL include both a connected-evidence case and a no-relationship case

#### Scenario: Evidence is retrieved from graph relationships
- **WHEN** the workflow begins evidence enrichment for an alert entity
- **THEN** it SHALL query Neo4j for directly related nodes and relationships within the configured investigation scope
- **AND THEN** it SHALL include the retrieved evidence in the triage state

#### Scenario: Missing relationships are handled safely
- **WHEN** Neo4j does not contain related evidence for an alert
- **THEN** the system SHALL continue the workflow with an empty or limited evidence set
- **AND THEN** it SHALL record that no related evidence was found

#### Scenario: Retrieved evidence matches workflow state shape
- **WHEN** graph evidence is returned from Neo4j queries
- **THEN** each evidence item SHALL include `kind`, `subject`, `details`, and `source`
- **AND THEN** the workflow SHALL accept the result without additional shape adaptation

### Requirement: Analyst-ready recommendation
The system MUST generate an analyst-ready triage recommendation that references the collected evidence and does not claim unsupported facts.

#### Scenario: Recommendation cites evidence
- **WHEN** the workflow generates a recommendation
- **THEN** it SHALL reference the evidence used to support the conclusion
- **AND THEN** it SHALL avoid asserting facts that are not present in the triage state or Neo4j results

#### Scenario: Recommendation remains deterministic in structure
- **WHEN** two alerts with the same input data are processed
- **THEN** the system SHALL produce recommendations with the same output fields and workflow stages

