"""Financial crime / AML alert prioritization."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class AmlAlert(BaseModel):
    transaction_narrative: str
    kyc_summary: str
    alert_history: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    amount_usd: float
    extras: dict[str, Any] = Field(default_factory=dict)


def prioritize_aml_alert(alert: AmlAlert, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds(high_stakes_noul=0.88)
    client = get_client()

    response = client.system_one(
        state=alert.model_dump(),
        questions={
            "suspicious": Noul(instructions="The narrative and KYC context look suspicious for financial crime"),
            "sanctions_risk": Noul(instructions="There are sanctions or prohibited-party risk signals"),
            "structuring": Noul(instructions="Activity resembles structuring or layering"),
            "kyc_gap": Noul(instructions="KYC information is insufficient for the observed activity"),
            "entity_match_quality": Score(
                instructions="Quality of entity identification across inconsistent names/profiles",
                criteria=["Poor / ambiguous", "Adequate", "Strong identity linkage"],
            ),
            "risk": Score(
                instructions="Overall financial-crime risk",
                criteria=["Low", "Moderate", "High", "Critical"],
            ),
            "route": Choice(
                instructions="Investigator routing",
                criteria={
                    "auto_close": "Close as false positive",
                    "enhanced_kyc": "Request enhanced KYC",
                    "l1_queue": "Level-1 investigator queue",
                    "l2_urgent": "Urgent Level-2 investigation",
                    "file_sar": "Prepare SAR filing review",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]

    if a["sanctions_risk"]["noul"] >= thr.noul_yes or a["risk"]["score"] >= 2.5:
        decision, band, actions = "l2_urgent", ActionBand.CONFIRM, ["route:l2", "freeze_pending_tx", "notify:compliance"]
    elif a["suspicious"]["noul"] >= thr.high_stakes_noul and alert.amount_usd >= 10000:
        decision, band, actions = "file_sar", ActionBand.CONFIRM, ["prepare_sar_packet", "assign:senior_investigator"]
    elif a["kyc_gap"]["noul"] >= thr.noul_yes:
        decision, band, actions = "enhanced_kyc", ActionBand.AUTO, ["request_enhanced_kyc", "hold_alert"]
    elif a["suspicious"]["noul"] <= thr.noul_no and a["risk"]["score"] < 0.8 and a["route"]["confidence"] >= thr.auto_confidence:
        decision, band, actions = "auto_close", ActionBand.AUTO, ["close_false_positive"]
    else:
        decision, band, actions = "l1_queue", ActionBand.AUTO, ["route:l1", f"priority:{'high' if a['risk']['score'] >= 1.5 else 'normal'}"]

    return UseCaseResult(
        use_case="financial_crime",
        decision=decision,
        action_band=band.value,
        rationale=(
            f"suspicious={a['suspicious']['noul']:.2f}; sanctions={a['sanctions_risk']['noul']:.2f}; "
            f"risk={a['risk']['score']:.2f}; model_route={a['route']['choice']}"
        ),
        actions=actions,
        raw_answers=a,
        metadata={"amount_usd": alert.amount_usd, "entities": alert.entities},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
