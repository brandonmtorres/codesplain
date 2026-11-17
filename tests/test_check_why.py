"""Tests for skills/codesplain/scripts/check_why.py.

All fixtures are created inside temporary directories at runtime. Secret-looking
strings are assembled from fragments so this repository never contains a literal
string that matches a secret pattern.
"""

import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
import re
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPT = os.path.join(REPO, "skills", "codesplain", "scripts", "check_why.py")

_spec = importlib.util.spec_from_file_location("check_why", SCRIPT)
cw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cw)

FAKE_STRIPE = "sk" + "_live_" + "FAKEfake1234567890abcdEF"
FAKE_ENV_VALUE = "hunter" + "2-correct-horse-77"

PAY_PY = "def create_payment(key):\n    return charge_card(key)\n\ndef charge_card(key):\n    return True\n"


def read(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def feature(name="payments", files=("shop/pay.py",), claims=None, extra=""):
    claims = claims if claims is not None else [
        ("c1", "recorded", "Payments start in create_payment and call charge_card.", "shop/pay.py#create_payment", "")]
    out = ["---", "feature: %s" % name, "files:"]
    out += ["  - %s" % f for f in files]
    out.append("claims:")
    for cid, kind, text, deps, req in claims:
        out.append("  - id: %s" % cid)
        out.append("    kind: %s" % kind)
        out.append("    text: %s" % text)
        if deps:
            out.append("    deps: %s" % deps)
        if req:
            out.append("    required_checks: %s" % req)
    out.append(extra.rstrip("\n")) if extra else None
    out += ["---", "", "# %s" % name, ""]
    return "\n".join(x for x in out if x is not None)


def journal(files=("shop/pay.py",), lifecycle="active", extra="", claims_text="Added idempotency keys."):
    lines = ["---", "title: Fix double charge", "date: 2026-11-17", "change_type: fix", "files:"]
    lines += ["  - %s" % f for f in files]
    lines += ["lifecycle: %s" % lifecycle]
    if extra:
        lines.append(extra.rstrip("\n"))
    lines += ["claims:", "  - id: j1", "    kind: recorded", "    text: %s" % claims_text, "---", "", "Body.", ""]
    return "\n".join(lines)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        write(self.root, "shop/pay.py", PAY_PY)
        write(self.root, "codesplain/features/payments.md", feature())

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *args):
        buf = io.StringIO()
        code = cw.main(["--root", self.root] + list(args), out=buf)
        return code, buf.getvalue()

    def check(self, strict=(), now=None, max_age=90):
        return cw.run_check(self.root, list(strict), max_age, now=now)

    def msgs(self, items):
        return " | ".join(i["message"] for i in items)

    def status(self, report, gid="codesplain/features/payments.md#c1"):
        for c in report.claims:
            if c["claim"] == gid:
                return c["status"]
        self.fail("claim %s not reported" % gid)

    def chash(self, note="codesplain/features/payments.md", cid="c1"):
        data, _ = cw.parse_frontmatter(read(os.path.join(self.root, note)))
        for c in data["claims"]:
            if c["id"] == cid:
                return cw.claim_hash(c)
        raise KeyError(cid)

    def event(self, eid, outcome="pass", check="t1", scope=None, at="2026-11-17T10:00:00Z",
              claim="codesplain/features/payments.md#c1", claim_hash=None, snapshot=None):
        ev = {"id": eid, "type": "validation", "claim": claim, "check": check, "outcome": outcome,
              "revision": "working-tree", "at": at, "evidence": "test run",
              "claim_hash": claim_hash or self.chash(),
              "snapshot": snapshot if snapshot is not None else {"shop/pay.py": cw.file_sha256(self.root, "shop/pay.py")}}
        if scope:
            ev["scope"] = scope
        write(self.root, "codesplain/events/%s.json" % eid, json.dumps(ev))

    def resolution(self, eid, resolves, claim="codesplain/features/payments.md#c1", at="2026-11-17T11:00:00Z"):
        write(self.root, "codesplain/events/%s.json" % eid, json.dumps(
            {"id": eid, "type": "resolution", "claim": claim, "resolves": resolves,
             "reason": "fixed in code", "at": at}))


NOW = dt.datetime(2026, 11, 18, tzinfo=dt.timezone.utc)


class StructureTests(Base):
    def test_valid_repo_passes(self):
        code, out = self.run_cli()
        self.assertEqual(code, 0, out)

    def test_missing_why_dir(self):
        with tempfile.TemporaryDirectory() as d:
            buf = io.StringIO()
            self.assertEqual(cw.main(["--root", d], out=buf), 1)
            self.assertIn("no codesplain/", buf.getvalue())

    def test_bad_root_is_usage_error(self):
        buf = io.StringIO()
        self.assertEqual(cw.main(["--root", os.path.join(self.root, "nope")], out=buf), 2)

    def test_missing_frontmatter(self):
        write(self.root, "codesplain/features/x.md", "# no frontmatter\n")
        r = self.check()
        self.assertIn("missing frontmatter", self.msgs(r.errors))

    def test_unsupported_syntax_rejected(self):
        write(self.root, "codesplain/features/x.md", "---\nfeature: x\nfiles: [a, b]\n  weird: {x: 1}\n---\n")
        r = self.check()
        self.assertTrue(r.errors)

    def test_required_keys(self):
        write(self.root, "codesplain/journal/2026-11-17-x.md", "---\ntitle: t\n---\n")
        r = self.check()
        m = self.msgs(r.errors)
        for k in ("date", "change_type", "files", "lifecycle", "claims"):
            self.assertIn("'%s'" % k, m)

    def test_hand_written_status_rejected(self):
        write(self.root, "codesplain/journal/2026-11-17-x.md", journal(extra="status: verified"))
        self.assertIn("do not hand-write", self.msgs(self.check().errors))

    def test_invalid_date(self):
        write(self.root, "codesplain/journal/2026-11-17-x.md", journal().replace("2026-11-17", "2026-13-45"))
        self.assertIn("YYYY-MM-DD", self.msgs(self.check().errors))


