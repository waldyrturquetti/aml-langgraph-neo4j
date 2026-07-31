## ADDED Requirements

### Requirement: Alert investigation snapshot persistence
The system MUST persist an immutable snapshot of the evidence, risk assessment, and insight that led to an alert, in a store separate from the live Neo4j graph, at the moment the alert is created.

#### Scenario: Snapshot is saved when a new alert is created
- **WHEN** the workflow creates a new `Alert` node for a customer
- **THEN** it SHALL persist a snapshot containing the alert id, customer id, reason, description, the full evidence list, the risk assessment, and the insight (summary, key observations, and which analysis mode produced it) to the auxiliary snapshot store

#### Scenario: Snapshot persistence failure does not break the investigation
- **WHEN** the auxiliary snapshot store is unreachable at alert-creation time
- **THEN** the workflow SHALL log the failure and still complete the investigation and the Neo4j alert creation
- **AND THEN** report generation for that alert SHALL fail clearly later, rather than the investigation itself failing

#### Scenario: Pre-registered alerts have seeded snapshots
- **WHEN** the fictional dataset is seeded, including its pre-registered alerts
- **THEN** a corresponding snapshot SHALL be seeded into the auxiliary store for each pre-registered alert, so report generation works for them too

### Requirement: Markdown alert investigation report
The system MUST generate a Markdown report for a given alert id, explaining why the case is suspicious and showing the related people/accounts and transactions that produced the alert.

#### Scenario: Report is generated from a persisted snapshot
- **WHEN** an operator requests a report for an alert id that has a persisted snapshot
- **THEN** the system SHALL render a Markdown file containing the alert's reason/description, the insight analysis that led to it (labeled by which mode produced it), and a table of the evidence items (relationships and transactions) behind the alert
- **AND THEN** it SHALL write the file to a predictable default location derived from the alert id, unless an explicit output path is given

#### Scenario: No snapshot exists for the requested alert
- **WHEN** an operator requests a report for an alert id with no persisted snapshot
- **THEN** the system SHALL fail with a clear error indicating no snapshot was found, rather than silently substituting live graph data

#### Scenario: Report generation makes no live LLM or Neo4j calls
- **WHEN** a report is generated
- **THEN** the system SHALL use only the data already contained in the persisted snapshot
- **AND THEN** it SHALL NOT call an LLM provider or query Neo4j as part of generating the report
