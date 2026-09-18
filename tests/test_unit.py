"""Unit tests that do not call the API."""

from jev_usecases.decisions import ActionBand, Thresholds, band_for_choice, band_for_noul
from jev_usecases.registry import USE_CASES


def test_registry_covers_expected_count():
    assert len(USE_CASES) >= 25


def test_band_for_choice():
    thr = Thresholds(auto_confidence=0.7, human_confidence=0.4)
    assert band_for_choice(confidence=0.9, thresholds=thr) is ActionBand.AUTO
    assert band_for_choice(confidence=0.5, thresholds=thr) is ActionBand.CONFIRM
    assert band_for_choice(confidence=0.2, thresholds=thr) is ActionBand.HUMAN


def test_band_for_noul_safety():
    thr = Thresholds(noul_yes=0.7, noul_no=0.3, high_stakes_noul=0.85)
    assert band_for_noul(noul=0.95, affirmative=False, thresholds=thr) is ActionBand.AUTO
    assert band_for_noul(noul=0.1, affirmative=False, high_stakes=True, thresholds=thr) is ActionBand.BLOCK
