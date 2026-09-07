<div align="center">

# 02 — Text Generation App

![Status](https://img.shields.io/badge/status-in%20progress-orange)
![Python](https://img.shields.io/badge/python-3.14-blue)
![OpenAI](https://img.shields.io/badge/API-OpenAI-412991)

A command-line tool exploring core LLM API parameters — prompt, temperature, and token limits — through the lens of product decisions rather than pure engineering.

</div>

---

## Why this project

Building an AI feature means translating raw model parameters into decisions a user (or a PM) can actually reason about. This project takes three technical concepts — **prompt**, **temperature**, and **token limits** — and treats each one as a product problem, not just an API argument:

| Technical concept | Product framing |
|---|---|
| Temperature (0–2) | A UX translation problem — exposed to the user as "focused / balanced / creative," not a raw float |
| Max tokens | A cost control lever — exposed as "max words," since users think in words, not tokens |
| Error handling | Reliability as a product requirement — the app fails gracefully with human-readable messages instead of raw tracebacks, tested against a real rate-limit scenario |

## What it does

A simple interactive CLI that:
- Accepts a text prompt from the user
- Lets the user choose a creativity level in plain language (mapped internally to the correct temperature value)
- Lets the user set a response length in words (converted internally to a token limit)
- Sends the request to OpenAI's API and prints the generated response
- Handles common failure modes (rate limits, invalid API keys, network errors, invalid model/config) with clear, non-technical error messages
- Loops continuously until the user types "quit"

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file in this folder with:
OPENAI_API_KEY=your_key_here


Run it:
```bash
python3 app.py
```

## Tech stack

- Python 3.14
- OpenAI Python SDK
- python-dotenv (environment variable management)

## What I'm adding next

- Log each session (prompt, settings, tokens used, estimated cost) to a file, to make cost trade-offs visible over time.
- Compare output quality/cost across models (e.g. `gpt-4o-mini` vs `gpt-4o`) as a lightweight model-selection exercise.