---
"hydroweaver": minor
---

Add closed-loop treatment-train optimization: run `hydroweaver optimize --input case.json --wait`, or ask the agent for `hydroweaver_optimize_trains`, to critique candidate trains, keep the critic's auto-revisions, and regenerate candidates with a revision directive until every chain passes or the round budget ends; the record states feasible, stalled, or budget-exhausted.
