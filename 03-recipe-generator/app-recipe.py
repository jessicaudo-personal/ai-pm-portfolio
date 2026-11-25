# Run with "python3 app-recipe.py"

import json
import os
import argparse
import threading
from datetime import datetime
from pathlib import Path
import webbrowser

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from openai import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)


MODEL = "gpt-4o-mini"
RECIPE_TEMPERATURE = 0.7
MAX_RECIPES = 5
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "generated"

load_dotenv()
client = None


def get_client() -> OpenAI:
    global client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing. Add it to the .env file in this folder."
        )
    if client is None:
        client = OpenAI(api_key=api_key, timeout=30.0, max_retries=2)
    return client


def prompt_required(label: str) -> str:
    while True:
        value = input(label).strip()
        if value:
            return value
        print("Please enter a value.")


def prompt_recipe_count() -> int:
    while True:
        value = input(
            f"Number of recipes (1-{MAX_RECIPES}, for example 5): "
        ).strip()
        try:
            count = int(value)
            if 1 <= count <= MAX_RECIPES:
                return count
        except ValueError:
            pass
        print(f"Please enter a whole number from 1 to {MAX_RECIPES}.")


def collect_preferences() -> dict:
    print("\nEnter recipe preferences.")
    return {
        "recipe_count": prompt_recipe_count(),
        "ingredients": prompt_required(
            "List of ingredients (for example chicken, potatoes, carrots): "
        ),
        "allergies": input(
            "Allergies to avoid, optional (for example peanuts, shellfish): "
        ).strip(),
        "dietary_filter": prompt_required(
            "Dietary preferences (for example vegetarian, vegan): "
        ),
        "time_constraint": prompt_required(
            "Time/difficulty constraint (for example under 30 minutes, beginner-friendly): "
        ),
        "cuisine": input(
            "Cuisine preference, optional (press enter to skip): "
        ).strip(),
    }


def create_completion(messages: list[dict], max_tokens: int, temperature: float):
    return get_client().chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )


def token_usage(response) -> int:
    return response.usage.total_tokens if response.usage else 0


def recipe_prompt(preferences: dict) -> str:
    cuisine_text = (
        f" in the style of {preferences['cuisine']} cuisine"
        if preferences["cuisine"]
        else ""
    )
    allergy_instruction = (
        f"Treat these stated allergies as strict exclusions: {preferences['allergies']}. "
        "Do not include these allergens or ingredients derived from them, including in "
        "optional toppings or substitutions. Never claim that a recipe is safe for an allergy. "
        if preferences.get("allergies")
        else ""
    )
    return (
        f"Generate exactly {preferences['recipe_count']} recipes{cuisine_text}. "
        f"The recipes must use the following available ingredients as appropriate: "
        f"{preferences['ingredients']}. "
        f"{allergy_instruction}"
        f"Adhere to this dietary filter: {preferences['dietary_filter']}. "
        f"Meet this constraint: {preferences['time_constraint']}. "
        "For each recipe, include a name, ingredients with exact or approximate measurements, "
        "numbered preparation steps, estimated minutes, and servings. "
        "If a constraint or cuisine preference cannot be fully met, say exactly what is missing "
        "and how close it comes. Add a constraint_check with met (boolean), explanation, and "
        "estimated_minutes. "
        "Return only a JSON object with this shape: "
        '{"recipes":[{"name":string,"ingredients":[{"name":string,"amount":string}],'
        '"steps":[string],"estimated_minutes":number,"servings":number,"constraint_check":'
        '{"met":boolean,"explanation":string}}]}'
    )


def parse_recipe_response(content: str, expected_count: int) -> dict:
    data = json.loads(content)
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("recipes"), list)
        or len(data["recipes"]) != expected_count
        or any(not isinstance(recipe, dict) or not recipe.get("name") for recipe in data["recipes"])
    ):
        raise ValueError(f"The recipe response did not contain exactly {expected_count} named recipe(s).")
    return data


