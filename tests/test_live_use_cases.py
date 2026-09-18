"""Live integration tests against TypeSafe Jev. Requires TYPESAFE_API_KEY."""

from __future__ import annotations

import os

import pytest

from jev_usecases.client import get_client
from jev_usecases.registry import USE_CASES, run_use_case

pytestmark = pytest.mark.live


@pytest.fixture(scope="session", autouse=True)
def _require_api_key():
    if not os.getenv("TYPESAFE_API_KEY"):
        pytest.skip("TYPESAFE_API_KEY not set")
    # Clear cached client in case env loaded late
    get_client.cache_clear()


def test_client_smoke():
    from typesafe_sdk import Noul

    client = get_client()
    resp = client.system_one(
        state="Urgent outage affecting all customers right now",
        questions={"urgent": Noul(instructions="Does this convey urgency?")},
    )
    assert float(resp.answers["urgent"].noul) > 0.5


@pytest.mark.parametrize("name", sorted(USE_CASES.keys()))
def test_use_case(name: str):
    result = run_use_case(name)
    assert result.use_case
    assert result.decision
    assert result.action_band in {"auto", "confirm", "human", "block"}
    assert isinstance(result.actions, list)
    assert result.model
