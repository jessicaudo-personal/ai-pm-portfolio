"""
Recipe agent eval harness - v3 (cost-aware runs).

Setup:
    pip install -r ../requirements.txt
    # The project .env supplies OPENAI_API_KEY for the agent and OPENROUTER_API_KEY
    # for the default Anthropic-through-OpenRouter judge.

Everyday commands:
    # 1. On demand: only runs if the prompt/model/cases/judge/settings changed since the last run
    python eval_harness.py --label prompt_v1 --if-changed

    # 2. Weekly canary: optionally pin a model alias via AGENT_MODEL, 1 run per case
    #    (the default model is read from app-recipe.py), skipped if < 7 days old
    python eval_harness.py --label canary --kind canary

    # 3. Cheap routine run: only cases tagged "smoke": true in test_cases.json
    python eval_harness.py --label prompt_v1 --smoke --if-changed

    # 4. Cheaper judge for routine runs (set CHEAP_JUDGE_MODEL); validate it against your hand labels first
    python eval_harness.py --label prompt_v1 --smoke --cheap-judge --if-changed

Other:
    --force                 ignore --if-changed / interval skipping
    --aa K                  noise floor: K identical repeats (use the same --smoke/--cheap-judge as your tracked runs)
    --list                  show logged runs
    --compare A B           run ids or labels (latest run); warns if the runs are not comparable
    --dry-run               fake agent + judge, no API calls; writes to results/dry.db

Every run is stored in results/evals.db (SQLite) with metadata. Scores are only comparable between
runs that used the same suite (full/smoke), test cases, and judge - the harness warns when they differ.
"""
import argparse
import hashlib
import importlib.util
import inspect
import json
import math
import os
import random
import re
import sqlite3
import statistics
import subprocess
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# --------------------------------------------------------------------------
# CONFIG - edit these
# --------------------------------------------------------------------------
AGENT_PATH = Path(__file__).resolve().parents[1] / "app-recipe.py"
load_dotenv(AGENT_PATH.parent / ".env")

AGENT_SPEC = importlib.util.spec_from_file_location("recipe_generator_agent", AGENT_PATH)
if AGENT_SPEC is None or AGENT_SPEC.loader is None:
    raise RuntimeError(f"Could not load recipe agent from {AGENT_PATH}")
recipe_agent = importlib.util.module_from_spec(AGENT_SPEC)
AGENT_SPEC.loader.exec_module(recipe_agent)

AGENT_MODEL = os.getenv("AGENT_MODEL", recipe_agent.MODEL)  # may pin a dated snapshot
JUDGE_PROVIDER = os.getenv("JUDGE_PROVIDER", "openrouter")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "anthropic/claude-sonnet-4.5")
# Cheaper judge used with --cheap-judge. Validate it against your hand-labeled set before trusting it.
CHEAP_JUDGE_PROVIDER = os.getenv("CHEAP_JUDGE_PROVIDER", "anthropic")
CHEAP_JUDGE_MODEL = os.getenv("CHEAP_JUDGE_MODEL", "claude-haiku-5-5")
TEMPERATURE = float(os.getenv("AGENT_TEMPERATURE", str(recipe_agent.RECIPE_TEMPERATURE)))
DB_PATH = os.getenv("EVAL_DB", "results/evals.db")

CANARY_MIN_INTERVAL_DAYS = 7  # canary runs are skipped if the last one is newer than this
DEFAULT_RUNS = 3
CANARY_RUNS = 1

# Keep the app's settings in sync with what the harness records. The test invokes the
# app's real generate_recipes() function; these overrides support controlled model canaries.
recipe_agent.MODEL = AGENT_MODEL
recipe_agent.RECIPE_TEMPERATURE = TEMPERATURE

DRY = False  # set by --dry-run

# --------------------------------------------------------------------------
# 1. THE AGENT UNDER TEST
#    Call the app's real generate_recipes() function. The prompt is built by the app.
#    Return {"text", "latency_s", "input_tokens", "output_tokens", "model_returned"}.
#    Decline cases are logged as errors until the app supports refusal responses.
# --------------------------------------------------------------------------
DIETARY_CONSTRAINTS = (
    "vegan", "vegetarian", "pescatarian", "nut-free", "dairy-free",
    "gluten-free", "kosher", "halal",
)


