<div align="center">

# 📖 Learning Journey

### Building Toward AI Product Leadership

![Phase 0](https://img.shields.io/badge/Phase%200-In%20Progress-FF8C00?style=flat-square)
![Phases 1–7](https://img.shields.io/badge/Phases%201–7-Queued-lightgrey?style=flat-square)
![Capstone](https://img.shields.io/badge/Capstone-Queued-lightgrey?style=flat-square)

[![Back to Portfolio](https://img.shields.io/badge/←-Back%20to%20Portfolio-24292E?style=flat)](./README.md)

</div>

---

Seven years at Microsoft taught me how to own platform-scale systems and the cross-functional tradeoffs that come with them. What I hadn't done yet was build with AI directly — so I closed that gap deliberately, in public, the same way I'd approach any capability build for a team: assess the gap, sequence the investment, and ship real artifacts at each stage rather than collect course certificates.

This log tracks that sequencing — not as a study log, but as a record of what I built and the calls I made at each stage. The approach pairs technical depth (prompting, RAG, evals, agents) with the strategic framing a senior PM is actually hired for: tradeoff ownership, cross-functional dependency mapping, and go/no-go judgment.

> 💡 **If you have five minutes:** start with **[Project 8 — AI Strategy Memo](./08-ai-strategy-memo)** and the exec summary in **[Project 7](./07-ai-feature-prd)**. Both are written to operate above the level of a single feature, which is the bar for this transition.

---

## Sequencing

| Phase | Focus | Key Resources | Status | Project |
|---|---|---|---|---|
| **0 — Foundations** | LLM fundamentals: tokens, context windows, training vs. inference, model vs. product vs. platform | [Karpathy: Intro to LLMs](https://www.youtube.com/watch?v=zjkBMFhNj_g) · [3Blue1Brown: Neural Networks](https://www.youtube.com/@3blue1brown) · [Generative AI for Beginners](https://github.com/microsoft/generative-ai-for-beginners) | ![In Progress](https://img.shields.io/badge/-In%20Progress-FF8C00) | — |
| **1 — Prompting** | Systematic prompt design: clarity, few-shot examples, structured output, chain-of-thought | [Anthropic Interactive Prompt Tutorial](https://github.com/anthropics/prompt-eng-interactive-tutorial) · [Anthropic Courses Repo](https://github.com/anthropics/courses) · [DeepLearning.AI: ChatGPT Prompt Engineering](https://www.deeplearning.ai/) | ![Queued](https://img.shields.io/badge/-Queued-lightgrey) | [01 — Prompt Library & Iteration Log](./01-prompt-library) |
| **2 — Context Engineering** | What goes into a model's context, why more isn't always better, curation strategies | [Effective Context Engineering (Anthropic)](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) · [Context Engineering for Agents (LangChain)](https://www.langchain.com/blog/context-engineering-for-agents) | ![Queued](https://img.shields.io/badge/-Queued-lightgrey) | [02 — Context Budget Case Study](./02-context-budget) |
| **3 — RAG** | Retrieval pipeline: chunking, embeddings, retrieval strategy, why RAG exists | [Generative AI for Beginners: RAG lesson](https://github.com/microsoft/generative-ai-for-beginners) · [DeepLearning.AI RAG courses](https://www.deeplearning.ai/courses) · NotebookLM | ![Queued](https://img.shields.io/badge/-Queued-lightgrey) | [03 — "Ask My Docs" RAG Tool](./03-ask-my-docs) |
| **4 — Prototyping** | Calling an LLM API, tool use / function calling, shipping a clickable demo | [Anthropic API Fundamentals](https://github.com/anthropics/courses) · [Generative AI for Beginners: Build lessons](https://github.com/microsoft/generative-ai-for-beginners) | ![Queued](https://img.shields.io/badge/-Queued-lightgrey) | [04 — AI Feature Prototype](./04-ai-feature-prototype) |
| **5 — Evals & Measurement** | Golden datasets, LLM-as-judge, offline vs. online evals, avoiding overfit | [Anthropic: Prompt Evaluations Course](https://github.com/anthropics/courses) · [A Gentle Intro to LLM Evaluation](https://www.confident-ai.com/blog/a-gentle-introduction-to-llm-evaluation) · [DeepEval Tutorials](https://deepeval.com/tutorials/tutorial-introduction) | ![Queued](https://img.shields.io/badge/-Queued-lightgrey) | [05 — Eval Harness](./05-eval-harness) |
| **6 — Agents & Agentic Workflows** | Planning + tool use, multi-agent patterns, failure modes, guardrails | [Building Effective Agents (Anthropic)](https://www.anthropic.com/engineering/building-effective-agents) · [AI Agents for Beginners](https://github.com/microsoft/ai-agents-for-beginners) · Hugging Face AI Agents Course | ![Queued](https://img.shields.io/badge/-Queued-lightgrey) | [06 — Multi-Tool Agent + Risk Memo](./06-agent-risk-memo) |
| **7 — AI PM Craft** | AI PRDs, build vs. buy vs. prompt, cost/latency/quality tradeoffs, safety basics | [How to Write a PRD for AI Features](https://www.ideaplan.io/blog/how-to-write-prd-for-ai-features) · [Writing PRDs for AI Products](https://neemz.medium.com/writing-prds-for-ai-products-a-practical-guide-for-senior-product-and-cross-functional-teams-f8f5040474a5) · Anthropic's Responsible Scaling Policy | ![Queued](https://img.shields.io/badge/-Queued-lightgrey) | [07 — AI Feature PRD](./07-ai-feature-prd) |
| **Capstone** | 12-month AI investment strategy for a real company: opportunities, sequencing, cross-functional dependencies, kill/continue metrics | — | ![Queued](https://img.shields.io/badge/-Queued-lightgrey) | [08 — AI Strategy Memo & Phased Roadmap](./08-ai-strategy-memo) |

---

## Extending the Core Sequence

Selecting 1–2 of these alongside the core phases, each targeting a distinct signal beyond technical execution:

| Addition | Signal it demonstrates |
|---|---|
| **AI Product Teardown Series** | Product judgment — reverse-engineering the architecture and failure points of 3–4 AI products in active use |
| **Model/Approach Comparison Study** | Build vs. buy vs. prompt, backed by eval data rather than opinion |
| **Cost/Latency Calculator** | AI features treated as products with real unit economics |
| **Failure Mode Museum** | An ongoing record of AI failures and root causes — visible, continuous engagement with the field |
| **Team Enablement Guide** | People-multiplication — a rollout plan for a team's AI adoption, not just individual output *(pairs with Project 1)* |

---

## How This Was Evaluated

Each phase closes on a demonstrated capability, not a completion badge — the bar was "can I diagnose why an AI output is wrong" or "can I sketch what belongs in a model's context," not hours logged. Phases 1–3 were sequenced to run in parallel, since prompting, context, and retrieval reinforce each other. Evals (Phase 5) were treated as non-negotiable rather than a phase to rush past on the way to agents — most AI PM failures come from shipping something that felt good in a demo with no way to know it degraded in production.
