"""Fetch jobs from a batch of Lever company sites.

Not part of the pytest suite - real network calls.
"""

from jobagg.sources.lever import fetch_batch

# Verified UK/EU tech, fintech, and AI employers on Lever - grown from a
# 2-company starter batch via research, not guessed. coinspaid is EU-host
# only; no special handling needed here, fetch_jobs()'s existing global-
# then-EU fallback already covers it. Veeva deliberately excluded: ~70 jobs
# in a live fetch, all Consultant/Manager/Product-Manager titles, zero
# hands-on technical roles - not a filter gap, a company that doesn't fit.
SITE_SLUGS = [
    "zopa",
    "moonpig",
    "ekimetrics",
    "fresha",
    "notonthehighstreet",
    "moonpay",
    "bumbleinc",
    "mistral",
    "pigment",
    "sonarsource",
    "1inch",
    "crypto",
    "yuno",
    "infinit",
    "coinspaid",
    "airalo",
    "valarian",
    "palantir",
    "termgrid",
    "wintermute-trading",
    "xsolla",
    "spotify",
    "octoenergy",
    "kraken123",
    "margo-group",
    "theodo",
    "mytos",
    "apolloresearch",
]


def main() -> None:
    print(f"Fetching {len(SITE_SLUGS)} companies...")
    jobs = fetch_batch(SITE_SLUGS)
    print(f"\n{len(jobs)} total jobs across all sites:")
    for job in jobs:
        print(f"  [{job['company']}] {job['title']}")


if __name__ == "__main__":
    main()
