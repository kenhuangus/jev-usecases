"""Invoice processing harness: pay, hold, dispute, or fraud-review."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class InvoicePacket(BaseModel):
    invoice_text: str
    vendor_name: str
    expected_vendor: str
    company_name: str
    expected_company: str
    po: dict[str, Any] | None = None
    delivery: dict[str, Any] | None = None
    amount_usd: float
    already_paid: bool = False
    prior_invoices: list[str] = Field(default_factory=list)


def process_invoice(packet: InvoicePacket, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds(high_stakes_noul=0.9, high_stakes_confidence=0.9)
    client = get_client()

    # Deterministic gates first (code owns exact checks)
    if packet.already_paid:
        return UseCaseResult(
            use_case="invoice_processing",
            decision="duplicate_paid",
            action_band=ActionBand.BLOCK.value,
            rationale="Invoice marked already_paid in system of record",
            actions=["mark_duplicate", "do_not_pay"],
            raw_answers={},
            metadata={"amount_usd": packet.amount_usd},
        )

    response = client.system_one(
        state=packet.model_dump(),
        questions={
            "is_invoice": Noul(instructions="The document is a real vendor invoice"),
            "wrong_vendor": Noul(
                instructions="vendor_name does not match expected_vendor (including lookalike fraud)",
            ),
            "wrong_company": Noul(
                instructions="The invoice is billed to the wrong company versus expected_company",
            ),
            "fraud_pattern": Noul(
                instructions="The invoice shows fraud patterns (lookalike domain, urgent wire change, etc.)",
            ),
            "matches_po": Noul(
                instructions="Line items and amounts are consistent with the purchase order when present",
            ),
            "matches_delivery": Noul(
                instructions="What was delivered supports paying this invoice",
            ),
            "needs_docs": Noul(
                instructions="Payment should be held pending missing supporting documents",
            ),
            "line_dispute": Noul(
                instructions="One or more lines should be disputed rather than paid in full",
            ),
            "approval_needed": Noul(
                instructions="This invoice requires additional managerial approval before payment",
            ),
            "risk": Score(
                instructions="Overall payment risk for this invoice",
                criteria=["Low", "Moderate", "High"],
            ),
            "action": Choice(
                instructions="Recommended AP action",
                criteria={
                    "pay": "Pay in full",
                    "schedule": "Schedule payment",
                    "short_pay": "Pay undisputed portion only",
                    "route_approval": "Route for approval",
                    "hold_docs": "Hold for documents",
                    "request_correction": "Request corrected invoice",
                    "dispute": "Dispute lines",
                    "fraud_review": "Send to fraud review",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]

    # Immediate terminal conditions
    if a["fraud_pattern"]["noul"] >= thr.noul_yes or a["wrong_vendor"]["noul"] >= thr.high_stakes_noul:
        return UseCaseResult(
            use_case="invoice_processing",
            decision="fraud_review",
            action_band=ActionBand.BLOCK.value,
            rationale=f"fraud={a['fraud_pattern']['noul']:.2f} wrong_vendor={a['wrong_vendor']['noul']:.2f}",
            actions=["fraud_review", "freeze_vendor_change", "do_not_pay"],
            raw_answers=a,
            model=raw.get("model"),
            usage=raw.get("usage"),
        )
    if a["is_invoice"]["noul"] <= thr.noul_no or a["wrong_company"]["noul"] >= thr.noul_yes:
        return UseCaseResult(
            use_case="invoice_processing",
            decision="request_correction",
            action_band=ActionBand.CONFIRM.value,
            rationale="Document is not a valid payable invoice for this company",
            actions=["request_corrected_invoice", "do_not_pay"],
            raw_answers=a,
            model=raw.get("model"),
            usage=raw.get("usage"),
        )

    action = a["action"]["choice"]
    conf = a["action"]["confidence"]
    actions: list[str] = []

    if a["needs_docs"]["noul"] >= thr.noul_yes:
        action = "hold_docs"
        actions = ["hold_for_documents"]
        band = ActionBand.AUTO
    elif a["line_dispute"]["noul"] >= thr.noul_yes:
        action = "dispute"
        actions = ["dispute_lines", "short_pay_undisputed"]
        band = ActionBand.CONFIRM
    elif a["approval_needed"]["noul"] >= thr.noul_yes or packet.amount_usd >= 10000:
        action = "route_approval"
        actions = ["route_for_approval"]
        band = ActionBand.CONFIRM
    elif (
        action in {"pay", "schedule"}
        and a["matches_po"]["noul"] >= thr.noul_yes
        and a["matches_delivery"]["noul"] >= thr.noul_yes
        and a["risk"]["score"] < 1.2
        and conf >= thr.high_stakes_confidence
    ):
        actions = ["pay" if action == "pay" else "schedule_payment"]
        band = ActionBand.AUTO
    else:
        actions = [f"ap_action:{action}"]
        band = ActionBand.CONFIRM if conf < thr.high_stakes_confidence else ActionBand.AUTO

    return UseCaseResult(
        use_case="invoice_processing",
        decision=action,
        action_band=band.value,
        rationale=(
            f"action={a['action']['choice']} conf={conf:.2f}; risk={a['risk']['score']:.2f}; "
            f"po={a['matches_po']['noul']:.2f}; delivery={a['matches_delivery']['noul']:.2f}"
        ),
        actions=actions,
        raw_answers=a,
        metadata={"amount_usd": packet.amount_usd, "vendor": packet.vendor_name},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
