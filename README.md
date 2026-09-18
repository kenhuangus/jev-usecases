# Jev use cases: typed decisions for software, not chat text

Jev returns Choice, Score, and Noul probabilities in 70 to 500 ms. This repository is the initial implementation of most of the decisions TypeSafe lists for that model.

Jev is the first public System One model from <a href="https://typesafe.ai" target="_blank">TypeSafe AI</a>. Diogo Almeida announced it on 15 September 2026, when TypeSafe made the company public, after a seed round led by DCVC. The model does not write prose. A program sends state plus typed questions. Jev returns a value inside the schema the program declared, plus a probability the program can threshold.

## What Jev is

A language model samples the next token from the tokens it already wrote. Software that needs a department, a severity, or a yes-or-no must parse that string and still handle a refusal, a type error, or an invented field. Jev does not generate strings. TypeSafe trains it with reinforcement learning for calibrated decisions (RLCD). The training target is a calibrated probability on a closed question, not a paragraph a rater prefers.

The public API is one endpoint, `POST https://api.typesafe.ai/v1/systemone`. The body contains `state` (a string, object, or array) and a map of questions. Three question types cover the closed decisions this repository implements:

- **Choice** picks one option from a set you name. The limit is 1 to 255 options. The answer includes the selected key, a probability for every key, and a confidence score.
- **Score** places the state on an ordered rubric of 2 to 10 levels. The answer can fall between levels. It also includes the level probabilities and a confidence score.
- **Noul** answers a yes-or-no instruction with a single probability from 0 to 1. That number is the estimated probability that the statement is true. Noul does not add a separate confidence field.

All three types can sit in one request. TypeSafe states that Jev evaluates them in parallel against the same state, so a tenth question adds tokens and almost no latency. Adding a question does not pass that answer as input to the next question.

TypeSafe publishes the cost and latency comparison in the launch note. Input is USD 0.042 per million tokens. Output tokens are not billed. End-to-end time on their West Coast service is 70 to 500 ms, against 3 to 329 seconds for the largest chat models they timed on the same task. Those figures are TypeSafe's, not an independent benchmark. Schema match is guaranteed: Jev cannot return a key you did not declare. It can still return the wrong valid key. Use the confidence value to decide whether to accept that label. On their calibration results, higher confidence corresponds to higher accuracy in aggregate. You still set the threshold in code according to the cost of a wrong label.

The class name System One refers to Daniel Kahneman's term for fast judgment in *Thinking, Fast and Slow*. The model name refers to William Stanley Jevons. TypeSafe states that a large decrease in the cost of a closed decision makes many more of those decisions worth running in software. Jev is not a smaller chat model. It has no text decoder for this task. Current model id in our fixture runs was `jev-1.13.0`.

Figure 1 compares a language model with Jev: the language model generates a string, and Jev returns a typed probability the program uses in an if-statement.

![Language model versus Jev](figures/fig1-llm-vs-jev.png)

*Figure 1: Language model versus Jev*

## How a call is built

Each module in this repository uses the same steps. The program assembles state from records it already has. It asks several narrow questions in one call. It reads probabilities. It applies thresholds, written procedures, and exact checks that code should compute instead of the model: sums, dates, duplicate flags, protected-path matches. The return value is a `UseCaseResult` with `decision`, `action_band`, and `actions`. The caller performs the action. Jev does not send email, move money, or run a shell command.

`action_band` is one of `auto`, `confirm`, `human`, or `block`. A read-only lookup can run automatically at a lower confidence than a refund or a host isolation. A flat probability distribution means the option descriptions do not separate the options.

TypeSafe's jaggedness note for `jev-1.13` lists known failures. Jev reads the instruction literally. It does not count reliably, and it does not compare dates as ordered quantities. Accuracy decreases when state contains fields the question does not need. User-controlled text in state can change the answer, so a check that puts that text in state has to be tested. Contradictory criteria score worse. Jev does not generate the missing sentence, the code diff, or the audit narrative. When a workflow needs those strings, a generative model writes them and Jev checks the draft.

Figure 2 lists those steps: state, questions, Jev, code, then a result the caller executes.

![Five-step Jev call](figures/fig2-call-path.png)

*Figure 2: Five steps from state to UseCaseResult*

## Why this repository exists

