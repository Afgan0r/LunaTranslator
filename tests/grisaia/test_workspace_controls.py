"""Exercise profile controls against real isolated journals and configuration."""

import contextlib
import io
import json
import os
import shutil
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import integration_control
from integrations.engine import Journal, TranslationError


class ControlTests(unittest.TestCase):
    def test_executable_entrypoints_help_returns_success_without_work(self):
        tools = Path(integration_control.__file__).parent
        for name in ("workspace.py", "build_native.py", "integration_control.py"):
            with self.subTest(name=name), patch.object(sys, "argv", [name, "--help"]), contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(tools / name), run_name="__main__")
            self.assertEqual(raised.exception.code, 0)
            self.assertIn("usage:", output.getvalue())

    def fixture(self, home):
        config = {"schema": 1, "defaults": {}, "profiles": {"one": {
            "adapter": "grisaia", "game_exe": str(home / "game.exe"),
            "settings": {"key_file": "SECRET_SENTINEL"}}}}
        (home / "config.json").write_text(json.dumps(config))
        return home / "games/one/journal.sqlite3"

    def control(self, home, command):
        output = io.StringIO()
        with patch.object(sys, "argv", ["integration_control", "--home", str(home), "--game", "one", *command]), contextlib.redirect_stdout(output):
            integration_control.main()
        return output.getvalue()

    def test_status_excludes_corpus_and_model_changes_only_selected_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            config = {"schema": 1, "defaults": {}, "profiles": {
                uid: {"adapter": "grisaia", "game_exe": str(home / (uid + ".exe")),
                      "settings": {"model": "gpt-6.1-sol", "reasoning_effort": "low",
                                   "key_file": "SECRET_PATH_SENTINEL", "proxy": {"host": "localhost"}}}
                for uid in ("one", "two")}}
            (home / "config.json").write_text(json.dumps(config))
            journal_path = home / "games/one/journal.sqlite3"
            with Journal(journal_path) as journal:
                journal.capture("PRIVATE_SYNTHETIC_CORPUS_SENTINEL")
            status = self.control(home, ["status"])
            self.assertEqual(json.loads(status)["counts"], {"pending": 1})
            self.assertNotIn("SECRET_PATH_SENTINEL", status)
            self.assertNotIn("PRIVATE_SYNTHETIC_CORPUS_SENTINEL", status)
            self.control(home, ["select-model", "gpt-6.1-sol", "medium"])
            updated = json.loads((home / "config.json").read_text())
            self.assertEqual(updated["profiles"]["two"], config["profiles"]["two"])
            self.assertEqual(updated["profiles"]["one"]["settings"]["reasoning_effort"], "medium")
            self.assertEqual(updated["profiles"]["one"]["settings"]["proxy"], {"host": "localhost"})
            with Journal(journal_path) as journal:
                self.assertEqual(journal.status()["counts"], {"pending": 1})

    def test_retry_and_new_run_preserve_existing_originals(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            path = self.fixture(home)
            with Journal(path) as journal:
                event = journal.capture("SYNTHETIC_CORPUS_SENTINEL")
                class FailingClient:
                    def translate(self, messages, cache_key):
                        raise TranslationError("request_failed")
                with self.assertRaises(TranslationError):
                    journal.process_one(FailingClient())
            self.assertIn("Retry enabled", self.control(home, ["retry"]))
            self.assertIn("No paused request", self.control(home, ["retry"]))
            self.assertIn("New run:", self.control(home, ["new-run", "--reason", "synthetic replay"]))
            with Journal(path) as journal:
                self.assertEqual(journal.entry(event)["original"], "SYNTHETIC_CORPUS_SENTINEL")
                self.assertEqual(journal.status()["active_run"], 2)

    def test_missing_journal_and_invalid_configuration_fail_without_creating_state(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            self.fixture(home)
            for invalid in (False, True):
                if invalid:
                    (home / "config.json").write_text("{}")
                with contextlib.redirect_stderr(io.StringIO()) as errors, self.assertRaises(SystemExit) as raised:
                    self.control(home, ["status"])
                self.assertEqual(raised.exception.code, 1)
                self.assertNotIn("SECRET_SENTINEL", errors.getvalue())
                self.assertFalse((home / "games").exists())

    def test_real_cli_returns_safe_status_and_nonzero_for_unknown_game(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            path = self.fixture(home)
            with Journal(path) as journal:
                journal.capture("PRIVATE_SYNTHETIC_CORPUS_SENTINEL")
            script = Path(integration_control.__file__)
            for uid, expected in (("one", 0), ("unknown", 1)):
                result = subprocess.run([sys.executable, "-X", "utf8", str(script),
                    "--home", str(home), "--game", uid, "status"], capture_output=True,
                    text=True, timeout=15)
                self.assertEqual(result.returncode, expected)
                self.assertNotIn("SECRET_SENTINEL", result.stdout + result.stderr)
                self.assertNotIn("PRIVATE_SYNTHETIC_CORPUS_SENTINEL", result.stdout + result.stderr)
                if expected == 0:
                    self.assertEqual(json.loads(result.stdout)["counts"], {"pending": 1})

    def test_actual_gobject_honors_workspace_config_and_cache_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            source = Path(__file__).resolve().parents[2] / "src/LunaTranslator"
            environment = dict(os.environ, PYTHONPATH=str(source),
                               LUNA_USERCONFIG_HOME=str(home / "persistent-config"),
                               LUNA_CACHE_HOME=str(home / "persistent-cache"))
            result = subprocess.run([sys.executable, "-X", "utf8", "-c",
                "import gobject,json;print(json.dumps([gobject.getconfig('nested/config.json'),gobject.getcachedir('nested/cache.json')]))"],
                cwd=home, env=environment, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            config, cache = map(Path, json.loads(result.stdout))
            self.assertEqual(config, home / "persistent-config/nested/config.json")
            self.assertEqual(cache, home / "persistent-cache/nested/cache.json")
            self.assertTrue(config.parent.is_dir())
            self.assertTrue(cache.parent.is_dir())
            self.assertFalse((home / "userconfig").exists())
            self.assertFalse((home / "cache").exists())

    def test_workspace_cli_missing_runtime_and_invalid_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            scripts = home / "tools"
            scripts.mkdir()
            original = Path(integration_control.__file__).parent
            for name in ("workspace.py", "workspace_build.py", "workspace_migrate.py"):
                shutil.copy2(original / name, scripts / name)
            for arguments, code in ((["launch"], 1), (["migrate"], 2), (["--help"], 0)):
                result = subprocess.run([sys.executable, str(scripts / "workspace.py"), *arguments],
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, code)
                self.assertNotIn("Traceback", result.stderr)
            self.assertFalse((home / ".local").exists())


if __name__ == "__main__":
    unittest.main()