class ReferenceTests(Base):
    def test_feature_missing_file_is_error(self):
        write(self.root, "codesplain/features/payments.md", feature(files=("shop/gone.py",)))
        self.assertIn("does not exist", self.msgs(self.check().errors))

    def test_fabricated_symbol_is_error_in_feature(self):
        write(self.root, "codesplain/features/payments.md", feature(claims=[
            ("c1", "recorded", "x", "shop/pay.py#refund_payment", "")]))
        self.assertIn("symbol not found", self.msgs(self.check().errors))

    def test_journal_missing_file_is_warning_not_error(self):
        write(self.root, "codesplain/journal/2026-11-17-x.md", journal(files=("shop/old.py",)))
        r = self.check()
        self.assertEqual(r.errors, [])
        self.assertIn("historical reference", self.msgs(r.warnings))

    def test_journal_missing_file_is_error_under_strict(self):
        write(self.root, "codesplain/journal/2026-11-17-x.md", journal(files=("shop/old.py",)))
        r = self.check(strict=["codesplain/journal/2026-11-17-x.md"])
        self.assertIn("does not exist", self.msgs(r.errors))

    def test_rename_and_symbol_removal_keep_old_journal_valid(self):
        write(self.root, "codesplain/journal/2026-11-01-a.md",
              journal(extra="symbols:\n  - shop/pay.py#charge_card"))
        write(self.root, "shop/pay.py", "def create_payment(key):\n    return True\n")  # symbol removed
        r = self.check()
        self.assertEqual(r.errors, [], r.errors)
        self.assertIn("historical reference", self.msgs(r.warnings))

    def test_new_deletion_journal_with_removed_validates_strict(self):
        write(self.root, "codesplain/journal/2026-11-17-del.md", journal(
            files=("shop/pay.py",), extra="removed:\n  - shop/legacy.py@abc1234\n  - shop/pay.py#old_fn@abc1234"))
        r = self.check(strict=["codesplain/journal/2026-11-17-del.md"])
        self.assertEqual(r.errors, [], r.errors)

    def test_bad_removed_format(self):
        write(self.root, "codesplain/journal/2026-11-17-del.md", journal(extra="removed:\n  - shop/legacy.py"))
        self.assertIn("removed entries", self.msgs(self.check().errors))

    def test_superseded_requires_target(self):
        write(self.root, "codesplain/journal/2026-11-17-x.md", journal(lifecycle="superseded"))
        self.assertIn("superseded_by", self.msgs(self.check().errors))
        write(self.root, "codesplain/journal/2026-11-17-x.md",
              journal(lifecycle="superseded", extra="superseded_by: 2026-11-18-y.md"))
        self.assertIn("missing journal", self.msgs(self.check().errors))
        write(self.root, "codesplain/journal/2026-11-18-y.md", journal())
        self.assertEqual(self.check().errors, [])


class SafetyTests(Base):
    def test_path_traversal_rejected(self):
        for bad in ("../outside.py", "/etc/hostname", "shop/../../outside.py"):
            write(self.root, "codesplain/features/payments.md", feature(files=(bad,)))
            m = self.msgs(self.check().errors)
            self.assertTrue("not allowed" in m or "escapes" in m or "outside" in m, (bad, m))

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            write(other, "secret.py", "x = 1\n")
            os.symlink(os.path.join(other, "secret.py"), os.path.join(self.root, "shop", "link.py"))
            write(self.root, "codesplain/features/payments.md", feature(files=("shop/link.py",)))
            self.assertIn("outside", self.msgs(self.check().errors))
            code, out = self.run_cli("--hash", "shop/link.py")
            self.assertEqual(code, 2)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "mkfifo not available")
    def test_fifo_rejected_without_blocking(self):
        os.mkfifo(os.path.join(self.root, "shop", "pipe.py"))
        write(self.root, "codesplain/features/payments.md", feature(files=("shop/pipe.py",)))
        self.assertIn("not a regular file", self.msgs(self.check().errors))
        code, out = self.run_cli("--hash", "shop/pipe.py")
        self.assertEqual(code, 2)
        self.assertIn("not a regular file", out)

    def test_oversized_file_skipped(self):
        write(self.root, "shop/big.py", "x" * (cw.MAX_FILE_BYTES + 10))
        write(self.root, "codesplain/features/payments.md", feature(files=("shop/big.py",)))
        self.assertIn("size limit", self.msgs(self.check().errors))

    def test_checker_does_not_modify_files(self):
        before = {}
        for d, _, fs in os.walk(self.root):
            for f in fs:
                p = os.path.join(d, f)
                before[p] = (os.stat(p).st_mtime_ns, read(p, "rb"))
        self.run_cli()
        self.run_cli("--json")
        self.run_cli("--hash", "shop/pay.py")
        after = {}
        for d, _, fs in os.walk(self.root):
            for f in fs:
                p = os.path.join(d, f)
                after[p] = (os.stat(p).st_mtime_ns, read(p, "rb"))
        self.assertEqual(before, after)

    def test_hash_mode(self):
        code, out = self.run_cli("--hash", "shop/pay.py")
        self.assertEqual(code, 0)
        self.assertRegex(out.strip(), r"^[0-9a-f]{64}$")


class SecretTests(Base):
    def test_pattern_secret_detected_and_not_echoed(self):
        write(self.root, "codesplain/journal/2026-11-17-x.md", journal(claims_text="Key is " + FAKE_STRIPE))
        for args in ((), ("--json",)):
            code, out = self.run_cli(*args)
            self.assertEqual(code, 1)
            self.assertIn("possible secret", out)
            self.assertNotIn(FAKE_STRIPE, out)
            self.assertNotIn(FAKE_STRIPE[8:], out)

    def test_env_value_detected_and_not_echoed(self):
        write(self.root, ".env", "DB_PASSWORD=%s\n" % FAKE_ENV_VALUE)
        write(self.root, "codesplain/journal/2026-11-17-x.md", journal(claims_text="Use " + FAKE_ENV_VALUE))
        code, out = self.run_cli("--json")
        self.assertEqual(code, 1)
        self.assertIn("value-from-.env-file", out)
        self.assertNotIn(FAKE_ENV_VALUE, out)

    def test_env_var_name_is_allowed(self):
        write(self.root, ".env", "DB_PASSWORD=%s\n" % FAKE_ENV_VALUE)
        write(self.root, "codesplain/journal/2026-11-17-x.md", journal(claims_text="Reads DB_PASSWORD from the environment."))
        code, out = self.run_cli()
        self.assertEqual(code, 0, out)

    def test_secret_in_event_file_detected(self):
        write(self.root, "codesplain/events/e1.json", json.dumps({"id": "e1", "evidence": FAKE_STRIPE}))
        code, out = self.run_cli()
        self.assertEqual(code, 1)
        self.assertNotIn(FAKE_STRIPE, out)

    def test_repository_contains_no_literal_secrets(self):
        hits = []
        for d, dirs, fs in os.walk(REPO):
            dirs[:] = [x for x in dirs if x not in (".git", "__pycache__")]
            for f in fs:
                p = os.path.join(d, f)
                try:
                    text = read(p)
                except (UnicodeDecodeError, OSError):
                    continue
                for line, rule in cw.scan_text_for_secrets(text):
                    hits.append("%s:%d %s" % (os.path.relpath(p, REPO), line, rule))
        self.assertEqual(hits, [])