Chat models have produced usable text for years. Almeida states in the launch note that the missing capability is automation: a decision other code can call without parsing a paragraph and without a person reviewing every decision. TypeSafe's use-case map and workflow evals describe this task structure. Security alerts, invoices, support threads, and finished agent traces become many small questions plus rules in code. The four published workflows (security incidents, invoice processing, customer service, agent-trace review) score models on agreement with one fixed evaluation program, not on a claim that this program is the only correct policy.

We built this repository to put most of those decisions into callable Python, with fixtures a developer can run against the live API. It is the initial implementation of those use cases. It is not a claim that the thresholds, procedures, or labels are ready to run unattended in production. Set confidence cutoffs on labeled traffic before any automatic action moves money, isolates a host, or rejects a person.

On 18 September 2026 the 27 runners that call only Jev each returned a decision from `jev-1.13.0` on the committed fixtures. That run checks that each request returns a typed answer. It does not measure whether the answer is correct.

The initial set covers the decision types TypeSafe documents: classification, detection, scoring, routing, search and ranking, verification, feature extraction, and bounded extraction. The modules are:

- **Routing and triage.** `customer_support`, `model_routing`, `lead_generation`, `gaming`, `agent_harness`.
- **Verification and guardrails.** `llm_guardrails`, `rag_retrieval`, `citation_check`, `agent_trace`, `semantic_linting`, `coding_agent_guardrails`.
- **Records and risk.** `security_incidents`, `invoice_processing`, `insurance_claims`, `financial_crime`, `legal_compliance`, `risk_assessment`.
- **People, catalog, and research.** `recruiting`, `ecommerce`, `moderation`, `advertising`, `demand_forecasting`, `knowledge_graph`, `feature_extraction`, `function_calling`, `hierarchical_classification`, `scientific_discovery`.

Three further runners add a generative model beside Jev for security text. Those are `security_incident_copilot`, `security_guarded_assistant`, and `security_tool_gate`.

Seven further runners are the agentic SOC. `soc_triage` is the triage agent. `soc_mitigation` is the mitigation agent. `soc_investigation`, `soc_escalation`, `soc_recovery`, and `soc_closeout` cover evidence collection, paging, restore, and case close. `soc_pipeline` runs triage, investigation, mitigation, and escalation in that order. None of these runners isolate a host or run a shell command.

## Use cases included

Each use case builds typed state and Jev questions (`Choice`, `Score`, `Noul`), calls the live TypeSafe API, applies decision logic in code, and returns a `UseCaseResult` with `decision`, `action_band`, and `actions`.

| Name | What it does |
|---|---|
| `customer_support` | Intent/department routing, urgency, refund policy automation |
| `model_routing` | Choose a lower-cost model or a higher-capability model |
| `llm_guardrails` | Jailbreak / injection / PII / tool-call screening |
| `rag_retrieval` | Passage relevance + injection filter for RAG |
| `citation_check` | Claim vs source support verification |
| `security_incidents` | SOC decision: close, queue, or contain |
| `security_incident_copilot` | Incident procedure, then a Claude or OpenAI analyst brief, then Jev verification of that brief |
| `security_guarded_assistant` | Jev checks the prompt, the language model answers only if allowed, Jev checks the completion |
| `security_tool_gate` | Language model proposes one shell command; Jev allow/ask/block. The command is not executed |
| `soc_triage` | SOC triage agent: eight closed questions, then close, notify, queue, or contain |
| `soc_mitigation` | Mitigation agent: approves or holds isolate, session revoke, credential reset, and lateral block. It does not perform those actions |
| `soc_investigation` | Investigation agent: names log collections (`collect:auth_logs` and the other `collect:*` actions) |
| `soc_escalation` | Escalation agent: page on-call, hand to incident response, or keep the queue |
| `soc_recovery` | Recovery agent: remain isolated, limited restore, or full restore. Hours and the monitoring flag come from the caller |
| `soc_closeout` | Closeout agent: close, monitor, or reopen. A containment case cannot close before a restore decision |
| `soc_pipeline` | Intake order: triage, then investigation, mitigation, and escalation. Containment actions come only from the mitigation agent |
| `invoice_processing` | AP pay / hold / dispute / fraud review |
| `agent_trace` | Post-run human-review urgency |
| `recruiting` | Required-skill checks plus a weighted fit score |
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
| `coding_agent_guardrails` | Probability check before a shell, write, or edit tool call |
| `function_calling` | Closed-catalog NL→typed function calls |
| `hierarchical_classification` | Hierarchical classification by beam search; stops when confidence is low |
| `scientific_discovery` | Systematic-review paper screening |
| `agent_harness` | Continue/retry/ask/stop + skill suggestion |

