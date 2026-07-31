## ADDED Requirements

### Requirement: Dual-language insight response for report rendering
The system MUST produce a Portuguese (pt-BR) translation of the insight summary, key observations, and alert reason alongside the existing English fields, in the same generation call, regardless of provider.

#### Scenario: Real LLM provider returns both languages in one call
- **WHEN** a real LLM provider (`anthropic` or `openai`) generates insights
- **THEN** the structured response SHALL include `summary_pt`, `key_observations_pt`, and `alert_reason_pt` alongside the English fields
- **AND THEN** no additional LLM request SHALL be made to obtain the Portuguese text

#### Scenario: Static mode also produces Portuguese text
- **WHEN** insights are generated in static (rule-based) mode
- **THEN** the response SHALL include Portuguese counterparts of the summary, observations, and alert reason, derived from the same evidence-based templates as the English ones

#### Scenario: Fallback insights include Portuguese text
- **WHEN** insight generation fails and the workflow falls back to safe default insight text
- **THEN** the fallback text SHALL be provided in both English and Portuguese

#### Scenario: English fields remain the source of truth outside the report
- **WHEN** the workflow builds the CLI response or writes `Alert` node properties to Neo4j
- **THEN** it SHALL use the English insight fields, not the Portuguese ones
