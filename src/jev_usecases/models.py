"""Common result envelope for every use case."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class UseCaseResult(BaseModel):
    use_case: str
    decision: str
    action_band: str
    rationale: str
    actions: list[str] = Field(default_factory=list)
    raw_answers: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    usage: dict[str, Any] | None = None

    def to_cli_dict(self) -> dict[str, Any]:
        return self.model_dump()
