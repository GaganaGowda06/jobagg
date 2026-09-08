"""Measure the real duplicate rate across the three ATS sources, under both
dedup keys, BEFORE wiring dedup into the classify pipeline. Evidence first:
the strict content key is safe but may catch little; the loose title key
catches per-location reposts but risks over-merging - this script shows its
groups so they can be eyeballed for over-merge before we trust it.

No LLM quota used - fetch calls only. Not part of the pytest suite.
"""

from jobagg.dedup import content_key, group_by_key, title_key
from jobagg.sources.ashby import fetch_batch as fetch_ashby
from jobagg.sources.greenhouse import fetch_batch as fetch_gh
from jobagg.sources.lever import fetch_batch as fetch_lever

GREENHOUSE_TOKENS = [
    "monzo",
    "gocardless",
    "truelayer",
    "tide",
    "capitalontap",
    "cleoai",
    "griffin",
    "modulrfinance",
    "mangopay",
    "blockchain",
    "fireblocks",
    "robinhood",
    "wayve",
    "isomorphiclabs",
    "graphcore",
    "polyai",
    "synthesia",
    "featurespace",
    "darktracelimited",
    "snyk",
    "scaleai",
    "lightningai",
    "togetherai",
    "thinkingmachines",
    "gleanwork",
    "xai",
    "waymo",
    "datadog",
    "roku",
    "nexxen",
    "indexexchange",
    "tripadvisor",
    "wpp",
    "dunnhumby",
    "shifttechnology",
    "schonfeld",
    "wheely",
    "shift4",
    "nmi",
    "lhvuk",
    "moniepoint",
    "policyexpert",
]
LEVER_SLUGS = [
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
ASHBY_NAMES = ["elevenlabs", "cohere", "thought-machine", "checkout.com"]


def main() -> None:
    print("Fetching all three ATS sources (no LLM quota used)...")
    jobs = fetch_gh(GREENHOUSE_TOKENS) + fetch_lever(LEVER_SLUGS) + fetch_ashby(ASHBY_NAMES)
    total = len(jobs)
    print(f"\n{total} jobs fetched.\n")

    content_groups = group_by_key(jobs, content_key)
    title_groups = group_by_key(jobs, title_key)
    content_dupes = total - len(content_groups)
    title_dupes = total - len(title_groups)

    print(f"{'key':<16}{'unique':>8}{'dupes caught':>14}{'rate':>8}")
    c_rate = content_dupes / total
    print(f"{'content_key':<16}{len(content_groups):>8}{content_dupes:>14}{c_rate:>8.1%}")
    t_rate = title_dupes / total
    print(f"{'title_key':<16}{len(title_groups):>8}{title_dupes:>14}{t_rate:>8.1%}")

    multi = {k: g for k, g in title_groups.items() if len(g) > 1}
    if multi:
        print(f"\ntitle_key groups with >1 posting ({len(multi)} groups) - eyeball for over-merge:")
        for group in sorted(multi.values(), key=len, reverse=True):
            job = group[0]
            same_content = len(group_by_key(group, content_key))
            note = "identical text" if same_content == 1 else f"{same_content} distinct texts"
            print(f"  x{len(group):<3} [{job['company']}] {job['title'][:60]}  ({note})")


if __name__ == "__main__":
    main()