class ClaimStatusTests(Base):
    def test_no_events_unverified(self):
        self.assertEqual(self.status(self.check(now=NOW)), "unverified")

    def test_pass_verified(self):
        self.event("e1")
        self.assertEqual(self.status(self.check(now=NOW)), "verified")

    def test_old_pass_unchanged_evidence(self):
        self.event("e1", at="2026-01-01T00:00:00Z")
        self.assertEqual(self.status(self.check(now=NOW)), "unchanged-evidence")

    def test_stale_after_dep_change(self):
        self.event("e1")
        write(self.root, "shop/pay.py", PAY_PY + "# changed\n")
        r = self.check(now=NOW)
        self.assertEqual(self.status(r), "stale")
        self.assertIn("stale", self.msgs(r.warnings))

    def test_snapshot_missing_dep_is_stale(self):
        self.event("e1", snapshot={})
        self.assertEqual(self.status(self.check(now=NOW)), "stale")

    def test_claim_edit_after_pass_unverified(self):
        self.event("e1")
        write(self.root, "codesplain/features/payments.md", feature(claims=[
            ("c1", "recorded", "Edited claim text.", "shop/pay.py#create_payment", "")]))
        self.assertEqual(self.status(self.check(now=NOW)), "unverified")

    def test_fail_then_pass_stays_contradicted(self):
        self.event("e1", outcome="fail", at="2026-11-17T09:00:00Z")
        self.event("e2", outcome="pass", at="2026-11-17T10:00:00Z")
        r = self.check(now=NOW)
        self.assertEqual(self.status(r), "contradicted")
        self.assertIn("unresolved contradiction", self.msgs(r.warnings))

    def test_fail_resolution_without_pass_unverified(self):
        self.event("e1", outcome="fail")
        self.resolution("r1", "e1")
        self.assertEqual(self.status(self.check(now=NOW)), "unverified")

    def test_pass_fail_resolution_unverified(self):
        self.event("e1", outcome="pass", at="2026-11-17T08:00:00Z")
        self.event("e2", outcome="fail", at="2026-11-17T09:00:00Z")
        self.resolution("r1", "e2")
        self.assertEqual(self.status(self.check(now=NOW)), "unverified")

    def test_fail_resolution_pass_verified(self):
        self.event("e1", outcome="fail", at="2026-11-17T08:00:00Z")
        self.resolution("r1", "e1", at="2026-11-17T09:00:00Z")
        self.event("e2", outcome="pass", at="2026-11-17T10:00:00Z")
        self.assertEqual(self.status(self.check(now=NOW)), "verified")

    def test_resolution_clears_only_its_target(self):
        self.event("e1", outcome="fail", check="a", at="2026-11-17T08:00:00Z")
        self.event("e2", outcome="fail", check="b", at="2026-11-17T08:30:00Z")
        self.resolution("r1", "e1")
        self.event("e3", outcome="pass", check="a", at="2026-11-17T10:00:00Z")
        self.event("e4", outcome="pass", check="b", at="2026-11-17T10:00:00Z")
        self.assertEqual(self.status(self.check(now=NOW)), "contradicted")

    def test_resolution_of_pass_is_error(self):
        self.event("e1", outcome="pass")
        self.resolution("r1", "e1")
        self.assertIn("must target an existing 'fail'", self.msgs(self.check(now=NOW).errors))

    def test_resolution_of_other_claims_event_is_error(self):
        write(self.root, "codesplain/features/payments.md", feature(claims=[
            ("c1", "recorded", "one", "shop/pay.py#create_payment", ""),
            ("c2", "recorded", "two", "shop/pay.py#charge_card", "")]))
        self.event("e1", outcome="fail", claim="codesplain/features/payments.md#c2",
                   claim_hash=self.chash(cid="c2"))
        self.resolution("r1", "e1", claim="codesplain/features/payments.md#c1")
        self.assertIn("different claim", self.msgs(self.check(now=NOW).errors))

    def test_mixed_claims_in_one_note(self):
        write(self.root, "codesplain/features/payments.md", feature(claims=[
            ("c1", "recorded", "one", "shop/pay.py#create_payment", ""),
            ("c2", "recorded", "two", "shop/pay.py#charge_card", "")]))
        self.event("e1", outcome="pass", claim="codesplain/features/payments.md#c1", claim_hash=self.chash(cid="c1"))
        self.event("e2", outcome="fail", claim="codesplain/features/payments.md#c2", claim_hash=self.chash(cid="c2"))
        r = self.check(now=NOW)
        self.assertEqual(self.status(r, "codesplain/features/payments.md#c1"), "verified")
        self.assertEqual(self.status(r, "codesplain/features/payments.md#c2"), "contradicted")

    def test_inconclusive_not_hidden_by_other_pass(self):
        self.event("e1", outcome="inconclusive", check="a")
        self.event("e2", outcome="pass", check="b", at="2026-11-17T12:00:00Z")
        self.assertEqual(self.status(self.check(now=NOW)), "inconclusive")

    def test_required_check_unavailable_unknown(self):
        write(self.root, "codesplain/features/payments.md", feature(claims=[
            ("c1", "recorded", "x", "shop/pay.py#create_payment", "a, b")]))
        self.event("e1", outcome="pass", check="a")
        self.event("e2", outcome="unavailable", check="b")
        self.assertEqual(self.status(self.check(now=NOW)), "unknown")

    def test_required_check_missing_unverified(self):
        write(self.root, "codesplain/features/payments.md", feature(claims=[
            ("c1", "recorded", "x", "shop/pay.py#create_payment", "a, b")]))
        self.event("e1", outcome="pass", check="a")
        self.assertEqual(self.status(self.check(now=NOW)), "unverified")

    def test_scope_is_separate(self):
        write(self.root, "codesplain/features/payments.md", feature(claims=[
            ("c1", "recorded", "x", "shop/pay.py#create_payment", "a@unit, a@integration")]))
        self.event("e1", outcome="pass", check="a", scope="unit")
        self.assertEqual(self.status(self.check(now=NOW)), "unverified")
        self.event("e2", outcome="pass", check="a", scope="integration")
        self.assertEqual(self.status(self.check(now=NOW)), "verified")

    def test_superseded_note_with_contradiction_still_warns(self):
        write(self.root, "codesplain/journal/2026-11-18-y.md", journal())
        write(self.root, "codesplain/journal/2026-11-17-x.md",
              journal(lifecycle="superseded", extra="superseded_by: 2026-11-18-y.md"))
        gid = "codesplain/journal/2026-11-17-x.md#j1"
        self.event("e1", outcome="fail", claim=gid, claim_hash=self.chash("codesplain/journal/2026-11-17-x.md", "j1"),
                   snapshot={})
        r = self.check(now=NOW)
        self.assertEqual(self.status(r, gid), "contradicted")
        self.assertIn("unresolved contradiction", self.msgs(r.warnings))

    def test_event_errors(self):
        write(self.root, "codesplain/events/a.json", json.dumps({"id": "x", "type": "validation",
              "claim": "codesplain/features/payments.md#nope", "at": "2026-11-17T00:00:00Z"}))
        self.event("dup")
        write(self.root, "codesplain/events/dup2.json", read(os.path.join(self.root, "codesplain/events/dup.json")))
        m = self.msgs(self.check(now=NOW).errors)
        self.assertIn("unknown claim", m)
        self.assertIn("duplicate event id", m)

    def test_claim_hash_cli(self):
        code, out = self.run_cli("--claim-hash", "codesplain/features/payments.md#c1")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), self.chash())

    def test_json_lists_claims_with_events(self):
        self.event("e1")
        code, out = self.run_cli("--json")
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(data["claims"][0]["events"], ["e1"])


