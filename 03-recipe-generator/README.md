<div align="center">

# 03 — Recipe Generator

![Status](https://img.shields.io/badge/status-complete-brightgreen)
![Python](https://img.shields.io/badge/python-3.14-blue)
![OpenAI](https://img.shields.io/badge/API-OpenAI-412991)

A multi-turn AI tool that generates recipes from available ingredients, then builds a shopping list and nutrition summary from the same conversation — exploring context management and dynamic cost control.

</div>

---

## Why this project

This project moves beyond a single-shot prompt into a genuine multi-turn conversation, and treats two real product problems as first-class design decisions rather than afterthoughts:

| Technical concept | Product framing |
|---|---|
| Multi-turn `messages` history | Shopping list and nutrition summary are generated *from* the recipes already in context — no redundant re-pasting of content, no wasted tokens |
| Dynamic `max_tokens` scaling | Token budget scales with `no_recipes` rather than a fixed guess — calibrated against real `usage` data instead of trial and error |
| Constraint transparency | The model is explicitly instructed to flag when a recipe can't fully meet a time or cuisine constraint, rather than silently drifting or hallucinating a fit |
| Nutrition framing | Nutrition output is explicitly scoped as general/informational, not personalized dietary advice |

## What it does

An interactive CLI that:
- Takes ingredients on hand, number of recipes wanted, a dietary filter, a time/difficulty constraint, and an optional cuisine preference
- Generates recipes matching those constraints, explicitly noting any it couldn't fully satisfy
- Follows up in the same conversation to generate a shopping list, excluding ingredients already on hand
- Follows up again to add a general nutritional estimate per recipe
- Prints token usage per call, plus a total for the full run, to make cost visible

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file in this folder with:
OPENAI_API_KEY=your_key_here


Run it:
```bash
python3 app-recipe.py
```

## Tech stack

- Python 3.14
- OpenAI Python SDK
- python-dotenv (environment variable management)

## What I'd build next

- Verification step: a second, smaller prompt that checks whether a recipe genuinely meets its stated time constraint, rather than trusting the model's self-report
- Save each run's output (recipes, shopping list, nutrition, token totals) to a file for a lightweight personal archive