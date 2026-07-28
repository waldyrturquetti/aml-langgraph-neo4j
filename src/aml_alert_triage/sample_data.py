from __future__ import annotations

from .models import AlertPayload

# Each alert is a neutral monitoring trigger (a threshold or rule that fired)
# - it deliberately does not say what AML typology, if any, is actually
# behind it. The typology (cycle, structuring fan-out/fan-in, or nothing at
# all) is discovered by the workflow querying the transaction graph in
# graph_dataset.py, not by reading a label pre-baked into the input.
SAMPLE_ALERTS: dict[str, AlertPayload] = {
    "alert-001": AlertPayload(
        alert_id="alert-001",
        customer_id="cust-100",
        alert_type="periodic-review",
        amount=0.0,
        currency="BRL",
        description="Routine compliance review of an active account.",
    ),
    "alert-002": AlertPayload(
        alert_id="alert-002",
        customer_id="cust-200",
        alert_type="new-account-monitoring",
        amount=0.0,
        currency="BRL",
        description="New account monitoring window; limited history reviewed.",
    ),
    "alert-003": AlertPayload(
        alert_id="alert-003",
        customer_id="cust-300",
        alert_type="large-value-transaction",
        amount=9800.0,
        currency="BRL",
        description="A transfer above the monitoring threshold was flagged for review.",
    ),
    "alert-004": AlertPayload(
        alert_id="alert-004",
        customer_id="cust-400",
        alert_type="velocity-alert",
        amount=950.0,
        currency="BRL",
        description="Multiple outgoing transfers in a short window triggered a velocity rule.",
    ),
    "alert-005": AlertPayload(
        alert_id="alert-005",
        customer_id="cust-500",
        alert_type="manual-referral",
        amount=640.0,
        currency="BRL",
        description="Manually referred for review by a branch employee.",
    ),
    "alert-006": AlertPayload(
        alert_id="alert-006",
        customer_id="cust-600",
        alert_type="velocity-alert",
        amount=910.0,
        currency="BRL",
        description="Multiple incoming transfers in a short window triggered a velocity rule.",
    ),
}