class StaticSafetyAudit(unittest.TestCase):
    """Shipped code must not contain dangerous capabilities (S1, S3). Inspects the AST, not comments."""

    ALLOWED_IMPORTS = {"argparse", "datetime", "hashlib", "json", "os", "re", "stat", "sys"}
    FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "open", "input", "breakpoint"}
    FORBIDDEN_OS = {"system", "popen", "remove", "unlink", "rmdir", "removedirs", "rename", "renames",
                    "replace", "chmod", "chown", "lchown", "makedirs", "mkdir", "mkfifo", "symlink", "link",
                    "truncate", "write", "execv", "execve", "execvp", "spawnv", "fork", "kill", "putenv",
                    "O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC"}

    def test_no_dangerous_capabilities_in_shipped_script(self):
        import ast
        tree = ast.parse(read(SCRIPT))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertIn(a.name.split(".")[0], self.ALLOWED_IMPORTS, a.name)
            elif isinstance(node, ast.ImportFrom):
                self.fail("from-import not allowed: %s" % node.module)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, self.FORBIDDEN_CALLS, node.func.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os":
                self.assertNotIn(node.attr, self.FORBIDDEN_OS, "os." + node.attr)
            elif isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
                self.fail("environment access not allowed")


class InspectionRegressionTests(Base):
    def test_secret_in_reference_is_redacted_everywhere(self):
        write(self.root, "codesplain/features/payments.md", feature(files=("shop/pay.py", "shop/" + FAKE_STRIPE + ".py")))
        for args in ((), ("--json",)):
            code, out = self.run_cli(*args)
            self.assertEqual(code, 1)
            self.assertNotIn(FAKE_STRIPE, out)
            self.assertIn("[REDACTED]", out)

    def test_env_value_in_claim_id_is_redacted(self):
        write(self.root, ".env", "TOKEN=%s\n" % FAKE_ENV_VALUE)
        write(self.root, "codesplain/features/payments.md", feature(claims=[
            ("c1", "recorded", "x", "shop/pay.py#create_payment", ""),
            (FAKE_ENV_VALUE.replace("-", ""), "recorded", "y", "", "")]))
        write(self.root, ".env", "TOKEN=%s\n" % FAKE_ENV_VALUE.replace("-", ""))
        for args in ((), ("--json",)):
            code, out = self.run_cli(*args)
            self.assertNotIn(FAKE_ENV_VALUE.replace("-", ""), out)

    def test_secret_outside_note_dirs_is_scanned(self):
        write(self.root, "codesplain/credentials.txt", "key " + FAKE_STRIPE + "\n")
        write(self.root, "codesplain/nested/deep/x.md", FAKE_STRIPE + "\n")
        code, out = self.run_cli()
        self.assertEqual(code, 1)
        self.assertEqual(out.count("possible secret"), 2)
        self.assertIn("not part of the codesplain/ format", out)

    def test_wrong_layout_is_error(self):
        write(self.root, "codesplain/features/notes.txt", "hello\n")
        write(self.root, "codesplain/journal/sub/x.md", journal())
        m = self.msgs(self.check().errors)
        self.assertIn("unsupported file type", m)
        self.assertIn("nested directories", m)

    def test_event_truncation_never_reports_verified(self):
        self.event("e1")
        old = cw.MAX_FILES
        try:
            cw.MAX_FILES = 1
            write(self.root, "codesplain/events/zz-fail.json", "{}")
            r = self.check(now=NOW)
        finally:
            cw.MAX_FILES = old
        self.assertIn("incomplete", self.msgs(r.errors))
        self.assertFalse(any(c["status"] in ("verified", "unchanged-evidence") for c in r.claims))

    def test_malformed_event_types_do_not_crash(self):
        write(self.root, "codesplain/events/a.json", json.dumps({"id": "a", "type": "validation", "claim": [],
                                                           "at": "2026-11-17T00:00:00Z"}))
        ev = {"id": "b", "type": "validation", "claim": "codesplain/features/payments.md#c1", "check": "t",
              "scope": ["x"], "outcome": "pass", "revision": "r", "evidence": "e", "at": "2026-11-17T00:00:00Z",
              "claim_hash": self.chash(), "snapshot": {}}
        write(self.root, "codesplain/events/b.json", json.dumps(ev))
        code, out = self.run_cli("--json")
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertIn("claim", out)
        self.assertIn("scope", out)

    def test_validation_requires_revision_and_evidence(self):
        ev = {"id": "c", "type": "validation", "claim": "codesplain/features/payments.md#c1", "check": "t",
              "outcome": "pass", "at": "2026-11-17T00:00:00Z", "claim_hash": self.chash(),
              "snapshot": {"shop/pay.py": cw.file_sha256(self.root, "shop/pay.py")}}
        write(self.root, "codesplain/events/c.json", json.dumps(ev))
        r = self.check(now=NOW)
        self.assertIn("revision", self.msgs(r.errors))
        self.assertEqual(self.status(r), "unknown")  # rejected history for this claim: never success

    def test_bare_required_scalars_rejected(self):
        write(self.root, "codesplain/journal/2026-11-17-x.md",
              journal().replace("date: 2026-11-17", "date:").replace("lifecycle: active", "lifecycle:"))
        m = self.msgs(self.check().errors)
        self.assertIn("'date' must be a non-empty value", m)
        self.assertIn("'lifecycle' must be a non-empty value", m)

    def test_binary_file_reference_ok(self):
        path = os.path.join(self.root, "shop", "logo.png")
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n\xff\xfe\x00")
        write(self.root, "codesplain/features/payments.md", feature(files=("shop/pay.py", "shop/logo.png")))
        self.assertEqual(self.check().errors, [])

    def test_env_inline_comment_and_quotes(self):
        self.assertEqual(cw.parse_env_value("abc123defg # local"), ("abc123defg", True))
        self.assertEqual(cw.parse_env_value("'quoted value#1' # c"), ("quoted value#1", True))
        self.assertEqual(cw.parse_env_value('"a#b c d e"'), ("a#b c d e", True))
        self.assertEqual(cw.parse_env_value("val#ue12345"), ("val#ue12345", True))
        write(self.root, ".env", "export TOKEN=%s # local dev\n# OTHER=%s\n" % (FAKE_ENV_VALUE, "commentedout99"))
        write(self.root, "codesplain/journal/2026-11-17-x.md", journal(claims_text="uses " + FAKE_ENV_VALUE))
        code, out = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("value-from-.env-file", out)
        self.assertNotIn(FAKE_ENV_VALUE, out)

    def test_format_example_scopes_match(self):
        fmt = read(os.path.join(REPO, "skills", "codesplain", "reference", "format.md"))
        self.assertIn("test_duplicate_request@unit", fmt)
        self.assertIn('"scope": "unit"', fmt)


