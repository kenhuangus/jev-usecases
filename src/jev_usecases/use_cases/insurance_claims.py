"""Insurance claims triage and complexity/fraud scoring."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class InsuranceClaim(BaseModel):
    fnol: str
    adjuster_notes: str | None = None
    documents_summary: str | None = None
    claim_amount_usd: float
    policy_type: str
    prior_claims_24m: int = 0
    extras: dict[str, Any] = Field(default_factory=dict)


def triage_claim(claim: InsuranceClaim, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()

    response = client.system_one(
        state=claim.model_dump(),
        questions={
            "complexity": Score(
                instructions="How complex is this claim to adjudicate?",
                criteria=["Straight-through simple", "Needs specialist judgment", "Highly complex / litigated risk"],
            ),
            "missing_info": Noul(instructions="Material information is missing to decide the claim"),
            "fraud_indicators": Noul(instructions="The claim shows potential fraud indicators"),
            "coverage_likely": Noul(instructions="Based on the FNOL and policy_type, coverage is likely"),
            "severity": Score(
                instructions="Loss severity relative to typical claims of this policy type",
                criteria=["Low", "Moderate", "Severe"],
            ),
            "route": Choice(
                instructions="Claims handling route",
                criteria={
                    "stp": "Straight-through processing",
                    "request_docs": "Request more documents",
                    "specialist": "Specialist adjuster",
                    "siu": "Special Investigation Unit",
                    "human_urgent": "Urgent human adjuster",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]
    route = a["route"]["choice"]
    conf = a["route"]["confidence"]

    if a["fraud_indicators"]["noul"] >= thr.noul_yes or claim.prior_claims_24m >= 3:
        decision, band, actions = "siu", ActionBand.CONFIRM, ["route:siu", "freeze_payment"]
    elif a["missing_info"]["noul"] >= thr.noul_yes:
        decision, band, actions = "request_docs", ActionBand.AUTO, ["request_documents", "hold_decision"]
    elif (
        a["complexity"]["score"] < 0.8
        and a["coverage_likely"]["noul"] >= thr.noul_yes
        and claim.claim_amount_usd < 5000
        and conf >= thr.auto_confidence
    ):
        decision, band, actions = "stp", ActionBand.AUTO, ["straight_through_pay", "generate_settlement"]
    elif a["severity"]["score"] >= 1.5 or claim.claim_amount_usd >= 50000:
        decision, band, actions = "human_urgent", ActionBand.CONFIRM, ["assign:senior_adjuster", "sla:4h"]
    else:
        decision = "specialist" if route == "specialist" else route
        band = ActionBand.AUTO if conf >= thr.auto_confidence else ActionBand.CONFIRM
        actions = [f"route:{decision}"]

    return UseCaseResult(
        use_case="insurance_claims",
        decision=decision,
        action_band=band.value,
        rationale=(
            f"route_model={route} conf={conf:.2f}; complexity={a['complexity']['score']:.2f}; "
            f"fraud={a['fraud_indicators']['noul']:.2f}; missing={a['missing_info']['noul']:.2f}"
        ),
        actions=actions,
        raw_answers=a,
        metadata={"claim_amount_usd": claim.claim_amount_usd, "policy_type": claim.policy_type},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
