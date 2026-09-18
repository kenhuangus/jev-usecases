"""Legal and compliance document checks."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typesafe_sdk import Choice, Noul, Score

from jev_usecases.client import answers_to_dict, get_client
from jev_usecases.decisions import ActionBand, Thresholds
from jev_usecases.models import UseCaseResult


class ComplianceDoc(BaseModel):
    doc_type: str
    text: str
    required_clauses: list[str] = Field(default_factory=list)
    prohibited_claims: list[str] = Field(default_factory=list)
    policy: str


def review_compliance_doc(doc: ComplianceDoc, *, thresholds: Thresholds | None = None) -> UseCaseResult:
    thr = thresholds or Thresholds()
    client = get_client()

    clause_q = {
        f"clause_{i}": Noul(instructions=f"The document includes required clause/requirement: {c}")
        for i, c in enumerate(doc.required_clauses)
    }
    prohibited_q = {
        f"prohibited_{i}": Noul(instructions=f"The document contains prohibited claim/content: {c}")
        for i, c in enumerate(doc.prohibited_claims)
    }

    response = client.system_one(
        state=doc.model_dump(),
        questions={
            **clause_q,
            **prohibited_q,
            "policy_violation": Noul(instructions="The document violates the stated policy"),
            "risk": Score(
                instructions="Legal/compliance risk if this document is published or signed as-is",
                criteria=["Low", "Moderate", "High"],
            ),
            "disposition": Choice(
                instructions="Recommended compliance disposition",
                criteria={
                    "approve": "Approve as-is",
                    "revise": "Needs revision",
                    "escalate_counsel": "Escalate to counsel",
                    "block": "Block publication/signing",
                },
            ),
        },
    )
    raw = answers_to_dict(response)
    a = raw["answers"]

    missing = [
        doc.required_clauses[i]
        for i in range(len(doc.required_clauses))
        if a[f"clause_{i}"]["noul"] < thr.noul_yes
    ]
    hits = [
        doc.prohibited_claims[i]
        for i in range(len(doc.prohibited_claims))
        if a[f"prohibited_{i}"]["noul"] >= thr.noul_yes
    ]

    if hits or a["policy_violation"]["noul"] >= thr.high_stakes_noul or a["risk"]["score"] >= 1.7:
        decision, band, actions = "block", ActionBand.BLOCK, ["block", "escalate:counsel"]
    elif missing or a["disposition"]["choice"] in {"revise", "escalate_counsel"}:
        decision = "escalate_counsel" if a["risk"]["score"] >= 1.2 else "revise"
        band = ActionBand.CONFIRM
        actions = ["request_revisions", *(["escalate:counsel"] if decision == "escalate_counsel" else [])]
    elif a["disposition"]["choice"] == "approve" and a["disposition"]["confidence"] >= thr.auto_confidence:
        decision, band, actions = "approve", ActionBand.AUTO, ["approve"]
    else:
        decision, band, actions = "revise", ActionBand.CONFIRM, ["request_revisions"]

    return UseCaseResult(
        use_case="legal_compliance",
        decision=decision,
        action_band=band.value,
        rationale=f"missing={missing}; prohibited_hits={hits}; risk={a['risk']['score']:.2f}",
        actions=actions,
        raw_answers=a,
        metadata={"missing_clauses": missing, "prohibited_hits": hits, "doc_type": doc.doc_type},
        model=raw.get("model"),
        usage=raw.get("usage"),
    )
