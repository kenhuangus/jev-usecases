"""Scientific discovery helpers: paper screening and claim support."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class PaperScreenRequest(BaseModel):
    title: str
    abstract: str
    inclusion_criteria: list[str] = Field(min_length=1)
    exclusion_criteria: list[str] = Field(default_factory=list)


def screen_paper(req: PaperScreenRequest, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()
    questions = {
        f"incl_{i}": Noul(instructions=f"Paper meets inclusion criterion: {c}")
        for i, c in enumerate(req.inclusion_criteria)
    }
    questions.update(
        {
            f"excl_{i}": Noul(instructions=f"Paper meets exclusion criterion (should be excluded): {c}")
            for i, c in enumerate(req.exclusion_criteria)
        }
    )
    questions.update(
        {
            "study_design": Choice(
                instructions="Primary study design",
                criteria={
                    "rct": "Randomized controlled trial",
                    "observational": "Observational study",
                    "review": "Review / meta-analysis",
                    "preclinical": "Preclinical / animal / in vitro",
                    "other": "Other / unclear",
                },
            ),
            "evidence_strength": Score(
                instructions="Strength of causal evidence for the paper's main claim as presented",
                criteria=["Anecdotal/preclinical", "Observational", "Single trial", "Meta-analysis of trials"],
            ),
            "methods_complete": Noul(
                instructions="Abstract/methods mention adequate controls, dataset, and experimental setting details",
            ),
        }
    )
    response = client.system_one(
        state={"title": req.title, "abstract": req.abstract},
        questions=questions,
    )
    raw = answers_to_dict(response)
    a = raw["answers"]

    incl = [a[f"incl_{i}"]["noul"] for i in range(len(req.inclusion_criteria))]
    excl = [a[f"excl_{i}"]["noul"] for i in range(len(req.exclusion_criteria))]
    include = all(v >= thr.noul_yes for v in incl) and all(v <= thr.noul_no for v in excl)

    if any(v >= thr.noul_yes for v in excl):
        decision, band, actions = "exclude", ActionBand.AUTO, ["exclude"]
    elif include and a["study_design"]["confidence"] >= thr.auto_confidence:
        decision, band, actions = "include", ActionBand.AUTO, ["include", f"design:{a['study_design']['choice']}"]
    elif min(incl) >= 0.45:
        decision, band, actions = "maybe", ActionBand.CONFIRM, ["full_text_review"]
    else:
        decision, band, actions = "exclude", ActionBand.AUTO, ["exclude"]

    return UseCaseResult(
        use_case="scientific_discovery",
        decision=decision,
        action_band=band.value,
        rationale=(
            f"incl_min={min(incl):.2f}; excl_max={max(excl) if excl else 0:.2f}; "
            f"design={a['study_design']['choice']}; evidence={a['evidence_strength']['score']:.2f}"
        ),
        actions=actions,
        raw_answers=a,
        metadata={"inclusion_scores": incl, "exclusion_scores": excl, "title": req.title},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
