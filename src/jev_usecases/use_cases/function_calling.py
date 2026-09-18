"""Natural-language to typed function call selection over a closed catalog."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class FunctionSpec(BaseModel):
    name: str
    description: str
    arg_enums: dict[str, dict[str, str]] = Field(default_factory=dict)


class FunctionCallRequest(BaseModel):
    utterance: str
    functions: list[FunctionSpec] = Field(min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)


def select_function_call(req: FunctionCallRequest, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()

    fn_criteria = {f.name: f.description for f in req.functions}
    fn_criteria["none"] = "No function should be called"

    questions: dict = {
        "function": Choice(
            instructions="Which function should be invoked for this utterance?",
            criteria=fn_criteria,
        ),
        "should_call": Noul(instructions="A function from the catalog should be called now"),
    }

    # Speculative fan-out: ask every closed arg set up front
    for fn in req.functions:
        for arg_name, options in fn.arg_enums.items():
            questions[f"{fn.name}__{arg_name}"] = Choice(
                instructions=f"If calling {fn.name}, choose value for argument {arg_name}",
                criteria=options,
            )

    response = client.system_one(
        state={"utterance": req.utterance, "context": req.context},
        questions=questions,
    )
    raw = answers_to_dict(response)
    a = raw["answers"]

    fn = a["function"]["choice"]
    conf = a["function"]["confidence"]
    should = a["should_call"]["noul"]

    if fn == "none" or should < thr.noul_yes or conf < thr.human_confidence:
        return UseCaseResult(
            use_case="function_calling",
            decision="no_call",
            action_band=ActionBand.HUMAN.value if conf < thr.human_confidence else ActionBand.AUTO.value,
            rationale=f"function={fn} conf={conf:.2f}; should_call={should:.2f}",
            actions=["ask_clarification"],
            raw_answers=a,
            model=raw.get("model"),
            usage=raw.get("usage"),
        )

    selected = next(f for f in req.functions if f.name == fn)
    args = {}
    arg_confs = []
    for arg_name in selected.arg_enums:
        key = f"{fn}__{arg_name}"
        args[arg_name] = a[key]["choice"]
        arg_confs.append(a[key]["confidence"])

    min_conf = min([conf, *arg_confs]) if arg_confs else conf
    if min_conf >= thr.auto_confidence and should >= thr.noul_yes:
        band, decision, actions = ActionBand.AUTO, "call", [f"call:{fn}", f"args:{args}"]
    else:
        band, decision, actions = ActionBand.CONFIRM, "confirm_call", [f"confirm:{fn}", f"args:{args}"]

    return UseCaseResult(
        use_case="function_calling",
        decision=decision,
        action_band=band.value,
        rationale=f"function={fn}; args={args}; min_conf={min_conf:.2f}; should={should:.2f}",
        actions=actions,
        raw_answers=a,
        metadata={"function": fn, "args": args, "min_confidence": min_conf},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
