# SPEC: Engineer Information Facets for the `why/` tracking layer

## Goal
Define the complete set of information ("facets") a software engineer needs to (1) get up to speed on unfamiliar code and (2) make an informed decision about it (change, fix, review, delete, extend, ship). This taxonomy becomes the note format and query surface of the product: a committed `why/` layer written by the developer's own coding agent, plus deterministic checks.

## Acceptance criteria
1. Every facet answers a concrete question an engineer asks, tied to at least one decision situation (S1–S8).
2. Every facet has a declared **source**: COMPUTED (derivable from code/git/CI deterministically), RECORDED (must be captured at creation time by the agent/human, cannot be recovered later), EXTERNAL (lives in another system: tickets, observability, docs), or HUMAN (only a person can supply).
3. Every facet has a **freshness strategy**, and every claim carries a **claim status** (see Claim model): verified, contradicted, inconclusive, unchanged-evidence, stale, unverified, or unknown. Change detection is never presented as semantic verification.
4. The taxonomy is complete enough that an engineer in each situation S1–S8 would not need to interrupt a teammate for common questions.
5. Grounded in prior research on developer information needs (Sillito et al. 2006 "Questions programmers ask during software evolution tasks"; Ko, DeLine & Venolia 2007 "Information needs in collocated software development teams"; LaToza & Myers 2010 "Hard-to-answer questions about code"), which consistently find **rationale/intent ("why")** and **reachability/impact ("what happens if")** are the hardest to answer from code alone.

## Settled decisions (grilling round 1, user-confirmed)
- v1 priority situations: S2 change, S4 review, S5 delete/refactor; S1 onboarding served incidentally.
- Notes are organized per feature, automatically linked to functions/files.
- v1 scope: RECORDED facets + cheap COMPUTED facets (entry points, callers/callees, covering tests, co-change). EXTERNAL integrations (tickets, observability, PR review state, section K) come later as paid features; until then those facets report `unknown`.
- HUMAN-only facets (A2, D5, etc.) are optional empty fields; never nag.
- Answers are shaped by question type: "how" leads with B/C/F/G; "why" leads with E/D/A/B11.
- Notes are written at commit time on significant changes only (rule-based trigger: new feature, behavior change, rule/contract change), not every session.

## Decision situations
- S1 Onboarding: build a mental model of a system/feature
- S2 Change/extend: add a capability safely
- S3 Debug/incident: find why behavior is wrong, fast
- S4 Review: judge whether a PR (often AI-written) is correct and safe
- S5 Delete/refactor: know whether something can go ("Chesterton's fence")
- S6 Decide/design: choose between approaches; estimate impact and reversibility
- S7 Operate: deploy, monitor, respond
- S8 Audit/trust: who/what produced this, was it reviewed, can I rely on the explanation

## Facets

### A. Purpose & context (S1, S5, S6)
| # | Facet | Question | Source | Freshness |
|---|---|---|---|---|
| A1 | Purpose | What problem does this solve, for whom? | RECORDED | Re-confirm on major change |
| A2 | Business criticality | How important is it; what if it breaks? | HUMAN/RECORDED | Periodic review |
| A3 | Status/lifecycle | Active, experimental, deprecated, temporary? Sunset date? | RECORDED | Date-based expiry |
| A4 | Ownership | Which team/person/agent owns it; who to ask/approve? | EXTERNAL (CODEOWNERS) + RECORDED | CODEOWNERS sync |
| A5 | Users/consumers | Who calls/depends on it (internal services, external API clients)? | COMPUTED within analysis boundary + RECORDED/EXTERNAL supplements; result marked complete/partial/unknown | Recompute on change; supplements re-confirmed |

### B. Behavior: how it works (S1, S2, S3)
| # | Facet | Question | Source | Freshness |
|---|---|---|---|---|
| B1 | Entry points | Where does execution start (route, job, event, CLI)? | COMPUTED | Recompute |
| B2 | Control flow | What steps happen in what order? | COMPUTED (call graph) + RECORDED (narrative) | Fingerprint called symbols |
| B3 | Data flow | What data comes in, transforms, goes out, where is it stored? | COMPUTED partial + RECORDED | Fingerprint |
| B4 | Contracts/interfaces | Inputs, outputs, types, schemas, error shapes | COMPUTED | Recompute |
| B5 | Side effects | Writes, emails, payments, external calls, caches | COMPUTED partial + RECORDED | Fingerprint |
| B6 | State & persistence | Tables, keys, files, queues touched; other readers/writers of the same state; migrations | COMPUTED within analysis boundary + RECORDED/EXTERNAL (cross-repo/shared-state users); marked complete/partial/unknown | Recompute; shared-state writers tracked as claim dependencies |
| B7 | External dependencies | Third-party services/libs and why chosen | COMPUTED + RECORDED (why) | Lockfile diff |
| B8 | Configuration | Env vars, feature flags, defaults, per-environment differences | COMPUTED + EXTERNAL (flag system) | Recompute |
| B9 | Concurrency/timing | Async, retries, ordering, race conditions, timeouts | RECORDED + COMPUTED hints | Fingerprint |
| B10 | Error handling | What fails how; retries, fallbacks, user-visible errors | COMPUTED partial + RECORDED | Fingerprint |
| B11 | Intended behavior & acceptance examples | What SHOULD it do (independent of what the code does)? Boundary cases, examples, the authoritative requirement and its revision | RECORDED + EXTERNAL (spec/ticket) | Refresh when requirement revision changes; mismatch with code flagged |

