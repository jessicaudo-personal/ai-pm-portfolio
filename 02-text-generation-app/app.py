import os
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError, AuthenticationError, APIConnectionError, APIStatusError

# run with "python3 app.py" in terminal 
# "quit" to exit

load_dotenv()  # reads your .env file and loads OPENAI_API_KEY into the environment

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) # makes the key available

# Human-readable creativity levels mapped to actual temperature values
CREATIVITY_LEVELS = {
    "focused": 0.2,
    "balanced": 0.7,
    "creative": 1.2
}

# prompt = "Write a short, upbeat product description for a reusable water bottle." #hard coding prompt
# prompt = input("Enter a prompt: ") #enter prompt in console instead

# Wrapping in a loop so I can keep prompting without restarting the script:
# Adding error handling by wrapping the API call in a try-except block
# this will catch things like rate limits, network issues, or invalid API keys and print an error message instead of crashing the script

while True:
    prompt = input("\nEnter a prompt (or 'quit' to exit): ")
    if prompt.lower() == "quit":
        break

    # Ask for creativity level in plain language
    level_input = input("Creativity level - focused / balanced / creative (default: balanced): ").strip().lower()
    temperature = CREATIVITY_LEVELS.get(level_input, 0.7)  # falls back to balanced if blank or invalid

    # Ask for max length in words instead of tokens
    words_input = input("Max response length in words (default: 100): ").strip()
    try:
        max_words = int(words_input) if words_input else 100
    except ValueError:
        max_words = 100

    # Convert words to tokens - roughly 1 word = 1.3 tokens for English text
    max_tokens = int(max_words * 1.3)

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            # model="gpt-9000-fake", # to trigger API status error for testing
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
            max_tokens=max_tokens
        )
        print(response.choices[0].message.content)

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
