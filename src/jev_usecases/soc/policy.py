"""Code-owned decisions for the agentic SOC pipeline.

Jev returns probabilities. These functions decide which named actions the
caller may perform. They do not run shell commands, isolate hosts, or
send network changes.
"""

from __future__ import annotations

from jev_usecases.decisions import ActionBand, Thresholds

CONTAINMENT_ACTIONS = (
    "isolate_host",
    "disable_sessions",
    "block_lateral_paths",
    "force_password_reset",
)

_BAND_RANK = {
    ActionBand.AUTO.value: 0,
    ActionBand.CONFIRM.value: 1,
    ActionBand.HUMAN.value: 2,
    ActionBand.BLOCK.value: 3,
}


def noul(answers: dict, key: str) -> float:
    return float(answers[key]["noul"])


def score(answers: dict, key: str) -> float:
    return float(answers[key]["score"])


def choice_of(answers: dict, key: str) -> tuple[str, float]:
    row = answers[key]
    confidence = row.get("confidence")
    return str(row["choice"]), float(confidence if confidence is not None else 0.0)


def stricter_band(*bands: str) -> str:
    return max(bands, key=lambda band: _BAND_RANK[band])


def mitigation_decision(
    *,
    triage_decision: str,
    triage_actions: list[str],
    asset_criticality: str,
    answers: dict,
    thresholds: Thresholds | None = None,
) -> tuple[str, str, list[str], str]:
    """Approve or hold each containment action triage already proposed."""
    thr = thresholds or Thresholds()
    if triage_decision != "contain_now":
        return (
            "no_mitigation",
            ActionBand.AUTO.value,
            [],
            "triage did not select contain_now",
        )

    proposed = set(triage_actions)
    over = noul(answers, "over_containment")
    approved: list[str] = []
    checks = (
        ("isolate_host", "isolate_warranted"),
        ("disable_sessions", "revoke_sessions_warranted"),
        ("force_password_reset", "reset_credentials_warranted"),
        ("block_lateral_paths", "block_lateral_warranted"),
    )
    for action, key in checks:
        if action not in proposed:
            continue
        if noul(answers, key) >= thr.noul_yes and over <= thr.noul_no:
            approved.append(action)

    if over > thr.noul_no or not approved:
        band = ActionBand.HUMAN.value if over >= thr.high_stakes_noul else ActionBand.CONFIRM.value
        return (
            "hold_mitigation",
            band,
            ["hold:containment"],
            f"over_containment={over:.2f}; approved={approved or 'none'}",
        )

    _picked, confidence = choice_of(answers, "mitigation_scope")
    band = ActionBand.AUTO.value if confidence >= thr.high_stakes_confidence else ActionBand.CONFIRM.value
    if asset_criticality == "critical":
        band = stricter_band(band, ActionBand.CONFIRM.value)
        if "page:security_oncall" not in approved:
            approved.append("page:security_oncall")
    return (
        "approve_mitigation",
        band,
        approved,
        f"approved={','.join(approved)}; confidence={confidence:.2f}; over={over:.2f}",
    )


def investigation_decision(
    *,
    answers: dict,
    thresholds: Thresholds | None = None,
) -> tuple[str, str, list[str], str]:
    thr = thresholds or Thresholds()
    tasks: list[str] = []
    mapping = (
        ("need_auth_logs", "collect:auth_logs"),
        ("need_process_tree", "collect:process_tree"),
        ("need_network_logs", "collect:network_logs"),
        ("need_identity_logs", "collect:identity_logs"),
    )
    for key, action in mapping:
        if noul(answers, key) >= thr.noul_yes:
            tasks.append(action)
    enough = noul(answers, "enough_evidence")
    picked, confidence = choice_of(answers, "investigation_next")
    if enough >= thr.noul_yes and picked == "wait":
        return (
            "evidence_sufficient",
            ActionBand.AUTO.value if confidence >= thr.auto_confidence else ActionBand.CONFIRM.value,
            tasks,
            f"enough_evidence={enough:.2f}",
        )
    if not tasks or picked == "hand_to_human":
        return (
            "investigation_needs_human",
            ActionBand.HUMAN.value,
            tasks + ["handoff:investigation"],
            f"choice={picked}; confidence={confidence:.2f}",
        )
    band = ActionBand.AUTO.value if confidence >= thr.auto_confidence else ActionBand.CONFIRM.value
    return ("collect_evidence", band, tasks, f"choice={picked}; tasks={len(tasks)}")


