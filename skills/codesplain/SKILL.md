---
name: codesplain
description: Use when someone asks how code works or why code exists, before changing, reviewing, refactoring or deleting code in a repository that has a codesplain/ folder, and after making a significant change (new or changed exported function, route, job or CLI command; schema or migration; config, feature flag or environment variable; new dependency; changed test assertions) that future engineers or agents will need to understand.
---

# codesplain

## Overview

A repository's `codesplain/` folder is its committed memory of **how features work and why code was written**. You answer questions from it and keep it current. Every statement in it is a **claim** that is labeled `recorded` (captured when the work happened) or `inferred` (deduced from code). Its status (verified, stale, contradicted…) is **derived by a checker, never typed by hand**.

`SKILL_DIR` below means the directory containing this `SKILL.md`.

## Safety rules (always)

- **Never open `.env*` files, credential files, or key stores** to write notes. Refer to configuration by variable **name** only (`STRIPE_API_KEY`), never by value.
- Never put secrets, tokens, passwords, personal data, customer data, or pasted transcripts in `codesplain/`.
- The checker is read-only and offline. Run it; never edit it to make errors disappear.

## Answer mode: "how does X work?" / "why does X exist?" / before changing or deleting X

1. Read `codesplain/features/*.md` and `codesplain/journal/*.md` that mention X (search file names, `files:`, `symbols:` and claim text).
2. Run `python3 SKILL_DIR/scripts/check_why.py --root . --json` to get each claim's derived status.
3. Confirm claims you rely on against the current code before stating them.
4. Compute the cheap facets yourself, read-only (search for callers and entry points, find covering tests, `git log` for co-change). Never write these into `codesplain/`. Always state the boundary and completeness, e.g. "callers: 2 found by text search in this repo; dynamic dispatch and other repos not checked → partial".
5. Answer in the matching shape below. Put each claim's status in brackets.

**A "how" answer has these parts, in order:**
1. **Flow:** entry point → steps → side effects (with function names).
2. **Where to change:** files to edit for common tasks.
3. **Rules:** invariants and assumptions that must stay true.
4. **Gotchas:** retries, timing, error handling, config.
5. **Verify:** tests that cover it and how to run them.
6. **Confidence:** claim statuses plus the completeness of computed facets.

**A "why" answer has these parts, in order:**
1. **Origin:** the problem or request that caused it, and its source (ticket, incident, journal entry).
2. **If removed:** what breaks.
3. **Still needed?** Permanent or a workaround, and the removal condition.
4. **Decision:** what was chosen over what, and why.
5. **Confidence:** claim statuses.

**When nothing is recorded,** say exactly **"No recorded intent."** You may then add a section headed **"Inferred from code (not recorded):"**. Never blend inference into recorded facts.

## Write mode: after a significant change

**Write a note when the change does any of these:**
- adds or changes an exported function, API route, background job or CLI command
- changes a schema or migration
- changes config, a feature flag or an environment variable
- adds a dependency
- changes test assertions

Skip typo, formatting and comment-only changes.

1. **Add a journal entry:** `codesplain/journal/YYYY-MM-DD-<short-slug>.md`. Use one new file per change, never one shared file. Use the journal template in `SKILL_DIR/reference/format.md`.
2. **Update the feature page:** `codesplain/features/<feature>.md`, using the feature template. If no feature fits, create one and say in your summary that the human should confirm the new feature boundary in the PR.
3. **Write claims:**
   - one fact per claim, with a stable `id`
   - `kind: recorded` covers exactly two sources: what the user, task, ticket or a teammate actually stated, and what you yourself changed (the edit itself). Use the stated reason in its stated words.
   - `kind: inferred` covers everything else: behavior read from code, consequences you predict, and any motivation, alternative or "why" detail you add yourself. If nobody stated an alternative, either write none or add it as `inferred`.
   - `deps` set to the exact files or `path#symbol` the claim depends on
   - a `facet` id from `SKILL_DIR/reference/facets.md` where one fits
   - include the facets people most need: purpose (A1), intended behavior (B11), if removed (E4), still needed (E5), decision and alternatives (E2), rules (D1), where to change (F1), how to verify (G3)
4. **Record removed code historically:** when you delete or rename code, list the old target under `removed:` as `path@commit` or `path#symbol@commit`. Don't list it under `files:`.
5. **Optionally record a validation event:** if you ran a test that checks a claim, record an event using the procedure in `format.md`. Capture the hashes around the actual run, and never record a pass you didn't observe.
6. **Run the checker last:** `python3 SKILL_DIR/scripts/check_why.py --root . --strict codesplain/journal/<your-entry>.md`. Fix every ERROR, then report any WARN lines to the user. **Rerun it after any further change under `codesplain/`, before committing.**

**Existing journal entries are append-only.** Change one only to mark it superseded (`lifecycle: superseded` + `superseded_by`). Record resolutions as new event files, not as edits.

## Claim statuses (derived by the checker)

| Status | Meaning | How to present it |
|---|---|---|
| verified | Recent passing check against current claim and file contents | State it |
| unchanged-evidence | Passed long ago; nothing it depends on changed | State it and note the age |
| stale | A dependency changed since it was checked | "may be outdated", then re-check the code |
| unverified | Never checked, or a failure was resolved without a new pass | Treat as unconfirmed |
| inconclusive | A check ran but couldn't decide | Say so |
| unknown | A required check was unavailable | Say so |
| contradicted | A check proved it false and that's unresolved | **Warn prominently. Never use it as an answer** |

## Common mistakes

| Mistake | Fix |
|---|---|
| Documenting in README, `docs/`, `CLAUDE.md` or `AGENTS.md` instead of `codesplain/` | Write the journal entry and feature page in `codesplain/`, and link to them from elsewhere if you like |
| Opening `.env` to see which variables exist | Read the code that loads the config; name variables only |
| Writing `status: verified` by hand | Delete it; status comes from `codesplain/events/` |
| Listing callers or coverage in notes | Compute them at answer time and label completeness |
| Presenting a guess as history | `kind: inferred`, or "Inferred from code (not recorded)" |
| Embellishing the stated reason ("to reduce load", "rejected as too slow") and marking it recorded | Record only the stated reason; mark your own additions `inferred` |
| Editing an old journal entry to match new code | Write a new entry; mark the old one `superseded` |
| Referencing a function that doesn't exist | Run `--strict` on new entries; the checker rejects made-up references |
