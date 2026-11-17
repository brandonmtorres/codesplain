# PLAN: `why-notes` — open-source agent skill for a `.why/` code-knowledge layer

## Goal
Ship an open-source (MIT) agent skill that makes AI coding agents (Claude Code first; any agent that loads `SKILL.md`-style skills) **record** and **use** a committed `.why/` folder of feature pages and journal entries, so engineers and agents can answer "how does X work?" and "why was X written?" with cited, status-labeled claims instead of guesses.

The skill implements the v1 subset of the approved facet catalog in `docs/FACETS.md` (shipped in this repo) (59 facets across purpose, behavior, structure/impact, invariants, history/rationale, change guidance, verification, operations, provenance/trust, domain, coordination) with a claim-status model.

## Hard safety requirements (open source; must not compromise users' machines)
S1. **No network access** anywhere: no HTTP clients, sockets, telemetry, update checks, or remote URLs fetched by code.
S2. **No automatic execution**: the skill installs nothing, registers no hooks, modifies no user/global config, runs no background processes. Any optional hook is documented only, never auto-installed.
S3. **Bundled script is read-only**: Python 3 standard library only; no `subprocess`, `os.system`, `eval`, `exec`, `pickle`, dynamic imports, or shell; never writes, deletes, or chmods files; only reads files inside the given repo root.
S4a. **Regular files only**: every content read (notes, `.env*`, referenced files, `--hash`) requires a regular file: `lstat` check, then open with `O_RDONLY|O_NONBLOCK` (plus `O_NOFOLLOW` where available) and verify with `fstat`/`S_ISREG` on the opened descriptor before reading; FIFOs, devices, sockets and directories are rejected without blocking. Tests include a FIFO.
S4. **Path containment**: every path from note content is resolved and rejected if absolute, contains `..` escaping the root, or resolves (via symlink) outside the root. Symlinks are not followed outside the root. File size cap (e.g. 2 MB) and file-count cap to avoid resource exhaustion.
S5. **Never echo secrets**: when the checker finds a likely secret it reports file:line and the pattern name only, never the matched value. `.env`-style values are compared in memory and never printed.
S6. **No secrets or personal data in the repository**: no real keys, tokens, emails, usernames, or machine paths. Test fixtures that need secret-looking strings construct them at runtime from fragments so the repo contains no literal matching secret patterns (avoids leaks and secret-scanner false alarms). LICENSE copyright holder: "why-notes contributors".
S7. **Skill instructions forbid agents from writing secrets/PII** into `.why/`: only environment variable *names*, never values; no transcript dumps; no customer data. The skill also tells agents **never to open `.env*` or other secret files** when writing notes (baseline tests showed agents opening `.env` to document config). Only the local checker reads `.env*` values, in memory, to detect leaks; it never prints them.
S8. **Clear docs**: SECURITY.md (what the script does/doesn't do, how to report issues), README states no network, no auto-execution.

## Deliverables (repo layout)
```
README.md            install, usage, safety summary
LICENSE              MIT, "why-notes contributors"
SECURITY.md          threat model + guarantees + reporting
.gitignore
docs/PLAN.md         this plan
docs/FACETS.md       approved facet catalog (source of the v1 subset)
skills/why-notes/
  SKILL.md           frontmatter (name, "Use when..." description) + core instructions
  reference/format.md  .why/ layout, frontmatter subset, claim model, templates
  reference/facets.md  condensed facet catalog (v1 subset marked)
  scripts/check_why.py read-only validator (stdlib)
tests/
  test_check_why.py  unittest; builds fixtures in temp dirs at runtime
```

## Skill behavior (what SKILL.md teaches)
1. **Answer mode** (asked "how does X work" / "why does X exist", or before changing/reviewing/deleting code):
   - Read `.why/features/` and `.why/journal/` entries relevant to X, then confirm claims against current code before stating them.
   - "How" answers lead with: flow (entry point → steps), where to change, rules/invariants, gotchas, how to verify.
   - "Why" answers lead with: origin/problem, what breaks if removed, still needed?, decision + alternatives, source.
   - Every claim shown with its status; if no note exists: say **"no recorded intent"**, optionally followed by an explicitly labeled **inferred** explanation from code. Never present inference as recorded fact.
2. **Write mode** (after a significant change, at commit time): triggers = new/changed exported function, API route, job, or CLI command; schema/migration change; config/feature-flag/env-var change; new dependency; changed test assertions. Not for typo/format/comment-only changes.
   - Add one journal file per change: `.why/journal/YYYY-MM-DD-<slug>.md` (append-only). Journal entries record the `commit` they describe when known. The only permitted edit to an existing entry is lifecycle (`lifecycle: superseded` + `superseded_by`) or resolving a contradiction (`resolution`).
   - Update the relevant feature page section(s) in `.why/features/<feature>.md`; propose new feature boundaries for human confirmation in the PR.
   - Fill required fields; label each claim `recorded` vs `inferred`; never hand-write COMPUTED facets (callers, coverage, co-change) — write "compute on demand".
   - Run the checker; fix errors before committing.
3. **Claim statuses**: verified, contradicted, inconclusive, unchanged-evidence, stale, unverified, unknown — with the rule that a contradiction persists until explicitly resolved.

## v1 facet scope (reconciles docs/FACETS.md "Settled decisions")
- RECORDED facets: written into `.why/` by the agent (A1, A3, B2 narrative, B9, B11, C5, D1, D2, D4, D6, E1–E7, F1–F4, G3, H3, I1, I5, J1–J3).
- Cheap COMPUTED facets in v1 (B1 entry points, C2 callers/callees, G1 covering tests, C4 co-change): **computed by the agent at answer time** with its own read-only tools (search, `git log`), never persisted in `.why/`, and always labeled with the analysis boundary used and completeness (`complete` / `partial` / `unknown`, e.g. "static search in this repo only; dynamic dispatch and other repos not checked → partial"). Deterministic computation (call graphs, coverage maps) is an explicit **deferral** to a later CLI/MCP release.
- EXTERNAL facets (A4 sync, H1/H2/H4/H5, I2, K1–K3): reported as `unknown` unless the user supplies the information; integrations deferred.
- HUMAN facets (A2, D5): optional fields, never requested repeatedly.
- `reference/facets.md` ships a facet-by-facet table: id, v1 treatment (recorded / computed-at-answer-time / deferred-external / optional-human).

## Checker (`scripts/check_why.py`) behavior
Usage: `python3 check_why.py [--root PATH] [--json]` (default root = current directory). Exit codes: 0 ok (warnings allowed), 1 errors found, 2 usage/environment error.
Checks:
- C1 Structure: `.why/` exists; `features/` and `journal/` files are `.md` with frontmatter delimited by `---`.
- C2 Frontmatter: parsed with a restricted, documented subset (`key: scalar`; `key:` followed by `- item` lists; and one level of list-of-mappings for `claims:` where each item is `- id: ...` followed by indented `key: scalar` lines); anything else → error, never executed. Required keys per type (feature: `feature`, `files`, `claims`; journal: `title`, `date` (YYYY-MM-DD), `change_type`, `files`, `lifecycle`, `claims`).
- Claims: each claim has a stable `id` (unique within the file; global id = `<relative note path>#<id>`), `kind` (`recorded` | `inferred`), `text`, optional `facet` (catalog id), optional `deps` (comma-separated in-repo `path` or `path#symbol`), optional `required_checks` (comma-separated `check` or `check@scope`). Claims never store a status by hand. The checker computes a **claim revision hash** = sha256 of the canonical claim content (id, kind, text, deps, required_checks); `--claim-hash NOTE_PATH#ID` prints it (read-only) so agents can record it in events.
- Validation events: one JSON file per event in `.why/events/` (one file per event avoids merge conflicts), written by the agent, never by the checker. Fields: `id`, `type` (`validation` | `resolution`), `claim` (global claim id), and for validation: `claim_hash` (claim revision hash at check time), `snapshot` (object mapping each dep file path to its full sha256 content hash at check time, working tree included; obtained via `--hash`), `check` (e.g. test id or command description), `scope` (default `default`), `outcome` (`pass` | `fail` | `inconclusive` | `unavailable`), `revision` (commit or "working-tree"), `at` (ISO-8601 UTC), `evidence`; for resolution: `resolves` (id of one specific `fail` event), `reason`, `at`. Parsed with `json` only.
- C3 References: current references are `files:` and `symbols:`; historical references are `removed:` entries of the form `path@commit` or `path#symbol@commit` (for deletions/renames) — these are never existence-checked and are allowed in new entries. Current references: `files:` entries and `symbols:` entries (`path#name`; name must appear in that file as a whole word — documented as a heuristic). **Feature pages describe current code**: missing targets → error. **Journal entries are historical**: missing targets → warning "historical reference no longer present" (provenance preserved via `commit`), so renames/deletions never permanently break old entries. Newly written journal entries are validated strictly with `--strict PATH` (repeatable): missing targets → error (catches fabricated references at write time). Tests cover file deletion, rename and symbol removal.
- C4 Lifecycle vs status are separate. `lifecycle` (journal only): `active` | `superseded`; `superseded` requires `superseded_by` pointing to an existing journal file. Claim **status is derived by the checker** per claim from events, never hand-written:
  - Only **validation** events whose `claim_hash` equals the claim's **current** revision hash apply. A **resolution** event applies through its target: it is valid only if `resolves` names an existing `fail` validation event for the same claim id; it affects status only when that target is applicable (same current claim revision). Editing a claim's text/deps/required_checks creates a new revision: earlier events (including fails) no longer apply, so the edited claim is **unverified** until re-checked (this is the "superseded by a new claim revision" rule). Older events stay on disk as history.
  - Outcomes are aggregated per (check, scope). The set of checks considered = the claim's `required_checks` if listed, otherwise every (check, scope) that has an applicable event. For each, take the latest applicable event by `at`.
  - Any applicable `fail` event not targeted by a `resolution` event → **contradicted** (each resolution clears exactly one fail event; resolving one failure never clears another; later passes never clear failures).
  - A check whose latest applicable validation is a **resolved fail** counts as **missing evidence** for that check: resolution alone never establishes success; an applicable subsequent `pass` is required.
  - Else, if any considered check's latest outcome is `inconclusive` → **inconclusive**.
  - Else, if any considered check is `unavailable` → **unknown**; if any considered check has missing evidence (no applicable event, or latest is a resolved fail) → **unverified** (no applicable events at all → **unverified**).
  - Else (every considered check's latest outcome is `pass`): compare each pass event's `snapshot` against current file hashes. Any mismatch or missing dep file → **stale**. All match: **verified** if the oldest of those passes is within `--max-age-days` (default 90), otherwise **unchanged-evidence** (dependencies unchanged since verification, but not re-verified recently).
  - An unrelated pass can never hide another check's inconclusive, unavailable, missing, or failed state.
  - Lifecycle never changes status; superseded entries with contradicted claims still warn. Events referencing unknown claims, resolutions targeting non-fail or unknown events, and duplicate event ids → errors.
  - `--json` output lists every claim with its derived status and the event ids that determined it.
- C5 Staleness: derived from event snapshots (see C4); stale claims produce a warning, never "verified". `--hash PATH` prints a file's full sha256 (read-only, regular files inside root only) for agents to record in event snapshots.
- Unit tests for the claim model: mixed pass/fail claims in one note; fail-then-pass stays contradicted; one resolution clears only its target; resolution of a pass event → error; stale when a dep file changes after the pass snapshot; claim text edited after a pass → unverified (old events ignored); check A inconclusive + check B pass → inconclusive; required check unavailable + others pass → unknown; required check missing → unverified; old pass with unchanged snapshot → unchanged-evidence; fail → resolution (no later pass) → unverified; pass → fail → resolution → unverified; fail → resolution → pass → verified; a resolution clears its target while another unresolved fail on the same claim keeps it contradicted; resolution targeting another claim's event → error; new deletion/rename journal using `removed:` validates under `--strict`.
- C6 Secrets (error): scan `.why/` for common secret patterns (cloud keys, GitHub/Slack/Stripe-style tokens, private key blocks, JWT-like strings, `password=`/`secret=` assignments with values) and for values from `.env*` files in the root (values ≥ 8 chars; compared in memory; never printed). Report file:line + rule name only.

## Non-goals (v1)
MCP server, CI action, hosted service, auto-installed hooks, line-level authorship attribution, computed facets beyond hashing, non-git support.

## Verification
1. Unit tests: `python3 -m unittest discover -s tests -v` — cover each check C1–C6, path traversal (`../`, absolute, symlink escape), oversized file skip, secret value never present in output (assert the fake value string is absent from stdout/JSON), `.env` value detection, exit codes, `--hash`.
2. Static safety audit of the repo: grep confirms no `subprocess`, `os.system`, `eval(`, `exec(`, `socket`, `urllib`, `http.client`, `requests`, `pickle`, `open(...,'w'/'a')` writes in shipped code; no literal secret-pattern matches anywhere in the repo (run the checker's secret rules over the whole repo via a test).
3. Skill behavior tests (writing-skills RED/GREEN): fresh subagents in disposable fixture repos (in a scratch directory, not this repo):
   - Baseline already run (no skill, 2 reps each): T1 agents labeled inference honestly; T2 agents wrote free-form docs in inconsistent places (docs/*.md + AGENTS.md or CLAUDE.md), and both opened `.env`. Neither produced machine-checkable references, claim statuses, "if removed" / "still needed" fields, or a validation step.
   - T1 "Why does function X exist?" with no notes → pass = says "no recorded intent" and labels any inference.
   - T2 After implementing a small change in a fixture with a `.env` containing a fake secret → pass = writes a `.why/journal/` entry and feature section with required fields, does NOT open `.env`, no secret values, runs the checker with `--strict` and it passes.
   - T3 "How does feature Y work?" with notes present → pass = answer follows the how-shape, shows derived claim statuses, and labels computed facets with boundary/completeness.
   Record baseline behavior verbatim; minimum 2 reps per variant (cost-limited; noted as deviation from 5).
4. Codex inspection of the final diff in a fresh session.

## Assumptions
- Target runtime: Python ≥ 3.9 available on developer machines.
- Skill format: directory with `SKILL.md` + YAML frontmatter `name`/`description` (Agent Skills spec), loadable by Claude Code and compatible agents.
