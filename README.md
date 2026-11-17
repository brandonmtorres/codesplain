# why-notes

**Make AI-written code explainable.** `why-notes` is an agent skill that teaches AI coding agents (Claude Code and other agents that load `SKILL.md` skills) to keep a committed `.why/` folder. It records **how each feature works** and **why each change was made**, so anyone (human or agent) can later ask "how does this work?" or "why does this exist?" and get cited, status-labeled answers instead of guesses.

```
.why/
  features/payments.md                      how payments work now
  journal/2026-11-17-configurable-retries.md    why retries became configurable
  events/…json                              which claims were checked, and the result
```

## What you get

- **Question-shaped answers.** "How" answers cover flow, where to change, rules, gotchas and how to verify. "Why" answers cover origin, what breaks if removed, whether it's still needed, and the decision.
- **Claims, not prose.** Every statement is labeled `recorded` or `inferred`. Its status (`verified`, `stale`, `contradicted`, …) is **derived** from recorded checks, never typed by hand.
- **Honest gaps.** With no note, the agent says "No recorded intent" instead of making a reason up.
- **A read-only checker.** It catches references to code that doesn't exist, stale claims, malformed notes and leaked secrets.

## Install (Claude Code)

Copy the skill folder into your skills directory:

```bash
mkdir -p ~/.claude/skills
cp -r skills/why-notes ~/.claude/skills/why-notes
```

Or install it per project: copy `skills/why-notes` into `.claude/skills/why-notes` inside the repository.

Other agents: point them at `skills/why-notes/SKILL.md`. It's plain Markdown plus one optional Python script.

## Use

- Ask your agent: *"How does checkout work?"* or *"Why does `seen_recently` exist? Can I delete it?"*
- After a significant change, the agent adds a journal entry and updates the feature page.
- Run the checker yourself, or in CI:

```bash
python3 skills/why-notes/scripts/check_why.py --root /path/to/your/repo
```

It needs Python 3.9+ and has no dependencies. Exit code 0 means no errors, 1 means errors were found, 2 means a usage error.

## Safety

- **No network access.** No telemetry, no update checks.
- **No automatic execution.** The skill installs no hooks, changes no configuration and starts no background processes.
- **The checker is read-only.** It uses the standard library only, never writes or deletes files, reads only regular files inside the repository you point it at, and **never prints secret values**.
- The skill tells agents never to open `.env` or credential files, and to refer to configuration by variable name only.

Details are in [SECURITY.md](SECURITY.md).

## Development

```bash
python3 -m unittest discover -s tests -v
```

The design and facet catalog are in [docs/PLAN.md](docs/PLAN.md) and [docs/FACETS.md](docs/FACETS.md).

## License

MIT, © why-notes contributors. See [LICENSE](LICENSE).
