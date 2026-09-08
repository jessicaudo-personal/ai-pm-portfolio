# run with "python3 app-recipe.py" in terminal 
# "quit" to exit

import os
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError, AuthenticationError, APIConnectionError, APIStatusError

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

no_recipes = input("Number of recipes (for example, 5): ")
ingredients = input("List of ingredients (for example chicken, potatoes, carrots etc.): ")
dietary_filter = input("Filter (for example, vegetarian, vegan or gluten-free): ")
time_constraint = input("Time/difficulty constraint (for example, under 30 minutes, beginner-friendly): ")
cuisine = input("Cuisine preference, optional (for example, Italian, Thai — press enter to skip): ")

cuisine_clause = f" in the style of {cuisine} cuisine" if cuisine.strip() else ""

# Scale token budget based on number of recipes requested
# Estimate ~150 tokens per recipe (ingredients + steps), plus a buffer
try:
    recipe_count = int(no_recipes)
except ValueError:
    recipe_count = 5  # fallback if input isn't a clean number

recipe_max_tokens = max(300, recipe_count * 180)  # 180 tokens/recipe estimate, 300 floor
nutrition_max_tokens = max(200, recipe_count * 80)  # nutrition blocks are shorter per recipe

prompt = (
    f"Show me {no_recipes} recipes{cuisine_clause} for a dish with the following ingredients: {ingredients}. "
    f"Per recipe, list the ingredients used with measurements, then how to prepare it. "
    f"Please adhere to this filter: {dietary_filter}. "
    f"Each recipe should meet this constraint: {time_constraint}. "
    f"If a recipe cannot fully meet the time constraint or cuisine preference, say so explicitly "
    f"and note how close it comes instead of ignoring the mismatch."
)

try:
    messages = [{"role": "user", "content": prompt}]

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.7,
        max_tokens=recipe_max_tokens
    )

    recipes = response.choices[0].message.content
    print("\n--- RECIPES ---\n")
    print(recipes)
    print(f"\n[Tokens used — prompt: {response.usage.prompt_tokens}, "
          f"completion: {response.usage.completion_tokens}, "
          f"total: {response.usage.total_tokens}]")

    messages.append({"role": "assistant", "content": recipes})

    messages.append({
        "role": "user",
        "content": f"Produce a shopping list for those recipes. I already have {ingredients} at home, "
                   f"so don't include those — only ingredients I need to buy."
    })

    shopping_response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.5,
        max_tokens=400
    )

    shopping_list = shopping_response.choices[0].message.content
    print("\n--- SHOPPING LIST ---\n")
    print(shopping_list)
    print(f"\n[Tokens used — total: {shopping_response.usage.total_tokens}]")

    messages.append({"role": "assistant", "content": shopping_list})

    messages.append({
        "role": "user",
        "content": "For each recipe, add an estimated nutritional breakdown per serving "
                   "(calories, protein, carbs, fat). Keep it general/informational, "
                   "not personalized medical or dietary advice."
    })

    nutrition_response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.5,
        max_tokens=nutrition_max_tokens
    )

    print("\n--- NUTRITION INFO (general estimates) ---\n")
    print(nutrition_response.choices[0].message.content)
    print(f"\n[Tokens used — total: {nutrition_response.usage.total_tokens}]")

    grand_total = (response.usage.total_tokens
                   + shopping_response.usage.total_tokens
                   + nutrition_response.usage.total_tokens)
    print(f"\n[TOTAL TOKENS THIS RUN: {grand_total}]")

except RateLimitError:
    print("\n⚠️ You've hit a rate limit or run out of credits. Check your OpenAI billing dashboard.")

except AuthenticationError:
    print("\n⚠️ Your API key is invalid or missing. Check your .env file.")

except APIConnectionError:
    print("\n⚠️ Couldn't connect to OpenAI's servers. Check your internet connection and try again.")

except APIStatusError as e:
    print(f"\n⚠️ OpenAI returned an error (status {e.status_code}): {e.message}")

except Exception as e:
    print(f"\n⚠️ Something unexpected went wrong: {e}")