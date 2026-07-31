"""Renders a Markdown investigation report from a persisted alert snapshot.

Deliberately makes no Neo4j or LLM calls: everything shown here was
captured in the snapshot at alert-creation time (see snapshot_store.py),
so a report always reflects "why this was flagged" as it looked then, even
if the graph or LLM availability has changed since.
"""

from __future__ import annotations

from pathlib import Path

from .snapshot_store import AlertSnapshot, AlertSnapshotStore

_INSIGHT_MODE_LABELS = {
    "static": "Static (rule-based) analysis",
    "anthropic": "LLM analysis (provider: anthropic)",
    "openai": "LLM analysis (provider: openai)",
}


def render_alert_report(snapshot: AlertSnapshot) -> str:
    insight_label = _INSIGHT_MODE_LABELS.get(snapshot.insight_mode, f"Analysis (mode: {snapshot.insight_mode})")

    lines: list[str] = []
    lines.append(f"# Alert Investigation Report: {snapshot.alert_id}\n")
    lines.append(f"- **Customer:** {snapshot.customer_id}")
    lines.append(f"- **Reason:** {snapshot.reason}")
    lines.append(f"- **Risk level:** {snapshot.risk.level}")
    lines.append(f"- **Created at:** {snapshot.created_at}\n")

    lines.append("## Description\n")
    lines.append(f"{snapshot.description}\n")

    lines.append("## Risk Assessment\n")
    lines.append(f"{snapshot.risk.rationale}\n")
    typologies = ", ".join(snapshot.risk.typologies) if snapshot.risk.typologies else "none"
    lines.append(f"**Typologies detected:** {typologies}\n")

    lines.append(f"## {insight_label}\n")
    lines.append(f"{snapshot.insight_summary}\n")
    if snapshot.insight_key_observations:
        lines.append("**Key observations:**\n")
        for observation in snapshot.insight_key_observations:
            lines.append(f"- {observation}")
        lines.append("")
    if snapshot.alert_reason:
        lines.append(f"**Why an alert was recommended:** {snapshot.alert_reason}\n")

    lines.append("## Evidence: Related People and Transactions\n")
    if snapshot.evidence:
        lines.append("| Kind | Related Account/Customer | Details | Source |")
        lines.append("| --- | --- | --- | --- |")
        for item in snapshot.evidence:
            details = item.details.replace("|", "\\|")
            lines.append(f"| {item.kind} | {item.subject} | {details} | {item.source} |")
    else:
        lines.append("No related evidence was recorded at the time this alert was created.")

    return "\n".join(lines) + "\n"


def generate_alert_report(
    alert_id: str, snapshot_store: AlertSnapshotStore, output_path: Path | None = None
) -> Path:
    snapshot = snapshot_store.get_snapshot(alert_id)
    if snapshot is None:
        raise RuntimeError(
            f"No snapshot found for alert '{alert_id}'. It may predate the report feature, or its "
            "snapshot write may have failed at creation time - a report cannot be generated without it."
        )

    markdown = render_alert_report(snapshot)
    target = output_path or Path("reports") / f"{alert_id}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    return target
