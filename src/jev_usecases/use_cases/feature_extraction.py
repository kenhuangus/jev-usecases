"""ML feature extraction: convert free text into calibrated numeric features."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class FeatureSpec(BaseModel):
    name: str
    kind: str  # noul | score | choice
    instructions: str
    criteria: list[str] | dict[str, str] | None = None


class FeatureExtractionRequest(BaseModel):
    record_id: str
    text: str
    extras: dict = Field(default_factory=dict)
    specs: list[FeatureSpec]


def extract_features(req: FeatureExtractionRequest, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    _ = thresholds or Thresholds()
    client = get_client()
    questions = {}
    for spec in req.specs:
        if spec.kind == "noul":
            questions[spec.name] = Noul(instructions=spec.instructions)
        elif spec.kind == "score":
            if not isinstance(spec.criteria, list) or len(spec.criteria) < 2:
                raise ValueError(f"Score feature {spec.name} needs list criteria with >=2 levels")
            questions[spec.name] = Score(instructions=spec.instructions, criteria=spec.criteria)
        elif spec.kind == "choice":
            if not isinstance(spec.criteria, dict) or not spec.criteria:
                raise ValueError(f"Choice feature {spec.name} needs dict criteria")
            questions[spec.name] = Choice(instructions=spec.instructions, criteria=spec.criteria)
        else:
            raise ValueError(f"Unknown feature kind: {spec.kind}")

    response = client.system_one(
        state={"record_id": req.record_id, "text": req.text, "extras": req.extras},
        questions=questions,
    )
    raw = answers_to_dict(response)
    a = raw["answers"]

    features: dict = {}
    for spec in req.specs:
        ans = a[spec.name]
        if spec.kind == "noul":
            features[spec.name] = ans["noul"]
        elif spec.kind == "score":
            # Normalize to 0-1 using max level index
            max_level = max(len(spec.criteria) - 1, 1)  # type: ignore[arg-type]
            features[spec.name] = ans["score"] / max_level
            features[f"{spec.name}__confidence"] = ans["confidence"]
        else:
            features[spec.name] = ans["choice"]
            features[f"{spec.name}__confidence"] = ans["confidence"]
            for opt, p in ans["probabilities"].items():
                features[f"{spec.name}__p_{opt}"] = p

    return UseCaseResult(
        use_case="feature_extraction",
        decision="features_ready",
        action_band=ActionBand.AUTO.value,
        rationale=f"extracted {len(req.specs)} features for {req.record_id}",
        actions=["upsert_feature_store"],
        raw_answers=a,
        metadata={"record_id": req.record_id, "features": features},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
