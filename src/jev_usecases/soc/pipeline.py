"""Run triage, investigation, mitigation, and escalation as one SOC intake."""

from __future__ import annotations

from jev_usecases.decisions import Thresholds
from jev_usecases.models import UseCaseResult
from jev_usecases.soc.agents import (
    run_escalation_agent,
    run_investigation_agent,
    run_mitigation_agent,
    run_triage_agent,
)
from jev_usecases.soc.policy import CONTAINMENT_ACTIONS, stricter_band
from jev_usecases.use_cases.security_incidents import SecurityAlert


def _step(result: UseCaseResult) -> dict:
    return {
        "use_case": result.use_case,
        "decision": result.decision,
        "action_band": result.action_band,
        "actions": result.actions,
        "rationale": result.rationale,
    }


def run_agentic_soc(alert: SecurityAlert, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    """Intake path. Recovery and closeout run later, when the caller has new case facts."""
    triage = run_triage_agent(alert, thresholds=thresholds)
    investigation = run_investigation_agent(alert, triage=triage, thresholds=thresholds)
    mitigation = run_mitigation_agent(alert, triage=triage, thresholds=thresholds)
    escalation = run_escalation_agent(alert, triage=triage, thresholds=thresholds)

    steps = [triage, investigation, mitigation, escalation]
    containment = set(CONTAINMENT_ACTIONS)
    actions: list[str] = []
    for action in triage.actions:
        if action not in containment and action not in actions:
            actions.append(action)
    for step in (mitigation, investigation, escalation):
        for action in step.actions:
            if action not in actions:
                actions.append(action)

    band = stricter_band(*(step.action_band for step in steps))
    return UseCaseResult(
        use_case="soc_pipeline",
        decision=triage.decision,
        action_band=band,
        rationale=(
            f"triage={triage.decision}; investigation={investigation.decision}; "
            f"mitigation={mitigation.decision}; escalation={escalation.decision}"
        ),
        actions=actions,
        raw_answers={"triage": triage.raw_answers},
        metadata={
            "host": alert.host,
            "steps": [_step(step) for step in steps],
        },
        model=triage.model,
        usage=triage.usage,
    )