## Security paths: Jev checks calls to the language model

A security workflow that needs a sentence still needs a language model. Jev does not write the analyst brief. The initial security runners keep the procedure in code, call Jev first, and call a generative model only when that check returns allow.

Provider selection lives in `jev_usecases.llm`. If `ANTHROPIC_API_KEY` or `CLAUDE_API_KEY` is set, the client calls Claude (`ANTHROPIC_MODEL`, default `claude-sonnet-4-5`). If neither Claude key is set, the client uses `OPENAI_API_KEY` (`OPENAI_MODEL`, default `gpt-4.1-mini`). There is no third provider.

`security_incident_copilot` runs the incident procedure, asks the language model for a brief that must follow that decision, then asks Jev whether the brief matches the decision, adds no facts absent from the alert, and includes no attack procedure. A failed check discards the brief. The procedure decision remains.

`security_guarded_assistant` checks the user text before any generative call. A block returns without calling Claude or OpenAI. An allowed call is checked again on the completion.

`security_tool_gate` asks the language model for one shell command, then runs the same tool check used by `coding_agent_guardrails`. The runner does not execute the command. `approved` in the metadata is the only field the caller should read before running the command. An allow from this initial check is not a change-management approval.

Figure 3 shows the check order: a blocked prompt never reaches the language model, and a draft that fails the second check is discarded.

![Jev checks the prompt and the draft](figures/fig3-security-gate.png)

*Figure 3: Jev checks the prompt and the draft*

## Agentic SOC agents

The SOC runners are the initial implementation of an agentic security operations flow. Jev answers closed questions. Code selects the action names. The caller executes them.

`soc_triage` calls `triage_security_incident`. The decision is `auto_close`, `notify_user`, `queue_tier2`, or `contain_now`. On 18 September 2026 the committed fixture returned `contain_now` from `jev-1.13.0`.

`soc_mitigation` runs only after that decision is `contain_now`. It asks whether isolation, session revocation, credential reset, and a lateral block are warranted, and whether the plan is broader than the evidence. A critical asset stays on `confirm` and adds `page:security_oncall`. If triage did not select `contain_now`, this agent returns `no_mitigation` and an empty action list.

`soc_investigation` returns `collect:auth_logs`, `collect:process_tree`, `collect:network_logs`, or `collect:identity_logs`. Those names are collection tasks for the caller. They are not shell commands.

`soc_escalation` chooses `page:security_oncall`, `handoff:incident_response`, `notice:affected_users`, or `stay:queue`. A critical asset or a `contain_now` decision pages on-call even when the Choice is `queue`.

`soc_recovery` reads `hours_contained` and `monitoring_clean` from the caller. Jev does not compute elapsed time. The agent keeps isolation when monitoring is not clean, or when a `contain_now` case has been contained for under four hours. `full_restore` still returns `confirm`, not `auto`.

`soc_closeout` cannot close a `contain_now` case until recovery has returned `limited_restore` or `full_restore`.

`soc_pipeline` calls triage once, then investigation, mitigation, and escalation with that same triage result. It removes `isolate_host`, `disable_sessions`, `block_lateral_paths`, and `force_password_reset` from the triage action list and publishes only the actions the mitigation agent approved.

`jev-usecases soc` runs these seven runners. It does not call Claude or OpenAI. Recovery and closeout are separate later steps because they need facts the intake alert does not contain.

## Run the initial set

Python 3.10 or newer. Copy `.env.example` to `.env` and set `TYPESAFE_API_KEY`. Do not commit `.env`.

```bash
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
jev-usecases list
jev-usecases run customer_support
```

`jev-usecases run-all` calls every registered runner, including the three security runners that need a reachable Claude or OpenAI endpoint and the seven SOC runners that call only Jev. `jev-usecases security` runs only those three language-model runners. `jev-usecases soc` runs the seven SOC runners. `pytest -m "not live"` checks thresholds, SOC action policy, and provider selection without the network. `pytest -m live` calls TypeSafe and needs `TYPESAFE_API_KEY`.

