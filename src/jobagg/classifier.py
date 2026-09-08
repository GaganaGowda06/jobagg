"""Semantic job-listing classifier using the Gemini API, with an optional
OpenRouter fallback when Gemini's daily free-tier quota is exhausted.

Classifies each listing as qualifies / doesnt_qualify / uncertain for someone
with zero professional experience in data science, ML, or AI engineering.
"""

from typing import Literal

import requests
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from jobagg.config import get_settings

MODEL = "gemini-3.5-flash-lite"
OPENROUTER_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"  # spare: minimax/minimax-m3:free
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_URL = "http://localhost:11434/v1/chat/completions"


class DailyQuotaExhaustedError(Exception):
    """The free tier's *daily* request quota is spent (and no fallback could
    take over). Unlike per-minute 429s (which the SDK retries through
    successfully), this cannot recover within a run - callers should stop
    cleanly and resume after the reset."""


def _is_daily_quota_error(e: Exception) -> bool:
    return isinstance(e, errors.ClientError) and e.code == 429 and "PerDay" in str(e)


SYSTEM_INSTRUCTION = """\
You judge whether a fresh university graduate (bachelor's or master's, no \
full-time industry experience) would qualify for a UK data science / ML / AI \
job posting.

Answer with one of:
- "qualifies": explicitly junior/graduate/trainee/intern/entry-level, OR no \
experience requirement stated and no senior signals.
- "doesnt_qualify": requires 2+ years experience, or is senior/lead/manager \
level, or is outside data science / ML / AI engineering entirely - but judge \
field relevance from what the role actually does, not the job title alone.
- "uncertain": the posting contains CONFLICTING seniority signals (e.g. \
junior title but 5+ years required).

IMPORTANT: many postings are short or cut off mid-sentence. That is normal \
and is NOT a reason for "uncertain". Judge from whatever signals are \
present; if a short description shows no experience requirement and no \
senior signals, that is "qualifies".

Do not infer seniority from salary, day rate, or contract-vs-permanent \
structure. A listing with "Trainee" or "Graduate" in the title that includes \
structured training as part of paid employment is a real job, not a training \
course.

Reason step-by-step FIRST (seniority signals, years required, role type), \
then give the classification.

Examples:

Job: "Graduate Data Analyst - join our 2026 graduate scheme, no prior \
experience needed, full training provided."
reasoning: Explicit graduate scheme, no experience required. Clear junior role.
classification: qualifies

Job: "Data Scientist - work on churn models with our analytics team. \
Python and SQL. You will build dashboards and..."
reasoning: Description is cut off, but the visible signals show no \
experience requirement and no senior indicators. Short text is not a \
reason for uncertain.
classification: qualifies

Job: "Senior Machine Learning Engineer - 5+ years production ML experience, \
you will mentor junior engineers."
reasoning: 'Senior' title, 5+ years required, mentoring duties. Clearly not \
entry-level.
classification: doesnt_qualify

Job: "Junior Data Analyst - must have 4+ years of commercial analytics \
experience."
reasoning: Title says junior but 4+ years is a mid-level requirement - the \
signals genuinely conflict.
classification: uncertain

Job: "Marketing Analytics Manager - own our attribution strategy, manage a \
team of 3 analysts."
reasoning: Manager title with direct reports. Management role, not entry-level.
classification: doesnt_qualify
"""


# NOTE: field order matters - `reasoning` comes BEFORE `classification`
# so the model reasons first, then commits to a verdict.
class Classification(BaseModel):
    reasoning: str
    classification: Literal["qualifies", "doesnt_qualify", "uncertain"]

    @property
    def reason(self) -> str:  # backwards-compat for existing scripts
        return self.reasoning


def _build_contents(job: dict) -> str:
    """Build the per-job text sent to the model from its title and description."""
    title = job.get("title") or ""
    description = job.get("description") or ""
    return f"Title: {title}\n\nDescription: {description}"


def get_gemini_client() -> genai.Client:
    """Construct a Gemini client with retry enabled for transient failures.

    Retries are opt-in in this SDK (no retry_options set = fail on first
    error), so this explicitly turns on the SDK's own documented defaults:
    5 attempts, exponential backoff, retrying on 408/429/500/502/503/504.
    """
    settings = get_settings()
    return genai.Client(
        api_key=settings.gemini_api_key.get_secret_value(),
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(),
        ),
    )


