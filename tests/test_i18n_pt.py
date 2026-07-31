from aml_alert_triage.i18n_pt import translate_evidence_detail_pt, translate_risk_rationale_pt
from aml_alert_triage.models import EvidenceItem, RiskAssessment


def test_translate_transaction_evidence_to_pt() -> None:
    item = EvidenceItem(kind="pix", subject="acct-108", details="PIX transfer of 640.00 BRL to acct-108.", source="neo4j")

    assert translate_evidence_detail_pt(item) == "Transferência PIX de 640.00 BRL para acct-108."


def test_translate_transaction_evidence_from_direction_to_pt() -> None:
    item = EvidenceItem(
        kind="boleto", subject="acct-112", details="Boleto payment of 7982.08 BRL from acct-112.", source="neo4j"
    )

    assert translate_evidence_detail_pt(item) == "Pagamento de boleto de 7982.08 BRL de acct-112."


def test_translate_cycle_evidence_to_pt() -> None:
    item = EvidenceItem(
        kind="cycle",
        subject="cust-200",
        details="Detected a directed fund-transfer cycle spanning 4 hop(s) that returns to the originating account.",
        source="neo4j",
    )

    result = translate_evidence_detail_pt(item)

    assert "ciclo direcionado" in result
    assert "4 salto(s)" in result


def test_translate_structuring_fanout_evidence_to_pt() -> None:
    item = EvidenceItem(
        kind="structuring-fanout",
        subject="cust-207",
        details=(
            "Detected 6 distinct outgoing transfers (possible structuring/pulverization); "
            "sample beneficiaries: ['acct-207-c207b1', 'acct-207-c207b2']."
        ),
        source="neo4j",
    )

    result = translate_evidence_detail_pt(item)

    assert "6 transferências distintas de saída" in result
    assert "acct-207-c207b1" in result


def test_translate_structuring_fanin_evidence_to_pt() -> None:
    item = EvidenceItem(
        kind="structuring-fanin",
        subject="cust-214",
        details=(
            "Detected 5 distinct incoming transfers converging onto this account "
            "(possible mule/collector pattern); sample sources: ['acct-214-c214s1']."
        ),
        source="neo4j",
    )

    result = translate_evidence_detail_pt(item)

    assert "5 transferências distintas de entrada" in result
    assert "conta-laranja" in result


def test_translate_alert_proximity_evidence_to_pt() -> None:
    item = EvidenceItem(
        kind="alert-proximity",
        subject="cust-129",
        details="Connected within 2 hop(s) to customer cust-200, who already has alert alert-auto-cust-200.",
        source="neo4j",
    )

    result = translate_evidence_detail_pt(item)

    assert result == "Conectado em 2 salto(s) ao cliente cust-200, que já possui o alerta alert-auto-cust-200."


def test_translate_evidence_falls_back_to_original_on_unrecognized_format() -> None:
    item = EvidenceItem(kind="pix", subject="acct-1", details="something unexpected", source="neo4j")

    assert translate_evidence_detail_pt(item) == "something unexpected"


def test_translate_risk_rationale_for_high_risk() -> None:
    risk = RiskAssessment(level="high", rationale="...", typologies=["cycle", "structuring-fanout"])

    result = translate_risk_rationale_pt(risk)

    assert "Ciclo de transferências" in result
    assert "Estruturação (fan-out)" in result


def test_translate_risk_rationale_for_elevated() -> None:
    risk = RiskAssessment(level="elevated", rationale="...", typologies=[])

    assert "evidências conectadas" in translate_risk_rationale_pt(risk)


def test_translate_risk_rationale_for_low() -> None:
    risk = RiskAssessment(level="low", rationale="...", typologies=[])

    assert "esgotar" in translate_risk_rationale_pt(risk)