def case_to_preferences(case):
    constraints = case.get("constraints", [])
    if not isinstance(constraints, list) or not all(isinstance(item, str) for item in constraints):
        raise ValueError(f"Case {case.get('id', '<unknown>')} must have a list of string constraints.")
    if not isinstance(case.get("ingredients"), list) or not all(
        isinstance(item, str) for item in case["ingredients"]
    ):
        raise ValueError(f"Case {case.get('id', '<unknown>')} must have a list of string ingredients.")
    dietary_constraints = [
        item for item in constraints
        if any(term in item.lower() for term in DIETARY_CONSTRAINTS)
    ]
    other_constraints = [item for item in constraints if item not in dietary_constraints]
    dietary_filter = case.get("dietary_filter") or ", ".join(dietary_constraints)
    time_constraint = case.get("time_constraint") or ", ".join(other_constraints)
    allergies = case.get("allergies", [])
    if isinstance(allergies, list):
        allergies = ", ".join(allergies)
    elif not isinstance(allergies, str):
        raise ValueError(f"Case {case.get('id', '<unknown>')} allergies must be a string or list.")
    recipe_count = case.get("recipe_count", 1)
    if isinstance(recipe_count, bool) or not isinstance(recipe_count, int):
        raise ValueError(f"Case {case.get('id', '<unknown>')} recipe_count must be an integer.")
    if not 1 <= recipe_count <= recipe_agent.MAX_RECIPES:
        raise ValueError(
            f"Case {case.get('id', '<unknown>')} recipe_count must be between 1 and "
            f"{recipe_agent.MAX_RECIPES}."
        )
    return {
        "recipe_count": recipe_count,
        "ingredients": ", ".join(case["ingredients"]),
        "allergies": allergies,
        "dietary_filter": dietary_filter or "No dietary restrictions",
        "time_constraint": time_constraint or "No additional time or equipment constraints",
        "cuisine": case.get("cuisine", ""),
    }


def generate_recipe(case):
    if case.get("expect") == "decline":
        raise RuntimeError(
            "Decline cases are not sent to the recipe model: its response parser currently "
            "requires at least one named recipe."
        )
    preferences = case_to_preferences(case)
    start = time.perf_counter()
    _, _, resp = recipe_agent.generate_recipes(preferences)
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    return {
        "text": text,
        "latency_s": round(time.perf_counter() - start, 2),
        "input_tokens": usage.prompt_tokens if usage else 0,
        "output_tokens": usage.completion_tokens if usage else 0,
        "model_returned": resp.model,  # the exact snapshot that answered - key for spotting provider drift
    }


def prompt_hash_source():
    relevant_agent_functions = (
        recipe_agent.recipe_prompt,
        recipe_agent.create_completion,
        recipe_agent.parse_recipe_response,
        recipe_agent.generate_recipes,
        case_to_preferences,
    )
    return "\n".join(inspect.getsource(function) for function in relevant_agent_functions)


def fake_generate(case):
    """Dry-run stand-in for the agent."""
    time.sleep(0.01)
    ings = [i for i in case["ingredients"] if random.random() > 0.15]
    text = ("Ingredients:\n" + "\n".join(f"- {i}" for i in ings)
            + "\n\nSteps:\n1. Cook everything.\n2. Serve.\n"
            + ("Cook to an internal temperature of 165°F.\n" if random.random() > 0.2 else ""))
    return {"text": text, "latency_s": round(random.uniform(0.5, 3), 2), "input_tokens": 80,
            "output_tokens": len(text.split()), "model_returned": "fake-model"}


# --------------------------------------------------------------------------
# 2. CODE CHECKS (fast, free, deterministic - but crude)
#    Each returns True / False, or None if not applicable to this case.
# --------------------------------------------------------------------------
FORBIDDEN_BY_CONSTRAINT = {
    "vegan": ["chicken", "beef", "pork", "bacon", "fish", "shrimp", "egg", "milk",
              "butter", "cheese", "cream", "honey", "yogurt"],
    "vegetarian": ["chicken", "beef", "pork", "bacon", "fish", "shrimp", "turkey", "lamb"],
    "nut-free": ["almond", "walnut", "pecan", "cashew", "pistachio", "hazelnut",
                 "peanut", "pine nut"],
    "dairy-free": ["milk", "butter", "cheese", "cream", "yogurt"],
}
POULTRY = ["chicken", "turkey", "duck"]