A library call does not go through the CLI. This support example builds state, asks Jev, and returns the decision object:

```python
from jev_usecases.use_cases.customer_support import SupportTicket, evaluate_support

result = evaluate_support(
    SupportTicket(
        message="Charged twice for order A-104. Refund the duplicate.",
        order={"id": "A-104"},
        refund_policy="Duplicate charges are eligible for a refund.",
    )
)
print(result.decision, result.action_band, result.actions)
```

The function sends one System One request, applies the refund rules in code, and returns `auto`, `confirm`, `human`, or `block`. It does not call a payment API.

## What this initial implementation did not implement

- Image, audio, or video input. Transcribe or describe those inputs before they enter `state`.
- Free-text extraction of an unknown string. Enumerate candidates in code or with a generative model, then have Jev select one.
- Counting and date comparison inside Jev. Those calculations run in code.
- One Jev question that combines several judgments. Split that into one question per judgment.
- Thresholds fitted to a measured false-positive rate. The numbers in `jev_usecases.decisions` are starting values.

TypeSafe's workflow evals on <a href="https://evals.typesafe.ai/" target="_blank">evals.typesafe.ai</a> measure agreement with GPT-6 Astra and Claude Fable 5.1 at high thinking. They do not measure agreement with a human label set. The charts compare cost and latency under one evaluation program.

## Key Takeaways

1. Jev answers closed questions. Choice, Score, and Noul come back with probabilities. The model does not write the string the user reads.
2. Code selects the next action. Thresholds, money, dates, and tool execution stay in code, not in Jev.
3. A wrong but valid label is still possible. Require higher confidence for high-cost actions, and send low-confidence cases to a person.
4. This repository is the initial implementation of most published Jev use cases, plus three security runners and seven SOC runners (triage, mitigation, investigation, escalation, recovery, closeout, and the intake pipeline). Jev checks the prompt before the generative call and checks the completion after it. The generative call uses Claude when a Claude key is set, and OpenAI otherwise. The SOC runners call Jev only and do not change hosts.
5. Fixture success on `jev-1.13.0` shows the calls return typed decisions. It does not show that the procedures are safe to run without review.

Additional reading on control of long-running multi-agent systems is <a href="https://www.amazon.com/dp/B0HF3F86YM" target="_blank">Harness Engineering</a>, and on agent graph structure is <a href="https://www.amazon.com/dp/B0HHZVDQQY" target="_blank">Graph Engineering for Agentic AI Systems</a>.

## References

1. **Diogo Almeida (2026).** *Introducing System One Models and Jev.* TypeSafe AI. <a href="https://typesafe.ai/blog/introducing-system-one-models-and-jev" target="_blank">Launch note</a>.
2. **TypeSafe AI (2026).** *Introduction.* TypeSafe docs. <a href="https://docs.typesafe.ai/introduction" target="_blank">Docs</a>.
3. **TypeSafe AI (2026).** *Example use cases.* TypeSafe docs. <a href="https://docs.typesafe.ai/concepts/use-case-map" target="_blank">Use-case map</a>.
4. **TypeSafe AI (2026).** *Jev 1.13 jaggedness.* TypeSafe docs. <a href="https://docs.typesafe.ai/model-jaggedness/jev-1.13" target="_blank">Jaggedness</a>.
5. **TypeSafe AI (2026).** *Workflow evals.* <a href="https://evals.typesafe.ai/" target="_blank">evals.typesafe.ai</a>.
6. **Sydney Runkle and Hunter Lovell (2026).** *Building a Harness with Jev.* LangChain. <a href="https://www.langchain.com/blog/building-a-harness-with-jev" target="_blank">LangChain</a>.
7. **Ken Huang (2026).** *Harness Engineering: Design Patterns for Securing Long-Horizon Multi-Agent AI Systems.* Amazon Kindle. <a href="https://www.amazon.com/dp/B0HF3F86YM" target="_blank">Amazon</a>.
8. **Ken Huang (2026).** *Graph Engineering for Agentic AI Systems.* Amazon Kindle. <a href="https://www.amazon.com/dp/B0HHZVDQQY" target="_blank">Amazon</a>.
