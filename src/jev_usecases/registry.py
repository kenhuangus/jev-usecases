"""Registry mapping CLI names to runnable use-case demos with fixtures."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jev_usecases.models import UseCaseResult
from jev_usecases.soc.agents import CloseoutRequest, RecoveryRequest
from jev_usecases.soc.pipeline import run_agentic_soc
from jev_usecases.soc import agents as soc_agents
from jev_usecases.use_cases import (
    advertising,
    agent_harness,
    agent_trace,
    citation_check,
    coding_agent_guardrails,
    customer_support,
    demand_forecasting,
    ecommerce,
    feature_extraction,
    financial_crime,
    function_calling,
    gaming,
    hierarchical_classification,
    insurance_claims,
    invoice_processing,
    knowledge_graph,
    lead_generation,
    legal_compliance,
    llm_guardrails,
    model_routing,
    moderation,
    rag_retrieval,
    recruiting,
    risk_assessment,
    scientific_discovery,
    security_copilot,
    security_incidents,
    semantic_linting,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def _load(name: str) -> dict[str, Any]:
    path = FIXTURES / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _run_customer_support() -> UseCaseResult:
    data = _load("customer_support")
    return customer_support.evaluate_support(customer_support.SupportTicket(**data))


def _run_model_routing() -> UseCaseResult:
    return model_routing.route_model(model_routing.ModelRouteRequest(**_load("model_routing")))


def _run_llm_guardrails() -> UseCaseResult:
    data = _load("llm_guardrails")
    payload = {
        "surface": data["surface"],
        "content": data["content"],
        "tool_name": data.get("tool_name"),
        "tool_args": data.get("tool_args"),
    }
    if data.get("policy"):
        payload["policy"] = data["policy"]
    return llm_guardrails.evaluate_guardrail(llm_guardrails.GuardrailInput(**payload))


def _run_rag() -> UseCaseResult:
    data = _load("rag_retrieval")
    passages = [rag_retrieval.Passage(**p) for p in data["passages"]]
    return rag_retrieval.filter_rag_passages(
        rag_retrieval.RagFilterRequest(query=data["query"], passages=passages, max_keep=data.get("max_keep", 5))
    )


def _run_citation() -> UseCaseResult:
    return citation_check.verify_citation(citation_check.CitationCheck(**_load("citation_check")))


def _run_security() -> UseCaseResult:
    return security_incidents.triage_security_incident(
        security_incidents.SecurityAlert(**_load("security_incidents"))
    )


def _run_invoice() -> UseCaseResult:
    return invoice_processing.process_invoice(invoice_processing.InvoicePacket(**_load("invoice_processing")))


def _run_agent_trace() -> UseCaseResult:
    return agent_trace.review_agent_trace(agent_trace.AgentTrace(**_load("agent_trace")))


def _run_recruiting() -> UseCaseResult:
    data = _load("recruiting")
    job = recruiting.JobCriteria(**data["job"])
    return recruiting.evaluate_candidate(
        recruiting.CandidatePacket(
            name=data["name"],
            resume_text=data["resume_text"],
            interview_notes=data.get("interview_notes"),
            job=job,
        )
    )


def _run_leads() -> UseCaseResult:
    data = _load("lead_generation")
    icp = lead_generation.IdealCustomerProfile(**data["icp"])
    return lead_generation.score_lead(
        lead_generation.Lead(
            company_profile=data["company_profile"],
            executive_bio=data.get("executive_bio"),
            inbound_message=data.get("inbound_message"),
            icp=icp,
        )
    )


def _run_insurance() -> UseCaseResult:
    return insurance_claims.triage_claim(insurance_claims.InsuranceClaim(**_load("insurance_claims")))


def _run_aml() -> UseCaseResult:
    return financial_crime.prioritize_aml_alert(financial_crime.AmlAlert(**_load("financial_crime")))


def _run_legal() -> UseCaseResult:
    return legal_compliance.review_compliance_doc(legal_compliance.ComplianceDoc(**_load("legal_compliance")))


def _run_ecommerce() -> UseCaseResult:
    return ecommerce.moderate_listing(ecommerce.ProductListing(**_load("ecommerce")))


def _run_moderation() -> UseCaseResult:
    return moderation.moderate_content(moderation.ModerationItem(**_load("moderation")))


def _run_ads() -> UseCaseResult:
    return advertising.review_ad(advertising.AdPacket(**_load("advertising")))


def _run_gaming() -> UseCaseResult:
    return gaming.evaluate_player_signal(gaming.PlayerSignal(**_load("gaming")))


def _run_risk() -> UseCaseResult:
    return risk_assessment.assess_risk(risk_assessment.RiskPacket(**_load("risk_assessment")))


def _run_demand() -> UseCaseResult:
    return demand_forecasting.extract_demand_features(
        demand_forecasting.DemandText(**_load("demand_forecasting"))
    )


def _run_kg() -> UseCaseResult:
    return knowledge_graph.align_entities(knowledge_graph.EntityPair(**_load("knowledge_graph")))


def _run_lint() -> UseCaseResult:
    data = _load("semantic_linting")
    rules = [semantic_linting.LintRule(**r) for r in data["rules"]]
    return semantic_linting.run_semantic_lint(
        semantic_linting.LintRequest(path=data["path"], content=data["content"], rules=rules, kind=data.get("kind", "code"))
    )


def _run_features() -> UseCaseResult:
    data = _load("feature_extraction")
    specs = [feature_extraction.FeatureSpec(**s) for s in data["specs"]]
    return feature_extraction.extract_features(
        feature_extraction.FeatureExtractionRequest(
            record_id=data["record_id"], text=data["text"], extras=data.get("extras", {}), specs=specs
        )
    )


def _run_coding_guard() -> UseCaseResult:
    return coding_agent_guardrails.gate_tool_call(
        coding_agent_guardrails.ToolCallGate(**_load("coding_agent_guardrails"))
    )


def _run_functions() -> UseCaseResult:
    data = _load("function_calling")
    fns = [function_calling.FunctionSpec(**f) for f in data["functions"]]
    return function_calling.select_function_call(
        function_calling.FunctionCallRequest(
            utterance=data["utterance"], functions=fns, context=data.get("context", {})
        )
    )


def _run_hierarchy() -> UseCaseResult:
    data = _load("hierarchical_classification")

    def build(node: dict) -> hierarchical_classification.TaxonomyNode:
        return hierarchical_classification.TaxonomyNode(
            id=node["id"],
            label=node["label"],
            description=node["description"],
            children=[build(c) for c in node.get("children", [])],
        )

    return hierarchical_classification.classify_hierarchy(
        hierarchical_classification.HierarchicalRequest(
            text=data["text"], taxonomy=build(data["taxonomy"]), beam_width=data.get("beam_width", 3)
        )
    )


def _run_science() -> UseCaseResult:
    return scientific_discovery.screen_paper(
        scientific_discovery.PaperScreenRequest(**_load("scientific_discovery"))
    )


def _run_harness() -> UseCaseResult:
    return agent_harness.decide_agent_next_step(agent_harness.HarnessState(**_load("agent_harness")))


def _run_incident_copilot() -> UseCaseResult:
    return security_copilot.run_incident_copilot(
        security_incidents.SecurityAlert(**_load("security_incidents"))
    )


def _run_guarded_assistant() -> UseCaseResult:
    return security_copilot.run_guarded_security_answer(
        security_copilot.GuardedSecurityQuestion(**_load("security_guarded_assistant"))
    )


def _run_security_tool_gate() -> UseCaseResult:
    return security_copilot.run_security_tool_gate(
        security_copilot.ToolProposalRequest(**_load("security_tool_gate"))
    )


def _alert() -> security_incidents.SecurityAlert:
    return security_incidents.SecurityAlert(**_load("security_incidents"))


def _run_soc_triage() -> UseCaseResult:
    return soc_agents.run_triage_agent(_alert())


def _run_soc_mitigation() -> UseCaseResult:
    return soc_agents.run_mitigation_agent(_alert())


def _run_soc_investigation() -> UseCaseResult:
    return soc_agents.run_investigation_agent(_alert())


def _run_soc_escalation() -> UseCaseResult:
    return soc_agents.run_escalation_agent(_alert())


def _run_soc_pipeline() -> UseCaseResult:
    return run_agentic_soc(_alert())


def _run_soc_recovery() -> UseCaseResult:
    data = _load("soc_recovery")
    alert = security_incidents.SecurityAlert(**data["alert"])
    return soc_agents.run_recovery_agent(
        RecoveryRequest(
            alert=alert,
            triage_decision=data["triage_decision"],
            containment_actions_completed=data["containment_actions_completed"],
            monitoring_clean=data["monitoring_clean"],
            hours_contained=data["hours_contained"],
        )
    )


def _run_soc_closeout() -> UseCaseResult:
    data = _load("soc_closeout")
    alert = security_incidents.SecurityAlert(**data["alert"])
    return soc_agents.run_closeout_agent(
        CloseoutRequest(
            alert=alert,
            triage_decision=data["triage_decision"],
            recovery_decision=data.get("recovery_decision"),
            monitoring_clean=data["monitoring_clean"],
        )
    )


USE_CASES: dict[str, Callable[[], UseCaseResult]] = {
    "customer_support": _run_customer_support,
    "model_routing": _run_model_routing,
    "llm_guardrails": _run_llm_guardrails,
    "rag_retrieval": _run_rag,
    "citation_check": _run_citation,
    "security_incidents": _run_security,
    "security_incident_copilot": _run_incident_copilot,
    "security_guarded_assistant": _run_guarded_assistant,
    "security_tool_gate": _run_security_tool_gate,
    "soc_triage": _run_soc_triage,
    "soc_mitigation": _run_soc_mitigation,
    "soc_investigation": _run_soc_investigation,
    "soc_escalation": _run_soc_escalation,
    "soc_recovery": _run_soc_recovery,
    "soc_closeout": _run_soc_closeout,
    "soc_pipeline": _run_soc_pipeline,
    "invoice_processing": _run_invoice,
    "agent_trace": _run_agent_trace,
    "recruiting": _run_recruiting,
    "lead_generation": _run_leads,
    "insurance_claims": _run_insurance,
    "financial_crime": _run_aml,
    "legal_compliance": _run_legal,
    "ecommerce": _run_ecommerce,
    "moderation": _run_moderation,
    "advertising": _run_ads,
    "gaming": _run_gaming,
    "risk_assessment": _run_risk,
    "demand_forecasting": _run_demand,
    "knowledge_graph": _run_kg,
    "semantic_linting": _run_lint,
    "feature_extraction": _run_features,
    "coding_agent_guardrails": _run_coding_guard,
    "function_calling": _run_functions,
    "hierarchical_classification": _run_hierarchy,
    "scientific_discovery": _run_science,
    "agent_harness": _run_harness,
}


def run_use_case(name: str) -> UseCaseResult:
    if name not in USE_CASES:
        known = ", ".join(sorted(USE_CASES))
        raise KeyError(f"Unknown use case '{name}'. Known: {known}")
    return USE_CASES[name]()
