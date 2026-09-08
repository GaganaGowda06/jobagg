# jobagg

I built this to fix my own problem: finding entry level data science and ML
jobs in the UK as a fresh graduate is mostly scrolling through postings I
don't qualify for. So this tool does the scrolling and the judging for me.

It pulls jobs from five places. Adzuna and Reed cover the big job boards,
and it also reads company hiring systems directly (Greenhouse, Lever and
Ashby), which is where a lot of fintech and AI startups post roles that
never reach the job boards. Around 70 companies and 470 postings per run.

Each posting goes through a cheap keyword filter first, then an LLM decides
one thing: would a fresh graduate qualify for this job. A free local model
running through Ollama rejects the obvious no's, Gemini judges the rest,
and if Gemini's daily quota runs out mid run it switches to OpenRouter on
its own. Everything lands in a SQLite database with history, dedup and a
UK location filter on top. Right now it holds 58 qualifying roles, 15 of
them actually workable from the UK.

## How I know it works

I hand labeled 213 jobs myself and score the classifier against them.
Current numbers: 80 percent accuracy (95 percent CI 72.3 to 86.9) and
Cohen's kappa 0.627 on the main set. The local triage layer keeps the same
accuracy as Gemini alone while cutting about 47 percent of API calls.

One experiment failed and I kept the evidence. I tried letting the LLM
judge UK eligibility from the location text (prompt v4). It dropped
qualifies recall from 78.6 to 67.9 percent because it couldn't reliably
recognise smaller UK towns, so I reverted it and wrote the location check
as plain code instead. The failed run's results are archived in the repo
history.

## Stack

Python 3.13, uv, pytest (146 tests), ruff, SQLite, Pydantic structured
outputs, Gemini, OpenRouter, Ollama.

## Limits I know about

Whether a fresh grad "qualifies" is genuinely subjective, so 80 percent
agreement with my own labels is good but not a solved problem. The
uncertain class barely has training signal (11 examples). Adzuna and Reed
cut descriptions at about 450 characters on their side, so full text only
comes from the three ATS sources. A GitHub Actions workflow runs the whole
pipeline daily and commits the database, so the dataset grows on its own.

## Run it

    uv sync
    cp .env.example .env
    uv run pytest
    uv run python scripts/classify_greenhouse_batch.py
