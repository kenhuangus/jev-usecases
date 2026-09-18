"""Model routing: pick the cheapest capable LLM for a request."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds, band_for_choice
from jev_usecases.models import UseCaseResult


class ModelRouteRequest(BaseModel):
    prompt: str
    domain_hint: str | None = None
    available_models: dict[str, str] = Field(
        default_factory=lambda: {
            "fast": "Inexpensive model for lookups, extraction, and localized edits",
            "balanced": "Mid-tier model for multi-step but routine work",
            "powerful": "Frontier model for architecture, novel bugs, and high-stakes decisions",
        }
    )


def route_model(req: ModelRouteRequest, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()

    state = {"prompt": req.prompt, "domain_hint": req.domain_hint}
    response = client.system_one(
        state=state,
        questions={
            "model": Choice(
                instructions="Choose the least costly model that can complete this task well",
                criteria=req.available_models,
            ),
            "domain": Choice(
                instructions="What domain does this request belong to?",
                criteria={
                    "coding": "Software engineering or debugging",
                    "writing": "Prose, docs, marketing copy",
                    "data": "Analytics, SQL, spreadsheet reasoning",
                    "support": "Customer support style Q&A",
                    "other": "Other",
                },
            ),
            "difficulty": Score(
                instructions="How difficult is this request?",
                criteria=[
                    "Trivial lookup or single-step edit",
                    "Multi-step but well-scoped",
                    "Ambiguous, architectural, or high-stakes",
                ],
            ),
            "needs_tools": Noul(
                instructions="Completing this request likely requires tool use or code execution",
            ),
            "high_risk": Noul(
                instructions="An incorrect answer would cause significant user or business harm",
            ),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]
    choice = a["model"]["choice"]
    conf = a["model"]["confidence"]
    difficulty = a["difficulty"]["score"]
    high_risk = a["high_risk"]["noul"]

    band = band_for_choice(confidence=conf, thresholds=thr)
    # Force upgrade when risk or difficulty is high
    if high_risk >= thr.noul_yes or difficulty >= 1.6:
        if choice != "powerful":
            choice = "powerful"
            band = ActionBand.AUTO
        if conf < thr.auto_confidence:
            band = ActionBand.CONFIRM

    if conf < thr.human_confidence:
        band = ActionBand.HUMAN
        choice = "powerful"

    return UseCaseResult(
        use_case="model_routing",
        decision=f"use_model:{choice}",
        action_band=band.value,
        rationale=(
            f"model={a['model']['choice']} conf={conf:.2f}; "
            f"domain={a['domain']['choice']}; difficulty={difficulty:.2f}; "
            f"needs_tools={a['needs_tools']['noul']:.2f}; high_risk={high_risk:.2f}"
        ),
        actions=[f"invoke_llm:{choice}", f"domain:{a['domain']['choice']}"],
        raw_answers=a,
        metadata={"selected_model": choice, "original_choice": a["model"]["choice"]},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