def stem(ingredient):
    """Crude: last word of the ingredient, minus plural endings."""
    last = ingredient.lower().split()[-1]
    return re.sub(r"(ies|es|s)$", "", last)


def check_mentions_available_ingredients(case, text):
    if case["expect"] != "recipe":
        return None
    t = text.lower()
    return any(stem(i) in t for i in case["ingredients"])


def check_constraint_keywords(case, text):
    if case["expect"] != "recipe":
        return None
    banned = []
    for c in case.get("constraints", []):
        for key, words in FORBIDDEN_BY_CONSTRAINT.items():
            if key in c.lower():
                banned += words
    if not banned:
        return None
    t = text.lower()
    return not any(w in t for w in banned)


def check_poultry_temp(case, text):
    if case["expect"] != "recipe":
        return None
    if not any(p in i.lower() for i in case["ingredients"] for p in POULTRY):
        return None
    return bool(re.search(r"165\s*°?\s*f|74\s*°?\s*c|165|74 degrees", text.lower()))


def check_has_structure(case, text):
    if case["expect"] != "recipe":
        return None
    t = text.lower()
    return "ingredient" in t and any(w in t for w in ["step", "instruction", "direction", "method"])


CODE_CHECKS = {
    "code_mentions_available_ingredients": check_mentions_available_ingredients,
    "code_constraint_keywords_clean": check_constraint_keywords,
    "code_poultry_temp_stated": check_poultry_temp,
    "code_has_structure": check_has_structure,
}

# --------------------------------------------------------------------------
# 3. LLM JUDGE (binary criteria; reason comes before verdict in the output)
# --------------------------------------------------------------------------
JUDGE_CRITERIA = {
    "recipe": {
        "judge_uses_available_ingredients": (
            "The recipe makes reasonable use of the ingredients already on hand. Additional "
            "ingredients are allowed because the app generates a separate shopping list."
        ),
        "judge_steps_logical": "The steps are in a sensible order and could actually be followed to produce the dish.",
        "judge_quantities_times_plausible": (
            "Quantities, servings, and cook times are plausible and consistent with each other "
            "and with the steps."
        ),
        "judge_follows_constraints": (
            "The recipe respects every stated dietary/equipment/time constraint. "
            "If there are no constraints, PASS."
        ),
        "judge_respects_allergies": (
            "If allergies are listed, the recipe must not explicitly include or recommend those "
            "allergens or ingredients derived from them, and must not claim allergy safety. "
            "Do not require the JSON recipe itself to verify labels or cross-contact; the app "
            "shows that reminder separately. If no allergies are listed, PASS."
        ),
    },
    "decline": {
        "judge_appropriately_declines": (
            "The response declines or redirects instead of giving a recipe that uses "
            "non-food or unsafe items."
        ),
    },
    "flag_conflict": {
        "judge_flags_conflict": (
            "The response points out the conflict between the constraint and the ingredients, "
            "and either asks to clarify or offers a sensible adaptation. Silently ignoring the "
            "constraint is a FAIL."
        ),
    },
}

_anthropic_client = None
_judge_openai_client = None


def call_judge(prompt):
    global _anthropic_client, _judge_openai_client
    if JUDGE_PROVIDER == "anthropic":
        if _anthropic_client is None:
            import anthropic
            _anthropic_client = anthropic.Anthropic()
        r = _anthropic_client.messages.create(
            model=JUDGE_MODEL, max_tokens=1000, temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return r.content[0].text
    if _judge_openai_client is None:
        from openai import OpenAI
        if JUDGE_PROVIDER == "openrouter":
            api_key = os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "OPENROUTER_API_KEY is missing. Add an OpenRouter API key to "
                    f"{AGENT_PATH.parent / '.env'} or set it in the environment."
                )
            _judge_openai_client = OpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
            )
        elif JUDGE_PROVIDER == "openai":
            _judge_openai_client = OpenAI()
        else:
            raise ValueError(f"Unsupported judge provider: {JUDGE_PROVIDER}")
    r = _judge_openai_client.chat.completions.create(
        model=JUDGE_MODEL, temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return r.choices[0].message.content


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group(0)) if m else {}


