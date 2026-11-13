"""Boundary and recovery cases using real journals and synthetic hook hosts."""

import hashlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_adapter as harness
from integrations.engine import Journal, TranslationError
from integrations.session import Session
from integrations import TranslationResult


class AdapterEdgeTests(unittest.TestCase):
    setUp = harness.AdapterTests.setUp
    adapter = harness.AdapterTests.adapter
    capture = harness.AdapterTests.capture

    def test_invalid_routes_and_foreign_game_never_enter_journal(self):
        adapter = self.adapter()
        adapter._capture_settings = None
        self.settings["game_exe"] = "relative.exe"
        self.path.write_text(json.dumps(self.settings))
        self.assertFalse(self.capture(adapter, "No approved route"))
        self.settings["game_exe"] = str(self.home / "Other.exe")
        self.path.write_text(json.dumps(self.settings))
        self.assertFalse(self.capture(adapter, "Foreign game"))
        self.assertEqual(adapter.journal.status()["counts"], {})

    def test_missing_route_stops_capture_but_capture_fault_preserves_pending_queue(self):
        adapter = self.adapter()
        adapter._capture_settings = None
        self.path.unlink()
        self.assertFalse(self.capture(adapter, "No fallback route"))
        self.path.write_text(json.dumps(self.settings))
        self.capture(adapter, "Complete queued original")
        adapter.capture_hook_event("game", self.hook, "GrisaiaWindows", self.tp, "invalid")
        adapter._last_notice = None
        notices = []
        adapter._notice_callback = lambda text: (notices.append(text), adapter.stop_lossless())
        Session._run(adapter)
        self.assertIn("paused", notices[0])
        with Journal(self.home / "journal.sqlite3") as reopened:
            self.assertEqual(reopened.status()["counts"], {"pending": 1})

    def test_malformed_packet_matrix_is_retained_and_blocks_worker_readiness(self):
        adapter = self.adapter()
        valid = {"schema": 1, "kind": "window", "serial": 1,
                 "session": "1:synthetic", "text": "Complete", "speaker": ""}
        invalid = [[], {**valid, "schema": 2}, {**valid, "kind": "fragment"},
                   {**valid, "serial": True}, {**valid, "serial": 0},
                   {**valid, "session": 3}, {**valid, "session": "2:foreign"},
                   {**valid, "text": 3}, {**valid, "text": " "}, {**valid, "speaker": None}]
        for packet in invalid:
            self.assertTrue(adapter.capture_hook_event("game", self.hook, "GrisaiaWindows",
                                                       self.tp, json.dumps(packet)))
        rows = (self.home / "capture-fault.jsonl").read_text().splitlines()
        self.assertEqual(len(rows), len(invalid))
        self.assertTrue(all(json.loads(row)["code"] == "invalid_packet" for row in rows))
        self.assertIn("paused", adapter.not_ready(self.settings))
        self.assertEqual(adapter.journal.status()["counts"], {})

    def test_unvalidated_readiness_requests_only_fingerprinted_diagnostic_hooks(self):
        adapter = self.adapter()
        Path(self.game).write_bytes(b"synthetic executable")
        requests = []
        source = SimpleNamespace(gameuid="game", pids={"game": {1}},
                                 Luna_InsertHookCode=lambda *args: requests.append(args))
        self.base.textsource = source
        settings = {**self.settings, "hook_validated": False,
                    "diagnostic_hooks": ["probe"], "diagnostic_exe_sha256": "wrong"}
        self.assertIn("pending", adapter.not_ready(settings))
        self.assertEqual(requests, [])
        settings["diagnostic_exe_sha256"] = hashlib.sha256(b"synthetic executable").hexdigest()
        self.assertIn("pending", adapter.not_ready(settings))
        adapter._prepare_probes(settings)
        self.assertEqual(requests, [(1, "probe")])
        retained = json.loads((self.home / "hook-probe-insertions.jsonl").read_text())
        self.assertEqual(retained["process_id"], 1)
        self.assertEqual(retained["exe_sha256"], settings["diagnostic_exe_sha256"])
        self.assertIsNone(adapter.not_ready(self.settings))

    def test_diagnostic_boundaries_reject_invalid_hooks_and_wrong_host(self):
        adapter = self.adapter()
        adapter._prepare_probes(self.settings)
        adapter._prepare_probes({**self.settings, "hook_validated": False,
                                 "diagnostic_hooks": ["probe"]})
        settings = {**self.settings, "hook_validated": False,
                    "diagnostic_hooks": [""], "diagnostic_exe_sha256": "digest"}
        with self.assertRaises(ValueError):
            adapter._prepare_probes(settings)
        settings["diagnostic_hooks"] = ["probe"]
        adapter._prepare_probes(settings)
        self.base.textsource = SimpleNamespace(gameuid="game", pids={"game": set()},
                                               Luna_InsertHookCode=lambda *args: None)
        adapter._prepare_probes(settings)
        settings["game_exe"] = str(self.home / "Another.exe")
        adapter._prepare_probes(settings)
        self.base.textsource = None
        adapter._prepare_probes(settings)
        self.assertFalse((self.home / "hook-probe-insertions.jsonl").exists())

    def test_legacy_init_is_idempotent_requires_absolute_home_and_rejects_stock_translation(self):
        adapter = self.adapter()
        journal = adapter.journal
        adapter.init()
        self.assertIs(adapter.journal, journal)
        with self.assertRaises(RuntimeError):
            adapter.translate("Use complete-window capture")
        with patch.dict("os.environ", {"LUNA_GRISAIA_HOME": "relative"}):
            with self.assertRaises(RuntimeError):
                self.adapter_type().init()
        constructor = self.adapter_type.__bases__[0].__init__

        class Base:
            def __init__(instance, name):
                instance.name = name

        with patch.dict(constructor.__globals__, {"basetrans": Base}):
            named = self.adapter_type("selfbuild")
        self.assertEqual(named.name, "selfbuild")