### C. Structure & impact (S2, S5, S6)
| # | Facet | Question | Source | Freshness |
|---|---|---|---|---|
| C1 | Location map | Which files/modules implement this feature? | COMPUTED + RECORDED (feature boundaries) | Recompute |
| C2 | Callers/callees | What calls this; what does it call? | COMPUTED within declared analysis boundary (static call graph) + RECORDED/EXTERNAL supplements for dynamic dispatch, runtime registration, cross-repo consumers; marked complete/partial/unknown | Recompute |
| C3 | Blast radius | What breaks or changes if I modify/remove this? | COMPUTED (reachability) + RECORDED | Recompute |
| C4 | Co-change coupling | What else usually changes with this? | COMPUTED (git history) | Recompute |
| C5 | Key abstractions | Core types/patterns and their meaning | RECORDED | Fingerprint |

### D. Invariants & constraints (S2, S4, S5)
| # | Facet | Question | Source | Freshness |
|---|---|---|---|---|
| D1 | Invariants | What must always be true? | RECORDED (+ tests/asserts as evidence) | Linked test passes |
| D2 | Assumptions | What does this assume about inputs/environment? | RECORDED | Fingerprint |
| D3 | Performance budgets | Latency/throughput/memory limits | RECORDED + EXTERNAL (metrics) | Metrics check |
| D4 | Security boundaries | Auth, permissions, trust boundaries, input validation | RECORDED + COMPUTED hints | Fingerprint |
| D5 | Data sensitivity/compliance | PII, retention, regulatory rules | RECORDED/HUMAN | Periodic review |
| D6 | Compatibility promises | Public API/schema/backward-compat obligations | RECORDED + COMPUTED (exported surface) | Recompute |

### E. History & rationale: why (S5, S6, S8)
| # | Facet | Question | Source | Freshness |
|---|---|---|---|---|
| E1 | Origin | What triggered this (feature request, bug, incident, customer)? | RECORDED + EXTERNAL (ticket link) | Immutable |
| E2 | Decision & alternatives | What was chosen over what, and why? | RECORDED | Immutable; superseded by later decisions |
| E3 | Constraints at the time | Deadlines, limits, missing info that shaped it | RECORDED | Immutable |
| E4 | If removed | What breaks if this goes away? | RECORDED + COMPUTED (C3, tests) | Fingerprint |
| E5 | Still needed? | Workaround or permanent? Removal condition? | RECORDED | Condition/date check |
| E6 | Decision status | Active, superseded, reversed (and by what) | RECORDED | Updated by later entries |
| E7 | Known debt/hacks | TODOs, shortcuts, why accepted | COMPUTED (TODO scan) + RECORDED | Recompute |

### F. Change guidance (S2)
| # | Facet | Question | Source | Freshness |
|---|---|---|---|---|
| F1 | Where to change | For common tasks, which files to touch | RECORDED | Fingerprint |
| F2 | Extension points | Intended ways to extend | RECORDED | Fingerprint |
| F3 | Do-not-touch / fragile areas | What is risky to modify and why | RECORDED + COMPUTED (churn, bug-fix density) | Recompute |
| F4 | Update-together list | Docs, configs, clients, migrations to update in lockstep | RECORDED + COMPUTED (C4) | Recompute |

### G. Verification (S2, S3, S4)
| # | Facet | Question | Source | Freshness |
|---|---|---|---|---|
| G1 | Covering tests | Which tests exercise this? | COMPUTED (coverage map) | CI |
| G2a | Execution coverage gaps | Which lines/branches were not executed by tests (for a specific revision + test run)? | COMPUTED | Per CI run |
| G2b | Behavioral gaps | Which intended behaviors (B11) or invariants (D1) have no asserting test? | RECORDED/HUMAN, linked to B11/D1 | Re-assess when B11/D1 or tests change |
| G3 | Run locally | How to run/reproduce this locally | RECORDED | CI smoke |
| G4 | Verify in production | How to confirm it works live | RECORDED + EXTERNAL | Periodic |

### H. Operations (S3, S7)
| # | Facet | Question | Source | Freshness |
|---|---|---|---|---|
| H1 | Deploy path | How it ships, rollout/rollback | EXTERNAL + RECORDED | Pipeline config |
| H2 | Observability | Logs, metrics, dashboards, alerts | EXTERNAL | Link check |
| H3 | Failure modes & runbook | Known ways it fails; what to do | RECORDED | After incidents |
| H4 | Incident history | Past incidents involving it | EXTERNAL + RECORDED | Append-only |
| H5 | Cost | Infra/API cost drivers | EXTERNAL | Periodic |