def generate_recipes(preferences: dict):
    messages = [{"role": "user", "content": recipe_prompt(preferences)}]
    max_tokens = max(1_000, preferences["recipe_count"] * 500)
    response = create_completion(messages, max_tokens, RECIPE_TEMPERATURE)
    content = response.choices[0].message.content
    data = parse_recipe_response(content, preferences["recipe_count"])

    messages.append({"role": "assistant", "content": content})
    return data, messages, response


def normalized_recipe_name(recipe: dict) -> str:
    return "".join(character.lower() for character in recipe.get("name", "") if character.isalnum())


def generate_alternative_recipe(
    preferences: dict, current_recipes: list[dict], history: list[dict], recipe_index: int
):
    previous_recipes = history + current_recipes
    unique_history = {}
    for recipe in previous_recipes:
        if isinstance(recipe, dict) and recipe.get("name"):
            unique_history[normalized_recipe_name(recipe)] = recipe

    previous_summary = [
        {
            "name": recipe.get("name"),
            "ingredients": [
                ingredient.get("name")
                for ingredient in recipe.get("ingredients", [])
                if isinstance(ingredient, dict) and ingredient.get("name")
            ],
        }
        for recipe in unique_history.values()
    ]
    target_recipe = current_recipes[recipe_index]
    messages = [
        {"role": "user", "content": recipe_prompt(preferences)},
        {"role": "assistant", "content": json.dumps({"recipes": current_recipes})},
        {
            "role": "user",
            "content": (
                f"Replace the recipe named '{target_recipe['name']}' with one new recipe. "
                "Make it a genuinely different dish, not the same dish with a renamed title. "
                "Do not repeat or rename any previously generated recipe listed here. "
                f"Previously generated recipes to avoid: {json.dumps(previous_summary)}. "
                "Follow the original ingredient, dietary, time, and cuisine preferences. "
                "Return exactly one recipe in the same JSON structure as before."
            ),
        },
    ]
    excluded_names = set(unique_history)
    for attempt in range(2):
        response = create_completion(messages, 1_000, 0.7)
        content = response.choices[0].message.content
        alternative = parse_recipe_response(content, 1)["recipes"][0]
        if normalized_recipe_name(alternative) not in excluded_names:
            return alternative, response
        messages.extend([
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": (
                    "That response repeated a recipe already generated. Return one genuinely "
                    "different recipe with a new dish concept and a name not in the exclusion list."
                ),
            },
        ])
    raise ValueError("The model repeated a previous recipe. Please try regenerating again.")


def generate_shopping_list(messages: list[dict], ingredients: str):
    prompt = (
        "Create a shopping list for the recipes in the conversation. "
        f"Do not include these ingredients already at home: {ingredients}. "
        "Combine equivalent ingredients and include a practical amount to buy. "
        'Return only a JSON object with this shape: '
        '{"shopping_list":[{"name":string,"amount":string}]}'
    )
    messages.append({"role": "user", "content": prompt})
    response = create_completion(messages, 600, 0.5)
    content = response.choices[0].message.content
    data = json.loads(content)
    if not isinstance(data, dict) or not isinstance(data.get("shopping_list"), list):
        raise ValueError("The shopping-list response was not valid.")

    messages.append({"role": "assistant", "content": content})
    return data, response


def generate_nutrition(messages: list[dict], recipe_count: int):
    prompt = (
        "For each recipe in the conversation, add estimated nutrition per serving. "
        "Include calories, protein_g, carbs_g, and fat_g. "
        "Keep estimates general and informational, not personalized medical or dietary advice. "
        'Return only a JSON object with this shape: '
        '{"nutrition":[{"recipe_name":string,"calories":number,"protein_g":number,'
        '"carbs_g":number,"fat_g":number,"note":string}]}'
    )
    messages.append({"role": "user", "content": prompt})
    max_tokens = max(600, recipe_count * 180)
    response = create_completion(messages, max_tokens, 0.5)
    content = response.choices[0].message.content
    data = json.loads(content)
    if not isinstance(data, dict) or not isinstance(data.get("nutrition"), list):
        raise ValueError("The nutrition response was not valid.")

    messages.append({"role": "assistant", "content": content})
    return data, response