class SecondInspectionRegressionTests(Base):
    def test_secret_in_claim_kind_not_printed(self):
        write(self.root, "codesplain/features/payments.md", feature(claims=[
            ("c1", FAKE_STRIPE, "x", "shop/pay.py#create_payment", "")]))
        for args in ((), ("--json",)):
            code, out = self.run_cli(*args)
            self.assertEqual(code, 1)
            self.assertNotIn(FAKE_STRIPE, out)
            self.assertNotIn("codesplain/features/payments.md#c1", json.dumps(json.loads(out)["claims"]) if args else "")

    def test_parser_errors_do_not_echo_keys(self):
        key = "sk" + "_live_" + "abcdefghijklmnop1234"
        write(self.root, "codesplain/features/x.md", "---\n%s: 1\n%s: 2\n---\n" % (key, key))
        code, out = self.run_cli()
        self.assertNotIn(key, out)
        code, out = self.run_cli("--claim-hash", "codesplain/features/x.md#c1")
        self.assertEqual(code, 2)
        self.assertNotIn(key, out)

    def test_unloadable_fail_event_prevents_verified(self):
        self.event("e1")
        big = {"id": "e2", "type": "validation", "claim": "codesplain/features/payments.md#c1", "outcome": "fail",
               "pad": "x" * (cw.MAX_FILE_BYTES + 10)}
        write(self.root, "codesplain/events/e2.json", json.dumps(big))
        r = self.check(now=NOW)
        self.assertFalse(any(c["status"] in ("verified", "unchanged-evidence") for c in r.claims))
        self.assertTrue(r.errors)

    def test_deeply_nested_event_does_not_crash(self):
        self.event("e1")
        write(self.root, "codesplain/events/deep.json", "[" * 100000 + "]" * 100000)
        code, out = self.run_cli("--json")
        self.assertEqual(code, 1)
        data = json.loads(out)  # structured output, no crash
        self.assertIn("details suppressed", out)
        self.assertEqual(data["claims"], [])

    def test_unreadable_env_suppresses_details(self):
        write(self.root, "codesplain/features/payments.md", feature(files=("shop/pay.py", "shop/missing.py")))
        os.mkfifo(os.path.join(self.root, ".env.local")) if hasattr(os, "mkfifo") else None
        if not hasattr(os, "mkfifo"):
            self.skipTest("mkfifo not available")
        code, out = self.run_cli("--json")
        self.assertEqual(code, 1)
        self.assertIn("details suppressed", out)
        self.assertNotIn("missing.py", out)

    def test_too_many_env_files_is_error(self):
        old = cw.MAX_ENV_FILES
        try:
            cw.MAX_ENV_FILES = 2
            for i in range(3):
                write(self.root, ".env.%d" % i, "A=b\n")
            code, out = self.run_cli()
        finally:
            cw.MAX_ENV_FILES = old
        self.assertEqual(code, 1)
        self.assertIn("details suppressed", out)

    def test_credential_assignments(self):
        pw = "pass" + "word"
        ak, sc = "api" + "_key", "sec" + "ret"
        bad = ["%s=hunterhunterhunterx" % pw, "%s: abc" % pw, ak + " = 'letters'", sc + "=qwerty"]
        ok = ["%s=<your-password>" % pw, "%s: ${DB_PASSWORD}" % pw, "%s=DB_PASSWORD" % pw,
              "%s is read from DB_PASSWORD" % pw, "api_key: [REDACTED]", "secret=***"]
        for line in bad:
            self.assertTrue(list(cw.scan_text_for_secrets(line)), line)
            self.assertNotIn(line.split("=")[-1].split(":")[-1].strip(" '"), cw.redact(line, []))
        for line in ok:
            self.assertEqual(list(cw.scan_text_for_secrets(line)), [], line)

    def test_list_item_limit(self):
        old = cw.MAX_LIST_ITEMS
        try:
            cw.MAX_LIST_ITEMS = 3
            write(self.root, "codesplain/features/payments.md", feature(files=("shop/pay.py",) * 4))
            self.assertIn("too many list items", self.msgs(self.check().errors))
        finally:
            cw.MAX_LIST_ITEMS = old

    def test_reference_budget_reports_incomplete(self):
        old = cw.MAX_REF_CHECKS
        try:
            cw.MAX_REF_CHECKS = 1
            write(self.root, "shop/b.py", "x = 1\n")
            write(self.root, "codesplain/features/payments.md", feature(files=("shop/pay.py", "shop/b.py")))
            self.assertIn("budget exhausted", self.msgs(self.check().errors))
        finally:
            cw.MAX_REF_CHECKS = old


