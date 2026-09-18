"""Agent harness helpers: next-step continue/retry/ask/stop + skill suggestion."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class HarnessState(BaseModel):
    goal: str
    last_observation: str
    last_error: str | None = None
    steps_taken: int = 0
    max_steps: int = 20
    candidate_skills: dict[str, str] = Field(default_factory=dict)


def decide_agent_next_step(state: HarnessState, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()

    questions: dict[str, Any] = {
        "next": Choice(
            instructions="What should the agent harness do next?",
            criteria={
                "continue": "Continue with the current plan",
                "retry": "Retry the last action with a fix",
                "ask_user": "Ask the user a clarifying question",
                "stop_success": "Stop; goal appears complete",
                "stop_failure": "Stop; cannot make progress",
            },
        ),
        "goal_complete": Noul(instructions="The goal has been completed based on the observation"),
        "blocked": Noul(instructions="The agent is blocked without user input or a new approach"),
        "progress": Score(
            instructions="Progress toward the goal",
            criteria=["None", "Some", "Nearly done", "Done"],
        ),
    }
    if state.candidate_skills:
        questions["skill"] = Choice(
            instructions="Which skill should be suggested for this turn, if any?",
            criteria={**state.candidate_skills, "none": "No skill needed"},
        )
        questions["needs_skill"] = Noul(instructions="A specialized skill should be loaded for this turn")

    response = client.system_one(state=state.model_dump(), questions=questions)
    raw = answers_to_dict(response)
    a = raw["answers"]

    # Hard code limits
    if state.steps_taken >= state.max_steps:
        return UseCaseResult(
            use_case="agent_harness",
            decision="stop_failure",
            action_band=ActionBand.BLOCK.value,
            rationale="max_steps exceeded",
            actions=["stop", "report:max_steps"],
            raw_answers=a,
            model=raw.get("model"),
            usage=raw.get("usage"),
        )

    nxt = a["next"]["choice"]
    conf = a["next"]["confidence"]
    if a["goal_complete"]["noul"] >= thr.noul_yes or a["progress"]["score"] >= 2.5:
        nxt = "stop_success"
    elif a["blocked"]["noul"] >= thr.noul_yes:
        nxt = "ask_user"

    band = ActionBand.AUTO if conf >= thr.auto_confidence else ActionBand.CONFIRM
    actions = [f"harness:{nxt}"]
    meta: dict[str, Any] = {"next": nxt}
    if "skill" in a and a.get("needs_skill", {}).get("noul", 0) >= thr.noul_yes and a["skill"]["choice"] != "none":
        actions.append(f"load_skill:{a['skill']['choice']}")
        meta["skill"] = a["skill"]["choice"]

    return UseCaseResult(
        use_case="agent_harness",
        decision=nxt,
        action_band=band.value,
        rationale=(
            f"next={a['next']['choice']} conf={conf:.2f}; complete={a['goal_complete']['noul']:.2f}; "
            f"blocked={a['blocked']['noul']:.2f}; progress={a['progress']['score']:.2f}"
        ),
        actions=actions,
        raw_answers=a,
        metadata=meta,
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
