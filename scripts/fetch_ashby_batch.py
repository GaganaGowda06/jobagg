"""Fetch jobs from a batch of Ashby company boards.

Not part of the pytest suite - real network calls.
"""

from jobagg.sources.ashby import fetch_batch

# Starter batch - the four companies already confirmed and verified against
# real data (ElevenLabs, Cohere, Thought Machine, Checkout.com). Meant to
# grow the same way Greenhouse's and Lever's did: small and verified first,
# expanded later via research.
#
# Note: "checkout.com"'s auto-derived display name comes out as
# "Checkout.Com" (fetch_batch has no per-slug company override yet) -
# cosmetic only, doesn't affect filtering, classification, or dedup.
BOARD_NAMES = ["elevenlabs", "cohere", "thought-machine", "checkout.com"]


def main() -> None:
    print(f"Fetching {len(BOARD_NAMES)} companies...")
    jobs = fetch_batch(BOARD_NAMES)
    print(f"\n{len(jobs)} total jobs across all boards:")
    for job in jobs:
        print(f"  [{job['company']}] {job['title']}")


if __name__ == "__main__":
    main()
