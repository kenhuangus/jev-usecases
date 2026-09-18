"""Trust & safety / content moderation."""

from __future__ import annotations

from pydantic import BaseModel
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class ModerationItem(BaseModel):
    content: str
    context: str | None = None
    community_standards: str = (
        "Disallow harassment, hate, sexual exploitation, credible threats, spam, "
        "scams, and doxxing. Allow heated but non-abusive disagreement."
    )


def moderate_content(item: ModerationItem, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()

    response = client.system_one(
        state=item.model_dump(),
        questions={
            "toxicity": Score(
                instructions="Toxicity / harassment level",
                criteria=["Civil", "Rude but allowed", "Harassing / abusive"],
            ),
            "spam": Noul(instructions="Content is spam or scam"),
            "threat": Noul(instructions="Content contains a credible threat of violence or harm"),
            "hate": Noul(instructions="Content is hate speech under the community standards"),
            "sexual": Noul(instructions="Content is sexually exploitative or otherwise disallowed sexual content"),
            "pii_dox": Noul(instructions="Content doxses or exposes personal data maliciously"),
            "severity": Score(
                instructions="Overall severity if action is needed",
                criteria=["None", "Warn-level", "Remove-level", "Ban-level"],
            ),
            "action": Choice(
                instructions="Moderation action",
                criteria={
                    "allow": "Allow",
                    "warn": "Warn the author",
                    "review": "Send to human review",
                    "remove": "Remove content",
                    "ban": "Remove and ban",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]

    hard = any(
        a[k]["noul"] >= thr.high_stakes_noul for k in ("threat", "hate", "sexual", "pii_dox")
    )
    if hard or a["severity"]["score"] >= 2.5:
        decision, band, actions = "ban" if a["threat"]["noul"] >= thr.noul_yes else "remove", ActionBand.BLOCK, [
            "remove_content",
            "notify:trust_safety",
        ]
        if decision == "ban":
            actions.append("ban_user_pending_appeal")
    elif a["spam"]["noul"] >= thr.noul_yes or a["toxicity"]["score"] >= 1.6:
        decision, band, actions = "remove", ActionBand.AUTO, ["remove_content", "warn_user"]
    elif a["action"]["choice"] == "warn" or a["severity"]["score"] >= 1.0:
        decision, band, actions = "warn", ActionBand.AUTO, ["warn_user"]
    elif a["action"]["choice"] == "allow" and a["action"]["confidence"] >= thr.auto_confidence:
        decision, band, actions = "allow", ActionBand.AUTO, ["allow"]
    else:
        decision, band, actions = "review", ActionBand.CONFIRM, ["queue:human_mods"]

    return UseCaseResult(
        use_case="moderation",
        decision=decision,
        action_band=band.value,
        rationale=(
            f"action_model={a['action']['choice']} conf={a['action']['confidence']:.2f}; "
            f"toxicity={a['toxicity']['score']:.2f}; severity={a['severity']['score']:.2f}"
        ),
        actions=actions,
        raw_answers=a,
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
