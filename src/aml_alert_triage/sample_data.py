from __future__ import annotations

from .models import AlertPayload, EvidenceItem


SAMPLE_ALERTS: dict[str, AlertPayload] = {
    "alert-001": AlertPayload(
        alert_id="alert-001",
        customer_id="cust-100",
        alert_type="cash-structuring",
        amount=12800.0,
        currency="USD",
        description="Multiple cash deposits below the reporting threshold.",
    ),
    "alert-002": AlertPayload(
        alert_id="alert-002",
        customer_id="cust-200",
        alert_type="new-beneficiary",
        amount=2400.0,
        currency="USD",
        description="Payment to a newly observed beneficiary account.",
    ),
}

SAMPLE_EVIDENCE: dict[str, list[EvidenceItem]] = {
    "cust-100": [
        EvidenceItem(
            kind="transaction",
            subject="acct-001",
            details="Five cash deposits were made over three business days.",
            source="neo4j",
        ),
        EvidenceItem(
            kind="relationship",
            subject="cust-101",
            details="Shared address with another customer who had prior alerts.",
            source="neo4j",
        ),
    ],
    "cust-200": [],
}
