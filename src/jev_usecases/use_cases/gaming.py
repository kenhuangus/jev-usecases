"""Gaming: player report / chat moderation and churn signals."""

from __future__ import annotations

from pydantic import BaseModel
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class PlayerSignal(BaseModel):
    kind: str  # report | chat | review | support
    text: str
    player_id: str
    match_context: str | None = None


def evaluate_player_signal(signal: PlayerSignal, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()
    response = client.system_one(
        state=signal.model_dump(),
        questions={
            "abuse": Noul(instructions="This indicates abuse, harassment, or toxic behavior worth action"),
            "cheating": Noul(instructions="This indicates cheating or account sharing suspicion"),
            "frustration": Score(
                instructions="Player frustration level",
                criteria=["Calm", "Frustrated", "Highly upset / churn risk"],
            ),
            "engagement": Score(
                instructions="Engagement signal strength",
                criteria=["Disengaged", "Neutral", "Highly engaged"],
            ),
            "support_intent": Choice(
                instructions="If this is a support-like message, what is needed?",
                criteria={
                    "none": "Not a support request",
                    "bug": "Bug report",
                    "billing": "Billing / purchases",
                    "account": "Account recovery / access",
                    "other": "Other support",
                },
            ),
            "action": Choice(
                instructions="Recommended player-ops action",
                criteria={
                    "ignore": "No action",
                    "mute_warn": "Mute or warn",
                    "ban_review": "Ban review",
                    "support_route": "Route to player support",
                    "retention": "Trigger retention offer",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]

    if a["cheating"]["noul"] >= thr.noul_yes or a["abuse"]["noul"] >= thr.high_stakes_noul:
        decision, band, actions = "ban_review", ActionBand.CONFIRM, ["queue:trust_safety", "snapshot:match_logs"]
    elif a["abuse"]["noul"] >= thr.noul_yes:
        decision, band, actions = "mute_warn", ActionBand.AUTO, ["warn_or_mute"]
    elif a["frustration"]["score"] >= 1.6 and a["engagement"]["score"] <= 1.0:
        decision, band, actions = "retention", ActionBand.AUTO, ["trigger:retention_campaign", "notify:community_manager"]
    elif a["support_intent"]["choice"] != "none":
        decision, band, actions = "support_route", ActionBand.AUTO, [f"route:support_{a['support_intent']['choice']}"]
    else:
        decision, band, actions = "ignore", ActionBand.AUTO, ["no_action"]

    return UseCaseResult(
        use_case="gaming",
        decision=decision,
        action_band=band.value,
        rationale=(
            f"abuse={a['abuse']['noul']:.2f}; cheating={a['cheating']['noul']:.2f}; "
            f"frustration={a['frustration']['score']:.2f}; action_model={a['action']['choice']}"
        ),
        actions=actions,
        raw_answers=a,
        metadata={"player_id": signal.player_id, "kind": signal.kind},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
