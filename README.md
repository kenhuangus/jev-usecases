# Jev Use Cases

Production-ready [TypeSafe AI Jev](https://typesafe.ai) (System One) harnesses for real software workflows.

Each use case:

1. Builds typed `state` + Jev questions (`Choice` / `Score` / `Noul`)
2. Calls the live TypeSafe API
3. Applies **code-owned** decision logic (thresholds, playbooks, deterministic gates)
4. Returns an actionable `UseCaseResult` (`decision`, `action_band`, `actions`)

This is not a demo stub layer. Fixtures drive realistic inputs; the CLI and tests hit the live API.

## Setup

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\pip install -e ".[dev]"
# macOS/Linux
source .venv/bin/activate && pip install -e ".[dev]"

cp .env.example .env
# put TYPESAFE_API_KEY in .env (never commit .env)
```

## CLI

```bash
jev-usecases list
jev-usecases run customer_support
jev-usecases run coding_agent_guardrails --json-out
jev-usecases run-all
```

## Library usage

```python
from jev_usecases.use_cases.customer_support import SupportTicket, evaluate_support

result = evaluate_support(
    SupportTicket(
        message="Charged twice for order A-104. Refund the duplicate.",
        order={"id": "A-104", "charges": [{"amount_usd": 49, "status": "captured"}] * 2},
        refund_policy="Duplicate charges are eligible for a refund.",
    )
)
print(result.decision, result.actions)
```

## Use cases included

| Name | What it does |
|---|---|
| `customer_support` | Intent/department routing, urgency, refund policy automation |
| `model_routing` | Cascade cheap vs frontier LLM selection |
| `llm_guardrails` | Jailbreak / injection / PII / tool-call screening |
| `rag_retrieval` | Passage relevance + injection filter for RAG |
| `citation_check` | Claim vs source support verification |
| `security_incidents` | SOC close / queue / contain playbook |
| `invoice_processing` | AP pay / hold / dispute / fraud review |
| `agent_trace` | Post-run human-review urgency |
| `recruiting` | Must-have gates + composite fit scoring |
| `lead_generation` | ICP fit and sales priority |
| `insurance_claims` | STP vs SIU vs specialist routing |
| `financial_crime` | AML alert prioritization |
| `legal_compliance` | Required clauses / prohibited claims |
| `ecommerce` | Listing moderation and category normalization |
| `moderation` | Trust & safety allow/warn/remove/ban |
| `advertising` | Brand safety and claim compliance |
| `gaming` | Player toxicity / churn / support routing |
| `risk_assessment` | Unstructured risk typing and escalation |
| `demand_forecasting` | Semantic demand features for forecasting models |
| `knowledge_graph` | Entity merge vs curator review |
| `semantic_linting` | CI semantic lints for code/writing |
| `feature_extraction` | Calibrated ML features from text |
| `coding_agent_guardrails` | Shell/write tool-call probability gate |
| `function_calling` | Closed-catalog NL→typed function calls |
| `hierarchical_classification` | Taxonomy beam walk with abstention |
| `scientific_discovery` | Systematic-review paper screening |
| `agent_harness` | Continue/retry/ask/stop + skill suggestion |

## Tests

```bash
# unit only
pytest -m "not live"

# live API (uses .env)
pytest -m live -q
```

## Design rules

- **Code owns control flow**; Jev owns narrow semantic judgments
- Prefer **many atomic questions** in one call (speculative fan-out)
- Gate high-stakes actions on **confidence + probability thresholds**
- Keep arithmetic, date math, and exact matches in code
- Filter state before calling Jev (avoid context rot)

## Security

- `.env` is gitignored. Rotate any key that was shared in chat or logs.
- Do not commit API keys, customer PII, or production traces.
