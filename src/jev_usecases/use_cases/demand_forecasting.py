"""Demand forecasting semantic feature extraction from text signals."""

from __future__ import annotations

from pydantic import BaseModel
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class DemandText(BaseModel):
    source: str  # inquiry | sales_note | review | ticket | market_report
    text: str
    product: str | None = None


def extract_demand_features(item: DemandText, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    _ = thresholds or Thresholds()
    client = get_client()
    response = client.system_one(
        state=item.model_dump(),
        questions={
            "purchase_intent": Score(
                instructions="Purchase intent expressed",
                criteria=["None", "Curious", "Comparing options", "Ready to buy"],
            ),
            "urgency": Score(
                instructions="Urgency of demand",
                criteria=["None", "Soon", "Immediate"],
            ),
            "product_interest": Noul(
                instructions="The text expresses interest in the specified product (or a clear product category if product is null)",
            ),
            "supply_concern": Noul(instructions="The text raises supply, stockout, or fulfillment concerns"),
            "competitive_pressure": Noul(instructions="The text indicates competitive pressure or switching consideration"),
            "theme": Choice(
                instructions="Dominant demand theme",
                criteria={
                    "price": "Price sensitivity",
                    "quality": "Quality / performance",
                    "availability": "Availability / shipping",
                    "feature": "Feature request / gap",
                    "support": "Support experience",
                    "other": "Other",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]
    features = {
        "purchase_intent": a["purchase_intent"]["score"] / 3,
        "urgency": a["urgency"]["score"] / 2,
        "product_interest": a["product_interest"]["noul"],
        "supply_concern": a["supply_concern"]["noul"],
        "competitive_pressure": a["competitive_pressure"]["noul"],
        "theme": a["theme"]["choice"],
        "theme_confidence": a["theme"]["confidence"],
    }
    return UseCaseResult(
        use_case="demand_forecasting",
        decision="features_extracted",
        action_band=ActionBand.AUTO.value,
        rationale=f"theme={features['theme']}; intent={features['purchase_intent']:.2f}; urgency={features['urgency']:.2f}",
        actions=["write_features:forecasting_store"],
        raw_answers=a,
        metadata={"features": features, "source": item.source, "product": item.product},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
