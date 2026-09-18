"""Jev-backed SOC agents. Each agent returns actions. None of them execute those actions."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import Thresholds
from jev_usecases.models import UseCaseResult
from jev_usecases.soc.policy import (
    closeout_decision,
    escalation_decision,
    investigation_decision,
    mitigation_decision,
    recovery_decision,
)
from jev_usecases.use_cases.security_incidents import SecurityAlert, triage_security_incident


class RecoveryRequest(BaseModel):
    alert: SecurityAlert
    triage_decision: str
    containment_actions_completed: list[str] = Field(default_factory=list)
    monitoring_clean: bool
    hours_contained: float


class CloseoutRequest(BaseModel):
    alert: SecurityAlert
    triage_decision: str
    recovery_decision: str | None = None
    monitoring_clean: bool


def _result(
    use_case: str,
    decision: str,
    band: str,
    rationale: str,
    actions: list[str],
    raw: dict[str, Any],
    metadata: dict[str, Any],
    response_raw: dict[str, Any] | None = None,
) -> UseCaseResult:
    model = None
    usage = None
    if response_raw:
        model = response_raw.get("model")
        usage = response_raw.get("usage")
    return UseCaseResult(
        use_case=use_case,
        decision=decision,
        action_band=band,
        rationale=rationale,
        actions=actions,
        raw_answers=raw,
        metadata=metadata,
        model=model,
        usage=usage,
    )


def run_triage_agent(alert: SecurityAlert, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    """Same eight-question triage as security_incidents, named as the SOC triage agent."""
    result = triage_security_incident(alert, thresholds=thresholds)
    return result.model_copy(update={"use_case": "soc_triage"})


def run_mitigation_agent(
    alert: SecurityAlert,
    *,
    triage: UseCaseResult | None = None,
    thresholds: Thresholds | None = None,
) -> UseCaseResult:
    triage_result = triage or run_triage_agent(alert, thresholds=thresholds)
    if triage_result.decision != "contain_now":
        decision, band, actions, why = mitigation_decision(
            triage_decision=triage_result.decision,
            triage_actions=triage_result.actions,
            asset_criticality=alert.asset_criticality,
            answers={},
            thresholds=thresholds,
        )
        return _result(
            "soc_mitigation",
            decision,
            band,
            why,
            actions,
            {},
            {"triage_decision": triage_result.decision, "host": alert.host},
        )

    response = get_client().system_one(
        state={
            "alert": alert.model_dump(),
            "triage_decision": triage_result.decision,
            "proposed_actions": triage_result.actions,
        },
        questions={
            "isolate_warranted": Noul(
                instructions="The evidence supports isolating this one host as a defensive containment step",
            ),
            "revoke_sessions_warranted": Noul(
                instructions="The evidence supports revoking active sessions for the accounts on this host",
            ),
            "reset_credentials_warranted": Noul(
                instructions="The evidence supports a password reset for the accounts named in the alert",
            ),
            "block_lateral_warranted": Noul(
                instructions="The evidence supports blocking this host from reaching other internal hosts",
            ),
            "over_containment": Noul(
                instructions="The proposed containment is broader than the evidence in the alert supports",
            ),
            "mitigation_scope": Choice(
                instructions="Scope of defensive containment to approve",
                criteria={
                    "approve": "Approve the warranted actions",
                    "narrow": "Approve only the smallest warranted action",
                    "hold": "Hold every containment action for a person",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    decision, band, actions, why = mitigation_decision(
        triage_decision=triage_result.decision,
        triage_actions=triage_result.actions,
        asset_criticality=alert.asset_criticality,
        answers=raw["answers"],
        thresholds=thresholds,
    )
    scope, _confidence = raw["answers"]["mitigation_scope"]["choice"], raw["answers"]["mitigation_scope"].get("confidence")
    if scope == "hold":
        decision, band, actions = "hold_mitigation", "confirm", ["hold:containment"]
        why = f"jev scope=hold; {why}"
    elif scope == "narrow" and len(actions) > 1:
        kept = [actions[0]]
        if "page:security_oncall" in actions:
            kept.append("page:security_oncall")
        actions = kept
        why = f"narrowed; {why}"
    return _result(
        "soc_mitigation",
        decision,
        band,
        why,
        actions,
        raw["answers"],
        {"triage_decision": triage_result.decision, "host": alert.host},
        raw,
    )


def run_investigation_agent(
    alert: SecurityAlert,
    *,
    triage: UseCaseResult | None = None,
    thresholds: Thresholds | None = None,
) -> UseCaseResult:
    triage_result = triage or run_triage_agent(alert, thresholds=thresholds)
    response = get_client().system_one(
        state={
            "alert": alert.model_dump(),
            "triage_decision": triage_result.decision,
            "triage_rationale": triage_result.rationale,
        },
        questions={
            "need_auth_logs": Noul(instructions="Authentication logs for this host are still needed"),
            "need_process_tree": Noul(instructions="A process-tree record for this host is still needed"),
            "need_network_logs": Noul(instructions="Network connection logs for this host are still needed"),
            "need_identity_logs": Noul(instructions="Identity-provider logs for the accounts on this alert are still needed"),
            "enough_evidence": Noul(instructions="The alert and explainable records are already enough to continue"),
            "investigation_next": Choice(
                instructions="Next investigation step",
                criteria={
                    "collect": "Collect the missing defensive logs",
                    "wait": "Current evidence is enough",
                    "hand_to_human": "A person should choose the next record",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    decision, band, actions, why = investigation_decision(answers=raw["answers"], thresholds=thresholds)
    return _result(
        "soc_investigation",
        decision,
        band,
        why,
        actions,
        raw["answers"],
        {"triage_decision": triage_result.decision, "host": alert.host},
        raw,
    )


def run_escalation_agent(
    alert: SecurityAlert,
    *,
    triage: UseCaseResult | None = None,
    thresholds: Thresholds | None = None,
) -> UseCaseResult:
    triage_result = triage or run_triage_agent(alert, thresholds=thresholds)
    response = get_client().system_one(
        state={
            "alert": alert.model_dump(),
            "triage_decision": triage_result.decision,
            "asset_criticality": alert.asset_criticality,
        },
        questions={
            "page_oncall": Noul(instructions="The on-call security person should be paged now"),
            "hand_to_ir": Noul(instructions="This case should move to the incident-response queue"),
            "affected_user_notice": Noul(
                instructions="Affected users should receive a defensive notice that their account or host is under review",
            ),
            "escalation_target": Choice(
                instructions="Who should receive this case next",
                criteria={
                    "queue": "Stay with the SOC queue",
                    "oncall": "Page security on-call",
                    "incident_response": "Hand to incident response",
                    "affected_users": "Prepare a notice for affected users",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    decision, band, actions, why = escalation_decision(
        triage_decision=triage_result.decision,
        asset_criticality=alert.asset_criticality,
        answers=raw["answers"],
        thresholds=thresholds,
    )
    return _result(
        "soc_escalation",
        decision,
        band,
        why,
        actions,
        raw["answers"],
        {"triage_decision": triage_result.decision, "host": alert.host},
        raw,
    )


def run_recovery_agent(request: RecoveryRequest, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    response = get_client().system_one(
        state={
            "alert": request.alert.model_dump(),
            "triage_decision": request.triage_decision,
            "containment_actions_completed": request.containment_actions_completed,
            "monitoring_clean": request.monitoring_clean,
            "hours_contained": request.hours_contained,
        },
        questions={
            "safe_to_restore": Noul(
                instructions="The recorded containment and monitoring support returning this host to normal use",
            ),
            "residual_risk": Score(
                instructions="How strong is the evidence that hostile activity remains on this host?",
                criteria=["No residual indicator", "Unclear", "Residual indicator present"],
            ),
            "restore_choice": Choice(
                instructions="Restore decision from the recorded case, not from a new theory",
                criteria={
                    "remain_isolated": "Keep the host isolated",
                    "limited_restore": "Restore with continued monitoring",
                    "full_restore": "Return the host to normal use",
                    "human_review": "A person must decide",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    decision, band, actions, why = recovery_decision(
        triage_decision=request.triage_decision,
        monitoring_clean=request.monitoring_clean,
        hours_contained=request.hours_contained,
        answers=raw["answers"],
        thresholds=thresholds,
    )
    if raw["answers"]["restore_choice"]["choice"] == "human_review":
        decision, band = "remain_isolated", "human"
        actions = ["keep:isolation", "handoff:recovery"]
        why = f"jev restore_choice=human_review; {why}"
    return _result(
        "soc_recovery",
        decision,
        band,
        why,
        actions,
        raw["answers"],
        {"host": request.alert.host, "hours_contained": request.hours_contained},
        raw,
    )


def run_closeout_agent(request: CloseoutRequest, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    response = get_client().system_one(
        state=request.model_dump(),
        questions={
            "notes_complete": Noul(
                instructions="The case notes record the decision, the actions, and the evidence used",
            ),
            "recurrence_risk": Score(
                instructions="How likely is the same activity to still be active?",
                criteria=["Unlikely", "Unclear", "Still indicated"],
            ),
            "close_choice": Choice(
                instructions="Case closeout",
                criteria={
                    "close": "Close the case",
                    "monitor": "Keep the case open for monitoring",
                    "reopen": "Reopen investigation",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    decision, band, actions, why = closeout_decision(
        triage_decision=request.triage_decision,
        recovery_decision_name=request.recovery_decision,
        monitoring_clean=request.monitoring_clean,
        answers=raw["answers"],
        thresholds=thresholds,
    )
    if raw["answers"]["close_choice"]["choice"] == "reopen":
        decision, band, actions = "reopen", "confirm", ["reopen:investigation"]
        why = f"jev close_choice=reopen; {why}"
    return _result(
        "soc_closeout",
        decision,
        band,
        why,
        actions,
        raw["answers"],
        {"host": request.alert.host, "recovery_decision": request.recovery_decision},
        raw,
    )