class SessionEdgeTests(unittest.TestCase):
    def session(self, folder, settings):
        notices, originals, published = [], [], []
        session = Session(folder, settings, notices.append, originals.append, published.append)
        self.addCleanup(session.journal.close)
        return session, notices, originals, published

    def test_inactive_capture_and_egress_receipt_have_no_dialogue_leak(self):
        with tempfile.TemporaryDirectory() as folder:
            session, notices, originals, published = self.session(folder, lambda: {})
            session._active = lambda: False
            self.assertTrue(session.capture("Ignored inactive dialogue", "one"))
            self.assertEqual(session.journal.status()["counts"], {})
            session._record_egress({"country": "DE"})
            record = json.loads((Path(folder) / "egress.jsonl").read_text())
            self.assertEqual(set(record), {"time", "country"})
            self.assertEqual(record["country"], "DE")
            self.assertEqual(originals, [])
            self.assertIsNone(session.not_ready({}))
            session.journal.close()

    def test_worker_busy_can_be_stopped_without_claiming_or_sending(self):
        with tempfile.TemporaryDirectory() as folder:
            holder = Journal(Path(folder) / "journal.sqlite3")
            holder.claim_worker()
            session, notices, _, _ = self.session(folder, lambda: {})
            session.capture("Waiting safely", "one")
            session.start()
            limit = threading.Event()
            for _ in range(100):
                if notices:
                    break
                limit.wait(.01)
            self.assertIn("previous worker", notices[0])
            session.stop_lossless()
            session._worker.join(2)
            self.assertFalse(session._worker.is_alive())
            self.assertEqual(holder.status()["counts"], {"pending": 1})
            holder.close()

    def test_configuration_failures_notify_safely_and_do_not_send(self):
        for error in (ValueError("private payload"), TranslationError("configuration")):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as folder:
                def settings():
                    raise error
                session, notices, _, _ = self.session(folder, settings)
                session.capture("Retained original", "one")
                session._notice_callback = lambda text: (notices.append(text), session.stop_lossless())
                session._run()
                self.assertEqual(len(notices), 1)
                self.assertNotIn("private payload", notices[0])
                with Journal(Path(folder) / "journal.sqlite3") as reopened:
                    self.assertEqual(reopened.status()["counts"], {"pending": 1})

    def test_completed_latest_is_published_on_restart_before_no_model_notice(self):
        with tempfile.TemporaryDirectory() as folder:
            with Journal(Path(folder) / "journal.sqlite3") as journal:
                journal.capture("Complete original", window_id="one")
                journal.process_one(SimpleNamespace(translate=lambda *args: TranslationResult("Saved result", {})))
            session, notices, _, published = self.session(folder, lambda: {})
            session._notice_callback = lambda text: (notices.append(text), session.stop_lossless())
            session._run()
            self.assertEqual(published[0]["translation"], "Saved result")
            self.assertIn("choose a model", notices[0])

    def test_startup_ownership_failure_closes_journal_and_inactive_worker_exits(self):
        with tempfile.TemporaryDirectory() as folder:
            session, notices, _, _ = self.session(folder, lambda: {})
            with patch.object(session.journal, "claim_worker", side_effect=TranslationError("configuration")):
                with self.assertRaises(TranslationError):
                    session._run()
            self.assertTrue(session.journal._closed)
            self.assertEqual(notices, [])
        with tempfile.TemporaryDirectory() as folder:
            session, notices, _, _ = self.session(folder, lambda: {})
            session.stop_lossless()
            session._run()
            self.assertTrue(session.journal._closed)
            self.assertEqual(notices, [])


if __name__ == "__main__":
    unittest.main()
