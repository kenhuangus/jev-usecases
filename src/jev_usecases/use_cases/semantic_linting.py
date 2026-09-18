"""Semantic code / writing lints for CI."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typesafe_sdk import Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class LintRule(BaseModel):
    id: str
    instructions: str
    severity: str = "error"  # error | warning


class LintRequest(BaseModel):
    path: str
    content: str
    rules: list[LintRule] = Field(min_length=1)
    kind: str = "code"  # code | writing


def run_semantic_lint(req: LintRequest, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()
    questions = {
        rule.id: Noul(instructions=f"Violation of rule '{rule.id}': {rule.instructions}")
        for rule in req.rules
    }
    questions["overall_quality"] = Score(
        instructions=f"Overall {req.kind} quality against the team's standards",
        criteria=["Poor", "Needs work", "Good", "Excellent"],
    )
    response = client.system_one(
        state={"path": req.path, "kind": req.kind, "content": req.content},
        questions=questions,
    )
    raw = answers_to_dict(response)
    a = raw["answers"]

    violations = []
    for rule in req.rules:
        noul = a[rule.id]["noul"]
        if noul >= thr.noul_yes:
            violations.append({"id": rule.id, "severity": rule.severity, "probability": noul})

    errors = [v for v in violations if v["severity"] == "error"]
    if errors:
        decision, band, actions = "fail", ActionBand.BLOCK, [f"fail:{v['id']}" for v in errors]
    elif violations:
        decision, band, actions = "warn", ActionBand.CONFIRM, [f"warn:{v['id']}" for v in violations]
    else:
        decision, band, actions = "pass", ActionBand.AUTO, ["pass"]

    return UseCaseResult(
        use_case="semantic_linting",
        decision=decision,
        action_band=band.value,
        rationale=f"violations={len(violations)}; quality={a['overall_quality']['score']:.2f}",
        actions=actions,
        raw_answers=a,
        metadata={"path": req.path, "violations": violations},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
