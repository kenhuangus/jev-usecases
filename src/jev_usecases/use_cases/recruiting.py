"""Recruiting: score candidates against explicit job criteria."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class JobCriteria(BaseModel):
    title: str
    must_have: list[str]
    nice_to_have: list[str] = Field(default_factory=list)
    level: str = "senior"


class CandidatePacket(BaseModel):
    name: str
    resume_text: str
    interview_notes: str | None = None
    job: JobCriteria


def evaluate_candidate(packet: CandidatePacket, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()

    must_questions = {
        f"must_{i}": Noul(instructions=f"The candidate evidence supports must-have requirement: {req}")
        for i, req in enumerate(packet.job.must_have)
    }
    nice_questions = {
        f"nice_{i}": Noul(instructions=f"The candidate evidence supports nice-to-have: {req}")
        for i, req in enumerate(packet.job.nice_to_have)
    }

    response = client.system_one(
        state={
            "name": packet.name,
            "resume": packet.resume_text,
            "interview_notes": packet.interview_notes,
            "job_title": packet.job.title,
            "level": packet.job.level,
            "must_have": packet.job.must_have,
            "nice_to_have": packet.job.nice_to_have,
        },
        questions={
            **must_questions,
            **nice_questions,
            "overall_fit": Score(
                instructions="Overall fit for this role based only on provided evidence",
                criteria=["Poor fit", "Partial fit", "Strong fit", "Exceptional fit"],
            ),
            "seniority_match": Score(
                instructions="How well does evidenced seniority match the target level?",
                criteria=["Below level", "At level", "Above level"],
            ),
            "route": Choice(
                instructions="How should recruiting route this candidate?",
                criteria={
                    "reject": "Does not meet must-haves",
                    "phone_screen": "Worth a screen",
                    "hiring_manager": "Send to hiring manager",
                    "onsite": "Fast-track to onsite",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]

    must_scores = [a[f"must_{i}"]["noul"] for i in range(len(packet.job.must_have))]
    nice_scores = [a[f"nice_{i}"]["noul"] for i in range(len(packet.job.nice_to_have))]
    must_pass = all(s >= thr.noul_yes for s in must_scores) if must_scores else True
    nice_avg = sum(nice_scores) / len(nice_scores) if nice_scores else 0.0
    # Composite controlled in code
    composite = 0.55 * (a["overall_fit"]["score"] / 3) + 0.25 * (a["seniority_match"]["score"] / 2) + 0.20 * nice_avg

    route = a["route"]["choice"]
    conf = a["route"]["confidence"]
    if not must_pass:
        route, band, actions = "reject", ActionBand.AUTO, ["reject", "send_rejection_template"]
    elif composite >= 0.75 and conf >= thr.auto_confidence:
        route = "onsite" if a["overall_fit"]["score"] >= 2.2 else "hiring_manager"
        band, actions = ActionBand.AUTO, [f"route:{route}", "notify:recruiter"]
    elif composite >= 0.45:
        route = "phone_screen"
        band, actions = ActionBand.CONFIRM, ["schedule:phone_screen"]
    else:
        route, band, actions = "reject", ActionBand.CONFIRM, ["reject_pending_recruiter_ack"]

    return UseCaseResult(
        use_case="recruiting",
        decision=route,
        action_band=band.value,
        rationale=(
            f"composite={composite:.2f}; must_pass={must_pass}; "
            f"overall={a['overall_fit']['score']:.2f}; route_model={a['route']['choice']} conf={conf:.2f}"
        ),
        actions=actions,
        raw_answers=a,
        metadata={
            "candidate": packet.name,
            "must_scores": must_scores,
            "nice_scores": nice_scores,
            "composite": composite,
        },
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
