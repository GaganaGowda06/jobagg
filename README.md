# jobagg

Finds UK junior data science / ML / AI jobs a fresh graduate can actually
apply to - by pulling entire company job boards, filtering them, and having
an LLM judge each posting against one question: *would a fresh graduate
qualify?*

Built as both a personal job-search tool and a measured ML engineering
project.

## What it does

- **Fetches** from 5 sources: two job-board APIs (Adzuna, Reed) and three
  ATS platforms read directly per company (Greenhouse, Lever, Ashby) -
  ~470 postings across ~70 UK/EU tech, fintech and AI employers per run.
- **Filters** titles deterministically (seniority exclusions, relevance
  keywords, false-positive phrases - every rule added from a real failure).
- **Classifies** each job as qualifies / doesnt_qualify / uncertain through
  a three-layer cascade: a free local model (Ollama, Qwen 2.5 7B) auto-
  rejects the clear negatives, Gemini judges the rest, and OpenRouter takes
  over automatically if Gemini's daily quota dies mid-run.
- **Stores** everything in SQLite with full history (first_seen/last_seen
  per posting), exact-content dedup, and success-beats-error verdict
  semantics.
- **Answers** with a deterministic UK-viability filter on top: the current
  database holds 58 qualifying roles, 15 of them workable from the UK.

## Measured, not claimed

Evaluated against 213 hand-labeled jobs (130 truncated job-board postings +
83 full ATS descriptions, labeled independently of the model):

- Accuracy 80.0% (95% CI 72.3-86.9%), Cohen's kappa 0.627 on the primary set
- The cascade's local triage matches Gemini-alone accuracy while cutting
  ~47% of API calls (measured by simulation on both result sets, then live)
- One prompt version (v4, LLM-judged geography) was built, measured, and
  **reverted on evidence**: it cut qualifies recall from 78.6% to 67.9%.
  Geography is now a code-level filter instead. The failed experiment's
  results are archived - negative results are results.

## Stack

Python 3.13, uv, pytest (146 tests), ruff, SQLite, Pydantic structured
outputs, Gemini + OpenRouter + Ollama.

## Honest limitations

- "Qualifies for a fresh graduate" is genuinely subjective; ~80% agreement
  with a human labeler is strong but not a solved problem. The `uncertain`
  class remains effectively unlearnable at this scale (11 examples).
- Adzuna/Reed truncate descriptions at the API (~450 chars); full text is
  only available from the ATS sources.
- Daily automation (GitHub Actions) is the next step; the longitudinal
  dataset starts accruing then.

## Run it

    uv sync
    cp .env.example .env   # add your own API keys
    uv run pytest
    uv run python scripts/classify_greenhouse_batch.py