def escalation_decision(
    *,
    triage_decision: str,
    asset_criticality: str,
    answers: dict,
    thresholds: Thresholds | None = None,
) -> tuple[str, str, list[str], str]:
    thr = thresholds or Thresholds()
    picked, confidence = choice_of(answers, "escalation_target")
    actions: list[str] = []
    if noul(answers, "page_oncall") >= thr.noul_yes or asset_criticality == "critical":
        actions.append("page:security_oncall")
    if noul(answers, "hand_to_ir") >= thr.noul_yes or picked == "incident_response":
        actions.append("handoff:incident_response")
    if noul(answers, "affected_user_notice") >= thr.high_stakes_noul and picked == "affected_users":
        actions.append("notice:affected_users")
    if triage_decision == "contain_now" and "page:security_oncall" not in actions:
        actions.append("page:security_oncall")

    if not actions:
        actions = ["stay:queue"]
        decision = "stay_in_queue"
    elif "handoff:incident_response" in actions:
        decision = "hand_to_ir"
    elif "notice:affected_users" in actions:
        decision = "notice_affected_users"
    else:
        decision = "page_oncall"

    band = ActionBand.AUTO.value if confidence >= thr.high_stakes_confidence else ActionBand.CONFIRM.value
    if asset_criticality == "critical" or "notice:affected_users" in actions:
        band = stricter_band(band, ActionBand.CONFIRM.value)
    return (decision, band, actions, f"choice={picked}; confidence={confidence:.2f}")


def recovery_decision(
    *,
    triage_decision: str,
    monitoring_clean: bool,
    hours_contained: float,
    answers: dict,
    thresholds: Thresholds | None = None,
) -> tuple[str, str, list[str], str]:
    """Hours and the monitoring flag are caller inputs. Jev does not compute them."""
    thr = thresholds or Thresholds()
    if hours_contained < 0:
        raise ValueError("hours_contained must be >= 0")
    safe = noul(answers, "safe_to_restore")
    residual = score(answers, "residual_risk")
    _picked, confidence = choice_of(answers, "restore_choice")

    must_wait = (not monitoring_clean) or (
        triage_decision == "contain_now" and hours_contained < 4
    )
    if must_wait:
        return (
            "remain_isolated",
            ActionBand.CONFIRM.value,
            ["keep:isolation", "collect:monitoring"],
            f"monitoring_clean={monitoring_clean}; hours={hours_contained:.1f}",
        )
    if safe < thr.high_stakes_noul or residual >= 1.0:
        return (
            "remain_isolated",
            ActionBand.HUMAN.value if residual >= 2.0 else ActionBand.CONFIRM.value,
            ["keep:isolation"],
            f"safe={safe:.2f}; residual={residual:.2f}",
        )
    if confidence < thr.high_stakes_confidence:
        return (
            "limited_restore",
            ActionBand.CONFIRM.value,
            ["restore:limited", "collect:monitoring"],
            f"confidence={confidence:.2f}",
        )
    return (
        "full_restore",
        ActionBand.CONFIRM.value,
        ["restore:full", "collect:monitoring"],
        f"safe={safe:.2f}; residual={residual:.2f}; confidence={confidence:.2f}",
    )


def closeout_decision(
    *,
    triage_decision: str,
    recovery_decision_name: str | None,
    monitoring_clean: bool,
    answers: dict,
    thresholds: Thresholds | None = None,
) -> tuple[str, str, list[str], str]:
    thr = thresholds or Thresholds()
    notes = noul(answers, "notes_complete")
    recurrence = score(answers, "recurrence_risk")
    _picked, confidence = choice_of(answers, "close_choice")
    contained = triage_decision == "contain_now"
    restored = recovery_decision_name in {"limited_restore", "full_restore"}

    if contained and not restored:
        return (
            "monitor",
            ActionBand.CONFIRM.value,
            ["monitor:open_case"],
            "containment has no restore decision",
        )
    if not monitoring_clean or recurrence >= 1.5 or notes < thr.noul_yes:
        return (
            "monitor",
            ActionBand.CONFIRM.value,
            ["monitor:open_case"],
            f"clean={monitoring_clean}; recurrence={recurrence:.2f}; notes={notes:.2f}",
        )
    if confidence < thr.auto_confidence:
        return (
            "monitor",
            ActionBand.HUMAN.value,
            ["monitor:open_case"],
            f"confidence={confidence:.2f}",
        )
    return (
        "close",
        ActionBand.CONFIRM.value,
        ["close:case"],
        f"notes={notes:.2f}; recurrence={recurrence:.2f}",
    )
