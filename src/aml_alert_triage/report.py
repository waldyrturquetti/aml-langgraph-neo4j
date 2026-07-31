"""Renders a Markdown investigation report (in Portuguese) from a persisted
alert snapshot.

Deliberately makes no Neo4j or LLM calls: everything shown here was
captured in the snapshot at alert-creation time (see snapshot_store.py),
so a report always reflects "why this was flagged" as it looked then, even
if the graph or LLM availability has changed since. Insight/evidence/risk
text is rendered in pt-BR (see i18n_pt.py and llm.py's *_pt response
fields) - the CLI response and Neo4j data stay in English.
"""

from __future__ import annotations

from pathlib import Path

from .i18n_pt import KIND_LABELS_PT, translate_evidence_detail_pt, translate_risk_rationale_pt
from .snapshot_store import AlertSnapshot, AlertSnapshotStore

_INSIGHT_MODE_LABELS_PT = {
    "static": "Análise estática (baseada em regras)",
    "anthropic": "Análise via LLM (provedor: anthropic)",
    "openai": "Análise via LLM (provedor: openai)",
}

# A generic, adjustable hop depth for the suggested visualization query -
# not tied to any specific config value, just a reasonable default for
# seeing a case's immediate neighborhood in Neo4j Browser.
_VISUALIZATION_HOPS = 3


def render_alert_report(snapshot: AlertSnapshot) -> str:
    insight_label = _INSIGHT_MODE_LABELS_PT.get(
        snapshot.insight_mode, f"Análise (modo: {snapshot.insight_mode})"
    )

    lines: list[str] = []
    lines.append(f"# Relatório de Investigação de Alerta: {snapshot.alert_id}\n")
    lines.append(f"- **Cliente:** {snapshot.customer_id}")
    lines.append(f"- **Motivo:** {snapshot.reason}")
    lines.append(f"- **Nível de risco:** {snapshot.risk.level}")
    lines.append(f"- **Criado em:** {snapshot.created_at}\n")

    lines.append("## Descrição\n")
    lines.append(f"{snapshot.description}\n")

    lines.append("## Avaliação de Risco\n")
    lines.append(f"{translate_risk_rationale_pt(snapshot.risk)}\n")
    if snapshot.risk.typologies:
        typology_labels = ", ".join(
            sorted({KIND_LABELS_PT.get(t, t) for t in snapshot.risk.typologies})
        )
    else:
        typology_labels = "nenhuma"
    lines.append(f"**Tipologias detectadas:** {typology_labels}\n")

    lines.append(f"## {insight_label}\n")
    lines.append(f"{snapshot.insight_summary}\n")
    if snapshot.insight_key_observations:
        lines.append("**Principais observações:**\n")
        for observation in snapshot.insight_key_observations:
            lines.append(f"- {observation}")
        lines.append("")
    if snapshot.alert_reason:
        lines.append(f"**Por que um alerta foi recomendado:** {snapshot.alert_reason}\n")

    lines.append("## Evidências: Pessoas e Transações Relacionadas\n")
    if snapshot.evidence:
        lines.append("| Tipo | Conta/Cliente Relacionado | Detalhes | Origem |")
        lines.append("| --- | --- | --- | --- |")
        for item in snapshot.evidence:
            kind_label = KIND_LABELS_PT.get(item.kind, item.kind)
            details_pt = translate_evidence_detail_pt(item).replace("|", "\\|")
            lines.append(f"| {kind_label} | {item.subject} | {details_pt} | {item.source} |")
    else:
        lines.append("Nenhuma evidência relacionada foi registrada no momento em que este alerta foi criado.")

    lines.append("\n## Consulta Cypher para Visualizar Este Caso no Neo4j\n")
    lines.append(
        "Execute no Neo4j Browser (http://localhost:7474) para visualizar as contas e transações "
        f"conectadas a este cliente (ajuste o número de saltos `*1..{_VISUALIZATION_HOPS}` se necessário):\n"
    )
    lines.append("```cypher")
    lines.append(
        f"MATCH (c:Customer {{customer_id: '{snapshot.customer_id}'}})-[:OWNS]->(acct)"
        f"-[t:TRANSFERRED_TO*1..{_VISUALIZATION_HOPS}]-(other)\n"
        "RETURN c, acct, t, other;"
    )
    lines.append("```\n")
    lines.append("Para ver apenas o nó do alerta e o cliente:\n")
    lines.append("```cypher")
    lines.append(
        f"MATCH (a:Alert {{alert_id: '{snapshot.alert_id}'}})-[:TARGETS]->(c:Customer) RETURN a, c;"
    )
    lines.append("```")

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
