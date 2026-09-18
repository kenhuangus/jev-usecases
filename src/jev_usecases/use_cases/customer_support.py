"""Customer support: intent routing, urgency, refund policy checks."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, DEFAULT, Thresholds, band_for_choice, band_for_noul
from jev_usecases.models import UseCaseResult


class SupportTicket(BaseModel):
    message: str
    subject: str | None = None
    account_tier: str = "standard"
    prior_refunds_30d: int = 0
    order: dict[str, Any] | None = None
    refund_policy: str = (
        "Duplicate charges and undelivered items are eligible for refund. "
        "Change-of-mind returns require unused goods within 30 days."
    )


class SupportConfig(BaseModel):
    thresholds: Thresholds = Field(default_factory=Thresholds)


def evaluate_support(ticket: SupportTicket, *, config: SupportConfig | None = None) -> UseCaseResult:
    config = config or SupportConfig()
    thr = config.thresholds
    client = get_client()

    state = {
        "subject": ticket.subject,
        "message": ticket.message,
        "account_tier": ticket.account_tier,
        "prior_refunds_30d": ticket.prior_refunds_30d,
        "order": ticket.order,
        "refund_policy": ticket.refund_policy,
    }

    response = client.system_one(
        state=state,
        questions={
            "department": Choice(
                instructions="Which team should handle this ticket?",
                criteria={
                    "billing": "Charges, invoices, refunds, payments",
                    "technical": "Bugs, outages, integrations, login failures",
                    "sales": "Pricing, upgrades, new accounts, demos",
                    "account": "Permissions, profile, security settings",
                    "other": "Does not fit the other teams",
                },
            ),
            "intent": Choice(
                instructions="What is the customer's primary intent?",
                criteria={
                    "refund": "Wants money back or credit",
                    "status": "Asking about order or ticket status",
                    "bug": "Reporting something broken",
                    "how_to": "Needs guidance using the product",
                    "complaint": "Unhappy and wants resolution beyond a simple lookup",
                    "other": "Other intent",
                },
            ),
            "urgency": Noul(
                instructions="The customer message conveys urgency or time-sensitivity",
                criteria={"true": "Explicit deadline or ASAP language", "false": "No time pressure"},
            ),
            "frustration": Score(
                instructions="How frustrated does the customer appear?",
                criteria=[
                    "Calm, factual",
                    "Frustrated but civil",
                    "Angry with strong language or threats to churn",
                ],
            ),
            "refund_requested": Noul(
                instructions="The customer is explicitly asking for a refund or credit",
            ),
            "policy_supports_refund": Noul(
                instructions=(
                    "Given refund_policy and order, the stated policy supports the refund "
                    "the customer is asking for in message"
                ),
            ),
            "churn_risk": Score(
                instructions="How likely is this customer to churn based on the message tone and ask?",
                criteria=["Low", "Moderate", "High"],
            ),
        },
    )

    raw = answers_to_dict(response)
    a = raw["answers"]

    dept = a["department"]["choice"]
    dept_conf = a["department"]["confidence"]
    intent = a["intent"]["choice"]
    intent_conf = a["intent"]["confidence"]
    urgent = a["urgency"]["noul"]
    frustration = a["frustration"]["score"]
    refund_req = a["refund_requested"]["noul"]
    policy_ok = a["policy_supports_refund"]["noul"]
    churn = a["churn_risk"]["score"]

    actions: list[str] = []
    band = band_for_choice(confidence=min(dept_conf, intent_conf), thresholds=thr)

    # Priority
    if urgent >= thr.noul_yes or frustration >= 1.5:
        actions.append("set_priority:high")
    elif urgent >= 0.5:
        actions.append("set_priority:medium")
    else:
        actions.append("set_priority:normal")

    # Routing
    queue = {
        "billing": "queue.billing",
        "technical": "queue.engineering",
        "sales": "queue.sales",
        "account": "queue.identity",
        "other": "queue.general",
    }[dept]
    actions.append(f"route:{queue}")

    decision = f"route_{dept}_{intent}"
    rationale_parts = [
        f"department={dept} (conf={dept_conf:.2f})",
        f"intent={intent} (conf={intent_conf:.2f})",
        f"urgency={urgent:.2f}",
        f"frustration={frustration:.2f}",
    ]

    # Refund automation — high stakes
    if refund_req >= thr.noul_yes:
        refund_band = band_for_noul(
            noul=min(refund_req, policy_ok),
            affirmative=True,
            high_stakes=True,
            thresholds=thr,
        )
        if (
            refund_band is ActionBand.AUTO
            and policy_ok >= thr.high_stakes_noul
            and ticket.prior_refunds_30d < 2
            and ticket.order is not None
        ):
            actions.append("start_refund_flow:auto")
            decision = "auto_refund"
            band = ActionBand.AUTO
        elif policy_ok >= thr.noul_yes:
            actions.append("start_refund_flow:confirm")
            decision = "refund_needs_confirmation"
            band = ActionBand.CONFIRM
        else:
            actions.append("escalate:billing_specialist")
            decision = "refund_policy_unclear"
            band = ActionBand.HUMAN
        rationale_parts.append(f"refund_req={refund_req:.2f} policy_ok={policy_ok:.2f}")

    if churn >= 1.5:
        actions.append("flag:retention_offer")
        if band is ActionBand.AUTO:
            band = ActionBand.CONFIRM

    if band is ActionBand.HUMAN or dept_conf < thr.human_confidence:
        actions.append("escalate:human_agent")
        decision = "human_review"
        band = ActionBand.HUMAN

    # VIP accounts get a human CC even on auto paths
    if ticket.account_tier in {"enterprise", "vip"} and "escalate:human_agent" not in actions:
        actions.append("notify:account_manager")

    return UseCaseResult(
        use_case="customer_support",
        decision=decision,
        action_band=band.value,
        rationale="; ".join(rationale_parts),
        actions=actions,
        raw_answers=a,
        metadata={"queue": queue, "account_tier": ticket.account_tier},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )


# Keep DEFAULT import used for re-export convenience
__all__ = ["SupportTicket", "SupportConfig", "evaluate_support", "DEFAULT"]
