## Problem

Describe the water-treatment workflow or software issue and link a related issue
when available. For scientific-behavior changes, state which stage of the
case-to-report flow is affected (readiness, assessment, retrieval,
recommendation, closed-loop optimization, audit, or handoff) and what decision
the change is meant to improve.

## Changes

Explain the resulting behavior, affected interfaces (CLI, TUI, Web, desktop, MCP
tools, adapter commands, persisted research state), and compatibility
considerations. For a renamed or removed flag, tool, environment variable, or
persisted field, name the population that used it before and where it goes now.

## Validation

List the checks performed and any remaining limitations. Distinguish software
tests from evidence of engineering performance. Typical checks:

```bash
npm run check          # lint, typecheck, tests, TUI checks, MCP/Web smoke, licenses, repo invariants
npm run smoke:desktop  # packaged desktop launch, for desktop changes
python3 -m unittest discover -s engine/apps/hydroweaver/test-python -t engine/apps/hydroweaver/test-python
```

When the change touches the closed-loop optimizer or the research gates, state
which behavior is pinned by a test and which known boundary remains. A `feasible`
optimization result is constraint-check feasibility only, never a performance or
compliance claim.
