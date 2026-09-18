"""Policy tests for SOC agents. These do not call Jev."""

import pytest

from jev_usecases.decisions import Thresholds
from jev_usecases.soc.policy import (
    closeout_decision,
    escalation_decision,
    investigation_decision,
    mitigation_decision,
    recovery_decision,
)


def _noul(value: float) -> dict:
    return {"noul": value}


def _choice(name: str, confidence: float = 0.95) -> dict:
    return {"choice": name, "confidence": confidence}


def test_mitigation_skips_when_triage_does_not_contain():
    decision, band, actions, _why = mitigation_decision(
        triage_decision="queue_tier2",
        triage_actions=["queue:tier2"],
        asset_criticality="critical",
        answers={},
    )
    assert decision == "no_mitigation"
    assert band == "auto"
    assert actions == []


def test_mitigation_approves_isolate_and_confirms_critical_hosts():
    answers = {
        "isolate_warranted": _noul(0.91),
        "revoke_sessions_warranted": _noul(0.2),
        "reset_credentials_warranted": _noul(0.2),
        "block_lateral_warranted": _noul(0.2),
        "over_containment": _noul(0.1),
        "mitigation_scope": _choice("approve", 0.95),
    }
    decision, band, actions, _why = mitigation_decision(
        triage_decision="contain_now",
        triage_actions=["isolate_host", "disable_sessions"],
        asset_criticality="critical",
        answers=answers,
        thresholds=Thresholds(),
    )
    assert decision == "approve_mitigation"
    assert band == "confirm"
    assert actions[0] == "isolate_host"
    assert "disable_sessions" not in actions
    assert "page:security_oncall" in actions


def test_mitigation_holds_when_containment_is_broader_than_evidence():
    answers = {
        "isolate_warranted": _noul(0.95),
        "revoke_sessions_warranted": _noul(0.95),
        "reset_credentials_warranted": _noul(0.95),
        "block_lateral_warranted": _noul(0.95),
        "over_containment": _noul(0.8),
        "mitigation_scope": _choice("approve", 0.99),
    }
    decision, _band, actions, _why = mitigation_decision(
        triage_decision="contain_now",
        triage_actions=["isolate_host"],
        asset_criticality="high",
        answers=answers,
    )
    assert decision == "hold_mitigation"
    assert actions == ["hold:containment"]


def test_investigation_names_log_collections_only():
    answers = {
        "need_auth_logs": _noul(0.9),
        "need_process_tree": _noul(0.2),
        "need_network_logs": _noul(0.8),
        "need_identity_logs": _noul(0.1),
        "enough_evidence": _noul(0.2),
        "investigation_next": _choice("collect", 0.9),
    }
    decision, band, actions, _why = investigation_decision(answers=answers)
    assert decision == "collect_evidence"
    assert band == "auto"
    assert actions == ["collect:auth_logs", "collect:network_logs"]


def test_escalation_pages_critical_containment():
    answers = {
        "page_oncall": _noul(0.2),
        "hand_to_ir": _noul(0.2),
        "affected_user_notice": _noul(0.1),
        "escalation_target": _choice("queue", 0.99),
    }
    decision, band, actions, _why = escalation_decision(
        triage_decision="contain_now",
        asset_criticality="critical",
        answers=answers,
    )
    assert "page:security_oncall" in actions
    assert decision == "page_oncall"
    assert band == "confirm"


def test_recovery_stays_isolated_until_monitoring_is_clean_and_four_hours_pass():
    answers = {
        "safe_to_restore": _noul(0.99),
        "residual_risk": {"score": 0.0},
        "restore_choice": _choice("full_restore", 0.99),
    }
    decision, _band, actions, _why = recovery_decision(
        triage_decision="contain_now",
        monitoring_clean=True,
        hours_contained=1.0,
        answers=answers,
    )
    assert decision == "remain_isolated"
    assert "keep:isolation" in actions

    dirty, _band, _actions, _why = recovery_decision(
        triage_decision="queue_tier2",
        monitoring_clean=False,
        hours_contained=48,
        answers=answers,
    )
    assert dirty == "remain_isolated"


def test_closeout_cannot_close_an_unrestored_containment():
    answers = {
        "notes_complete": _noul(0.99),
        "recurrence_risk": {"score": 0.0},
        "close_choice": _choice("close", 0.99),
    }
    decision, _band, actions, _why = closeout_decision(
        triage_decision="contain_now",
        recovery_decision_name="remain_isolated",
        monitoring_clean=True,
        answers=answers,
    )
    assert decision == "monitor"
    assert actions == ["monitor:open_case"]


def test_hours_contained_rejects_negative():
    with pytest.raises(ValueError):
        recovery_decision(
            triage_decision="contain_now",
            monitoring_clean=True,
            hours_contained=-1,
            answers={
                "safe_to_restore": _noul(0.99),
                "residual_risk": {"score": 0.0},
                "restore_choice": _choice("full_restore"),
            },
        )
