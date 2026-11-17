# `codesplain/` format reference

```
codesplain/
  features/<feature>.md          how a feature works now (describes CURRENT code)
  journal/YYYY-MM-DD-<slug>.md   one entry per significant change (HISTORICAL, append-only)
  events/<event-id>.json         one validation or resolution event per file
```

## Frontmatter subset (the checker rejects anything else)

Each note begins with `---` and ends its frontmatter with `---`. Inside, only this syntax is allowed:

```yaml
key: scalar value
list_key:
  - item
  - item
claims:
  - id: c1
    kind: recorded
    text: one sentence
```

- No inline lists (`[a, b]`), no nested objects except `claims`, no tabs, no multi-line strings.
- Quotes around a scalar are optional and get stripped. **Quote any value that starts with** `| > { [ & * ! % @` or a backtick. Claim fields must all use the same indentation.
- Event JSON files must not repeat a key.
- Comma-separated values are used inside claims for `deps` and `required_checks`.

## Feature page template: `codesplain/features/<feature>.md`

```markdown
---
feature: payments
files:
  - shop/payments.py
  - shop/idempotency.py
symbols:
  - shop/payments.py#create_payment
claims:
  - id: purpose
    kind: recorded
    facet: A1
    text: Charges customers once per checkout request.
    deps: shop/payments.py#create_payment
  - id: no-double-charge
    kind: recorded
    facet: D1
    text: Every charge passes an idempotency key; a repeated key within 24h is ignored.
    deps: shop/payments.py#create_payment, shop/idempotency.py#seen_recently
    required_checks: tests/test_payments.py::test_duplicate_request@unit
  - id: where-retries
    kind: recorded
    facet: F1
    text: To change retry behavior edit charge_card; the limit comes from PAYMENT_MAX_RETRIES.
    deps: shop/payments.py#charge_card
---

# Payments

## Flow
create_payment → seen_recently → remember → charge_card → provider

## Where to change
...

## Rules
...

## Gotchas
...

## Verify
...
```

`files` and `symbols` on a feature page must exist (the checker reports an ERROR otherwise).

## Journal entry template: `codesplain/journal/YYYY-MM-DD-<slug>.md`

```markdown
---
title: Make payment retries configurable
date: 2026-11-17
change_type: config
commit: working-tree
files:
  - shop/payments.py
symbols:
  - shop/payments.py#charge_card
lifecycle: active
claims:
  - id: origin
    kind: recorded
    facet: E1
    text: The payment provider asked for fewer retries during their outage.
  - id: decision
    kind: recorded
    facet: E2
    text: Chose an environment variable (default 3) over a code constant so ops can change it without a deploy.
    deps: shop/payments.py#charge_card
  - id: if-removed
    kind: recorded
    facet: E4
    text: Removing it restores a hard-coded 3 retries; ops lose the ability to lower retries during outages.
    deps: shop/payments.py
  - id: still-needed
    kind: recorded
    facet: E5
    text: The mechanism is permanent; any lowered value is temporary until the provider confirms recovery.
---

## What changed
...

## Why
...

## Alternatives considered
...
```

- `change_type`: feature | fix | refactor | config | dependency | schema | removal | other.
- `commit`: the commit hash when known; otherwise `working-tree`.
- Deleted or renamed code goes under `removed:` as `path@commit` or `path#symbol@commit`.
- Only `features/*.md`, `journal/*.md` and `events/*.json` are part of the format. Other files under `codesplain/` are warned about, and everything under `codesplain/` is scanned for secrets.
- Superseding: in the old entry, set `lifecycle: superseded` and `superseded_by: <new-entry-file-name>.md`.
- Never write `status:`. The checker derives it.

## Validation events: `codesplain/events/<id>.json`

Only record an event for a check you actually ran and observed. The hashes must describe exactly what was checked:

1. **Immediately before** running the check, get the claim's revision hash and the hash of every file in its `deps`:
   `python3 SKILL_DIR/scripts/check_why.py --root . --claim-hash codesplain/features/payments.md#no-double-charge`
   `python3 SKILL_DIR/scripts/check_why.py --root . --hash shop/payments.py`
2. Run the check, for example the test, and note the result. **Immediately after**, recompute the same hashes. If any hash changed, the result doesn't describe the current code: discard it and rerun the check. Never record hashes taken at a different time from the check.
3. Write one JSON file:

```json
{
  "id": "2026-11-17-payments-no-double-charge-1",
  "type": "validation",
  "claim": "codesplain/features/payments.md#no-double-charge",
  "claim_hash": "<64-hex from step 1>",
  "snapshot": {"shop/payments.py": "<64-hex>", "shop/idempotency.py": "<64-hex>"},
  "check": "tests/test_payments.py::test_duplicate_request",
  "scope": "unit",
  "outcome": "pass",
  "revision": "working-tree",
  "at": "2026-11-17T10:00:00Z",
  "evidence": "pytest: 1 passed"
}
```

`outcome` is one of `pass`, `fail`, `inconclusive` or `unavailable`. `check`, `revision` and `evidence` are required. `scope` is optional and defaults to `default`. A `required_checks` entry `name@scope` only matches events with that same `check` and `scope`, and an entry without `@scope` matches scope `default`.

**A resolution** clears exactly one failure. It doesn't make the claim verified; a new passing check is still needed.

```json
{"id": "2026-11-17-r1", "type": "resolution", "claim": "codesplain/features/payments.md#no-double-charge",
 "resolves": "<id of the fail event>", "reason": "Fixed race in remember(); see journal 2026-11-17-fix-race.md",
 "at": "2026-11-17T12:00:00Z"}
```

## How status is derived

- Only validation events whose `claim_hash` matches the claim's **current** text, kind, deps and required_checks count. Editing a claim makes it `unverified` until it's re-checked.
- Results are grouped by (check, scope). If the claim lists `required_checks`, exactly those count. Otherwise every check with an event counts.
- Statuses are applied in this order:
  1. **contradicted:** any unresolved fail.
  2. **inconclusive.**
  3. **unknown:** a check was unavailable.
  4. **unverified:** a check is missing, or its latest result is a resolved fail.
  5. **stale:** a snapshot no longer matches the current files.
  6. **verified:** all passes are within `--max-age-days` (default 90). Otherwise **unchanged-evidence**.

## Checker reference

```
python3 SKILL_DIR/scripts/check_why.py --root .                    # human-readable
python3 SKILL_DIR/scripts/check_why.py --root . --json             # machine-readable
python3 SKILL_DIR/scripts/check_why.py --root . --strict PATH      # strict refs for a new entry
python3 SKILL_DIR/scripts/check_why.py --root . --hash PATH        # sha256 of a file in the repo
python3 SKILL_DIR/scripts/check_why.py --root . --claim-hash NOTE#ID
```

Exit codes: 0 means no errors (warnings may be present), 1 means errors were found, 2 means a usage or environment error.

**Errors:**
- broken or unsupported frontmatter
- missing required keys
- feature-page references that don't exist
- `--strict` references that don't exist
- hand-written status
- malformed events
- resolutions that target something other than a fail event of the same claim
- possible secrets (reported by rule name only, never by value)

**Warnings:**
- historical references in journals that no longer exist
- stale claims
- unresolved contradictions
- skipped symlinks or special files
