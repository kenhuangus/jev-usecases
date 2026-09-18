"""Agent trace observability: decide if a human must review a finished run."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class AgentTrace(BaseModel):
    goal: str
    transcript: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    final_response: str
    customer_tier: str = "standard"


def review_agent_trace(trace: AgentTrace, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()

    response = client.system_one(
        state=trace.model_dump(),
        questions={
            "goal_met": Noul(instructions="The agent achieved the stated goal"),
            "policy_ok": Noul(instructions="The agent stayed within acceptable policy and scope"),
            "tool_misuse": Noul(instructions="One or more tool calls look incorrect, unsafe, or unnecessary"),
            "customer_harm": Noul(instructions="The customer may have been harmed or misled"),
            "needs_review": Noul(instructions="A human should review this run"),
            "urgency": Score(
                instructions="How soon should a human review this run?",
                criteria=["No review needed", "Review within a day", "Review immediately"],
            ),
            "issue_type": Choice(
                instructions="Primary issue type if any",
                criteria={
                    "none": "No material issue",
                    "quality": "Answer quality problem",
                    "policy": "Policy or compliance issue",
                    "tooling": "Tool-call failure or misuse",
                    "safety": "Safety or security issue",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]

    needs = a["needs_review"]["noul"]
    urgency = a["urgency"]["score"]
    issue = a["issue_type"]["choice"]

    if a["customer_harm"]["noul"] >= thr.noul_yes or a["tool_misuse"]["noul"] >= thr.high_stakes_noul:
        band, decision = ActionBand.CONFIRM, "review_immediate"
        actions = ["page:oncall", "hold_followups", f"label:{issue}"]
    elif needs >= thr.noul_yes or urgency >= 1.2:
        band = ActionBand.CONFIRM if a["issue_type"]["confidence"] < thr.auto_confidence else ActionBand.AUTO
        decision = "review_same_day" if urgency < 1.7 else "review_immediate"
        actions = ["enqueue:human_review", f"sla:{'1h' if urgency >= 1.7 else '24h'}", f"label:{issue}"]
    elif a["goal_met"]["noul"] >= thr.noul_yes and a["policy_ok"]["noul"] >= thr.noul_yes:
        band, decision, actions = ActionBand.AUTO, "no_review", ["close_trace", "sample_for_qa"]
    else:
        band, decision, actions = ActionBand.CONFIRM, "spot_check", ["enqueue:qa_sample"]

    if trace.customer_tier in {"enterprise", "vip"} and decision != "no_review":
        actions.append("notify:account_manager")

    return UseCaseResult(
        use_case="agent_trace",
        decision=decision,
        action_band=band.value,
        rationale=(
            f"needs_review={needs:.2f}; urgency={urgency:.2f}; issue={issue}; "
            f"goal_met={a['goal_met']['noul']:.2f}; tool_misuse={a['tool_misuse']['noul']:.2f}"
        ),
        actions=actions,
        raw_answers=a,
        metadata={"customer_tier": trace.customer_tier, "tool_call_count": len(trace.tool_calls)},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
