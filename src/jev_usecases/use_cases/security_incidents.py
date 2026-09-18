"""Security incident triage: close, queue, or contain."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class SecurityAlert(BaseModel):
    alert_name: str
    description: str
    host: str
    environment: str = "production"
    asset_criticality: str = "high"
    recent_events: list[str] = Field(default_factory=list)
    explainable_records: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def triage_security_incident(alert: SecurityAlert, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds(high_stakes_confidence=0.9, high_stakes_noul=0.9)
    client = get_client()

    state = alert.model_dump()
    response = client.system_one(
        state=state,
        questions={
            "unauthorized": Noul(
                instructions="The described activity appears unauthorized for this host and user context",
            ),
            "explained_by_record": Noul(
                instructions="An entry in explainable_records adequately explains this alert as benign",
            ),
            "evidence_strength": Score(
                instructions="How strong is the evidence that this alert is a real security incident?",
                criteria=["Weak / noisy", "Moderate", "Strong multi-signal evidence"],
            ),
            "blast_radius": Score(
                instructions="If this is malicious, how wide could the blast radius be?",
                criteria=["Single host", "Multiple hosts in one segment", "Org-wide credential or data risk"],
            ),
            "initial_disposition": Choice(
                instructions="Initial disposition before containment playbook",
                criteria={
                    "auto_close": "Benign and safe to close",
                    "notify_user": "Likely identity anomaly; notify the user",
                    "queue_tier2": "Needs analyst review",
                    "contain_now": "Contain immediately",
                },
            ),
            "credential_theft": Noul(
                instructions="Indicators suggest credential theft or dumping",
            ),
            "persistence": Noul(
                instructions="Indicators suggest attacker persistence on the host",
            ),
            "lateral_movement": Noul(
                instructions="Indicators suggest lateral movement beyond this host",
            ),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]

    unauthorized = a["unauthorized"]["noul"]
    explained = a["explained_by_record"]["noul"]
    evidence = a["evidence_strength"]["score"]
    blast = a["blast_radius"]["score"]
    disposition = a["initial_disposition"]["choice"]
    conf = a["initial_disposition"]["confidence"]

    actions: list[str] = []
    # Code-owned playbook
    if explained >= thr.high_stakes_noul and unauthorized <= thr.noul_no and evidence < 1.0:
        decision, band = "auto_close", ActionBand.AUTO
        actions = ["close_alert", "log:benign_explained"]
    elif (
        a["credential_theft"]["noul"] >= thr.noul_yes
        or a["persistence"]["noul"] >= thr.noul_yes
        or a["lateral_movement"]["noul"] >= thr.noul_yes
        or (unauthorized >= thr.high_stakes_noul and alert.environment == "production")
    ):
        decision, band = "contain_now", ActionBand.AUTO if conf >= thr.high_stakes_confidence else ActionBand.CONFIRM
        actions = ["isolate_host", "disable_sessions", "escalate:urgent_soc"]
        if a["credential_theft"]["noul"] >= thr.noul_yes:
            actions.append("force_password_reset")
        if a["lateral_movement"]["noul"] >= thr.noul_yes:
            actions.append("block_lateral_paths")
    elif disposition == "notify_user":
        decision, band = "notify_user", ActionBand.AUTO if conf >= thr.auto_confidence else ActionBand.CONFIRM
        actions = ["notify_user", "queue:identity"]
    else:
        decision, band = "queue_tier2", ActionBand.CONFIRM if conf < thr.auto_confidence else ActionBand.AUTO
        actions = ["queue:tier2", f"priority:{'p1' if blast >= 1.5 else 'p2'}"]

    if alert.asset_criticality == "critical" and decision != "auto_close":
        actions.append("page:security_oncall")
        if band is ActionBand.AUTO:
            band = ActionBand.CONFIRM

    return UseCaseResult(
        use_case="security_incidents",
        decision=decision,
        action_band=band.value,
        rationale=(
            f"disposition={disposition} conf={conf:.2f}; unauthorized={unauthorized:.2f}; "
            f"explained={explained:.2f}; evidence={evidence:.2f}; blast={blast:.2f}"
        ),
        actions=actions,
        raw_answers=a,
        metadata={"host": alert.host, "environment": alert.environment},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
