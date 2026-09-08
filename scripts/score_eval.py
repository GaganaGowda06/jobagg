"""Score eval_results.json: accuracy with a bootstrap confidence interval,
Cohen's kappa, confusion matrix, per-class precision/recall/F1, and a
per-source accuracy slice.

Run after run_eval.py has produced eval_results.json for the full eval set.

Statistical additions:
- Cohen's kappa: chance-corrected agreement between the model and the hand
  labels. Guards against a classifier that scores high accuracy just by
  predicting the majority class.
- Bootstrap 95% CI: on ~130 items a single accuracy number is fragile
  (roughly +/-7 points of sampling noise), so a prompt change only counts
  as a real improvement if its CI lower bound clears the previous
  version's point estimate.
"""

import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

# optional argument: which results file to score (default: the Gemini eval).
# lets the same harness score eval_results_local.json for the Ollama model.
RESULTS_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("eval_results.json")
LABELS = ("qualifies", "doesnt_qualify", "uncertain")
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 42  # fixed so reruns on the same results give the same CI


def _accuracy(rows: list[dict]) -> float:
    return sum(1 for r in rows if r["predicted"] == r["true_label"]) / len(rows)


def _cohens_kappa(rows: list[dict]) -> float:
    n = len(rows)
    observed = _accuracy(rows)
    true_counts = Counter(r["true_label"] for r in rows)
    pred_counts = Counter(r["predicted"] for r in rows)
    expected = sum(true_counts[label] * pred_counts[label] for label in LABELS) / (n * n)
    if expected == 1.0:
        return 0.0
    return (observed - expected) / (1 - expected)


def _bootstrap_ci(rows: list[dict], statistic, seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    samples = sorted(statistic(rng.choices(rows, k=len(rows))) for _ in range(BOOTSTRAP_RESAMPLES))
    lo = samples[int(0.025 * BOOTSTRAP_RESAMPLES)]
    hi = samples[int(0.975 * BOOTSTRAP_RESAMPLES) - 1]
    return lo, hi


def score() -> None:
    results = json.loads(RESULTS_PATH.read_text())

    errors = [r for r in results if r["predicted"] is None]
    scored = [r for r in results if r["predicted"] is not None]

    if errors:
        print(f"{len(errors)} job(s) failed to classify (API error, not a wrong prediction):")
        for r in errors:
            print(f"  - {r['title']}: {r['reason']}")
        print()

    total = len(scored)
    correct = sum(1 for r in scored if r["predicted"] == r["true_label"])
    acc = correct / total
    acc_lo, acc_hi = _bootstrap_ci(scored, _accuracy, BOOTSTRAP_SEED)
    print(f"Overall accuracy: {correct}/{total} ({acc:.1%})  [95% CI: {acc_lo:.1%} - {acc_hi:.1%}]")

    kappa = _cohens_kappa(scored)
    k_lo, k_hi = _bootstrap_ci(scored, _cohens_kappa, BOOTSTRAP_SEED)
    print(f"Cohen's kappa:    {kappa:.3f}  [95% CI: {k_lo:.3f} - {k_hi:.3f}]\n")

    # confusion matrix: rows = true label, columns = predicted label
    confusion = {t: Counter() for t in LABELS}
    for r in scored:
        confusion[r["true_label"]][r["predicted"]] += 1

    header = "true \\ predicted".ljust(18) + "".join(label.rjust(16) for label in LABELS)
    print(header)
    for true_label in LABELS:
        row = confusion[true_label]
        print(true_label.ljust(18) + "".join(str(row[p]).rjust(16) for p in LABELS))
    print()

    # precision / recall / f1 per class
    print(f"{'label':<16}{'support':>8}{'precision':>11}{'recall':>9}{'f1':>7}")
    for label in LABELS:
        support = sum(confusion[label].values())
        tp = confusion[label][label]
        predicted_as_label = sum(confusion[t][label] for t in LABELS)
        precision = tp / predicted_as_label if predicted_as_label else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        flag = "  (small support - treat cautiously)" if support < 20 else ""
        print(f"{label:<16}{support:>8}{precision:>11.1%}{recall:>9.1%}{f1:>7.1%}{flag}")
    print()

    # per-source accuracy slice
    by_source: dict[str, list[dict]] = defaultdict(list)
    for r in scored:
        by_source[r["source"]].append(r)
    print(f"{'source':<12}{'n':>5}{'accuracy':>10}")
    for source in sorted(by_source):
        rows = by_source[source]
        print(f"{source:<12}{len(rows):>5}{_accuracy(rows):>10.1%}")


if __name__ == "__main__":
    score()