class ThirdInspectionRegressionTests(Base):
    def test_detected_credential_redacted_in_ids_and_names(self):
        val = "hunterhunter" + "123"
        pw = "pass" + "word"
        write(self.root, "codesplain/features/payments.md", feature(claims=[
            ("c1", "recorded", "x", "shop/pay.py#create_payment", ""),
            (val, "recorded", "%s=%s" % (pw, val), "", "")]))
        write(self.root, "codesplain/notes-%s.txt" % val, "%s=%s\n" % (pw, val))
        for args in ((), ("--json",)):
            code, out = self.run_cli(*args)
            self.assertEqual(code, 1)
            self.assertNotIn(val, out)

    def test_skipped_fail_event_prevents_verified(self):
        self.event("e1")
        with tempfile.TemporaryDirectory() as other:
            write(other, "fail.json", "{}")
            os.symlink(os.path.join(other, "fail.json"), os.path.join(self.root, "codesplain", "events", "fail.json"))
            r = self.check(now=NOW)
        self.assertIn("symlinks are not supported", self.msgs(r.errors))
        self.assertEqual(self.status(r), "unknown")

    def test_quoted_passphrases_detected(self):
        pw = "pass" + "word"
        for line in ('%s="correct horse battery staple"' % pw, "%s='correct horse battery staple'" % pw,
                     '%s: "with \\"escaped\\" quote"' % pw):
            self.assertTrue(list(cw.scan_text_for_secrets(line)), line)
            self.assertNotIn("battery staple", cw.redact(line, []))
        self.assertEqual(list(cw.scan_text_for_secrets('%s="<your password here>"' % pw)), [])

    def test_future_event_rejected(self):
        self.event("e1", at="2099-01-01T00:00:00Z")
        r = self.check(now=NOW)
        self.assertIn("in the future", self.msgs(r.errors))
        self.assertNotIn(self.status(r), ("verified", "unchanged-evidence"))


class FourthInspectionRegressionTests(Base):
    def test_json_escaped_credential_in_event_detected_and_redacted(self):
        pw = "pass" + "word"
        val = "s3cr3t pass phrase"
        ev = {"id": val, "type": "validation", "claim": "codesplain/features/payments.md#c1", "check": "t",
              "outcome": "fail", "revision": "r", "evidence": '%s="%s"' % (pw, val),
              "at": "2026-11-17T10:00:00Z", "claim_hash": self.chash(), "snapshot": {}}
        write(self.root, "codesplain/events/x.json", json.dumps(ev))
        for args in ((), ("--json",)):
            code, out = self.run_cli(*args)
            self.assertEqual(code, 1)
            self.assertIn("JSON value", out)
            self.assertNotIn(val, out)

    def test_json_escaped_env_value_detected(self):
        val = 'abc"def"ghij12'
        write(self.root, ".env", 'TOKEN="abc\\"def\\"ghij12"\n')
        self.assertEqual(cw.parse_env_value('"abc\\"def\\"ghij12"'), (val, True))
        write(self.root, "codesplain/events/x.json", json.dumps({"id": "x", "evidence": val}))
        code, out = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("JSON value", out)
        self.assertNotIn("ghij12", out)

    def test_malformed_env_quote_suppresses_details(self):
        write(self.root, ".env", 'TOKEN="unterminated value here\n')
        code, out = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("details suppressed", out)

    def test_env_value_as_filename_is_error(self):
        val = "plainletters" + "value"
        write(self.root, ".env", "TOKEN=%s\n" % val)
        write(self.root, "codesplain/features/%s.md" % val, feature(name="x"))
        code, out = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("file name", out)
        self.assertNotIn(val, out)

    def test_resolution_ids_in_provenance(self):
        self.event("f1", outcome="fail", at="2026-11-17T08:00:00Z")
        self.resolution("r1", "f1", at="2026-11-17T09:00:00Z")
        code, out = self.run_cli("--json")
        claim = json.loads(out)["claims"][0]
        self.assertEqual(claim["status"], "unverified")
        self.assertIn("r1", claim["events"])
        self.assertIn("f1", claim["events"])
        self.event("p1", outcome="pass", at="2026-11-17T10:00:00Z")
        claim = json.loads(self.run_cli("--json")[1])["claims"][0]
        self.assertEqual(claim["status"], "verified")
        self.assertIn("r1", claim["events"])

    def test_backslash_only_credential_value_ignored(self):
        pw = "pass" + "word"
        self.assertEqual(list(cw._credential_values(pw + "=\\")), [])


