"""General risk assessment from unstructured incident/vendor notes."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class RiskPacket(BaseModel):
    text: str
    context: str | None = None
    risk_types: dict[str, str] = Field(
        default_factory=lambda: {
            "cyber": "Cybersecurity / IT risk",
            "operational": "Operational disruption",
            "financial": "Financial loss risk",
            "compliance": "Regulatory/compliance risk",
            "reputational": "Brand/reputation risk",
            "other": "Other",
        }
    )


def assess_risk(packet: RiskPacket, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()
    response = client.system_one(
        state=packet.model_dump(),
        questions={
            "risk_type": Choice(instructions="Primary risk type", criteria=packet.risk_types),
            "suspicious": Noul(instructions="There are suspicious characteristics requiring investigation"),
            "severity": Score(
                instructions="Severity of the risk",
                criteria=["Low", "Moderate", "High", "Critical"],
            ),
            "urgency": Score(
                instructions="Urgency of response",
                criteria=["Monitor", "Plan response this week", "Act within 24h", "Act now"],
            ),
            "escalate": Noul(instructions="This should be escalated to a human risk owner immediately"),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]
    severity = a["severity"]["score"]
    urgency = a["urgency"]["score"]

    if a["escalate"]["noul"] >= thr.noul_yes or severity >= 2.5 or urgency >= 2.5:
        decision, band, actions = "escalate", ActionBand.CONFIRM, ["page:risk_owner", f"label:{a['risk_type']['choice']}"]
    elif severity >= 1.5:
        decision, band, actions = "priority_review", ActionBand.AUTO, ["queue:risk_review", "sla:24h"]
    elif a["suspicious"]["noul"] >= thr.noul_yes:
        decision, band, actions = "investigate", ActionBand.AUTO, ["open:investigation"]
    else:
        decision, band, actions = "monitor", ActionBand.AUTO, ["log:monitor"]

    return UseCaseResult(
        use_case="risk_assessment",
        decision=decision,
        action_band=band.value,
        rationale=f"type={a['risk_type']['choice']}; severity={severity:.2f}; urgency={urgency:.2f}",
        actions=actions,
        raw_answers=a,
        metadata={"features": {"severity": severity, "urgency": urgency, "suspicious": a["suspicious"]["noul"]}},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
