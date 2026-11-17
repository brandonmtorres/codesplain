#!/usr/bin/env python3
"""check_why.py - read-only validator for a repository's `codesplain/` folder.

Safety properties (see SECURITY.md):
  * Standard library only. No network, no subprocess, no eval/exec, no pickle.
  * Never writes, deletes, renames or chmods anything.
  * Reads only regular files inside the chosen repository root.
  * Never prints the value of a detected secret or of any `.env*` entry.

Usage:
  python3 check_why.py [--root PATH] [--json] [--strict PATH ...] [--max-age-days N]
  python3 check_why.py [--root PATH] --hash PATH
  python3 check_why.py [--root PATH] --claim-hash NOTE_PATH#CLAIM_ID

Exit codes: 0 = no errors (warnings allowed), 1 = errors found, 2 = usage/environment error.
"""

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import stat
import sys

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 5000
MAX_ENV_FILES = 100
CLOCK_SKEW = _dt.timedelta(hours=24)
MAX_LIST_ITEMS = 2000
MAX_REF_CHECKS = 20000
MAX_SNAPSHOT_ENTRIES = 200
TEXT_CACHE_SIZE = 64

CLAIM_STATUSES = (
    "verified", "contradicted", "inconclusive", "unchanged-evidence",
    "stale", "unverified", "unknown",
)
OUTCOMES = ("pass", "fail", "inconclusive", "unavailable")
LIFECYCLES = ("active", "superseded")
KINDS = ("recorded", "inferred")

KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
CLAIM_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
FACET_RE = re.compile(r"^[A-K][0-9]{1,2}[a-z]?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
REMOVED_RE = re.compile(r"^[^@#\s]+(#[A-Za-z_][A-Za-z0-9_.]*)?@[0-9A-Za-z._/-]+$")

# Secret detectors. Matches are reported by rule name only, never by value.
_PK = "-----BEGIN" + r" [A-Z ]*PRIVATE KEY-----"
# Whole block, header to footer (or to end of text when unterminated), for collection and redaction.
PRIVATE_KEY_BLOCK_RE = re.compile("-----BEGIN" + r"[ A-Z]*PRIVATE KEY-----.*?(?:-----END[ A-Z]*PRIVATE KEY-----|\Z)",
                                  re.DOTALL)
SECRET_RULES = [
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("github-fine-grained-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe-key", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("sk-style-api-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("private-key-block", re.compile(_PK)),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
]

# Literal credential assignments: `password = value`, `api_key: value`. Any non-empty literal value counts,
# except documented placeholders and references to environment variable NAMES (UPPER_SNAKE_CASE).
CRED_RE = re.compile(
    r"(?i)\b(?:password|passwd|pwd|secret|client[_-]?secret|api[_-]?key|apikey|access[_-]?key|auth[_-]?token|"
    r"private[_-]?key)"
    r"\b[\"']?[ \t]*(?:=|:(?!:))[ \t]*"
    r"(?:\"((?:[^\"\\\n]|\\.)*)\"|'((?:[^'\\\n]|\\.)*)'|([^\s'\"`]+))")
# Placeholders exempt in any form (quoted or not).
_PLACEHOLDER_RE = re.compile(
    r"^(?:<[^>]*>|\$\{[A-Za-z_][A-Za-z0-9_]*\}|\{\{[^}]*\}\}|\[REDACTED\]|\*+|x+|X+|\.\.\.|"
    r"null|none|nil|redacted|placeholder|example|changeme|value)$")
# References to environment variable NAMES, exempt only when unquoted: $VAR, %VAR%, UPPER_SNAKE (with an underscore).
_VARREF_RE = re.compile(r"^(?:\$[A-Za-z_][A-Za-z0-9_]*|%[A-Za-z_][A-Za-z0-9_]*%|[A-Z][A-Z0-9]*_[A-Z0-9_]+)$")


def _credential_values(line):
    for m in CRED_RE.finditer(line):
        quoted = m.group(1) is not None or m.group(2) is not None
        if quoted:
            value = (m.group(1) if m.group(1) is not None else m.group(2)).strip()
        else:
            value = m.group(3).rstrip(".,;)")
        if not value or set(value) <= {"\\"}:
            continue
        if _PLACEHOLDER_RE.match(value):
            continue
        if not quoted and _VARREF_RE.match(value):
            continue
        yield value


class ReadError(Exception):
    """A file could not be read safely (reason is safe to print)."""


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.claims = []
        self.env_complete = True

    def error(self, where, msg):
        self.errors.append({"where": where, "message": msg})

    def warn(self, where, msg):
        self.warnings.append({"where": where, "message": msg})


# --------------------------------------------------------------------------- paths


def _within(root, path):
    try:
        return os.path.commonpath([root, path]) == root
    except ValueError:
        return False


def resolve_in_root(root, rel):
    """Return the real path for a repo-relative path, or raise ReadError."""
    if not isinstance(rel, str) or not rel or "\x00" in rel:
        raise ReadError("empty or invalid path")
    if os.path.isabs(rel) or rel.startswith("~"):
        raise ReadError("absolute paths are not allowed")
    try:
        rel.encode("utf-8")
    except UnicodeEncodeError:
        raise ReadError("invalid path encoding")
    norm = os.path.normpath(rel)
    if norm == ".." or norm.startswith(".." + os.sep) or norm.startswith("../"):
        raise ReadError("path escapes the repository root")
    try:
        real = os.path.realpath(os.path.join(root, norm))
    except (ValueError, OSError, UnicodeError):
        raise ReadError("invalid path")
    if not _within(root, real):
        raise ReadError("path resolves outside the repository root")
    return real


def _open_anchored(root, real, final_flags):
    """Open `real` (already resolved inside root) by walking from root with no-follow, descriptor-relative
    opens, so a directory swapped for a symlink after resolution cannot redirect the read."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    o_dir = getattr(os, "O_DIRECTORY", 0)
    rel = os.path.relpath(real, root)
    parts = [] if rel == "." else rel.split(os.sep)
    if not parts:
        raise ReadError("not a regular file")
    anchored = bool(nofollow and o_dir and os.open in os.supports_dir_fd)
    if not anchored:  # platform fallback: final-component no-follow only (documented in SECURITY.md)
        return os.open(real, final_flags | nofollow)
    fd = os.open(root, os.O_RDONLY | o_dir)
    try:
        for comp in parts[:-1]:
            nxt = os.open(comp, os.O_RDONLY | o_dir | nofollow, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return os.open(parts[-1], final_flags | nofollow, dir_fd=fd)
    finally:
        os.close(fd)


def safe_read(root, rel):
    """Read a regular file inside root without following it outside root or blocking."""
    real = resolve_in_root(root, rel)
    try:
        st = os.lstat(real)
    except FileNotFoundError:
        raise ReadError("file not found")
    except OSError:
        raise ReadError("file not accessible")
    if not stat.S_ISREG(st.st_mode):
        raise ReadError("not a regular file")
    if st.st_size > MAX_FILE_BYTES:
        raise ReadError("file larger than size limit; skipped")
    try:
        fd = _open_anchored(root, real, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        raise ReadError("file could not be opened safely")
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode):
            raise ReadError("not a regular file")
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                raise ReadError("file larger than size limit; skipped")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def safe_read_text(root, rel):
    try:
        return safe_read(root, rel).decode("utf-8")
    except UnicodeDecodeError:
        raise ReadError("file is not valid UTF-8")


def file_sha256(root, rel):
    return hashlib.sha256(safe_read(root, rel)).hexdigest()


def cached_sha256(root, rel):
    if rel not in _RUN.hash_cache:
        _RUN.ref_checks += 1
        if _RUN.ref_checks > MAX_REF_CHECKS:
            _RUN.exhausted = True
            return None
        try:
            _RUN.hash_cache[rel] = file_sha256(root, rel)
        except ReadError:
            _RUN.hash_cache[rel] = None
    return _RUN.hash_cache[rel]


def _bounded_scandir(real_dir, limit):
    """Return (entries, truncated) reading at most limit+1 entries before sorting."""
    entries = []
    truncated = False
    with os.scandir(real_dir) as it:
        for entry in it:
            if len(entries) >= limit:
                truncated = True
                break
            entries.append(entry)
    entries.sort(key=lambda e: e.name)
    return entries, truncated


def list_note_dir(root, rel_dir, suffix, report):
    """List note/event files in a format directory. Returns (files, complete).
    Wrong extensions, nested directories, symlinks and special files are errors."""
    out = []
    try:
        real_dir = resolve_in_root(root, rel_dir)
    except ReadError as e:
        report.error(rel_dir, str(e))
        return out, False
    if os.path.islink(os.path.join(root, rel_dir)):
        report.error(rel_dir, "format directory must not be a symlink")
        return out, False
    if not os.path.lexists(os.path.join(root, rel_dir)):
        return out, True  # optional directory, simply absent
    if not os.path.isdir(real_dir):
        report.error(rel_dir, "must be a directory")
        return out, False
    try:
        entries, truncated = _bounded_scandir(real_dir, MAX_FILES)
    except OSError:
        report.error(rel_dir, "directory not readable")
        return out, False
    rejected = False
    for entry in entries:
        rel = rel_dir + "/" + entry.name
        if entry.is_symlink():
            report.error(rel, "symlinks are not supported in codesplain/")
            rejected = True
        elif entry.is_dir(follow_symlinks=False):
            report.error(rel, "nested directories are not supported here")
            rejected = True
        elif not entry.is_file(follow_symlinks=False):
            report.error(rel, "not a regular file")
            rejected = True
        elif not entry.name.endswith(suffix):
            report.error(rel, "unsupported file type here (expected %s)" % suffix)
            rejected = True
        else:
            out.append(rel)
    if truncated:
        report.error(rel_dir, "more than %d entries; results are incomplete" % MAX_FILES)
    return out, not (truncated or rejected)


def walk_why_files(root, report):
    """All regular files under codesplain/ (recursive, bounded). Returns (files, complete)."""
    out = []
    complete = True
    stack = ["codesplain"]
    seen = 0
    while stack:
        rel_dir = stack.pop()
        if rel_dir.count("/") > 8:
            report.error(rel_dir, "directory nesting too deep; secret scan incomplete")
            complete = False
            continue
        try:
            entries, truncated = _bounded_scandir(resolve_in_root(root, rel_dir), MAX_FILES)
        except (OSError, ReadError):
            report.error(rel_dir, "directory not readable; secret scan incomplete")
            complete = False
            continue
        if truncated:
            complete = False
        for entry in entries:
            seen += 1
            if seen > MAX_FILES:
                complete = False
                break
            rel = rel_dir + "/" + entry.name
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                stack.append(rel)
            elif entry.is_file(follow_symlinks=False):
                out.append(rel)
            else:  # never read, so it cannot leak into output; still not allowed in codesplain/
                report.error(rel, "not a regular file")
    if not complete:
        report.error("codesplain", "secret scan incomplete (file or depth limit reached)")
    return sorted(out), complete


# --------------------------------------------------------------------- frontmatter


class ParseError(Exception):
    def __init__(self, line, msg):
        Exception.__init__(self, msg)
        self.line = line
        self.msg = msg


_UNSUPPORTED_SCALAR_START = ("|", ">", "{", "[", "&", "*", "!", "%", "@", "`")


def _scalar(raw, lineno=0):
    v = raw.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    if v.startswith(_UNSUPPORTED_SCALAR_START):
        raise ParseError(lineno, "unsupported value syntax (block, flow collection, anchor or tag); quote the value")
    return v


def parse_frontmatter(text):
    """Parse the restricted frontmatter subset. Returns (data, body_start_line)."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ParseError(1, "missing frontmatter: file must start with '---'")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise ParseError(1, "frontmatter is not closed with '---'")
    data = {}
    list_kind = {}  # key -> "scalar" | "mapping"
    cur_key = None  # key whose list is being filled
    cur_item = None  # current mapping item
    item_indent = None
    field_indent = None
    for idx in range(1, end):
        lineno = idx + 1
        line = lines[idx].rstrip("\r")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise ParseError(lineno, "tabs are not allowed for indentation")
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            if ":" not in line:
                raise ParseError(lineno, "expected 'key: value'")
            key, _, value = line.partition(":")
            key = key.strip()
            if not KEY_RE.match(key):
                raise ParseError(lineno, "invalid key")
            if key in data:
                raise ParseError(lineno, "duplicate key")
            cur_item = None
            if value.strip():
                data[key] = _scalar(value, lineno)
                cur_key = None
            else:
                data[key] = []
                cur_key = key
            continue
        if cur_key is None:
            raise ParseError(lineno, "unexpected indented line")
        if stripped.startswith("- ") or stripped == "-":
            content = stripped[1:].strip()
            lst = data[cur_key]
            if len(lst) >= MAX_LIST_ITEMS:
                raise ParseError(lineno, "too many list items (limit %d)" % MAX_LIST_ITEMS)
            item_indent = indent
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):(\s.*|)$", content)
            kind = "mapping" if (m and cur_key == "claims") else "scalar"
            if list_kind.setdefault(cur_key, kind) != kind:
                raise ParseError(lineno, "cannot mix scalars and mappings in a list")
            if kind == "mapping":
                cur_item = {m.group(1): _scalar(m.group(2), lineno)}
                field_indent = None
                lst.append(cur_item)
            else:
                if not content:
                    raise ParseError(lineno, "empty list item")
                cur_item = None
                lst.append(_scalar(content, lineno))
            continue
        if cur_item is not None and indent > (item_indent or 0):
            if field_indent is None:
                field_indent = indent
            if indent != field_indent:
                raise ParseError(lineno, "claim fields must all use the same indentation (no multi-line values)")
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):(\s.*|)$", stripped)
            if not m:
                raise ParseError(lineno, "expected 'key: value' inside a claim")
            k = m.group(1)
            if k in cur_item:
                raise ParseError(lineno, "duplicate claim key")
            cur_item[k] = _scalar(m.group(2), lineno)
            continue
        raise ParseError(lineno, "unsupported syntax (see reference/format.md)")
    return data, end + 2


def _csv(value):
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


# -------------------------------------------------------------------------- notes


class Note:
    def __init__(self, rel, kind, data):
        self.rel = rel
        self.kind = kind  # "feature" | "journal"
        self.data = data
        self.claims = []  # list of dicts (validated)


def claim_hash(claim):
    canonical = {
        "id": claim.get("id", ""),
        "kind": claim.get("kind", ""),
        "text": claim.get("text", ""),
        "deps": _csv(claim.get("deps", "")),
        "required_checks": _csv(claim.get("required_checks", "")),
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class _Budget:
    """Per-run caches and work budget for reference checks and hashing."""

    def __init__(self):
        self.ref_results = {}
        self.text_cache = {}
        self.hash_cache = {}
        self.ref_checks = 0
        self.exhausted = False
        self.root = "/"


_RUN = _Budget()


def _ref_exists(root, ref):
    """Cached, budgeted wrapper. Returns (ok, reason)."""
    if ref in _RUN.ref_results:
        return _RUN.ref_results[ref]
    _RUN.ref_checks += 1
    if _RUN.ref_checks > MAX_REF_CHECKS:
        _RUN.exhausted = True
        return False, "reference-check budget exhausted"
    result = _ref_exists_uncached(root, ref)
    _RUN.ref_results[ref] = result
    return result


def _ref_exists_uncached(root, ref):
    """ref is 'path' or 'path#symbol'. Returns (ok, reason)."""
    path, _, symbol = ref.partition("#")
    text = _RUN.text_cache.get(path)
    if text is None:
        try:
            data = safe_read(root, path)
        except ReadError as e:
            return False, str(e)
        if symbol:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                return False, "file is not valid UTF-8 text; cannot check symbol"
            if len(_RUN.text_cache) >= TEXT_CACHE_SIZE:
                _RUN.text_cache.pop(next(iter(_RUN.text_cache)))
            _RUN.text_cache[path] = text
    if "#" in ref and not symbol:
        return False, "empty symbol name after '#'"
    if symbol:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", symbol):
            return False, "symbol must be a single identifier (qualified names like A.b are not supported)"
        name = symbol
        if not re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", text):
            return False, "symbol not found in file (whole-word search)"
    return True, ""


def _check_refs(root, note, refs, strict, report, label):
    for ref in refs:
        if not isinstance(ref, str):
            report.error(note.rel, "%s entries must be strings" % label)
            continue
        path = ref.partition("#")[0]
        try:
            resolve_in_root(root, path)
        except ReadError as e:
            report.error(note.rel, "%s '%s': %s" % (label, ref, e))
            continue
        ok, reason = _ref_exists(root, ref)
        if ok:
            continue
        if note.kind == "feature" or strict:
            report.error(note.rel, "%s '%s' does not exist: %s" % (label, ref, reason))
        else:
            report.warn(note.rel, "historical reference no longer present: '%s' (%s)" % (ref, reason))


def validate_note(root, note, strict, report):
    d = note.data
    req = ("feature", "files", "claims") if note.kind == "feature" else (
        "title", "date", "change_type", "files", "lifecycle", "claims")
    for key in req:
        if key not in d:
            report.error(note.rel, "missing required key '%s'" % key)
        elif key in ("files", "claims"):
            if not isinstance(d[key], list):
                report.error(note.rel, "'%s' must be a list" % key)
        elif not isinstance(d[key], str) or not d[key].strip():
            report.error(note.rel, "'%s' must be a non-empty value" % key)
    for key in ("files", "symbols", "removed", "claims"):
        if key in d and not isinstance(d[key], list):
            report.error(note.rel, "'%s' must be a list" % key)
    if note.kind == "journal":
        date = d.get("date")
        if isinstance(date, str):
            ok = bool(DATE_RE.match(date))
            if ok:
                try:
                    _dt.date.fromisoformat(date)
                except ValueError:
                    ok = False
            if not ok:
                report.error(note.rel, "date must be a valid YYYY-MM-DD")
        lc = d.get("lifecycle")
        if isinstance(lc, str):
            if lc not in LIFECYCLES:
                report.error(note.rel, "lifecycle must be one of: %s" % ", ".join(LIFECYCLES))
            elif lc == "superseded":
                sb = d.get("superseded_by")
                if not isinstance(sb, str) or not sb:
                    report.error(note.rel, "superseded entries require 'superseded_by'")
                else:
                    target = "codesplain/journal/" + os.path.basename(sb)
                    try:
                        safe_read(root, target)
                    except ReadError:
                        report.error(note.rel, "superseded_by points to a missing journal entry")
    if "status" in d:
        report.error(note.rel, "do not hand-write 'status'; claim status is derived from codesplain/events/")
    if isinstance(d.get("files"), list):
        _check_refs(root, note, d["files"], strict, report, "files")
    if isinstance(d.get("symbols"), list):
        bad = [s for s in d["symbols"] if not isinstance(s, str) or "#" not in s or not s.partition("#")[2]]
        for _ in bad:
            report.error(note.rel, "symbols entries must look like 'path#name' with a non-empty name")
        _check_refs(root, note, [s for s in d["symbols"] if s not in bad], strict, report, "symbols")
    if isinstance(d.get("removed"), list):
        for r in d["removed"]:
            if not isinstance(r, str) or not REMOVED_RE.match(r):
                report.error(note.rel, "removed entries must look like 'path@commit' or 'path#symbol@commit'")
    claims = d.get("claims")
    if isinstance(claims, list):
        if not claims:
            report.warn(note.rel, "no claims recorded")
        seen = set()
        for c in claims:
            if not isinstance(c, dict):
                report.error(note.rel, "claims must be mappings starting with '- id: ...'")
                continue
            cid = c.get("id", "")
            where = "%s#%s" % (note.rel, cid)
            if not CLAIM_ID_RE.match(cid):
                report.error(note.rel, "claim id missing or invalid")
                continue
            if cid in seen:
                report.error(note.rel, "duplicate claim id '%s'" % cid)
                continue
            seen.add(cid)
            valid = True
            if c.get("kind") not in KINDS:
                report.error(where, "kind must be 'recorded' or 'inferred'")
                valid = False
            if not c.get("text"):
                report.error(where, "claim text is required")
                valid = False
            if "status" in c:
                report.error(where, "do not hand-write 'status'; it is derived from events")
                valid = False
            facet = c.get("facet")
            if facet and not FACET_RE.match(facet):
                report.error(where, "facet must be a catalog id like 'E4'")
            for k in c:
                if k not in ("id", "kind", "text", "facet", "deps", "required_checks"):
                    report.warn(where, "unknown claim key")
            deps = _csv(c.get("deps", ""))
            fake = Note(note.rel, note.kind, {})
            _check_refs(root, fake, deps, strict, report, "deps of %s" % cid)
            if valid:
                note.claims.append(c)


# ------------------------------------------------------------------------- events


def _parse_time(value):
    if not isinstance(value, str) or not value:
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        t = _dt.datetime.fromisoformat(v)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=_dt.timezone.utc)
    return t


def _reject_duplicate_keys(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise ValueError("duplicate JSON key")
        obj[k] = v
    return obj


def _strict_json(text):
    return json.loads(text, object_pairs_hook=_reject_duplicate_keys)


def _nonempty_str(v):
    return isinstance(v, str) and bool(v.strip())


def _validate_event(ev, claims_by_gid, now):
    """Return an error message, or None if the event is well-formed."""
    if not isinstance(ev, dict):
        return "event must be a JSON object"
    if not _nonempty_str(ev.get("id")):
        return "event 'id' must be a non-empty string"
    if not _nonempty_str(ev.get("claim")):
        return "event 'claim' must be a non-empty string"
    if ev["claim"] not in claims_by_gid:
        return "event references unknown claim"
    t = _parse_time(ev.get("at"))
    if t is None:
        return "'at' must be an ISO-8601 timestamp"
    if t > now + CLOCK_SKEW:
        return "'at' is in the future (more than 24h ahead of the current time)"
    etype = ev.get("type")
    if etype == "validation":
        if ev.get("outcome") not in OUTCOMES:
            return "outcome must be one of: %s" % ", ".join(OUTCOMES)
        for k in ("check", "revision", "evidence"):
            if not _nonempty_str(ev.get(k)):
                return "validation events require a non-empty string '%s'" % k
        if "scope" in ev and not _nonempty_str(ev.get("scope")):
            return "'scope' must be a non-empty string when present"
        if not isinstance(ev.get("claim_hash"), str) or not HEX64_RE.match(ev["claim_hash"]):
            return "validation events require a 64-hex 'claim_hash'"
        snap = ev.get("snapshot")
        if not isinstance(snap, dict) or not all(
                isinstance(k, str) and isinstance(v, str) and HEX64_RE.match(v) for k, v in snap.items()):
            return "'snapshot' must be an object mapping file paths to 64-hex sha256 values"
        if len(snap) > MAX_SNAPSHOT_ENTRIES:
            return "'snapshot' has too many entries (limit %d)" % MAX_SNAPSHOT_ENTRIES
        for k in snap:
            try:
                resolve_in_root(_RUN.root, k)
            except ReadError:
                return "'snapshot' contains an invalid or out-of-root path"
        return None
    if etype == "resolution":
        if not _nonempty_str(ev.get("resolves")) or not _nonempty_str(ev.get("reason")):
            return "resolution events require non-empty 'resolves' and 'reason'"
        return None
    return "type must be 'validation' or 'resolution'"


def load_events(root, files, claims_by_gid, report, now):
    """Returns (events, incomplete_claims, all_incomplete). History that could not be loaded marks the
    affected claim (or every claim, when the claim cannot be identified) as incomplete."""
    events = {}
    incomplete = set()
    all_incomplete = False
    for rel in files:
        try:
            ev = _strict_json(safe_read_text(root, rel))
        except ReadError as e:
            report.error(rel, str(e))
            all_incomplete = True
            continue
        except (ValueError, RecursionError):
            report.error(rel, "invalid JSON (malformed, too deeply nested, or duplicate keys)")
            all_incomplete = True
            continue
        try:
            problem = _validate_event(ev, claims_by_gid, now)
        except Exception:  # defensive: malformed input must never abort the run
            problem = "malformed event"
        if problem:
            report.error(rel, problem)
            gid = ev.get("claim") if isinstance(ev, dict) else None
            if isinstance(gid, str) and gid in claims_by_gid:
                incomplete.add(gid)
            elif problem != "event references unknown claim":
                all_incomplete = True
            continue
        if ev["id"] in events:
            report.error(rel, "duplicate event id")
            incomplete.add(ev["claim"])
            incomplete.add(events[ev["id"]]["claim"])
            continue
        ev = dict(ev)
        ev["_time"] = _parse_time(ev["at"])
        ev["_rel"] = rel
        if ev["type"] == "validation":
            ev["scope"] = ev.get("scope") or "default"
        events[ev["id"]] = ev
    for eid, ev in list(events.items()):
        if ev["type"] != "resolution":
            continue
        target = events.get(ev["resolves"])
        if target is None or target["type"] != "validation" or target.get("outcome") != "fail":
            report.error(ev["_rel"], "resolution must target an existing 'fail' validation event")
            del events[eid]
        elif target["claim"] != ev["claim"]:
            report.error(ev["_rel"], "resolution targets an event of a different claim")
            del events[eid]
    return events, incomplete, all_incomplete


def derive_status(root, claim, current_hash, events, now, max_age_days):
    """Return (status, [event ids that determined it])."""
    applicable = [e for e in events if e["type"] == "validation" and e.get("claim_hash") == current_hash]
    app_ids = set(e["id"] for e in applicable)
    resolved = set(e["resolves"] for e in events if e["type"] == "resolution" and e["resolves"] in app_ids)
    unresolved_fails = [e for e in applicable if e["outcome"] == "fail" and e["id"] not in resolved]
    resolution_ids = [e["id"] for e in events if e["type"] == "resolution" and e["resolves"] in app_ids]
    if unresolved_fails:
        return "contradicted", sorted(set([e["id"] for e in unresolved_fails] + resolution_ids + sorted(resolved)))
    required = []
    for item in _csv(claim.get("required_checks", "")):
        check, _, scope = item.partition("@")
        required.append((check, scope or "default"))
    keys = required or sorted(set((e["check"], e["scope"]) for e in applicable))
    if not keys:
        return "unverified", []
    latest = {}  # (check, scope) -> list of events sharing the latest timestamp
    for e in applicable:
        k = (e["check"], e["scope"])
        cur = latest.get(k)
        if cur is None or e["_time"] > cur[0]["_time"]:
            latest[k] = [e]
        elif e["_time"] == cur[0]["_time"]:
            cur.append(e)
    states = {}
    used_ids = []
    for k in keys:
        group = latest.get(k)
        if not group:
            states[k] = ("missing", None)
            continue
        used_ids.extend(e["id"] for e in group)
        outcomes = set(e["outcome"] for e in group)
        if len(outcomes) != 1 or "fail" in outcomes:
            # Ambiguous same-time results, or a latest fail (necessarily resolved): no usable evidence.
            states[k] = ("missing", group[0])
        else:
            states[k] = (group[0]["outcome"], group)
    used = sorted(set(used_ids + resolution_ids + list(resolved)))
    outs = [st for st, _ in states.values()]
    if "inconclusive" in outs:
        return "inconclusive", used
    if "unavailable" in outs:
        return "unknown", used
    if "missing" in outs:
        return "unverified", used
    deps_files = set(d.partition("#")[0] for d in _csv(claim.get("deps", "")))
    oldest = None
    for _, group in states.values():
        for e in group:  # every tied pass must match current content; filenames never decide
            snap = e.get("snapshot", {})
            if not deps_files.issubset(set(snap.keys())):
                return "stale", used
            for path, digest in snap.items():
                if cached_sha256(root, path) != digest:
                    return "stale", used
            if oldest is None or e["_time"] < oldest:
                oldest = e["_time"]
    if oldest is not None and (now - oldest) > _dt.timedelta(days=max_age_days):
        return "unchanged-evidence", used
    if oldest is not None and oldest > now + CLOCK_SKEW:  # defensive; future events are rejected earlier
        return "unknown", used
    return "verified", used


# ------------------------------------------------------------------------ secrets


_DQ_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "$": "$"}


def parse_env_value(raw):
    """Parse a dotenv value without expansion or execution. Returns (value, ok).
    Double quotes support \\n \\r \\t \\" \\\\ \\$ escapes; single quotes are literal; unquoted values end at
    ' #'. Unterminated quotes or unknown escapes return ok=False (collection is then incomplete)."""
    v = raw.strip()
    if v[:1] == "'":
        close = v.find("'", 1)
        if close == -1:
            return v[1:], False
        return v[1:close], True
    if v[:1] == '"':
        out = []
        i = 1
        while i < len(v):
            ch = v[i]
            if ch == "\\":
                if i + 1 >= len(v) or v[i + 1] not in _DQ_ESCAPES:
                    return "".join(out), False
                out.append(_DQ_ESCAPES[v[i + 1]])
                i += 2
                continue
            if ch == '"':
                return "".join(out), True
            out.append(ch)
            i += 1
        return "".join(out), False
    hash_at = v.find(" #")
    if hash_at != -1:
        v = v[:hash_at]
    return v.strip(), True


def load_env_values(root, report):
    """Returns (values, complete). Incomplete collection is reported as an error."""
    values = []
    complete = True
    try:
        entries = []
        with os.scandir(root) as it:  # stream the root listing; only .env* names are kept
            for entry in it:
                if entry.name.startswith(".env"):
                    entries.append(entry)
                    if len(entries) > MAX_ENV_FILES:
                        complete = False
                        break
    except OSError:
        report.error(".env*", "repository root not readable; .env leak detection incomplete")
        return values, False
    for entry in sorted(entries, key=lambda e: e.name)[:MAX_ENV_FILES]:
        if entry.is_dir(follow_symlinks=False):
            continue
        try:
            text = safe_read_text(root, entry.name)
        except ReadError:
            complete = False
            continue
        for line in text.splitlines():
            st = line.strip()
            if st.startswith("export "):
                st = st[len("export "):].lstrip()
            if not st or st.startswith("#") or "=" not in st:
                continue
            _, _, raw = st.partition("=")
            val, ok = parse_env_value(raw)
            if not ok:
                complete = False
            if len(val) >= 8:
                values.append(val)
    if not complete:
        report.error(".env*", "could not read every .env* file; leak detection and redaction incomplete")
    return values, complete


def redact(text, env_values):
    """Replace anything secret-shaped or equal to a .env value with [REDACTED]."""
    if not isinstance(text, str):
        return text
    text = PRIVATE_KEY_BLOCK_RE.sub("[REDACTED]", text)
    for val in sorted(env_values, key=len, reverse=True):
        text = text.replace(val, "[REDACTED]")
    for _, rx in SECRET_RULES:
        text = rx.sub("[REDACTED]", text)
    for value in sorted(set(_credential_values(text)), key=len, reverse=True):
        text = text.replace(value, "[REDACTED]")
    return text


def _redact_deep(obj, env_values):
    if isinstance(obj, str):
        return redact(obj, env_values)
    if isinstance(obj, list):
        return [_redact_deep(x, env_values) for x in obj]
    if isinstance(obj, dict):
        return {k: _redact_deep(v, env_values) for k, v in obj.items()}
    return obj


def secret_values_in(text, env_values=()):
    """Return the set of secret-looking substrings found (kept private, used only for redaction)."""
    found = set()
    for m in PRIVATE_KEY_BLOCK_RE.finditer(text):
        found.add(m.group(0))
        for line in m.group(0).splitlines():
            if line.strip():
                found.add(line.strip())
    for _, rx in SECRET_RULES:
        for m in rx.finditer(text):
            found.add(m.group(0))
    for line in text.splitlines():
        found.update(_credential_values(line))
    for val in env_values:
        if val in text:
            found.add(val)
    return found


def scan_text_for_secrets(text, env_values=()):
    """Yield (line_number, rule_name). Never yields matched values."""
    for i, line in enumerate(text.splitlines(), 1):
        for name, rx in SECRET_RULES:
            if rx.search(line):
                yield i, name
        for _ in _credential_values(line):
            yield i, "credential-assignment"
            break
    for val in env_values:  # whole-text search so multi-line values are caught too
        idx = text.find(val)
        if idx != -1:
            yield text.count("\n", 0, idx) + 1, "value-from-.env-file"


def scan_why_for_secrets(root, files, env_values, report):
    """Scan file names and contents. Returns (detected values for output redaction, complete)."""
    detected = set()
    complete = True
    for rel in files:
        if list(scan_text_for_secrets(rel, env_values)):
            detected.update(secret_values_in(rel, env_values))
            report.error(rel, "possible secret in file name; rename the file")
        try:
            text = safe_read(root, rel).decode("utf-8", errors="replace")
        except ReadError as e:
            report.error(rel, "could not be scanned for secrets: %s" % e)
            complete = False
            continue
        detected.update(secret_values_in(text, env_values))
        for lineno, rule in scan_text_for_secrets(text, env_values):
            report.error("%s:%d" % (rel, lineno), "possible secret (%s); remove it, never commit secret values" % rule)
        if rel.endswith(".json"):
            strings = _json_strings(text)
            if strings is None:
                report.error(rel, "not valid JSON, so escaped content could not be scanned for secrets")
                complete = False
                strings = []
            for value in strings:
                hits = sorted(set(rule for _, rule in scan_text_for_secrets(value, env_values)))
                if hits:
                    detected.update(secret_values_in(value, env_values))
                    report.error(rel, "possible secret in a JSON value (%s)" % ", ".join(hits))
    return detected, complete


class _Pairs(list):
    """A JSON object kept as its full list of (key, value) members, duplicates included."""


def _json_strings(text):
    """Every decoded string in a JSON document, duplicates included, plus synthetic `key="value"` strings for
    each string member so credential keys and their values are scanned together. Returns None when the text
    is not decodable JSON (the caller then treats scanning as incomplete)."""
    try:
        doc = json.loads(text, object_pairs_hook=_Pairs)
    except (ValueError, RecursionError):
        return None
    out = []  # bounded by the 2 MB file-size limit
    stack = [doc]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, _Pairs):
            for k, v in item:
                out.append(k)
                if isinstance(v, str):
                    out.append('%s="%s"' % (k, v.replace("\\", "\\\\").replace('"', '\\"')))
                stack.append(v)
        elif isinstance(item, list):
            stack.extend(item)
    return out


