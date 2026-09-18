"""Advertising brand-safety and claim compliance."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class AdPacket(BaseModel):
    creative_copy: str
    landing_page_summary: str
    placement_context: str
    brand_rules: str
    prohibited_claims: list[str] = Field(default_factory=list)


def review_ad(ad: AdPacket, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()
    prohibited_q = {
        f"claim_{i}": Noul(instructions=f"Creative or landing page makes prohibited claim: {c}")
        for i, c in enumerate(ad.prohibited_claims)
    }
    response = client.system_one(
        state=ad.model_dump(),
        questions={
            **prohibited_q,
            "brand_safe": Noul(instructions="Placement context is brand-safe for this advertiser"),
            "audience_suitable": Noul(instructions="Creative is suitable for the intended audience/placement"),
            "lp_alignment": Score(
                instructions="How well does the ad creative align with the landing page?",
                criteria=["Mismatch / bait", "Partial alignment", "Strong alignment"],
            ),
            "creative_quality": Score(
                instructions="Creative quality",
                criteria=["Poor", "Acceptable", "Strong"],
            ),
            "regulatory": Noul(instructions="Creative raises regulatory compliance concerns under brand_rules"),
            "disposition": Choice(
                instructions="Ad review disposition",
                criteria={
                    "approve": "Approve",
                    "revise": "Request creative revisions",
                    "reject": "Reject",
                    "legal_review": "Send to legal/compliance",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]
    prohibited_hits = [
        ad.prohibited_claims[i]
        for i in range(len(ad.prohibited_claims))
        if a[f"claim_{i}"]["noul"] >= thr.noul_yes
    ]

    if prohibited_hits or a["regulatory"]["noul"] >= thr.noul_yes:
        decision, band, actions = "legal_review", ActionBand.BLOCK, ["hold_campaign", "escalate:legal"]
    elif a["brand_safe"]["noul"] <= thr.noul_no or a["lp_alignment"]["score"] < 0.8:
        decision, band, actions = "reject", ActionBand.AUTO, ["reject_creative"]
    elif a["disposition"]["choice"] == "revise" or a["creative_quality"]["score"] < 1.0:
        decision, band, actions = "revise", ActionBand.AUTO, ["request_revisions"]
    elif a["disposition"]["choice"] == "approve" and a["disposition"]["confidence"] >= thr.auto_confidence:
        decision, band, actions = "approve", ActionBand.AUTO, ["approve_creative"]
    else:
        decision, band, actions = "legal_review", ActionBand.CONFIRM, ["queue:ad_ops"]

    return UseCaseResult(
        use_case="advertising",
        decision=decision,
        action_band=band.value,
        rationale=f"prohibited={prohibited_hits}; lp={a['lp_alignment']['score']:.2f}; brand_safe={a['brand_safe']['noul']:.2f}",
        actions=actions,
        raw_answers=a,
        metadata={"prohibited_hits": prohibited_hits},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