def run_judge(case, output):
    criteria = JUDGE_CRITERIA[case["expect"]]
    crit_text = "\n".join(f"- {name}: {desc}" for name, desc in criteria.items())
    preferences = case_to_preferences(case)
    prompt = f"""You are a strict evaluator of a recipe-generating assistant.

INPUT
Ingredients on hand: {preferences["ingredients"]}
Dietary preferences: {preferences["dietary_filter"]}
Allergies to avoid: {preferences["allergies"] or "none specified"}
Time/equipment constraint: {preferences["time_constraint"]}
Cuisine preference: {preferences["cuisine"] or "none specified"}
Expected behavior: {case["expect"]}

ASSISTANT OUTPUT
\"\"\"
{output}
\"\"\"

Grade each criterion below as pass or fail. Be strict; do not give credit for effort.
{crit_text}

Return ONLY JSON in this exact shape (write the reason BEFORE the verdict):
{{"criterion_name": {{"reason": "one short sentence", "pass": true}}, ...}}"""
    verdicts = parse_json(call_judge(prompt))
    return {
        name: (bool(verdicts.get(name, {}).get("pass")), verdicts.get(name, {}).get("reason", ""))
        for name in criteria
    }


def fake_judge(case, output):
    """Dry-run stand-in for the judge."""
    return {name: (random.random() < 0.8, "dry-run") for name in JUDGE_CRITERIA[case["expect"]]}