# --------------------------------------------------------------------------- main


def run_check(root, strict_paths, max_age_days, now=None):
    global _RUN
    _RUN = _Budget()
    _RUN.root = root
    report = Report()
    now = now or _dt.datetime.now(_dt.timezone.utc)
    why = os.path.join(root, "codesplain")
    if os.path.islink(why) or not os.path.isdir(why):
        report.error("codesplain", "no codesplain/ directory found at the repository root")
        return report
    strict = set()
    for p in strict_paths:
        norm = os.path.normpath(p).replace(os.sep, "/")
        if norm.startswith("./"):
            norm = norm[2:]
        strict.add(norm)
    notes = []
    note_files = []
    for kind, sub in (("feature", "codesplain/features"), ("journal", "codesplain/journal")):
        files, _ = list_note_dir(root, sub, ".md", report)
        for rel in files:
            note_files.append(rel)
            try:
                text = safe_read_text(root, rel)
            except ReadError as e:
                report.error(rel, str(e))
                continue
            try:
                data, _ = parse_frontmatter(text)
            except ParseError as e:
                report.error("%s:%d" % (rel, e.line), e.msg)
                continue
            note = Note(rel, kind, data)
            validate_note(root, note, rel in strict, report)
            notes.append(note)
    for s in strict:
        if s not in note_files:
            report.error(s, "--strict path is not a note file under codesplain/features or codesplain/journal")
    claims_by_gid = {}
    for note in notes:
        for c in note.claims:
            claims_by_gid["%s#%s" % (note.rel, c["id"])] = (note, c)
    event_files, events_complete = list_note_dir(root, "codesplain/events", ".json", report)
    events, incomplete_claims, all_incomplete = load_events(root, event_files, claims_by_gid, report, now)
    by_claim = {}
    for ev in events.values():
        by_claim.setdefault(ev["claim"], []).append(ev)
    for gid in sorted(claims_by_gid):
        note, c = claims_by_gid[gid]
        h = claim_hash(c)
        status, used = derive_status(root, c, h, by_claim.get(gid, []), now, max_age_days)
        history_gap = (not events_complete) or all_incomplete or gid in incomplete_claims
        if history_gap and status in ("verified", "unchanged-evidence", "unverified", "stale"):
            status = "unknown"  # some event history was not loaded; never claim success
        report.claims.append({"claim": gid, "kind": c.get("kind"), "status": status, "events": used})
        if status == "contradicted":
            report.warn(gid, "unresolved contradiction (events: %s)" % ", ".join(used))
        elif status == "stale":
            report.warn(gid, "stale: a dependency changed since it was checked")
    if _RUN.exhausted:
        report.error("codesplain", "file-read budget exhausted; validation incomplete")
        for c in report.claims:
            if c["status"] in ("verified", "unchanged-evidence"):
                c["status"] = "unknown"
    why_files, scan_complete = walk_why_files(root, report)
    env_values, env_complete = load_env_values(root, report)
    report.env_complete = env_complete
    detected, contents_complete = scan_why_for_secrets(root, why_files, env_values, report)
    scan_complete = scan_complete and contents_complete
    redact_values = list(env_values) + sorted(detected)
    known_dirs = ("codesplain/features/", "codesplain/journal/", "codesplain/events/")
    for rel in why_files:
        if not rel.startswith(known_dirs):
            report.warn(rel, "not part of the codesplain/ format (scanned for secrets only)")
    # S5: never echo secret-shaped text or .env values in any output field (final output boundary).
    report.errors = _redact_deep(report.errors, redact_values)
    report.warnings = _redact_deep(report.warnings, redact_values)
    report.claims = _redact_deep(report.claims, redact_values)
    if not (env_complete and scan_complete):
        # Redaction cannot be guaranteed: suppress every input-derived detail.
        n_err, n_warn = len(report.errors), len(report.warnings)
        report.errors = [{"where": "codesplain" if env_complete else ".env*",
                          "message": "secret scan or .env collection incomplete; details suppressed because "
                          "secret redaction cannot be guaranteed (%d error(s), %d warning(s) hidden)"
                          % (n_err, n_warn)}]
        report.warnings = []
        report.claims = []
    return report


