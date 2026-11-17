# codesplain

**Explain AI-written code: what it does, and why it exists.**

AI agents write code faster than anyone can read it. A month later, nobody can say why a function exists, whether it's safe to delete, or what breaks if it changes. The agent that wrote it is gone, and the reasoning went with it.

codesplain is an agent skill that fixes this. It teaches your coding agent to keep a small, committed `why/` folder: **how each feature works**, and **why each change was made**, written at the moment the reasoning exists. When anyone (human or agent) later asks "how does this work?" or "why is this here?", they get a cited answer that says how sure it is, not a confident guess.

It's small, plain Markdown, works with any model, and ships with an offline, read-only checker. Adapt it however you like.

## Installation (30-second setup)

### 1. Get the skill

<details open>
<summary><strong>Claude Code</strong> (plugin, recommended)</summary>

In Claude Code, run:

```
/plugin install codesplain --marketplace brandonmtorres/codesplain
```

On versions older than 2.1.275, use two steps instead:

```
/plugin marketplace add brandonmtorres/codesplain
/plugin install codesplain@codesplain
```

From a terminal: `claude plugin marketplace add brandonmtorres/codesplain`, then `claude plugin install codesplain@codesplain`.

Update with `/plugin update codesplain`.

</details>

<details>
<summary><strong>Claude Code</strong> (manual copy)</summary>

```bash
git clone https://github.com/brandonmtorres/codesplain.git
mkdir -p ~/.claude/skills
cp -r codesplain/skills/codesplain ~/.claude/skills/codesplain
```

For one project only, copy it to `.claude/skills/codesplain` inside that repository instead.

</details>

<details>
<summary><strong>Codex, Copilot CLI, Gemini CLI</strong></summary>

These agents also read skills from `~/.agents/skills/`:

```bash
git clone https://github.com/brandonmtorres/codesplain.git
mkdir -p ~/.agents/skills
cp -r codesplain/skills/codesplain ~/.agents/skills/codesplain
```

</details>

<details>
<summary><strong>Any other agent</strong></summary>

Point your agent at `skills/codesplain/SKILL.md`. It's plain Markdown plus one optional Python script, with no dependencies.

</details>

### 2. Use your agent normally

There's no setup step. The skill activates when you ask how or why something works, before you change or delete code, and after a significant change. You can also load it explicitly: `/codesplain:codesplain` when installed as a plugin, or `/codesplain` when copied manually.

### 3. Done. Your codebase now remembers why.

## Why This Exists

I built this to fix the failure modes I kept hitting when AI writes most of the code.

### #1: Nobody Can Explain The Code

> Before you remove a fence, find out why it was put up.
>
> Paraphrasing G. K. Chesterton, "Chesterton's fence"

**The Problem.** The *why* behind a change exists for a few minutes, inside the agent session: the request, the plan, the alternatives it rejected. Then the session ends and only the code survives. Code tells you *what*, never *why*.

**The Fix.** After any significant change (a new function, route, job or CLI command; a schema or migration; config, flags or env vars; a new dependency; changed test assertions), the agent writes:

- **A journal entry** in `why/journal/`: the origin, the decision and its alternatives, what breaks if it's removed, and whether it's still needed.
- **An updated feature page** in `why/features/`: the flow, where to change things, the rules, the gotchas, and how to verify.

Each entry is one small file, so there are no merge conflicts, and history is append-only.

### #2: The Agent Guesses "Why", Confidently

**The Problem.** Ask an agent why some code exists and it will give you a plausible story, whether or not anyone ever decided that.

**The Fix.** Every statement in `why/` is a claim labeled **`recorded`** (someone actually said it, or the agent actually did it) or **`inferred`** (deduced from code). When nothing was recorded, the agent says **"No recorded intent."** and labels any guess as a guess.

### #3: Docs Lie As Soon As The Code Changes

**The Problem.** Documentation goes stale silently, and stale docs are worse than none because people trust them.

**The Fix.** Claim status is **calculated by the checker, never typed by hand**. Each claim is tied to the files it depends on and to recorded checks:

| Status | Meaning |
|---|---|
| `verified` | A recent check passed against the current code |
| `unchanged-evidence` | Passed a while ago, and nothing it depends on has changed |
| `stale` | Something it depends on changed after it was checked |
| `unverified` | Never checked |
| `inconclusive` / `unknown` | A check couldn't decide, or wasn't available |
| `contradicted` | A check proved it false. It stays flagged until it's explicitly resolved |

The checker also rejects notes that reference functions or files that don't exist, which catches made-up details at write time.

### #4: Secrets End Up In Docs

**The Problem.** When agents document config, they open `.env` files and copy what they see.

**The Fix.** The skill tells agents to **never open `.env` or credential files** and to refer to configuration by variable *name* only. As a backstop, the checker scans `why/` for secrets and never prints a secret's value.

### Summary

Agents made writing code nearly free. Understanding it is now the bottleneck. codesplain keeps a record of why your code exists, with honest labels for what's known and what's guessed.

## Reference

### Skill

**Model-invoked** (the agent reaches for it automatically when the task fits, or you can call it with `/codesplain:codesplain`, or `/codesplain` if copied manually)

- **[codesplain](./skills/codesplain/SKILL.md)**: Answers "how does X work?" and "why does X exist?" from `why/`, with the status of each claim. Writes journal entries and feature pages after significant changes.

**Ways to use it**

- **"How does checkout work?"**: flow, where to change, rules, gotchas, how to verify, and confidence.
- **"Why does `seen_recently` exist? Can I delete it?"**: origin, what breaks if removed, whether it's still needed, the decision, and confidence.
- **After a significant change**: the agent writes the journal entry and feature page, then runs the checker.

### Format

```
why/
  features/<feature>.md          how a feature works now
  journal/YYYY-MM-DD-<slug>.md   why each significant change was made (append-only)
  events/<id>.json               recorded checks behind each claim's status
```

Templates and the full rules are in [`reference/format.md`](./skills/codesplain/reference/format.md). The facet catalog (the 59 kinds of information an engineer needs) is in [`docs/FACETS.md`](./docs/FACETS.md).

## Safety

- **No network access.** No telemetry, no update checks.
- **No automatic execution.** The skill installs no hooks, changes no configuration and starts no background processes.
- **The checker is read-only.** It never writes or deletes files, reads only regular files inside the repository you point it at, and never prints a secret's value. If it can't guarantee redaction, it hides all details and fails.
- **The secret scan is a backstop, not a guarantee.** The main protection is that agents never copy secrets into notes in the first place.

Details are in [SECURITY.md](SECURITY.md).

## Development

```bash
python3 -m unittest discover -s tests -v
```

The design is in [`docs/PLAN.md`](./docs/PLAN.md).

## License

MIT. See [LICENSE](LICENSE).
