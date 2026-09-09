"""Probe candidate Workable account slugs and report which exist, with job
counts and how many pass the title filter. Grows WORKABLE_SLUGS on
evidence, not guesses. No LLM quota used. Not part of the pytest suite."""

import requests

from jobagg.sources.workable import LIST_URL, fetch_jobs

CANDIDATES = [
    "plum", "plum-fintech", "marshmallow", "curve", "zilch", "moneybox",
    "wagestream", "yoti", "paddle", "beamery", "peak-ai", "signal-ai",
    "tessian", "gophr", "ziglu", "fscom", "ipid",
]


def main() -> None:
    for slug in CANDIDATES:
        try:
            r = requests.get(LIST_URL.format(slug=slug), timeout=15)
            if r.status_code != 200:
                print(f"{slug:16} -> {r.status_code}")
                continue
            data = r.json()
            total = len(data.get("jobs", []))
            passed = len(fetch_jobs(slug))
            print(f"{slug:16} -> LIVE  {data.get('name', '?'):24} {total:3} jobs, {passed} pass filter")
        except requests.exceptions.RequestException as e:
            print(f"{slug:16} -> {type(e).__name__}")


if __name__ == "__main__":
    main()
