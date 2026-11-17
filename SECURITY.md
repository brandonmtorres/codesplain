# Security

## What this project ships

1. `skills/why-notes/SKILL.md` and `skills/why-notes/reference/*.md`: plain-text instructions for AI agents.
2. `skills/why-notes/scripts/check_why.py`: an optional, read-only validator.

## Guarantees for `check_why.py`

- **Standard library only.** It imports only `argparse`, `datetime`, `hashlib`, `json`, `os`, `re`, `stat` and `sys`.
- **No network.** No sockets, HTTP clients, telemetry or update checks.
- **No code execution.** No `subprocess`, shell, `eval`, `exec`, `pickle` or dynamic imports. Note content is parsed with a small restricted parser, and events are parsed with `json` only.
- **Read-only.** It never writes, creates, deletes, renames or changes permissions on files.
- **Contained reads.** Paths taken from notes are rejected if they are absolute, escape the root with `..`, or resolve through a symlink to anything outside the root.
- **Anchored opens.** Files are opened by walking from the repository root one directory at a time, with descriptor-relative, no-follow opens (`O_NOFOLLOW` + `dir_fd`). A directory swapped for a symlink mid-run can't redirect a read. On platforms without `dir_fd` support, only the final path component is opened no-follow.
- **Regular files only.** Before reading, the file type is checked with `lstat`, and again with `fstat` on the opened descriptor (opened with `O_NONBLOCK` and, where available, `O_NOFOLLOW`). FIFOs, devices and sockets are refused without blocking.
- **Resource limits.** Files larger than 2 MB are skipped, and directory listings are capped.
- **Secrets are never printed.** Every output field (locations, messages, claim ids) is redacted before printing. Anything matching a secret rule, or equal to a `.env*` value, becomes `[REDACTED]`. `.env` values are parsed without expansion or execution, handling quoted values and inline ` #` comments.
- **Complete scanning or an error.** Everything under `.why/` is scanned for secrets, recursively, up to the limits. Hitting a limit is reported as an error, never as silent success. If event history is incomplete, no claim is reported as verified.
- **Detection details.** Possible secrets are reported as `file:line` plus a rule name. To detect leaks, the checker reads `.env*` files at the repository root and compares their values in memory. It never prints, stores or sends those values.

These guarantees are enforced by tests in `tests/test_check_why.py`. They include a static audit of the script's syntax tree that fails if forbidden modules or calls appear.

## What the skill instructions ask of agents

- Never open `.env*`, credential files or key stores when writing notes. Refer to configuration by variable **name** only.
- Never write secrets, tokens, personal data, customer data or transcripts into `.why/`.
- Never hand-edit the checker to silence errors.

Instructions can't technically force an agent's behavior. The checker's secret scan is the backstop.

## Out of scope

- Hosting, CI integration and network services. None are included.
- Protecting against a malicious person with write access to your repository.

## Reporting a vulnerability

Please open a private security advisory on the project's repository hosting page (for example, GitHub's "Report a vulnerability" under the Security tab) instead of a public issue. Include steps to reproduce. Please don't include real secrets in reports.
