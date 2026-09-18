"""Confidence / probability thresholds and routing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ActionBand(str, Enum):
    AUTO = "auto"
    CONFIRM = "confirm"
    HUMAN = "human"
    BLOCK = "block"


@dataclass(frozen=True)
class Thresholds:
    """Per-action confidence and probability floors.

    Tune these against labeled production traffic. Defaults are conservative.
    """

    # Minimum Choice/Score confidence to act without human review
    auto_confidence: float = 0.72
    # Below this confidence, always escalate
    human_confidence: float = 0.45
    # Noul "yes" / "no" cutoffs
    noul_yes: float = 0.70
    noul_no: float = 0.30
    # High-stakes actions (money movement, destructive tools)
    high_stakes_confidence: float = 0.88
    high_stakes_noul: float = 0.85


DEFAULT = Thresholds()


def band_for_choice(
    *,
    confidence: float,
    high_stakes: bool = False,
    thresholds: Thresholds = DEFAULT,
) -> ActionBand:
    floor = thresholds.high_stakes_confidence if high_stakes else thresholds.auto_confidence
    if confidence < thresholds.human_confidence:
        return ActionBand.HUMAN
    if confidence < floor:
        return ActionBand.CONFIRM
    return ActionBand.AUTO


def band_for_noul(
    *,
    noul: float,
    affirmative: bool,
    high_stakes: bool = False,
    thresholds: Thresholds = DEFAULT,
) -> ActionBand:
    """Map a Noul probability into an action band.

    ``affirmative=True`` means acting when the proposition is likely true
    (e.g. refund_requested). ``affirmative=False`` means acting when it is
    likely false (e.g. no_prompt_injection).
    """
    yes_floor = thresholds.high_stakes_noul if high_stakes else thresholds.noul_yes
    if affirmative:
        if noul >= yes_floor:
            return ActionBand.AUTO
        if noul <= thresholds.noul_no:
            return ActionBand.BLOCK if high_stakes else ActionBand.HUMAN
        return ActionBand.CONFIRM
    # Safety propositions: high noul => safe to proceed
    if noul >= yes_floor:
        return ActionBand.AUTO
    if noul <= thresholds.noul_no:
        return ActionBand.BLOCK
    return ActionBand.CONFIRM


def pick_handler(
    choice: str,
    confidence: float,
    handlers: dict[str, Any],
    *,
    fallback: str = "human",
    thresholds: Thresholds = DEFAULT,
) -> dict[str, Any]:
    band = band_for_choice(confidence=confidence, thresholds=thresholds)
    if band is ActionBand.HUMAN or choice not in handlers:
        return {"band": band.value, "handler": fallback, "choice": choice, "confidence": confidence}
    if band is ActionBand.CONFIRM:
        return {
            "band": band.value,
            "handler": handlers[choice],
            "requires_confirmation": True,
            "choice": choice,
            "confidence": confidence,
        }
    return {
        "band": band.value,
        "handler": handlers[choice],
        "requires_confirmation": False,
        "choice": choice,
        "confidence": confidence,
    }
