## MODIFIED Requirements

### Requirement: Markdown alert investigation report
The system MUST generate a Markdown report, in Portuguese, for a given alert id, explaining why the case is suspicious, showing the related people/accounts and transactions that produced the alert, and including a Cypher query for visualizing the case in Neo4j.

#### Scenario: Report is generated from a persisted snapshot
- **WHEN** an operator requests a report for an alert id that has a persisted snapshot
- **THEN** the system SHALL render a Markdown file, in Portuguese, containing the alert's reason/description, the insight analysis that led to it (labeled by which mode produced it), and a table of the evidence items (relationships and transactions) behind the alert
- **AND THEN** it SHALL write the file to a predictable default location derived from the alert id, unless an explicit output path is given

#### Scenario: Evidence and risk text are rendered in Portuguese
- **WHEN** the report includes evidence details or risk rationale that were generated from fixed English templates
- **THEN** the system SHALL render them in Portuguese
- **AND THEN** if a given evidence item's text does not match a known template, the system SHALL fall back to rendering its original text rather than failing

#### Scenario: Report includes a Cypher query to visualize the case
- **WHEN** a report is generated
- **THEN** it SHALL include a ready-to-run Cypher query, parameterized with the alert's customer id, for visualizing that customer's accounts and transactions in Neo4j Browser
- **AND THEN** it SHALL include a second query for locating the alert node itself

#### Scenario: No snapshot exists for the requested alert
- **WHEN** an operator requests a report for an alert id with no persisted snapshot
- **THEN** the system SHALL fail with a clear error indicating no snapshot was found, rather than silently substituting live graph data

#### Scenario: Report generation makes no live LLM or Neo4j calls
- **WHEN** a report is generated
- **THEN** the system SHALL use only the data already contained in the persisted snapshot, translating deterministic text locally rather than via a live call
- **AND THEN** it SHALL NOT call an LLM provider or query Neo4j as part of generating the report
