import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "LunaTranslator"))

from integrations.configuration import Workspace
from integrations.engine import Journal, TranslationError
from integrations.transport import ClientConfig, ResponsesClient, TranslationResult


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.game = self.home / "game.exe"
        self.data = {"schema": 1, "defaults": {"proxy": {"host": "host", "port": 123}, "nested": [1]},
                     "profiles": {"a": {"adapter": "grisaia", "game_exe": str(self.game),
                                        "settings": {"proxy": {"port": 456}}},
                                  "b": {"adapter": "grisaia", "game_exe": str(self.game), "settings": {}}}}
        self.write()
        self.workspace = Workspace(self.home)

    def write(self):
        (self.home / "config.json").write_text(json.dumps(self.data), encoding="utf-8")

    def test_merge_isolation_and_match(self):
        settings = self.workspace.settings_for("a")
        self.assertEqual(settings["proxy"], {"host": "host", "port": 456})
        settings["nested"].append(2)
        self.assertEqual(self.workspace.settings_for("b")["nested"], [1])
        self.assertEqual(self.workspace.profile_home("a"), self.home / "games" / "a")
        self.assertFalse(self.workspace.profile_home("a").exists())
        self.assertEqual(self.workspace.profile_for_game("a", self.game)["adapter"], "grisaia")
        self.assertIsNone(self.workspace.profile_for_game("a", self.home / "other.exe"))
        self.assertIsNone(self.workspace.profile_for_game("missing", self.game))

    def test_invalid_profiles_and_configuration(self):
        for uid in ("", "../a", "a/b", "a.b", "Ã©"):
            with self.subTest(uid=uid), self.assertRaises(TranslationError):
                self.workspace.profile_home(uid)
        with self.assertRaises(TranslationError):
            self.workspace.settings_for("missing")
        self.data["profiles"]["a"]["settings"] = []
        self.write()
        with self.assertRaises(TranslationError):
            self.workspace.profile_for_game("a", self.game)

    def test_only_selected_profile_is_validated(self):
        for malformed in (None, {}, {"adapter": "grisaia", "game_exe": "relative", "settings": {}},
                          {"adapter": "grisaia", "game_exe": str(self.game), "settings": []}):
            with self.subTest(profile=malformed):
                self.data["profiles"]["a"] = malformed
                self.write()
                self.assertIsNone(self.workspace.profile_for_game("stock", self.game))
                self.assertEqual(self.workspace.profile_for_game("b", self.game)["adapter"], "grisaia")
                for operation in (lambda: self.workspace.profile_for_game("a", self.game),
                                  lambda: self.workspace.settings_for("a"),
                                  lambda: self.workspace.set_model("a", "gpt-6.1-sol", "low")):
                    with self.assertRaises(TranslationError):
                        operation()

    def test_model_is_profile_override(self):
        self.workspace.set_model("a", "gpt-6.1-sol", "high")
        self.assertEqual(self.workspace.settings_for("a")["model"], "gpt-6.1-sol")
        self.assertNotIn("model", self.workspace.settings_for("b"))
        with self.assertRaises(TranslationError):
            self.workspace.set_model("a", "unsupported", "low")

    def test_client_mapping_has_file_failure_contract(self):
        with self.assertRaises(TranslationError) as mapping:
            ClientConfig.from_mapping({})
        with self.assertRaises(TranslationError) as file:
            ClientConfig.from_file(self.home / "missing")
        self.assertEqual(str(mapping.exception), str(file.exception))

    def test_invalid_schema_paths_and_unknown_profile_fail_safely(self):
        with self.assertRaises(TranslationError):
            Workspace("relative")
        for bad in (None, {}, {"schema": True, "defaults": {}, "profiles": {}},
                    {"schema": 2, "defaults": {}, "profiles": {}},
                    {"schema": 1, "defaults": [], "profiles": {}},
                    {"schema": 1, "defaults": {}, "profiles": []}):
            with self.subTest(config=bad):
                self.workspace.config_path.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaises(TranslationError):
                    self.workspace.settings_for("a")
        self.write()
        self.assertIsNone(self.workspace.profile_for_game("a", "relative.exe"))
        self.assertIsNone(self.workspace.profile_for_game("a", None))
        with self.assertRaises(TranslationError):
            self.workspace.set_model("missing", "gpt-6.1-sol", "low")

    def test_atomic_model_write_failure_preserves_original_and_cleans_temporary(self):
        original = self.workspace.config_path.read_bytes()
        with patch("integrations.configuration.os.replace", side_effect=OSError("unavailable")):
            with self.assertRaises(TranslationError):
                self.workspace.set_model("a", "gpt-6.1-sol", "high")
        self.assertEqual(self.workspace.config_path.read_bytes(), original)
        self.assertEqual(list(self.home.iterdir()), [self.workspace.config_path])

    def test_model_write_fails_when_temporary_file_cannot_be_created(self):
        original = self.workspace.config_path.read_bytes()
        with patch("integrations.configuration.tempfile.NamedTemporaryFile", side_effect=OSError("unavailable")):
            with self.assertRaises(TranslationError):
                self.workspace.set_model("a", "gpt-6.1-sol", "low")
        self.assertEqual(self.workspace.config_path.read_bytes(), original)


