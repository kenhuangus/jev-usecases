"""Lead generation / ICP matching and prioritization."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class IdealCustomerProfile(BaseModel):
    industries: list[str]
    company_sizes: list[str]
    buyer_titles: list[str]
    pains: list[str]
    disqualifiers: list[str] = Field(default_factory=list)


class Lead(BaseModel):
    company_profile: str
    executive_bio: str | None = None
    inbound_message: str | None = None
    icp: IdealCustomerProfile


def score_lead(lead: Lead, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()

    response = client.system_one(
        state={
            "company_profile": lead.company_profile,
            "executive_bio": lead.executive_bio,
            "inbound_message": lead.inbound_message,
            "icp": lead.icp.model_dump(),
        },
        questions={
            "industry_fit": Noul(instructions="Company industry fits the ICP industries list"),
            "size_fit": Noul(instructions="Company size fits the ICP company_sizes list"),
            "buyer_relevance": Noul(instructions="The contact looks like a relevant buyer per buyer_titles"),
            "pain_match": Noul(instructions="Evidence of pains listed in the ICP"),
            "purchase_intent": Score(
                instructions="How strong is purchase intent from the inbound message and profile?",
                criteria=["None", "Exploratory", "Active evaluation", "Ready to buy"],
            ),
            "disqualified": Noul(instructions="A disqualifier from the ICP clearly applies"),
            "priority": Choice(
                instructions="Sales priority bucket",
                criteria={
                    "discard": "Not a fit",
                    "nurture": "Fit but low intent",
                    "sdr_queue": "Worth SDR outreach",
                    "ae_hot": "Hot lead for AE",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]

    if a["disqualified"]["noul"] >= thr.noul_yes:
        return UseCaseResult(
            use_case="lead_generation",
            decision="discard",
            action_band=ActionBand.AUTO.value,
            rationale=f"disqualified={a['disqualified']['noul']:.2f}",
            actions=["discard", "log:disqualifier"],
            raw_answers=a,
            model=raw.get("model"),
            usage=raw.get("usage"),
        )

    fit = (
        0.3 * a["industry_fit"]["noul"]
        + 0.2 * a["size_fit"]["noul"]
        + 0.25 * a["buyer_relevance"]["noul"]
        + 0.25 * a["pain_match"]["noul"]
    )
    intent = a["purchase_intent"]["score"] / 3
    composite = 0.6 * fit + 0.4 * intent
    model_priority = a["priority"]["choice"]
    conf = a["priority"]["confidence"]

    if composite >= 0.75 and intent >= 0.5:
        decision, actions = "ae_hot", ["route:ae", "sla:4h"]
        band = ActionBand.AUTO if conf >= thr.auto_confidence else ActionBand.CONFIRM
    elif composite >= 0.55:
        decision, actions = "sdr_queue", ["route:sdr", "sequence:default"]
        band = ActionBand.AUTO
    elif composite >= 0.35:
        decision, actions = "nurture", ["add:nurture_campaign"]
        band = ActionBand.AUTO
    else:
        decision, actions = "discard", ["discard"]
        band = ActionBand.AUTO

    # Prefer model priority when confidence is high and not contradictory
    if conf >= thr.auto_confidence and model_priority != decision:
        if {model_priority, decision} <= {"sdr_queue", "ae_hot", "nurture"}:
            decision = model_priority
            actions = [f"route:{decision}"]

    return UseCaseResult(
        use_case="lead_generation",
        decision=decision,
        action_band=band.value,
        rationale=f"composite={composite:.2f}; fit={fit:.2f}; intent={intent:.2f}; model={model_priority} conf={conf:.2f}",
        actions=actions,
        raw_answers=a,
        metadata={"composite": composite, "fit": fit, "intent": intent},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
