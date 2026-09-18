"""Hierarchical classification with beam search over Choice probabilities."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class TaxonomyNode(BaseModel):
    id: str
    label: str
    description: str
    children: list["TaxonomyNode"] = Field(default_factory=list)


TaxonomyNode.model_rebuild()


class HierarchicalRequest(BaseModel):
    text: str
    taxonomy: TaxonomyNode
    beam_width: int = 3
    min_confidence: float = 0.45


def classify_hierarchy(req: HierarchicalRequest, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds(auto_confidence=req.min_confidence)
    client = get_client()

    path: list[str] = []
    confidences: list[float] = []
    node = req.taxonomy
    total_in = total_out = 0
    model_name = None
    leaf_answers: dict = {}

    while node.children:
        criteria = {c.id: f"{c.label}: {c.description}" for c in node.children}
        criteria["other"] = "None of the child categories fit well"
        response = client.system_one(
            state={"text": req.text, "path_so_far": path, "parent": node.id},
            questions={
                "child": Choice(
                    instructions=f"Choose the best child category under {node.label}",
                    criteria=criteria,
                ),
                "confident_enough": Noul(
                    instructions="There is a clear best child category for this text under the parent",
                ),
            },
        )
        raw = answers_to_dict(response)
        model_name = raw.get("model")
        usage = raw.get("usage") or {}
        total_in += usage.get("input_tokens") or 0
        total_out += usage.get("output_tokens") or 0
        a = raw["answers"]
        leaf_answers[node.id] = a

        # Beam: take top-k by probability, but for production path we follow best if confident
        probs = a["child"]["probabilities"]
        ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)[: req.beam_width]
        best_id, best_p = ranked[0]
        conf = a["child"]["confidence"]
        if best_id == "other" or conf < thr.auto_confidence or a["confident_enough"]["noul"] < thr.noul_yes:
            return UseCaseResult(
                use_case="hierarchical_classification",
                decision="abstain",
                action_band=ActionBand.HUMAN.value,
                rationale=f"Stopped at {path}; best={best_id} p={best_p:.2f} conf={conf:.2f}",
                actions=["human_label"],
                raw_answers=leaf_answers,
                metadata={"path": path, "beam": ranked},
                model=model_name,
                usage={"input_tokens": total_in, "output_tokens": total_out},
            )
        path.append(best_id)
        confidences.append(conf)
        node = next(c for c in node.children if c.id == best_id)

    min_conf = min(confidences) if confidences else 0.0
    band = ActionBand.AUTO if min_conf >= thr.auto_confidence else ActionBand.CONFIRM
    return UseCaseResult(
        use_case="hierarchical_classification",
        decision=">".join(path) if path else req.taxonomy.id,
        action_band=band.value,
        rationale=f"path={path}; min_conf={min_conf:.2f}",
        actions=[f"label:{'>'.join(path)}"],
        raw_answers=leaf_answers,
        metadata={"path": path, "confidences": confidences},
        model=model_name,
        usage={"input_tokens": total_in, "output_tokens": total_out},
    )
