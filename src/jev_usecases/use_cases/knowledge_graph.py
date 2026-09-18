"""Knowledge graph entity alignment / relationship classification."""

from __future__ import annotations

from pydantic import BaseModel
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class EntityPair(BaseModel):
    left: dict
    right: dict
    left_source: str
    right_source: str


def align_entities(pair: EntityPair, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()
    response = client.system_one(
        state=pair.model_dump(),
        questions={
            "same_entity": Score(
                instructions="Do these records describe the same real-world entity?",
                criteria=[
                    "Different entities — leave unlinked",
                    "Uncertain — needs curator review",
                    "Same entity — merge/link",
                ],
            ),
            "contradiction": Noul(instructions="The two records contain contradictory facts that block auto-merge"),
            "entity_type": Choice(
                instructions="Shared entity type if linked",
                criteria={
                    "person": "Person",
                    "org": "Organization",
                    "product": "Product",
                    "location": "Location",
                    "other": "Other / unknown",
                },
            ),
            "relation_if_distinct": Choice(
                instructions="If they are distinct, what relation is most likely?",
                criteria={
                    "none": "No meaningful relation",
                    "parent_child": "Parent/child or brand/variant",
                    "alias": "Alias / alternate name for same concept but weak evidence",
                    "competitor": "Competitors",
                    "other": "Other relation",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]
    score = a["same_entity"]["score"]
    conf = a["same_entity"]["confidence"]

    if a["contradiction"]["noul"] >= thr.noul_yes:
        decision, band, actions = "curator_review", ActionBand.CONFIRM, ["queue:curator", "flag:contradiction"]
    elif score >= 1.6 and conf >= thr.auto_confidence:
        decision, band, actions = "merge", ActionBand.AUTO, ["link_entities", f"type:{a['entity_type']['choice']}"]
    elif score <= 0.6 and conf >= thr.auto_confidence:
        decision, band, actions = "unlink", ActionBand.AUTO, [
            "leave_unlinked",
            f"relation:{a['relation_if_distinct']['choice']}",
        ]
    else:
        decision, band, actions = "curator_review", ActionBand.CONFIRM, ["queue:curator"]

    return UseCaseResult(
        use_case="knowledge_graph",
        decision=decision,
        action_band=band.value,
        rationale=f"same_entity={score:.2f} conf={conf:.2f}; contradiction={a['contradiction']['noul']:.2f}",
        actions=actions,
        raw_answers=a,
        metadata={"left_source": pair.left_source, "right_source": pair.right_source},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