class FifthInspectionRegressionTests(Base):
    def test_multiline_env_value_detected_in_note_and_event(self):
        write(self.root, ".env", 'TOKEN="first-line-abc\\nsecond-line-xyz"\n')
        write(self.root, "codesplain/journal/2026-11-17-x.md", journal() + "first-line-abc\nsecond-line-xyz\n")
        code, out = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("value-from-.env-file", out)
        os.remove(os.path.join(self.root, "codesplain/journal/2026-11-17-x.md"))
        write(self.root, "codesplain/events/x.json", json.dumps({"id": "x", "evidence": "first-line-abc\nsecond-line-xyz"}))
        code, out = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("value-from-.env-file", out)

    def test_duplicate_json_keys_rejected(self):
        self.event("e1")
        raw = read(os.path.join(self.root, "codesplain/events/e1.json"))
        raw = raw.replace('"outcome": "pass"', '"outcome": "fail", "outcome": "pass"')
        write(self.root, "codesplain/events/e1.json", raw)
        r = self.check(now=NOW)
        self.assertIn("duplicate keys", self.msgs(r.errors))
        self.assertNotIn(self.status(r), ("verified", "unchanged-evidence"))

    def test_block_scalar_and_deeper_indent_rejected(self):
        text = ("---\nfeature: payments\nfiles:\n  - shop/pay.py\nclaims:\n  - id: c1\n    kind: recorded\n"
                "    text: |\n      deps: missing.py\n---\n")
        write(self.root, "codesplain/features/payments.md", text)
        self.assertIn("unsupported value syntax", self.msgs(self.check().errors))
        text2 = text.replace("    text: |\n      deps: missing.py", "    text: hello\n      deps: missing.py")
        write(self.root, "codesplain/features/payments.md", text2)
        self.assertIn("same indentation", self.msgs(self.check().errors))
        code, out = self.run_cli("--claim-hash", "codesplain/features/payments.md#c1")
        self.assertEqual(code, 2)

    def test_flow_collections_rejected(self):
        write(self.root, "codesplain/features/payments.md", feature().replace("feature: payments", "feature: {a: 1}"))
        self.assertIn("unsupported value syntax", self.msgs(self.check().errors))
        write(self.root, "codesplain/features/payments.md", feature().replace("feature: payments", "feature: '[quoted ok]'"))
        self.assertEqual(self.check().errors, [])

    def test_format_path_as_file_is_error(self):
        os.remove(os.path.join(self.root, "codesplain/features/payments.md"))
        os.rmdir(os.path.join(self.root, "codesplain/features"))
        write(self.root, "codesplain/features", "not a dir\n")
        self.assertIn("must be a directory", self.msgs(self.check().errors))

    def test_events_path_as_file_marks_history_incomplete(self):
        write(self.root, "codesplain/events", "not a dir\n")
        r = self.check(now=NOW)
        self.assertIn("must be a directory", self.msgs(r.errors))
        self.assertEqual(self.status(r), "unknown")


class SixthInspectionRegressionTests(Base):
    def test_private_key_block_fully_redacted(self):
        body = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC" + "BKcwggSjAgEAAoIBAQC7"
        pem = "-----BEGIN" + " PRIVATE KEY-----\n" + body + "\n-----END" + " PRIVATE KEY-----"
        ev = {"id": pem, "type": "validation", "claim": "codesplain/features/payments.md#c1", "check": "t",
              "outcome": "fail", "revision": "r", "evidence": "e", "at": "2026-11-17T10:00:00Z",
              "claim_hash": self.chash(), "snapshot": {}}
        write(self.root, "codesplain/events/x.json", json.dumps(ev))
        for args in ((), ("--json",)):
            code, out = self.run_cli(*args)
            self.assertEqual(code, 1)
            self.assertNotIn(body, out)
            self.assertNotIn(body[:20], out)
        unterminated = "-----BEGIN" + " RSA PRIVATE KEY-----\n" + body
        self.assertNotIn(body, cw.redact("x " + unterminated, []))

    def test_quoted_uppercase_and_punctuation_passwords_detected(self):
        pw = "pass" + "word"
        for line in ('%s="ABC123XYZ"' % pw, "%s='DB_PASSWORD'" % pw, '%s="!@#$%%^&*"' % pw, "%s=ABC123XYZ" % pw):
            self.assertTrue(list(cw.scan_text_for_secrets(line)), line)
        for line in ("%s=DB_PASSWORD" % pw, "%s=$DB_PASSWORD" % pw, '%s="<your password>"' % pw):
            self.assertEqual(list(cw.scan_text_for_secrets(line)), [], line)

    def test_feature_page_status_rejected(self):
        write(self.root, "codesplain/features/payments.md", feature(extra="status: verified"))
        self.assertIn("do not hand-write", self.msgs(self.check().errors))

    def test_docs_require_hashes_around_check_and_checker_last(self):
        fmt = read(os.path.join(REPO, "skills", "codesplain", "reference", "format.md"))
        self.assertIn("Immediately before", fmt)
        self.assertIn("Immediately after", fmt)
        skill = read(os.path.join(REPO, "skills", "codesplain", "SKILL.md"))
        self.assertLess(skill.index("record a validation event"), skill.index("Run the checker last"))


class SeventhInspectionRegressionTests(Base):
    def test_private_key_assignment_value_redacted_everywhere(self):
        k = "QUJDREVGR0hJSktMTU5PUA" + "xyz"
        ev = {"id": k, "type": "validation", "claim": "codesplain/features/payments.md#c1", "check": "t",
              "outcome": "fail", "revision": "r", "evidence": "private" + "_key=" + k,
              "at": "2026-11-17T10:00:00Z", "claim_hash": self.chash(), "snapshot": {}}
        write(self.root, "codesplain/events/x.json", json.dumps(ev))
        for args in ((), ("--json",)):
            code, out = self.run_cli(*args)
            self.assertEqual(code, 1)
            self.assertNotIn(k, out)

    def test_padded_json_still_scanned(self):
        token = "sk" + "_live_" + "FAKEfake1234567890abcdEF"
        escaped = "".join("\\u%04x" % ord(ch) for ch in token)
        raw = '{"id": "x", "evidence": "%s", "pad": [%s]}' % (escaped, ",".join(['""'] * 100001))
        write(self.root, "codesplain/events/x.json", raw)
        code, out = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("JSON value", out)
        self.assertNotIn(token, out)

    def test_lone_surrogate_snapshot_path_does_not_crash(self):
        raw = ('{"id": "e1", "type": "validation", "claim": "codesplain/features/payments.md#c1", "check": "t", '
               '"outcome": "pass", "revision": "r", "evidence": "e", "at": "2026-11-17T10:00:00Z", '
               '"claim_hash": "%s", "snapshot": {"shop/pay.py": "%s", "\\ud800": "%s"}}'
               % (self.chash(), cw.file_sha256(self.root, "shop/pay.py"), "0" * 64))
        write(self.root, "codesplain/events/e1.json", raw)
        code, out = self.run_cli("--json")
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertIn("invalid or out-of-root path", out)
        self.assertNotIn(data["claims"][0]["status"], ("verified", "unchanged-evidence"))


