"""Simulate the two-stage cascade (local Qwen triage -> Gemini escalation)
using the two existing eval result files - zero API calls.

Rule under test: accept Qwen's doesnt_qualify verdicts locally; escalate
everything else to Gemini. Scored only on jobs where BOTH models have real
results, so the comparison is fair.

Temporary analysis helper - not part of the pytest suite.
"""

import json
from pathlib import Path

local = {(r["source"], r["id"]): r for r in json.loads(Path("eval_results_local.json").read_text())}
gemini = {(r["source"], r["id"]): r for r in json.loads(Path("eval_results.json").read_text())}

both = [
    k
    for k in local
    if local[k]["predicted"] is not None and k in gemini and gemini[k]["predicted"] is not None
]
print(f"{len(both)} jobs have real results from both models.\n")

cascade_correct = 0
escalated = 0
local_rejects = 0
local_reject_wrong = []
for k in both:
    truth = local[k]["true_label"]
    if local[k]["predicted"] == "doesnt_qualify":
        verdict = "doesnt_qualify"
        local_rejects += 1
        if truth != "doesnt_qualify":
            local_reject_wrong.append(local[k]["title"])
    else:
        verdict = gemini[k]["predicted"]
        escalated += 1
    if verdict == truth:
        cascade_correct += 1

gemini_correct = sum(1 for k in both if gemini[k]["predicted"] == both and False)
gemini_correct = sum(1 for k in both if gemini[k]["predicted"] == gemini[k]["true_label"])
local_correct = sum(1 for k in both if local[k]["predicted"] == local[k]["true_label"])

n = len(both)
print(f"{'system':<22}{'accuracy':>10}{'gemini calls':>14}")
print(f"{'Gemini alone':<22}{gemini_correct / n:>10.1%}{n:>14}")
print(f"{'Qwen alone':<22}{local_correct / n:>10.1%}{0:>14}")
print(f"{'cascade':<22}{cascade_correct / n:>10.1%}{escalated:>14}")
print(
    f"\ncascade: {local_rejects} local auto-rejects ({local_rejects / n:.0%} of Gemini calls saved)"
)
if local_reject_wrong:
    print(
        f"\n{len(local_reject_wrong)} true non-doesnt_qualify jobs wrongly auto-rejected locally:"
    )
    for t in local_reject_wrong:
        print(f"  - {t}")