class CancellationTests(unittest.TestCase):
    def test_route_change_during_preflight_never_reads_key_or_posts(self):
        with tempfile.TemporaryDirectory() as home, Journal(Path(home) / "journal.sqlite3") as journal:
            active = [True]
            requests = []
            config = ClientConfig(str(Path(home) / "missing-key"), "127.0.0.1", 8118,
                                  "PL", "gpt-6.1-sol")

            class Client(ResponsesClient):
                def _request(self, host, method, path, **kwargs):
                    requests.append((host, method))
                    active[0] = False
                    return 200, {"ip": "8.8.8.8", "country_code": "PL"}

            client = Client(config, should_continue=lambda: active[0])
            head = journal.capture("synthetic")
            self.assertIsNone(journal.process_one(client, lambda: active[0]))
            self.assertEqual(requests, [("ipapi.co", "GET")])
            self.assertEqual(journal.entry(head)["state"], "pending")

    def test_cancel_after_claim_before_compaction_sends_no_request(self):
        with tempfile.TemporaryDirectory() as home, Journal(Path(home) / "journal.sqlite3") as journal:
            class Client:
                compact_every = 1
                def compact(self, messages, key):
                    self.fail("Unexpected compaction")
                def translate(self, messages, key):
                    return TranslationResult("translated", {})

            client = Client()
            journal.capture("first")
            journal.process_one(client)
            head = journal.capture("second")
            calls = iter((True, False))
            self.assertIsNone(journal.process_one(client, lambda: next(calls)))
            self.assertEqual(journal.entry(head)["state"], "pending")

    def test_cancel_before_claim_and_after_compaction(self):
        with tempfile.TemporaryDirectory() as home, Journal(Path(home) / "journal.sqlite3") as journal:
            active = [True]

            class Client:
                compact_every = 1
                compact_count = 0
                translate_count = 0

                def translate(self, messages, key):
                    self.translate_count += 1
                    return TranslationResult("translated", {})

                def compact(self, messages, key):
                    self.compact_count += 1
                    active[0] = False
                    return TranslationResult(json.dumps({"reference_updates": {}, "events": "event"}), {})

            client = Client()
            first = journal.capture("first")
            self.assertIsNone(journal.process_one(client, lambda: False))
            self.assertEqual(journal.entry(first)["state"], "pending")
            journal.process_one(client)
            head = journal.capture("second")
            self.assertIsNone(journal.process_one(client, lambda: active[0]))
            self.assertEqual(journal.entry(head)["state"], "pending")
            self.assertEqual(client.translate_count, 1)
            self.assertEqual(client.compact_count, 1)
            active[0] = True
            journal.process_one(client, lambda: active[0])
            self.assertEqual(journal.entry(head)["state"], "completed")
            self.assertEqual(client.compact_count, 1)


if __name__ == "__main__":
    unittest.main()