class EighthInspectionRegressionTests(Base):
    def test_incomplete_secret_scan_suppresses_details(self):
        pw = "pass" + "word"
        val = "plainpw" + "value9"
        write(self.root, "codesplain/features/payments.md", feature(claims=[
            (val, "recorded", "%s=%s" % (pw, val), "shop/pay.py#create_payment", "")]))
        old = cw.MAX_FILES
        try:
            cw.MAX_FILES = 1
            write(self.root, "codesplain/zz/a.txt", "x\n")
            write(self.root, "codesplain/zz/b.txt", "x\n")
            code, out = self.run_cli("--json")
        finally:
            cw.MAX_FILES = old
        self.assertEqual(code, 1)
        self.assertNotIn(val, out)
        self.assertIn("details suppressed", out)

    def test_special_file_in_why_is_error(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("mkfifo not available")
        os.mkfifo(os.path.join(self.root, "codesplain", "pipe"))
        code, out = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("not a regular file", out)

    def test_tied_timestamps_with_conflicting_outcomes_not_verified(self):
        self.event("z", outcome="pass", at="2026-11-17T10:00:00Z")
        self.event("a", outcome="fail", at="2026-11-17T10:00:00Z")
        self.resolution("r1", "a", at="2026-11-17T11:00:00Z")
        self.assertEqual(self.status(self.check(now=NOW)), "unverified")
        self.event("p2", outcome="pass", at="2026-11-17T12:00:00Z")
        self.assertEqual(self.status(self.check(now=NOW)), "verified")

    def test_empty_and_qualified_symbols_rejected(self):
        write(self.root, "codesplain/features/payments.md", feature(extra="symbols:\n  - shop/pay.py#"))
        self.assertIn("non-empty name", self.msgs(self.check().errors))
        write(self.root, "codesplain/features/payments.md",
              feature(extra="symbols:\n  - shop/pay.py#Nonexistent.charge_card"))
        self.assertIn("single identifier", self.msgs(self.check().errors))

    def test_snapshot_entry_limit(self):
        snap = {"shop/f%d.py" % i: "0" * 64 for i in range(cw.MAX_SNAPSHOT_ENTRIES + 1)}
        snap["shop/pay.py"] = cw.file_sha256(self.root, "shop/pay.py")
        self.event("e1", snapshot=snap)
        r = self.check(now=NOW)
        self.assertIn("too many entries", self.msgs(r.errors))
        self.assertNotIn(self.status(r), ("verified", "unchanged-evidence"))

    def test_hash_budget_exhaustion_not_verified(self):
        self.event("e1")
        old = cw.MAX_REF_CHECKS
        try:
            cw.MAX_REF_CHECKS = 1
            r = self.check(now=NOW)
        finally:
            cw.MAX_REF_CHECKS = old
        self.assertIn("budget exhausted", self.msgs(r.errors))
        self.assertNotIn(self.status(r), ("verified", "unchanged-evidence"))


class NinthInspectionRegressionTests(Base):
    def test_invalid_json_event_suppresses_details(self):
        write(self.root, "codesplain/events/b.json", "{not json")
        code, out = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("details suppressed", out)

    def test_json_credential_in_markdown_and_event(self):
        val = "plaincredential" + "x"
        pw = "pass" + "word"
        self.assertTrue(list(cw.scan_text_for_secrets('{"%s": "%s"}' % (pw, val))))
        write(self.root, "codesplain/features/payments.md", feature(claims=[
            ("c1", "recorded", "x", "shop/pay.py#create_payment", ""),
            (val, "recorded", "config is {\"%s\": \"%s\"}" % (pw, val), "", "")]))
        code, out = self.run_cli("--json")
        self.assertEqual(code, 1)
        self.assertNotIn(val, out)
        write(self.root, "codesplain/features/payments.md", feature())
        write(self.root, "codesplain/events/x.json", json.dumps({"id": val, "config": {pw: val}}))
        code, out = self.run_cli("--json")
        self.assertEqual(code, 1)
        self.assertNotIn(val, out)

    def test_duplicate_key_values_all_scanned(self):
        val = "hiddencredential" + "z"
        pw = "pass" + "word"
        escaped = "".join("\\u%04x" % ord(ch) for ch in '%s="%s"' % (pw, val))
        raw = '{"id": "%s", "evidence": "%s", "evidence": "innocent"}' % (val, escaped)
        write(self.root, "codesplain/events/x.json", raw)
        code, out = self.run_cli("--json")
        self.assertEqual(code, 1)
        self.assertNotIn(val, out)
        self.assertIn("JSON value", out)

    def test_tied_passes_with_different_snapshots_are_stale_regardless_of_names(self):
        good = cw.file_sha256(self.root, "shop/pay.py")
        self.event("a", snapshot={"shop/pay.py": good})
        self.event("z", snapshot={"shop/pay.py": "0" * 64})
        self.assertEqual(self.status(self.check(now=NOW)), "stale")
        os.remove(os.path.join(self.root, "codesplain/events/a.json"))
        os.remove(os.path.join(self.root, "codesplain/events/z.json"))
        self.event("a", snapshot={"shop/pay.py": "0" * 64})
        self.event("z", snapshot={"shop/pay.py": good})
        self.assertEqual(self.status(self.check(now=NOW)), "stale")


if __name__ == "__main__":
    unittest.main()