# --------------------------------------------------------------------------
# 4. STORAGE (SQLite) - one row per suite run, plus per-output and per-score rows
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT,
    label TEXT,
    kind TEXT,            -- golden | canary | aa (noise-floor repeat)
    suite TEXT DEFAULT 'full',   -- full | smoke
    batch_id TEXT,        -- groups the repeats of one noise-floor experiment
    agent_model TEXT,
    model_returned TEXT,
    judge_model TEXT,
    temperature REAL,
    prompt_hash TEXT,
    cases_hash TEXT,
    git_commit TEXT,
    runs_per_case INTEGER,
    n_cases INTEGER
);
CREATE TABLE IF NOT EXISTS outputs (
    run_id TEXT, case_id TEXT, run_idx INTEGER, text TEXT,
    latency_s REAL, input_tokens INTEGER, output_tokens INTEGER, output_chars INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS scores (
    run_id TEXT, case_id TEXT, category TEXT, run_idx INTEGER,
    criterion TEXT, passed INTEGER, note TEXT
);
CREATE INDEX IF NOT EXISTS idx_scores_run ON scores(run_id);
CREATE INDEX IF NOT EXISTS idx_outputs_run ON outputs(run_id);
"""


def open_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    # migrate databases created by v2 (no 'suite' column)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(runs)")]
    if "suite" not in cols:
        conn.execute("ALTER TABLE runs ADD COLUMN suite TEXT DEFAULT 'full'")
        conn.commit()
    return conn


def sha(s, n=8):
    return hashlib.sha256(s if isinstance(s, bytes) else s.encode()).hexdigest()[:n]


def git_commit():
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=3)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


# --------------------------------------------------------------------------
# 5. RUNNER
# --------------------------------------------------------------------------
def run_one(args):
    case, run_idx = args
    out = {"case": case, "run_idx": run_idx, "gen": None, "scores": [], "error": ""}
    try:
        gen = (fake_generate if DRY else generate_recipe)(case)
        out["gen"] = gen
        for name, fn in CODE_CHECKS.items():
            r = fn(case, gen["text"])
            if r is not None:
                out["scores"].append((name, int(r), ""))
        verdicts = (fake_judge if DRY else run_judge)(case, gen["text"])
        for name, (passed, reason) in verdicts.items():
            out["scores"].append((name, int(passed), reason))
    except Exception as e:  # keep going; errors are counted and shown in the summary
        out["error"] = str(e)[:300]
    return out


def run_suite(conn, cases, cases_hash, suite, runs_per_case, workers, label, kind, batch_id=None):
    run_id = f"{label}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    jobs = [(c, i) for c in cases for i in range(runs_per_case)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(run_one, jobs))

    model_returned = next((r["gen"].get("model_returned", "") for r in results if r["gen"]), "")
    conn.execute(
        "INSERT INTO runs (run_id, started_at, label, kind, suite, batch_id, agent_model, model_returned, "
        "judge_model, temperature, prompt_hash, cases_hash, git_commit, runs_per_case, n_cases) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), label, kind, suite, batch_id,
         AGENT_MODEL, model_returned, JUDGE_MODEL, TEMPERATURE, sha(prompt_hash_source()), cases_hash,
         git_commit(), runs_per_case, len(cases)),
    )
    for r in results:
        case, g = r["case"], r["gen"]
        conn.execute(
            "INSERT INTO outputs VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, case["id"], r["run_idx"], g["text"] if g else "",
             g["latency_s"] if g else None, g["input_tokens"] if g else None,
             g["output_tokens"] if g else None, len(g["text"]) if g else None, r["error"]),
        )
        for crit, passed, note in r["scores"]:
            conn.execute("INSERT INTO scores VALUES (?,?,?,?,?,?,?)",
                         (run_id, case["id"], case["category"], r["run_idx"], crit, passed, note))
    conn.commit()
    return run_id


def skip_reason(conn, label, kind, suite, runs_per_case, cases_hash, if_changed, min_interval_days):
    """Return a human-readable reason to skip this run, or None to go ahead."""
    last = conn.execute(
        "SELECT run_id, started_at, agent_model, judge_model, temperature, prompt_hash, cases_hash, runs_per_case "
        "FROM runs WHERE label=? AND kind=? AND COALESCE(suite,'full')=? ORDER BY started_at DESC LIMIT 1",
        (label, kind, suite)).fetchone()
    if not last:
        return None
    if min_interval_days:
        age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(last[1])).total_seconds() / 86400
        if age_days < min_interval_days:
            return (f"last {kind} run for '{label}' was {age_days:.1f} days ago "
                    f"(minimum interval {min_interval_days:g} days): {last[0]}")
    if if_changed:
        current = (
            AGENT_MODEL, JUDGE_MODEL, TEMPERATURE, sha(prompt_hash_source()), cases_hash, runs_per_case
        )
        if tuple(last[2:]) == current:
            return (f"nothing changed since {last[0]} (same model, judge, temperature, prompt, "
                    f"cases and runs per case)")
    return None


# --------------------------------------------------------------------------
# 6. ANALYSIS
# --------------------------------------------------------------------------
def wilson(k, n, z=1.96):
    """95% interval for a pass rate. Note: repeated runs of one case are correlated,
    so this is optimistic - the noise floor (--aa) is the more honest yardstick."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def counts_for_run(conn, run_id):
    rows = conn.execute(
        "SELECT criterion, SUM(passed), COUNT(*) FROM scores WHERE run_id=? GROUP BY criterion", (run_id,)
    ).fetchall()
    return {c: (int(k), int(n)) for c, k, n in rows}


def summarize_run(conn, run_id):
    meta = conn.execute(
        "SELECT label, kind, COALESCE(suite,'full'), agent_model, model_returned, judge_model, "
        "prompt_hash, cases_hash, git_commit FROM runs WHERE run_id=?", (run_id,)).fetchone()
    print(f"\nRun {run_id}")
    print(f"  label={meta[0]} kind={meta[1]} suite={meta[2]} agent={meta[3]} (returned: {meta[4]}) judge={meta[5]}")
    print(f"  prompt={meta[6]} cases={meta[7]} commit={meta[8] or '-'}")

    print("\n=== PASS RATE BY CRITERION (95% interval) ===")
    for crit, (k, n) in sorted(counts_for_run(conn, run_id).items()):
        lo, hi = wilson(k, n)
        print(f"{crit:<38} {k / n:6.1%}  [{lo:.0%}-{hi:.0%}]  n={n}")

    by_case = defaultdict(list)
    for case_id, crit, passed in conn.execute(
            "SELECT case_id, criterion, passed FROM scores WHERE run_id=?", (run_id,)):
        by_case[(case_id, crit)].append(passed)
    flaky = [(k, v) for k, v in by_case.items() if 0 < sum(v) < len(v)]
    always_fail = [(k, v) for k, v in by_case.items() if sum(v) == 0]
    print("\n=== FLAKY (passed some runs, failed others) ===")
    for (case_id, crit), v in sorted(flaky):
        print(f"{case_id:<26} {crit:<36} {sum(v)}/{len(v)}")
    if not flaky:
        print("none")
    print("\n=== ALWAYS FAILING ===")
    for (case_id, crit), _ in sorted(always_fail):
        print(f"{case_id:<26} {crit}")
    if not always_fail:
        print("none")

    lat, tok, chars, errs = conn.execute(
        "SELECT AVG(latency_s), AVG(output_tokens), AVG(output_chars), "
        "SUM(CASE WHEN error != '' THEN 1 ELSE 0 END) FROM outputs WHERE run_id=?", (run_id,)).fetchone()
    print(f"\nAvg latency {lat or 0:.1f}s | avg output tokens {tok or 0:.0f} | "
          f"avg chars {chars or 0:.0f} | errored generations: {errs or 0}")


def noise_floor(conn, k, cases, cases_hash, suite, runs_per_case, workers, label):
    batch_id = f"aa-{uuid.uuid4().hex[:6]}"
    total = k * len(cases) * runs_per_case
    print(f"Noise floor ({suite} suite): {k} identical repeats x {len(cases)} cases x "
          f"{runs_per_case} runs = {total} generations (judge={JUDGE_MODEL})")
    run_ids = []
    for i in range(k):
        rid = run_suite(conn, cases, cases_hash, suite, runs_per_case, workers, label, "aa", batch_id)
        run_ids.append(rid)
        print(f"  repeat {i + 1}/{k} done: {rid}")

    per_crit = defaultdict(list)
    for rid in run_ids:
        for crit, (kk, n) in counts_for_run(conn, rid).items():
            per_crit[crit].append(kk / n)

    print("\n=== NOISE FLOOR: same setup, repeated ===")
    print(f"{'criterion':<38} {'mean':>6} {'sd':>6} {'min':>6} {'max':>6}  treat changes under")
    for crit, rates in sorted(per_crit.items()):
        sd = statistics.stdev(rates) if len(rates) > 1 else 0.0
        print(f"{crit:<38} {statistics.mean(rates):6.0%} {sd:6.1%} {min(rates):6.0%} {max(rates):6.0%}  "
              f"+/-{2 * sd:.0%} as noise")
    print(f"\nbatch_id={batch_id}. With few repeats the sd itself is rough; 5+ repeats is better.")


def resolve_run(conn, ref):
    row = conn.execute("SELECT run_id FROM runs WHERE run_id=?", (ref,)).fetchone()
    if row:
        return row[0]
    row = conn.execute(
        "SELECT run_id FROM runs WHERE label=? AND kind!='aa' ORDER BY started_at DESC LIMIT 1", (ref,)
    ).fetchone()
    if not row:
        raise SystemExit(f"No run or label matches '{ref}'. Try --list.")
    return row[0]


def compare(conn, ref_a, ref_b):
    a_id, b_id = resolve_run(conn, ref_a), resolve_run(conn, ref_b)
    a, b = counts_for_run(conn, a_id), counts_for_run(conn, b_id)
    q = "SELECT COALESCE(suite,'full'), judge_model, cases_hash FROM runs WHERE run_id=?"
    ma, mb = conn.execute(q, (a_id,)).fetchone(), conn.execute(q, (b_id,)).fetchone()
    print(f"\nA = {a_id}\nB = {b_id}")
    for name, i in (("suite (full vs smoke)", 0), ("judge model", 1), ("test cases", 2)):
        if ma[i] != mb[i]:
            print(f"WARNING: {name} differs ({ma[i]} vs {mb[i]}) - these scores are not directly comparable.")
    print(f"\n{'criterion':<38} {'A':>6} {'B':>6} {'delta':>7}  verdict")
    for crit in sorted(set(a) | set(b)):
        if crit not in a or crit not in b:
            print(f"{crit:<38} only in {'A' if crit in a else 'B'}")
            continue
        (ka, na), (kb, nb) = a[crit], b[crit]
        lo_a, hi_a = wilson(ka, na)
        lo_b, hi_b = wilson(kb, nb)
        overlap = not (hi_a < lo_b or hi_b < lo_a)
        print(f"{crit:<38} {ka / na:6.0%} {kb / nb:6.0%} {kb / nb - ka / na:+7.0%}  "
              f"{'within noise?' if overlap else 'likely real'}")


def list_runs(conn):
    rows = conn.execute(
        "SELECT run_id, started_at, kind, COALESCE(suite,'full'), judge_model, model_returned, prompt_hash "
        "FROM runs ORDER BY started_at DESC LIMIT 50"
    ).fetchall()
    print(f"{'run_id':<34} {'started (UTC)':<20} {'kind':<7} {'suite':<6} {'judge':<20} {'model returned':<22} prompt")
    for r in rows:
        print(f"{r[0]:<34} {r[1][:19]:<20} {r[2]:<7} {r[3]:<6} {str(r[4]):<20} {str(r[5]):<22} {r[6]}")


def main():
    global DRY, DB_PATH, JUDGE_PROVIDER, JUDGE_MODEL
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="test_cases.json")
    ap.add_argument("--runs", type=int, default=None,
                    help=f"repeats per case (default {DEFAULT_RUNS}; canary default {CANARY_RUNS})")
    ap.add_argument("--label", default="run", help="name for this prompt/model setup")
    ap.add_argument("--kind", default="golden", choices=["golden", "canary"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--smoke", action="store_true", help='only cases tagged "smoke": true (cheap routine run)')
    ap.add_argument("--cheap-judge", action="store_true", help="use CHEAP_JUDGE_MODEL instead of JUDGE_MODEL")
    ap.add_argument("--if-changed", action="store_true",
                    help="skip if model/judge/temperature/prompt/cases/runs match this label's latest run")
    ap.add_argument("--min-interval-days", type=float, default=None,
                    help=f"skip if this label's last run (same kind/suite) is newer; canary default {CANARY_MIN_INTERVAL_DAYS}")
    ap.add_argument("--force", action="store_true", help="ignore --if-changed and interval skipping")
    ap.add_argument("--aa", type=int, metavar="K", help="noise floor: repeat the identical suite K times")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="fake agent + judge, no API calls (uses results/dry.db)")
    args = ap.parse_args()

    DRY = args.dry_run
    if DRY and "EVAL_DB" not in os.environ:
        DB_PATH = "results/dry.db"  # keep fake data out of the real database
    if args.cheap_judge:
        JUDGE_PROVIDER, JUDGE_MODEL = CHEAP_JUDGE_PROVIDER, CHEAP_JUDGE_MODEL

    conn = open_db()
    if args.list:
        return list_runs(conn)
    if args.compare:
        return compare(conn, *args.compare)

    with open(args.cases) as f:
        cases = json.load(f)
    suite = "full"
    if args.smoke:
        cases = [c for c in cases if c.get("smoke")]
        suite = "smoke"
        if not cases:
            raise SystemExit('No cases tagged "smoke": true in the test file.')
    cases_hash = sha(json.dumps(cases, sort_keys=True))

    kind = args.kind
    runs = args.runs if args.runs is not None else (CANARY_RUNS if kind == "canary" else DEFAULT_RUNS)

    if args.aa:
        noise_floor(conn, args.aa, cases, cases_hash, suite, runs, args.workers, args.label)
        return

    min_interval = args.min_interval_days
    if min_interval is None:
        min_interval = CANARY_MIN_INTERVAL_DAYS if kind == "canary" else 0
    if args.if_changed and kind == "canary":
        print("Note: --if-changed is ignored for canary runs (the point is to catch changes you didn't make).")
    if not args.force:
        reason = skip_reason(conn, args.label, kind, suite, runs, cases_hash,
                             args.if_changed and kind != "canary", min_interval)
        if reason:
            print(f"Skipping: {reason}.\nUse --force to run anyway.")
            return

    print(f"Running {len(cases)} cases ({suite} suite) x {runs} runs = {len(cases) * runs} generations "
          f"(agent={AGENT_MODEL}, judge={JUDGE_MODEL}){' [DRY RUN: fake agent + judge]' if DRY else ''}")
    run_id = run_suite(conn, cases, cases_hash, suite, runs, args.workers, args.label, kind)
    summarize_run(conn, run_id)
    print(f"\nLogged to {DB_PATH}. Read the raw outputs (table: outputs), not just the numbers.")


if __name__ == "__main__":
    main()
