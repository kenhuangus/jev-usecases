"""E-commerce marketplace listing moderation and attribute judgment."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class ProductListing(BaseModel):
    title: str
    description: str
    category_hint: str | None = None
    seller_history: str | None = None
    policy: str = (
        "Prohibit counterfeits, weapons, adult content, medical claims without approval, "
        "and review manipulation."
    )
    allowed_categories: dict[str, str] = Field(
        default_factory=lambda: {
            "electronics": "Consumer electronics and accessories",
            "apparel": "Clothing and fashion",
            "home": "Home and garden",
            "other": "Other allowed category",
            "prohibited": "Listing should not be sold on the marketplace",
        }
    )


def moderate_listing(listing: ProductListing, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()

    response = client.system_one(
        state=listing.model_dump(),
        questions={
            "category": Choice(
                instructions="Normalize this listing into a category",
                criteria=listing.allowed_categories,
            ),
            "counterfeit": Noul(instructions="Signals suggest a counterfeit or trademark-infringing product"),
            "prohibited_item": Noul(instructions="The listing violates marketplace prohibited-item policy"),
            "review_abuse": Noul(instructions="Seller history or listing text suggests review abuse"),
            "medical_claim": Noul(instructions="The listing makes unapproved medical or health claims"),
            "quality": Score(
                instructions="Listing quality for customer trust",
                criteria=["Poor / spammy", "Adequate", "High quality"],
            ),
            "disposition": Choice(
                instructions="Moderation disposition",
                criteria={
                    "publish": "Publish listing",
                    "edit_required": "Require seller edits",
                    "human_review": "Send to human moderators",
                    "takedown": "Remove / reject listing",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]

    if (
        a["category"]["choice"] == "prohibited"
        or a["prohibited_item"]["noul"] >= thr.noul_yes
        or a["counterfeit"]["noul"] >= thr.high_stakes_noul
    ):
        decision, band, actions = "takedown", ActionBand.BLOCK, ["reject_listing", "notify:seller", "log:policy"]
    elif a["review_abuse"]["noul"] >= thr.noul_yes or a["medical_claim"]["noul"] >= thr.noul_yes:
        decision, band, actions = "human_review", ActionBand.CONFIRM, ["queue:trust_safety"]
    elif a["quality"]["score"] < 0.8 or a["disposition"]["choice"] == "edit_required":
        decision, band, actions = "edit_required", ActionBand.AUTO, ["request_seller_edits"]
    elif a["disposition"]["choice"] == "publish" and a["disposition"]["confidence"] >= thr.auto_confidence:
        decision, band, actions = "publish", ActionBand.AUTO, [f"publish:{a['category']['choice']}"]
    else:
        decision, band, actions = "human_review", ActionBand.CONFIRM, ["queue:moderation"]

    return UseCaseResult(
        use_case="ecommerce",
        decision=decision,
        action_band=band.value,
        rationale=(
            f"category={a['category']['choice']}; quality={a['quality']['score']:.2f}; "
            f"counterfeit={a['counterfeit']['noul']:.2f}; disposition={a['disposition']['choice']}"
        ),
        actions=actions,
        raw_answers=a,
        metadata={"title": listing.title},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