### I. Provenance & trust (S4, S8) — AI-era specific
| # | Facet | Question | Source | Freshness |
|---|---|---|---|---|
| I1 | Authorship | Human, agent (which tool/model), or unknown | RECORDED | Immutable |
| I2 | Human review | Was it reviewed/approved, by whom, for which exact code+note revision and scope? Is the CURRENT revision covered? | EXTERNAL (PR review events) | Historical events immutable; current approval derived and invalidated by later changes, dismissed reviews, squash/rebase without mapping; unknown if provider data unavailable |
| I3 | Note evidence | What supports each claim (code refs, tests, tickets, session) | RECORDED + COMPUTED (validation) | Validation run |
| I4 | Claim status | Per claim: verified, contradicted (a check proved it false), inconclusive (check ran but could not decide), unchanged-evidence, stale, unverified, unknown | COMPUTED from per-claim dependencies | Per-claim dependency checks (code symbols, shared-state writers, config, external revision/observation time, review expiry) |
| I5 | Confidence | Recorded fact vs inferred guess | RECORDED | Labeled at write |

### K. Current work & coordination (S2, S5, S6)
| # | Facet | Question | Source | Freshness |
|---|---|---|---|---|
| K1 | In-flight work | Are there open PRs/branches/tickets touching this right now? | EXTERNAL (PR/ticket state) | Refresh timestamp; unknown if integration unavailable |
| K2 | Planned replacements/migrations | Is this scheduled to be replaced, migrated or deleted? | EXTERNAL + HUMAN/RECORDED | Refresh timestamp |
| K3 | Blockers & dependencies on people | Who must be consulted/approve; what is blocked on what | EXTERNAL + HUMAN | Refresh timestamp |

### J. Domain & environment (S1)
| # | Facet | Question | Source | Freshness |
|---|---|---|---|---|
| J1 | Glossary | What do domain terms mean here? | RECORDED | On change |
| J2 | Dev setup | Prereqs, secrets needed (names only), services to run | RECORDED + COMPUTED | CI smoke |
| J3 | Open questions | Known unknowns, unresolved decisions | RECORDED | Until resolved |

## Claim model (applies to every facet)
- Each statement in `why/` is a **claim** with: facet id, evidence refs, dependencies, source type, recorded-vs-inferred label, and status.
- Status values: **verified** (a check passed at time T), **contradicted** (a completed check showed the claim is false), **inconclusive** (a check ran but could not decide, e.g. flaky or partial), **unchanged-evidence** (dependencies unchanged since last verification; not re-verified), **stale** (a dependency changed), **unverified** (never checked), **unknown** (cannot be determined, e.g. missing integration or outside analysis boundary).
- COMPUTED results declare their analysis boundary and completeness (complete/partial/unknown). Supplements for what static analysis cannot see are allowed as RECORDED/EXTERNAL claims, never as edits to computed output.
- A working link or unchanged fingerprint is never shown as "verified true".
- Every validation is recorded as an event: check id, scope, code revision, time, outcome (pass / fail / inconclusive / unavailable), and failure evidence. Status is aggregated per claim revision, dependency snapshot, check and scope (not simply the latest event): any failure makes the claim **contradicted**, and a later failure always overrides an earlier pass. A demonstrated contradiction stays active until it is explicitly resolved (the claim is rewritten, the code is fixed and the failing check/scenario passes, or a human marks it resolved with a reason) or superseded by a new claim revision; an unrelated pass or a successful rerun alone never clears it, and one check's pass cannot resolve another check's failure. Contradicted claims are shown prominently and never used as answers without the warning.

## Key product implications (hypotheses)
- RECORDED facets (A1, A3, E1–E6, D1–D2, F1–F3, H3, I5) are the moat: they cannot be recovered from code later.
- COMPUTED facets should never be hand-written; generate them so they cannot drift.
- EXTERNAL facets are integrations (tickets, PRs, observability), likely paid tier.
- Answers should be situation-shaped: "how" answers lead with B/C/F/G; "why" answers lead with E/D/A.

## Non-goals
Replacing observability, ticketing, or docs tools; we link to them.

## Verification
- Discovery: interview 10–15 engineers; map their last 3 "how/why" questions to facets (≥ 90% mapped); log unmapped needs as candidate facets.
- Task trials across all situations, using only declared sources (no hand-filling COMPUTED facets): one representative task per S1–S8 on 3 real features (e.g. S3 reproduce a seeded bug, S4 review a PR with a seeded defect, S5 decide whether to delete a function with a hidden consumer, S8 determine authorship/review of current code).
- Measure separately per situation: answer availability, evidence correctness, correct uncertainty handling (partial/unknown/stale shown when true), and interruptions.
- Pass per situation: ≥ 80% questions answered from `why/` + code, 0 incorrect "verified" claims, all seeded partial/stale/unknown cases surfaced, ≤ 1 interruption per task.
- Include adverse cases: missing integrations, stale evidence, dynamic dispatch / cross-repo consumer, squash-merged approval, a claim contradicted on first validation, a check that passes then later fails, a check that fails then passes on rerun with unchanged code (must stay contradicted), and mixed outcomes across different checks for the same claim.
