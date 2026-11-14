"""Exercise scope discovery and refusal using isolated real Git repositories."""

from __future__ import annotations

import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from typing import cast

from tools import check_engineering as checks


class EngineeringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for arguments in (
            ["init", "-q"],
            ["config", "user.email", "fixture@example.invalid"],
            ["config", "user.name", "Synthetic Fixture"],
            ["config", "commit.gpgsign", "false"],
            ["config", "core.hooksPath", "fixture-hooks"],
        ):
            self.git(*arguments)
        (self.root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
        (self.root / "old.py").write_text("value = 1\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.base = self.git("rev-parse", "HEAD").strip()

    def git(self, *arguments: str) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)
        return result.stdout

    def test_discovers_committed_worktree_untracked_and_excludes_ignored(self) -> None:
        (self.root / "old.py").write_text("value = 2\n", encoding="utf-8")
        self.git("commit", "-qam", "changed")
        (self.root / "new file.py").write_text("pass\n", encoding="utf-8")
        (self.root / "ignored").mkdir()
        (self.root / "ignored/private.py").write_text("pass\n", encoding="utf-8")
        self.assertEqual(checks.affected(self.root, self.base), ["new file.py", "old.py"])
        (self.root / "old.py").unlink()
        self.assertEqual(checks.affected(self.root, self.base), ["new file.py"])

    def test_invalid_base_fails_instead_of_claiming_empty_scope(self) -> None:
        with self.assertRaises(subprocess.CalledProcessError):
            checks.affected(self.root, "missing-base")

    def test_scope_includes_direct_nested_and_native_owned_files(self) -> None:
        patterns = ["tools/**/*.py", "tests/**/*.py"]
        for name in ("tools/check.py", "tools/nested/check.py", "tests/engineering/test.py"):
            self.assertTrue(checks.matches(name, patterns), name)
        for name in ("src/LunaTranslator/LunaTranslator.py", "tools/data.json"):
            self.assertFalse(checks.matches(name, patterns), name)
        self.assertTrue(checks.matches("native/GrisaiaState.h", ["native/Grisaia*.h"]))

    def test_current_policy_covers_existing_compatibility_modules(self) -> None:
        with (checks.ROOT / "pyproject.toml").open("rb") as stream:
            policy = cast(checks.Policy, tomllib.load(stream)["tool"]["luna-engineering"])
        for name in ("__init__.py", "engine.py", "prompt.py", "transport.py"):
            path = "src/LunaTranslator/translator/grisaia/" + name
            self.assertTrue(checks.matches(path, policy["python"]), path)

    def test_500_passes_501_fails_including_blank_lines_and_comments(self) -> None:
        path = self.root / "source.py"
        path.write_bytes(b"# comment\r\n" * 499 + b"\r\n")
        self.assertEqual(checks.size_errors(self.root, [path.name], 500), [])
        path.write_bytes(path.read_bytes() + b"pass")
        errors = checks.size_errors(self.root, [path.name], 500)
        self.assertEqual(len(errors), 1)
        self.assertIn("501", errors[0])

    def test_push_uses_server_base_and_refuses_a_different_candidate(self) -> None:
        self.assertEqual(
            checks.push_bases(
                self.root, [f"refs/heads/main {self.base} refs/heads/main {self.base}"]
            ),
            [self.base],
        )
        with self.assertRaisesRegex(RuntimeError, "reviewed HEAD"):
            checks.push_bases(
                self.root, [f"refs/heads/other {'1' * 40} refs/heads/main {self.base}"]
            )
        self.assertEqual(
            checks.push_bases(
                self.root, [f"refs/heads/main {'0' * 40} refs/heads/main {self.base}"]
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
