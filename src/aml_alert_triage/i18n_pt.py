"""Portuguese (pt-BR) rendering helpers for deterministic, template-generated
text: evidence details and risk rationale.

These strings are always built from fixed templates elsewhere in the
codebase (format_transaction_details in graph_engine.py, and the
cycle/structuring/alert-proximity sentences in graph_engine.py/
repository.py), so translating them here via small, kind-dispatched
regexes is reliable - unlike free-form LLM prose, which is translated by
asking the model itself (see llm.py's *_pt response fields) rather than
regex, since there is no fixed pattern to parse.
"""

from __future__ import annotations

import re

from .models import EvidenceItem, RiskAssessment

CHANNEL_LABELS_PT = {
    "pix": "Transferência PIX",
    "boleto": "Pagamento de boleto",
    "ted": "Transferência TED",
    "deposit": "Depósito",
}

KIND_LABELS_PT = {
    "pix": "PIX",
    "boleto": "Boleto",
    "ted": "TED",
    "deposit": "Depósito",
    "cycle": "Ciclo de transferências",
    "structuring-fanout": "Estruturação (fan-out)",
    "structuring-fanin": "Estruturação (fan-in)",
    "alert-proximity": "Proximidade a cliente já alertado",
}

_TRANSACTION_RE = re.compile(r"^.+ of ([\d.]+) (\w+) (to|from) (.+)\.$")
_CYCLE_RE = re.compile(r"spanning (\d+) hop")
_STRUCTURING_RE = re.compile(r"Detected (\d+) distinct \w+ transfers.*sample \w+: (\[.*\])\.")
_PROXIMITY_RE = re.compile(r"Connected within (\d+) hop\(s\) to customer (\S+), who already has alert (\S+)\.")


def translate_evidence_detail_pt(item: EvidenceItem) -> str:
    """Renders an EvidenceItem's `details` in Portuguese, dispatching on
    `kind` (which template produced it). Falls back to the original text
    if the pattern isn't recognized, rather than raising - a report should
    never fail to render over a formatting mismatch."""
    if item.kind in CHANNEL_LABELS_PT:
        match = _TRANSACTION_RE.match(item.details)
        if match:
            amount, currency, direction, counterparty = match.groups()
            preposition = "para" if direction == "to" else "de"
            return f"{CHANNEL_LABELS_PT[item.kind]} de {amount} {currency} {preposition} {counterparty}."
    elif item.kind == "cycle":
        match = _CYCLE_RE.search(item.details)
        if match:
            return (
                f"Detectado um ciclo direcionado de transferências com {match.group(1)} salto(s) "
                "que retorna à conta de origem."
            )
    elif item.kind == "structuring-fanout":
        match = _STRUCTURING_RE.search(item.details)
        if match:
            count, sample = match.groups()
            return (
                f"Detectadas {count} transferências distintas de saída (possível estruturação/"
                f"pulverização); amostra de beneficiários: {sample}."
            )
    elif item.kind == "structuring-fanin":
        match = _STRUCTURING_RE.search(item.details)
        if match:
            count, sample = match.groups()
            return (
                f"Detectadas {count} transferências distintas de entrada convergindo para esta "
                f"conta (possível conta-laranja/coletora); amostra de origens: {sample}."
            )
    elif item.kind == "alert-proximity":
        match = _PROXIMITY_RE.search(item.details)
        if match:
            hops, linked_customer_id, linked_alert_id = match.groups()
            return (
                f"Conectado em {hops} salto(s) ao cliente {linked_customer_id}, "
                f"que já possui o alerta {linked_alert_id}."
            )
    return item.details


def translate_evidence_summary_pt(evidence: list[EvidenceItem]) -> str:
    return "; ".join(translate_evidence_detail_pt(item) for item in evidence)


def translate_risk_rationale_pt(risk: RiskAssessment) -> str:
    if risk.typologies:
        labels = sorted({KIND_LABELS_PT.get(typology, typology) for typology in risk.typologies})
        return "Padrão(ões) estrutural(is) detectado(s): " + ", ".join(labels) + "."
    if risk.level == "elevated":
        return "Foram encontradas evidências conectadas, mas nenhum padrão estrutural de alto risco foi detectado."
    return "Nenhuma evidência conectada foi encontrada após esgotar o orçamento de tentativas de investigação."
