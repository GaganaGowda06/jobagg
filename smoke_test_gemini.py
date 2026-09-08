"""One-off smoke test: confirms GEMINI_API_KEY actually works against the live API.

Not part of the pytest suite on purpose - it makes a real network call and costs
a token, and pytest should never depend on network/API state. Run once, then
delete it.
"""

from google import genai

from jobagg.config import get_settings


def main() -> None:
    settings = get_settings()
    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents="Reply with exactly one word: pong",
    )
    print("Gemini replied:", response.text)


if __name__ == "__main__":
    main()
