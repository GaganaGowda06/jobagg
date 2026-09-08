"""One-call smoke test for the OpenRouter fallback path. Costs 1 OpenRouter
request, 0 Gemini requests. Not part of the pytest suite - real network call."""

from jobagg.classifier import _classify_job_openrouter
from jobagg.config import get_settings


def main() -> None:
    key = get_settings().openrouter_api_key
    if key is None:
        print("OPENROUTER_API_KEY missing from .env - add it first.")
        return
    job = {
        "title": "Graduate Data Analyst",
        "description": "Join our 2026 graduate scheme. No experience needed, full training given.",
    }
    result = _classify_job_openrouter(job, key.get_secret_value())
    print(f"classification: {result.classification}")
    print(f"reasoning: {result.reasoning}")


if __name__ == "__main__":
    main()
