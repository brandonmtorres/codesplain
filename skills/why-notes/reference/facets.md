# Facet catalog: v1 treatment

Use these ids in a claim's `facet:` field. The full catalog, with questions, sources and freshness rules, is in `docs/FACETS.md` in the why-notes repository.

**Treatment values:**
- **recorded:** write it into `.why/` as claims.
- **computed (answer time):** derive it yourself when answering, read-only. Never persist it. Always state the boundary and completeness (complete / partial / unknown).
- **external (deferred):** report `unknown` unless the user provides it.
- **human (optional):** fill it only if a person supplies it. Never nag.

| Id | Facet | v1 treatment |
|---|---|---|
| A1 | Purpose | recorded |
| A2 | Business criticality | human (optional) |
| A3 | Status/lifecycle (active, experimental, deprecated, temporary) | recorded |
| A4 | Ownership | external (deferred; CODEOWNERS may be read) |
| A5 | Users/consumers | computed (answer time) for this repo; other repos unknown |
| B1 | Entry points | computed (answer time) |
| B2 | Control flow | recorded narrative; call details computed (answer time) |
| B3 | Data flow | recorded |
| B4 | Contracts/interfaces | computed (answer time) from code |
| B5 | Side effects | recorded |
| B6 | State and persistence (including other readers and writers) | recorded; mark partial when shared state is used elsewhere |
| B7 | External dependencies, and why chosen | recorded (why); versions computed (answer time) |
| B8 | Configuration (variable names only) | recorded |
| B9 | Concurrency/timing | recorded |
| B10 | Error handling | recorded |
| B11 | Intended behavior and acceptance examples | recorded |
| C1 | Location map | recorded (`files:` on feature pages) |
| C2 | Callers/callees | computed (answer time) |
| C3 | Blast radius | computed (answer time), plus recorded notes |
| C4 | Co-change coupling | computed (answer time, `git log`) |
| C5 | Key abstractions | recorded |
| D1 | Invariants | recorded |
| D2 | Assumptions | recorded |
| D3 | Performance budgets | recorded if known; metrics external (deferred) |
| D4 | Security boundaries | recorded |
| D5 | Data sensitivity/compliance | human (optional) |
| D6 | Compatibility promises | recorded |
| E1 | Origin | recorded |
| E2 | Decision and alternatives | recorded |
| E3 | Constraints at the time | recorded |
| E4 | If removed | recorded |
| E5 | Still needed? (removal condition) | recorded |
| E6 | Decision status | journal `lifecycle` + `superseded_by` |
| E7 | Known debt/hacks | recorded; TODO scan computed (answer time) |
| F1 | Where to change | recorded |
| F2 | Extension points | recorded |
| F3 | Do-not-touch / fragile areas | recorded |
| F4 | Update-together list | recorded |
| G1 | Covering tests | computed (answer time) |
| G2a | Execution coverage gaps | external (deferred) |
| G2b | Behavioral gaps (intended behaviors without asserting tests) | recorded |
| G3 | How to run locally | recorded |
| G4 | Verify in production | recorded if known |
| H1–H5 | Deploy, observability, runbook, incidents, cost | external (deferred); H3 runbook may be recorded |
| I1 | Authorship (human / agent / unknown) | recorded |
| I2 | Human review of the current revision | external (deferred) |
| I3 | Evidence for claims | `deps` + `.why/events/` |
| I4 | Claim status | derived by the checker |
| I5 | Recorded vs inferred | claim `kind` |
| J1 | Glossary | recorded |
| J2 | Dev setup (secret names only) | recorded |
| J3 | Open questions | recorded |
| K1–K3 | In-flight work, planned replacements, blockers | external (deferred) |