def verify_recipes(messages: list[dict], recipe_count: int):
    prompt = (
        "Verify the generated recipes against the original ingredient list, dietary filter, "
        "allergies, time constraint, and cuisine preference. For every stated allergy, inspect "
        "the listed ingredients, steps, and suggested substitutions for explicit allergen sources. "
        "Do not infer that a recipe is allergy-safe, and state that labels and cross-contact "
        "cannot be assessed from recipe text. Do not assume a constraint is met. "
        "Only flag a mismatch when it is supported by the recipe text. "
        'Return only a JSON object with this shape: '
        '{"verifications":[{"recipe_name":string,"passes":boolean,"issues":[string]}]}'
    )
    messages.append({"role": "user", "content": prompt})
    response = create_completion(messages, max(600, recipe_count * 180), 0.2)
    content = response.choices[0].message.content
    data = json.loads(content)
    if not isinstance(data, dict) or not isinstance(data.get("verifications"), list):
        raise ValueError("The verification response was not valid.")
    return data, response


def format_markdown(preferences: dict, recipes: dict, shopping: dict,
                    nutrition: dict, verifications: dict) -> str:
    lines = [
        "# Generated recipes",
        "",
        f"- Ingredients: {preferences['ingredients']}",
        f"- Allergies to avoid: {preferences.get('allergies') or 'None specified'}",
        f"- Dietary filter: {preferences['dietary_filter']}",
        f"- Time/difficulty: {preferences['time_constraint']}",
        f"- Cuisine: {preferences['cuisine'] or 'Not specified'}",
        "",
    ]

    for index, recipe in enumerate(recipes["recipes"], start=1):
        lines.extend([
            f"## {index}. {recipe.get('name', 'Unnamed recipe')}",
            "",
            f"- Servings: {recipe.get('servings', 'Not specified')}",
            f"- Estimated time: {recipe.get('estimated_minutes', 'Not specified')} minutes",
            "",
            "### Ingredients",
            "",
        ])
        for ingredient in recipe.get("ingredients", []):
            lines.append(
                f"- {ingredient.get('amount', '')} {ingredient.get('name', '')}".strip()
            )

        lines.extend(["", "### Steps", ""])
        for step_number, step in enumerate(recipe.get("steps", []), start=1):
            lines.append(f"{step_number}. {step}")

        check = recipe.get("constraint_check", {})
        lines.extend([
            "",
            "### AI constraint check (not an allergy safety check)",
            "",
            f"- Met: {'Yes' if check.get('met') else 'No'}",
            f"- {check.get('explanation', 'No explanation provided.')}",
        ])

        verification = next(
            (
                item for item in verifications["verifications"]
                if item.get("recipe_name") == recipe.get("name")
            ),
            None,
        )
        if verification:
            lines.extend([
                "",
                "### AI review",
                "",
                f"- Passes: {'Yes' if verification.get('passes') else 'No'}",
            ])
            for issue in verification.get("issues", []):
                lines.append(f"- Issue: {issue}")

        nutrition_entry = next(
            (
                item for item in nutrition["nutrition"]
                if item.get("recipe_name") == recipe.get("name")
            ),
            None,
        )
        if nutrition_entry:
            lines.extend([
                "",
                "### Estimated nutrition (per serving)",
                "",
                (
                    f"- Calories: {nutrition_entry.get('calories', 'N/A')} | "
                    f"Protein: {nutrition_entry.get('protein_g', 'N/A')} g | "
                    f"Carbs: {nutrition_entry.get('carbs_g', 'N/A')} g | "
                    f"Fat: {nutrition_entry.get('fat_g', 'N/A')} g"
                ),
            ])
            if nutrition_entry.get("note"):
                lines.append(f"- Note: {nutrition_entry['note']}")
        lines.append("")

    lines.extend(["## Shopping list", ""])
    for item in shopping["shopping_list"]:
        lines.append(f"- {item.get('amount', '')} {item.get('name', '')}".strip())
    lines.extend([
        "",
        "## Allergy safety reminder",
        "",
        "These AI-generated recipes are not guaranteed to be allergen-safe. Verify every "
        "ingredient label, including packaged products, and check for cross-contact during "
        "preparation. Consult a qualified professional for allergy-related guidance.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def save_run(preferences: dict, data: dict) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    json_path = OUTPUT_DIR / f"recipe-run-{timestamp}.json"
    markdown_path = OUTPUT_DIR / f"recipe-run-{timestamp}.md"

    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(data["markdown"], encoding="utf-8")
    return markdown_path


def print_usage(label: str, response) -> None:
    print(f"[{label} tokens: {token_usage(response)}]")


def generate_run(preferences: dict) -> dict:
    recipes, messages, recipe_response = generate_recipes(preferences)
    total_tokens = token_usage(recipe_response)
    print_usage("Recipes", recipe_response)

    shopping, shopping_response = generate_shopping_list(
        messages, preferences["ingredients"]
    )
    total_tokens += token_usage(shopping_response)
    print_usage("Shopping list", shopping_response)

    nutrition, nutrition_response = generate_nutrition(
        messages, preferences["recipe_count"]
    )
    total_tokens += token_usage(nutrition_response)
    print_usage("Nutrition", nutrition_response)

    verifications, verification_response = verify_recipes(
        messages, preferences["recipe_count"]
    )
    total_tokens += token_usage(verification_response)
    print_usage("Verification", verification_response)

    markdown = format_markdown(preferences, recipes, shopping, nutrition, verifications)
    data = {
        "preferences": preferences,
        "recipes": recipes,
        "shopping": shopping,
        "nutrition": nutrition,
        "verifications": verifications,
        "markdown": markdown,
        "total_tokens": total_tokens,
        "generated_recipe_history": recipes["recipes"].copy(),
    }
    saved_markdown = save_run(preferences, data)
    data["saved_file"] = saved_markdown.name
    return data


def regenerate_run(current_result: dict, recipe_index: int) -> dict:
    preferences = current_result["preferences"]
    current_recipes = current_result["recipes"]["recipes"]
    history = current_result.get("generated_recipe_history", current_recipes)

    replacement, replacement_response = generate_alternative_recipe(
        preferences, current_recipes, history, recipe_index
    )
    updated_recipes = current_recipes.copy()
    updated_recipes[recipe_index] = replacement
    recipes = {"recipes": updated_recipes}

    messages = [
        {"role": "user", "content": recipe_prompt(preferences)},
        {"role": "assistant", "content": json.dumps(recipes)},
    ]
    shopping, shopping_response = generate_shopping_list(
        messages, preferences["ingredients"]
    )
    nutrition, nutrition_response = generate_nutrition(
        messages, preferences["recipe_count"]
    )
    verifications, verification_response = verify_recipes(
        messages, preferences["recipe_count"]
    )
    total_tokens = (
        current_result.get("total_tokens", 0)
        + token_usage(replacement_response)
        + token_usage(shopping_response)
        + token_usage(nutrition_response)
        + token_usage(verification_response)
    )
    print_usage("Replacement recipe", replacement_response)
    print_usage("Updated shopping list", shopping_response)
    print_usage("Updated nutrition", nutrition_response)
    print_usage("Updated verification", verification_response)

    markdown = format_markdown(preferences, recipes, shopping, nutrition, verifications)
    generated_history = history.copy()
    generated_history.append(replacement)
    data = {
        "preferences": preferences,
        "recipes": recipes,
        "shopping": shopping,
        "nutrition": nutrition,
        "verifications": verifications,
        "markdown": markdown,
        "total_tokens": total_tokens,
        "generated_recipe_history": generated_history,
    }
    saved_markdown = save_run(preferences, data)
    data["saved_file"] = saved_markdown.name
    return data


def create_web_app() -> Flask:
    web_app = Flask(__name__, template_folder="templates", static_folder="static")
    web_app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    @web_app.get("/")
    def index():
        response = web_app.make_response(
            render_template("index.html", max_recipes=MAX_RECIPES)
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @web_app.post("/api/generate")
    def api_generate():
        if not request.is_json:
            return jsonify(error="Please submit the form data as JSON."), 400

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="The submitted form data was not valid."), 400

        count = payload.get("recipe_count")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_RECIPES:
            return jsonify(
                error=f"Choose between 1 and {MAX_RECIPES} recipes."
            ), 400

        string_fields = ("ingredients", "dietary_filter", "time_constraint")
        preferences = {"recipe_count": count}
        for field in string_fields:
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                return jsonify(error=f"Please enter {field.replace('_', ' ')}."), 400
            if len(value) > 500:
                return jsonify(error=f"{field.replace('_', ' ').capitalize()} must be 500 characters or fewer."), 400
            preferences[field] = value.strip()

        cuisine = payload.get("cuisine", "")
        if not isinstance(cuisine, str) or len(cuisine) > 100:
            return jsonify(error="Cuisine must be 100 characters or fewer."), 400
        preferences["cuisine"] = cuisine.strip()
        allergies = payload.get("allergies", "")
        if not isinstance(allergies, str) or len(allergies) > 500:
            return jsonify(error="Allergies must be 500 characters or fewer."), 400
        preferences["allergies"] = allergies.strip()

        try:
            return jsonify(result=generate_run(preferences))
        except RateLimitError:
            return jsonify(
                error="OpenAI rate limit reached or credits exhausted. Check your billing settings."
            ), 429
        except AuthenticationError:
            return jsonify(
                error="The OpenAI API key is invalid. Check the key in your .env file."
            ), 401
        except APIConnectionError:
            return jsonify(
                error="Could not connect to OpenAI. Check your internet connection and try again."
            ), 503
        except APIStatusError as error:
            web_app.logger.exception("OpenAI API request failed")
            return jsonify(
                error=f"OpenAI returned an error (status {error.status_code}). Please try again."
            ), 502
        except (json.JSONDecodeError, ValueError) as error:
            web_app.logger.exception("Could not process the generated response")
            return jsonify(error=f"Could not process the response: {error}"), 502
        except RuntimeError as error:
            return jsonify(error=str(error)), 503
        except Exception:
            web_app.logger.exception("Unexpected recipe generation failure")
            return jsonify(
                error="Something unexpected went wrong. Check the terminal for details."
            ), 500

    @web_app.post("/api/regenerate")
    def api_regenerate():
        if not request.is_json:
            return jsonify(error="Please submit the regeneration request as JSON."), 400

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="The regeneration request was not valid."), 400

        current_result = payload.get("current_result")
        recipe_index = payload.get("recipe_index")
        if not isinstance(current_result, dict):
            return jsonify(error="Generate recipes before asking for a replacement."), 400
        if (
            isinstance(recipe_index, bool)
            or not isinstance(recipe_index, int)
            or not isinstance(current_result.get("recipes"), dict)
            or not isinstance(current_result["recipes"].get("recipes"), list)
            or not 0 <= recipe_index < len(current_result["recipes"]["recipes"])
        ):
            return jsonify(error="The selected recipe could not be found."), 400

        preferences = current_result.get("preferences")
        recipe_list = current_result["recipes"]["recipes"]
        history = current_result.get("generated_recipe_history", recipe_list)
        if isinstance(preferences, dict):
            preferences.setdefault("allergies", "")
        if (
            not isinstance(preferences, dict)
            or isinstance(preferences.get("recipe_count"), bool)
            or not isinstance(preferences.get("recipe_count"), int)
            or preferences.get("recipe_count") != len(recipe_list)
            or not 1 <= len(recipe_list) <= MAX_RECIPES
            or not all(
                isinstance(recipe, dict) and isinstance(recipe.get("name"), str)
                for recipe in recipe_list
            )
            or not isinstance(history, list)
            or not all(
                isinstance(recipe, dict) and isinstance(recipe.get("name"), str)
                for recipe in history
            )
            or any(
                not isinstance(preferences.get(field), str)
                for field in (
                    "ingredients", "dietary_filter", "time_constraint", "cuisine", "allergies"
                )
            )
        ):
            return jsonify(error="The recipe results are no longer valid. Please start a new run."), 400

        try:
            return jsonify(result=regenerate_run(current_result, recipe_index))
        except RateLimitError:
            return jsonify(
                error="OpenAI rate limit reached or credits exhausted. Check your billing settings."
            ), 429
        except AuthenticationError:
            return jsonify(
                error="The OpenAI API key is invalid. Check the key in your .env file."
            ), 401
        except APIConnectionError:
            return jsonify(
                error="Could not connect to OpenAI. Check your internet connection and try again."
            ), 503
        except APIStatusError as error:
            web_app.logger.exception("OpenAI API request failed during regeneration")
            return jsonify(
                error=f"OpenAI returned an error (status {error.status_code}). Please try again."
            ), 502
        except (json.JSONDecodeError, ValueError) as error:
            web_app.logger.exception("Could not process regenerated recipe")
            return jsonify(error=f"Could not process the response: {error}"), 502
        except Exception:
            web_app.logger.exception("Unexpected recipe regeneration failure")
            return jsonify(
                error="Something unexpected went wrong. Check the terminal for details."
            ), 500

    return web_app


def start_web_app() -> None:
    url = "http://127.0.0.1:8000"
    threading.Timer(1, lambda: webbrowser.open_new_tab(url)).start()
    print(f"Opening Recipe Generator at {url}")
    print("Leave this window running while you use the app. Press Ctrl+C to stop.")
    create_web_app().run(host="127.0.0.1", port=8000, debug=False)


def run() -> None:
    print("Recipe Generator")

    while True:
        preferences = collect_preferences()

        try:
            data = generate_run(preferences)
            print("\n--- RECIPES ---\n")
            print(data["markdown"])
            print(f"\nSaved results to: {OUTPUT_DIR / data['saved_file']}")
            print(f"[TOTAL TOKENS THIS RUN: {data['total_tokens']}]")

        except RateLimitError:
            print("\nWarning: Rate limit reached or credits exhausted. Check OpenAI billing.")
        except AuthenticationError:
            print("\nWarning: API key is invalid or missing. Check your .env file.")
        except APIConnectionError:
            print("\nWarning: Could not connect to OpenAI. Check your internet connection.")
        except APIStatusError as error:
            print(
                f"\nWarning: OpenAI returned an error "
                f"(status {error.status_code}): {error.message}"
            )
        except json.JSONDecodeError as error:
            print(f"\nWarning: OpenAI returned invalid JSON: {error}")
        except Exception as error:
            print(f"\nWarning: Something unexpected went wrong: {error}")

        again = input("\nGenerate another run? (y/n, or quit): ").strip().lower()
        if again in {"n", "no", "q", "quit"}:
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the local recipe generator.")
    parser.add_argument(
        "--web",
        action="store_true",
        help="Start the browser interface (the default)",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Use the terminal-based interface instead of the browser",
    )
    arguments = parser.parse_args()
    if arguments.cli:
        run()
    else:
        start_web_app()
