"""Security workflows where Jev decides and a generative LLM drafts.

Claude is used when ``ANTHROPIC_API_KEY`` or ``CLAUDE_API_KEY`` is set.
Otherwise the OpenAI key in the environment is used. Jev remains the
gate: a blocked prompt never reaches the LLM, and an LLM draft that
fails verification is discarded.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field
from typesafe_sdk import Noul

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.llm import LLMCompletion, complete
from jev_usecases.models import UseCaseResult
from jev_usecases.use_cases.coding_agent_guardrails import ToolCallGate, gate_tool_call
from jev_usecases.use_cases.llm_guardrails import GuardSurface, GuardrailInput, evaluate_guardrail
from jev_usecases.use_cases.security_incidents import SecurityAlert, triage_security_incident

DEFENSIVE_SYSTEM = (
    "You are a defensive security operations assistant. "
    "Describe detection, containment, and response using only the evidence provided. "
    "Do not write exploits, malware, payloads, or procedures for unauthorized access. "
    "If the request asks for those, refuse in one sentence. "
    "Keep the answer under 250 words."
)


class GuardedSecurityQuestion(BaseModel):
    question: str
    policy: str = (
        "Allow defensive incident-response guidance. "
        "Block jailbreaks, exploit development, malware, credential theft, "
        "and requests for unauthorized access."
    )


class ToolProposalRequest(BaseModel):
    goal: str
    cwd: str = "/workspace/ir"
    conversation_summary: str | None = None


def _llm_meta(completion: LLMCompletion) -> dict[str, Any]:
    return {
        "provider": completion.provider,
        "model": completion.model,
        "key_env": completion.key_env,
        "usage": completion.usage,
    }


def run_incident_copilot(
    alert: SecurityAlert,
    *,
    thresholds: Thresholds | None = None,
) -> UseCaseResult:
    """Jev playbook first, then an LLM analyst brief, then Jev verification."""
    thr = thresholds or Thresholds(noul_yes=0.7, noul_no=0.35, high_stakes_noul=0.85)
    playbook = triage_security_incident(alert, thresholds=thresholds)

    completion = complete(
        DEFENSIVE_SYSTEM
        + " The playbook decision is final. Write a SOC analyst brief that follows it. "
        "Do not invent hosts, IOCs, or actions that are not in the alert or playbook.",
        json.dumps(
            {
                "alert": alert.model_dump(),
                "playbook_decision": playbook.decision,
                "action_band": playbook.action_band,
                "playbook_actions": playbook.actions,
                "jev_rationale": playbook.rationale,
            },
            indent=2,
        ),
    )

    verify = get_client().system_one(
        state={
            "alert": alert.model_dump(),
            "playbook_decision": playbook.decision,
            "playbook_actions": playbook.actions,
            "analyst_brief": completion.text,
        },
        questions={
            "matches_decision": Noul(
                instructions="The analyst_brief agrees with playbook_decision and does not recommend a conflicting disposition",
            ),
            "stays_in_evidence": Noul(
                instructions="The analyst_brief does not invent hosts, indicators, or events absent from the alert",
            ),
            "defensive_only": Noul(
                instructions="The analyst_brief is defensive and does not include exploit, malware, or attack procedures",
            ),
            "unsafe_action": Noul(
                instructions="The analyst_brief recommends an action that contradicts the playbook or is unsafe",
            ),
        },
    )
    raw = answers_to_dict(verify)
    a = raw["answers"]
    accepted = (
        a["matches_decision"]["noul"] >= thr.noul_yes
        and a["stays_in_evidence"]["noul"] >= thr.noul_yes
        and a["defensive_only"]["noul"] >= thr.noul_yes
        and a["unsafe_action"]["noul"] <= thr.noul_no
    )

    actions = list(playbook.actions)
    if accepted:
        actions.append("attach_analyst_brief")
        brief = completion.text
        decision = playbook.decision
        band = playbook.action_band
    else:
        actions.append("discard_llm_brief")
        brief = None
        decision = playbook.decision
        band = ActionBand.CONFIRM.value if playbook.action_band == ActionBand.AUTO.value else playbook.action_band

    return UseCaseResult(
        use_case="security_incident_copilot",
        decision=decision,
        action_band=band,
        rationale=(
            f"playbook={playbook.decision}; brief_accepted={accepted}; "
            f"matches={a['matches_decision']['noul']:.2f}; "
            f"evidence={a['stays_in_evidence']['noul']:.2f}; "
            f"defensive={a['defensive_only']['noul']:.2f}; "
            f"unsafe={a['unsafe_action']['noul']:.2f}; "
            f"llm={completion.provider}/{completion.model}"
        ),
        actions=actions,
        raw_answers={"playbook": playbook.raw_answers, "brief_verification": a},
        metadata={
            "host": alert.host,
            "analyst_brief": brief,
            "brief_accepted": accepted,
            "llm": _llm_meta(completion),
            "jev_model": playbook.model,
        },
        model=raw.get("model") or playbook.model,
        usage=raw.get("usage"),
    )


def run_guarded_security_answer(
    request: GuardedSecurityQuestion,
    *,
    thresholds: Thresholds | None = None,
) -> UseCaseResult:
    """Screen the prompt with Jev, call the LLM only if allowed, then screen the answer."""
    inbound = evaluate_guardrail(
        GuardrailInput(surface=GuardSurface.PROMPT, content=request.question, policy=request.policy),
        thresholds=thresholds,
    )
    if inbound.decision == "block":
        return UseCaseResult(
            use_case="security_guarded_assistant",
            decision="blocked_prompt",
            action_band=ActionBand.BLOCK.value,
            rationale=f"Jev blocked the prompt before the LLM was called. {inbound.rationale}",
            actions=["deny", "log:blocked_prompt"],
            raw_answers={"inbound": inbound.raw_answers},
            metadata={"llm_called": False, "answer": None},
            model=inbound.model,
            usage=inbound.usage,
        )

    completion = complete(DEFENSIVE_SYSTEM, request.question)
    outbound = evaluate_guardrail(
        GuardrailInput(surface=GuardSurface.COMPLETION, content=completion.text, policy=request.policy),
        thresholds=thresholds,
    )
    if outbound.decision == "block":
        return UseCaseResult(
            use_case="security_guarded_assistant",
            decision="blocked_completion",
            action_band=ActionBand.BLOCK.value,
            rationale=f"Jev blocked the LLM completion. {outbound.rationale}",
            actions=["deny", "log:blocked_completion"],
            raw_answers={"inbound": inbound.raw_answers, "outbound": outbound.raw_answers},
            metadata={"llm_called": True, "llm": _llm_meta(completion), "answer": None},
            model=outbound.model,
            usage=outbound.usage,
        )

    band = outbound.action_band if outbound.decision == "allow" else ActionBand.CONFIRM.value
    decision = "answered" if outbound.decision == "allow" else "answered_needs_review"
    actions = ["return_answer"] if decision == "answered" else ["hold_answer_for_review"]
    return UseCaseResult(
        use_case="security_guarded_assistant",
        decision=decision,
        action_band=band,
        rationale=(
            f"inbound={inbound.decision}; outbound={outbound.decision}; "
            f"llm={completion.provider}/{completion.model}"
        ),
        actions=actions,
        raw_answers={"inbound": inbound.raw_answers, "outbound": outbound.raw_answers},
        metadata={
            "llm_called": True,
            "llm": _llm_meta(completion),
            "answer": completion.text,
        },
        model=outbound.model,
        usage=outbound.usage,
    )


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_command(text: str) -> tuple[str, str]:
    candidate = text.strip()
    fenced = _JSON_FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1)
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end > start:
            candidate = candidate[start : end + 1]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        first = text.strip().splitlines()[0].strip().strip("`")
        return first, "unparsed"
    command = str(payload.get("command") or "").strip()
    why = str(payload.get("why") or "").strip()
    if not command:
        raise ValueError("LLM JSON did not include a command")
    return command, why


def run_security_tool_gate(
    request: ToolProposalRequest,
    *,
    thresholds: Thresholds | None = None,
) -> UseCaseResult:
    """LLM proposes one shell command; Jev decides whether it may run.

    The command is never executed here. Callers must honor ``decision``.
    """
    completion = complete(
        DEFENSIVE_SYSTEM
        + " Propose exactly one shell command for the defensive goal. "
        "Reply with JSON only: {\"command\": \"...\", \"why\": \"...\"}. "
        "Prefer read-only diagnostics. Do not propose destructive commands.",
        request.goal,
        max_tokens=300,
    )
    command, why = _parse_command(completion.text)
    gate = gate_tool_call(
        ToolCallGate(
            tool_name="bash",
            command_or_args=command,
            cwd=request.cwd,
            user_goal=request.goal,
            conversation_summary=request.conversation_summary or why,
        ),
        thresholds=thresholds,
    )
    approved = gate.decision == "allow"
    return UseCaseResult(
        use_case="security_tool_gate",
        decision=gate.decision,
        action_band=gate.action_band,
        rationale=(
            f"proposed={command!r}; gate={gate.decision}; "
            f"llm={completion.provider}/{completion.model}; {gate.rationale}"
        ),
        actions=(["execute"] if approved else ["do_not_execute"]) + list(gate.actions),
        raw_answers=gate.raw_answers,
        metadata={
            "proposed_command": command,
            "why": why,
            "approved": approved,
            "llm": _llm_meta(completion),
            "gate_decision": gate.decision,
        },
        model=gate.model,
        usage=gate.usage,
    )


class SecurityBundle(BaseModel):
    """Inputs for the three security pipelines, used by the CLI fixture runner."""

    alert: SecurityAlert
    question: GuardedSecurityQuestion
    tool: ToolProposalRequest = Field(default_factory=lambda: ToolProposalRequest(goal="List listening TCP ports"))