def _extract_json_object(text: str) -> str:
    """Free OpenRouter models don't all support forced-JSON mode, so the
    JSON sometimes arrives wrapped in markdown fences or prose. Slice out
    the outermost {...} object."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON object found in model output: {text[:200]!r}")
    return text[start : end + 1]


def _classify_job_openrouter(job: dict, api_key: str) -> Classification:
    """Classify via OpenRouter's OpenAI-compatible API. Used only as a
    fallback when Gemini's daily quota is exhausted; results are marked in
    the reasoning so mixed-model batches stay auditable."""
    response = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": OPENROUTER_MODEL,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {
                    "role": "user",
                    "content": (
                        f"{_build_contents(job)}\n\n"
                        'Respond with ONLY a JSON object exactly like {"reasoning": "...", '
                        '"classification": "qualifies" | "doesnt_qualify" | "uncertain"} '
                        "and nothing else."
                    ),
                },
            ],
        },
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    result = Classification.model_validate_json(_extract_json_object(content))
    return Classification(
        reasoning=f"[openrouter-fallback] {result.reasoning}",
        classification=result.classification,
    )


def classify_job_local(job: dict) -> Classification:
    """Classify via a local Ollama model (OpenAI-compatible endpoint). Zero
    API quota, zero cost - the candidate triage layer for a two-stage
    cascade. Requires `ollama serve` running with OLLAMA_MODEL pulled."""
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {
                    "role": "user",
                    "content": (
                        f"{_build_contents(job)}\n\n"
                        'Respond with ONLY a JSON object exactly like {"reasoning": "...", '
                        '"classification": "qualifies" | "doesnt_qualify" | "uncertain"} '
                        "and nothing else."
                    ),
                },
            ],
        },
        timeout=120,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return Classification.model_validate_json(_extract_json_object(content))


def classify_job_cascade(job: dict, client: genai.Client) -> Classification:
    """Two-stage cascade: free local triage first, API model only when needed.

    The local model's doesnt_qualify verdicts are accepted directly - measured
    on the eval set, its rejections are MORE precise than Gemini's (82.5% vs
    76.7%), and the simulated cascade matched Gemini-alone accuracy (80.0%)
    while cutting 47% of API calls. Anything else (qualifies / uncertain /
    local failure) escalates to classify_job, which carries the OpenRouter
    fallback. Local-triage verdicts are marked in the reasoning.
    """
    try:
        local = classify_job_local(job)
    except Exception:
        # Ollama down or misbehaving - degrade gracefully to API-only.
        return classify_job(job, client)
    if local.classification == "doesnt_qualify":
        return Classification(
            reasoning=f"[local-triage] {local.reasoning}",
            classification="doesnt_qualify",
        )
    return classify_job(job, client)


def classify_job(job: dict, client: genai.Client, allow_fallback: bool = True) -> Classification:
    """Classify a single job listing as qualifies / doesnt_qualify / uncertain.

    Gemini is the primary (and the judge of record for eval runs - pass
    allow_fallback=False there so scores stay single-model). If Gemini's
    daily quota is exhausted and an OPENROUTER_API_KEY is configured, falls back
    to OpenRouter so batch runs can keep going; fallback results carry a
    "[openrouter-fallback]" prefix in their reasoning. If both are unavailable,
    raises DailyQuotaExhaustedError so callers stop cleanly.
    """
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=_build_contents(job),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=Classification,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
    except errors.ClientError as e:
        if not _is_daily_quota_error(e):
            raise
        or_key = get_settings().openrouter_api_key
        if allow_fallback and or_key is not None:
            try:
                return _classify_job_openrouter(job, or_key.get_secret_value())
            except Exception as fallback_error:
                raise DailyQuotaExhaustedError(
                    f"Gemini daily quota exhausted AND OpenRouter fallback failed "
                    f"({type(fallback_error).__name__}: {fallback_error})"
                ) from fallback_error
        raise DailyQuotaExhaustedError(str(e)) from e
    return response.parsed