def _print_human(report, out):
    for e in report.errors:
        out.write("ERROR %s: %s\n" % (e["where"], e["message"]))
    for w in report.warnings:
        out.write("WARN  %s: %s\n" % (w["where"], w["message"]))
    if report.claims:
        out.write("\nClaims:\n")
        for c in report.claims:
            out.write("  %-18s %s\n" % (c["status"], c["claim"]))
    out.write("\n%d error(s), %d warning(s)\n" % (len(report.errors), len(report.warnings)))


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description="Read-only validator for codesplain/ notes.")
    parser.add_argument("--root", default=".", help="repository root (default: current directory)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--strict", action="append", default=[], metavar="PATH",
                        help="validate this (new) note strictly; repeatable")
    parser.add_argument("--max-age-days", type=int, default=90)
    parser.add_argument("--hash", metavar="PATH", help="print sha256 of a file inside the root")
    parser.add_argument("--claim-hash", metavar="NOTE#ID", help="print the revision hash of a claim")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    root = os.path.realpath(args.root)
    if not os.path.isdir(root):
        out.write("ERROR: --root is not a directory\n")
        return 2
    if args.max_age_days < 0:
        out.write("ERROR: --max-age-days must be >= 0\n")
        return 2
    if args.hash:
        try:
            out.write(file_sha256(root, args.hash) + "\n")
            return 0
        except ReadError as e:
            out.write("ERROR: %s\n" % e)  # ReadError messages never contain input text
            return 2
    if args.claim_hash:
        note_path, _, cid = args.claim_hash.partition("#")
        try:
            data, _ = parse_frontmatter(safe_read_text(root, note_path))
        except (ReadError, ParseError) as e:
            msg = e.msg if isinstance(e, ParseError) else str(e)
            out.write("ERROR: %s\n" % redact(msg, []))  # messages are fixed strings; redaction is a backstop
            return 2
        for c in data.get("claims", []) if isinstance(data.get("claims"), list) else []:
            if isinstance(c, dict) and c.get("id") == cid:
                out.write(claim_hash(c) + "\n")
                return 0
        out.write("ERROR: claim not found\n")
        return 2
    try:
        report = run_check(root, args.strict, args.max_age_days)
    except Exception:  # never let an unexpected error print input-derived text
        out.write("ERROR: internal error while checking; no details are printed for safety\n")
        return 2
    if args.json:
        out.write(json.dumps({
            "ok": not report.errors,
            "errors": report.errors,
            "warnings": report.warnings,
            "claims": report.claims,
        }, indent=2) + "\n")
    else:
        _print_human(report, out)
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
