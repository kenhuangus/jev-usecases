"""Citation verification: does the source support the claim?"""

from __future__ import annotations

from pydantic import BaseModel
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class CitationCheck(BaseModel):
    claim: str
    quote: str
    source_context: str
    source_id: str | None = None


def verify_citation(check: CitationCheck, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()

    response = client.system_one(
        state={
            "claim": check.claim,
            "quote": check.quote,
            "source_context": check.source_context,
            "source_id": check.source_id,
        },
        questions={
            "support": Choice(
                instructions="Does the source context support the claim, given the quote?",
                criteria={
                    "supports": "Context clearly supports the claim",
                    "partial": "Context partially supports or is ambiguous",
                    "contradicts": "Context contradicts the claim",
                    "unrelated": "Context is unrelated to the claim",
                },
            ),
            "quote_faithful": Noul(
                instructions="The quote accurately appears in or fairly represents the source_context",
            ),
            "overclaim": Noul(
                instructions="The claim asserts more than the source_context warrants",
            ),
            "evidence_strength": Score(
                instructions="How strong is the evidentiary support for the claim?",
                criteria=["Weak or absent", "Moderate", "Strong and direct"],
            ),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]
    support = a["support"]["choice"]
    conf = a["support"]["confidence"]
    faithful = a["quote_faithful"]["noul"]
    overclaim = a["overclaim"]["noul"]

    if support == "supports" and faithful >= thr.noul_yes and overclaim <= thr.noul_no and conf >= thr.auto_confidence:
        band, decision, actions = ActionBand.AUTO, "accept_citation", ["accept"]
    elif support in {"contradicts", "unrelated"} or faithful <= thr.noul_no:
        band, decision, actions = ActionBand.BLOCK, "reject_citation", ["reject", "flag:hallucinated_citation"]
    else:
        band, decision, actions = ActionBand.CONFIRM, "review_citation", ["human_review"]

    return UseCaseResult(
        use_case="citation_check",
        decision=decision,
        action_band=band.value,
        rationale=(
            f"support={support} conf={conf:.2f}; faithful={faithful:.2f}; "
            f"overclaim={overclaim:.2f}; strength={a['evidence_strength']['score']:.2f}"
        ),
        actions=actions,
        raw_answers=a,
        metadata={"source_id": check.source_id},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
