"""Observable capture/reload behavior against a real journal; no network."""

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src/LunaTranslator"))
from translator.grisaia import TranslationResult


class Signal:
    def __init__(self):
        self.values = []

    def emit(self, *values):
        self.values.append(values)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.game = str(self.home / "Grisaia.exe")
        self.hook = "synthetic-full-window-hook"
        self.settings = {"game_exe": self.game, "hook_code": self.hook,
                         "hook_validated": True, "capture_protocol": "grisaia-windows-v1"}
        self.serial = 0
        self.path = self.home / "settings.json"
        self.path.write_text(json.dumps(self.settings), encoding="utf-8")
        self.ui = SimpleNamespace(displayraw1=Signal(), displayres=Signal())
        self.base = SimpleNamespace(translation_ui=self.ui,
                                   displayinfomessage=lambda *args: None,
                                   currenttranslate="")
        modules = {}
        for name, values in {
            "gobject": {"base": self.base},
            "myutils.config": {"uid2gamepath": {"game": self.game}},
            "translator.basetranslator": {"basetrans": object},
            "gui.rendertext.texttype": {"TranslateColor": lambda name: name},
        }.items():
            module = ModuleType(name)
            module.__dict__.update(values)
            modules[name] = module
        self.modules = patch.dict(sys.modules, modules)
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.env = patch.dict(os.environ, {"LUNA_GRISAIA_HOME": str(self.home),
                                          "LUNA_GRISAIA_GAME_EXE": self.game,
                                          "LUNA_GRISAIA_HOOK_CODE": self.hook})
        self.env.start()
        self.addCleanup(self.env.stop)
        spec = importlib.util.spec_from_file_location("grisaia_adapter_test", REPO / "extensions/grisaia/selfbuild.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class NoNetworkAdapter(module.TS):
            def _run(self):
                pass

        self.adapter_type = NoNetworkAdapter
        self.tp = SimpleNamespace(processId=1, ctx=2, ctx2=3)

    def adapter(self):
        adapter = self.adapter_type()
        adapter.init()
        adapter._worker.join(1)
        self.addCleanup(adapter.journal.close)
        return adapter

    def capture(self, adapter, text, speaker="", serial=None, render_revision=None):
        self.serial += 1
        packet = json.dumps({"schema": 1, "kind": "window", "session": "1:123456",
                             "serial": serial or self.serial, "render_revision": render_revision,
                             "text": text, "speaker": speaker})
        return adapter.capture_hook_event("game", self.hook, "GrisaiaWindows", self.tp, packet)

    def test_configuration_outage_retains_new_captures_in_fifo(self):
        adapter = self.adapter()
        self.assertTrue(self.capture(adapter, "First complete window"))
        first = adapter._latest
        self.path.unlink()
        self.assertTrue(self.capture(adapter, "Second complete window"))
        second = adapter._latest
        self.assertEqual(adapter.journal.entry(first)["original"], "First complete window")
        self.assertEqual(adapter.journal.entry(second)["original"], "Second complete window")
        self.assertEqual(adapter.journal.status()["head"]["id"], first)
        self.assertEqual(adapter.journal.status()["counts"], {"pending": 2})

    def test_first_boot_without_settings_retains_raw_events(self):
        self.path.unlink()
        adapter = self.adapter()
        self.assertTrue(self.capture(adapter, "Retained diagnostic window"))
        row = json.loads((self.home / "hook-probe.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(row["text"])["text"], "Retained diagnostic window")
        self.assertEqual(adapter.journal.status()["counts"], {})

    def test_bom_configuration_is_valid_capture_routing(self):
        self.path.write_text(json.dumps(self.settings), encoding="utf-8-sig")
        adapter = self.adapter()
        self.assertTrue(self.capture(adapter, "Captured with BOM configuration"))
        self.assertEqual(adapter.journal.latest_capture()["original"], "Captured with BOM configuration")

    def test_unvalidated_game_streams_are_durable_and_never_enter_api_queue(self):
        self.settings["hook_validated"] = False
        self.path.write_text(json.dumps(self.settings), encoding="utf-8")
        adapter = self.adapter()
        self.assertTrue(adapter.capture_hook_event("game", "rendered-body", "Body", self.tp, "A complete window"))
        self.assertTrue(adapter.capture_hook_event("game", "rendered-name", "Name", self.tp, "Speaker"))
        retained = [json.loads(line) for line in (self.home / "hook-probe.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["text"] for r in retained], ["A complete window", "Speaker"])
        self.assertEqual([r["sequence"] for r in retained], [1, 2])
        self.assertEqual(retained[0]["instance"], retained[1]["instance"])
        self.assertEqual(adapter.journal.status()["counts"], {})

    def test_validated_capture_ignores_an_unselected_stream(self):
        adapter = self.adapter()
        self.assertTrue(adapter.capture_hook_event("game", "other-hook", "Other", self.tp, "Unselected text"))
        self.assertEqual(adapter.journal.status()["counts"], {})
        self.assertFalse((self.home / "hook-probe.jsonl").exists())

    def test_native_serial_suppresses_redraws_and_keeps_real_identical_replies(self):
        adapter = self.adapter()
        self.capture(adapter, "Same reply", "Speaker", serial=1)
        self.capture(adapter, "Same reply", "Speaker", serial=1)
        self.capture(adapter, "Same reply", "Speaker", serial=2)
        newest = adapter._latest
        self.capture(adapter, "Same reply", "Speaker", serial=1)
        self.assertEqual(adapter.journal.status()["counts"], {"pending": 2})
        self.assertEqual(adapter._latest, newest)
        self.assertEqual(len(self.ui.displayraw1.values), 2)

    def test_empty_native_speaker_clears_previous_name(self):
        adapter = self.adapter()
        self.capture(adapter, "A spoken line", "Speaker")
        self.capture(adapter, "A narrative line")
        self.assertEqual(adapter.journal.latest_capture()["original"], "A narrative line")
        self.assertEqual(self.base.currenttext, "A narrative line")

    def test_backlog_restoration_stays_one_capture_but_new_run_accepts_loaded_window(self):
        adapter = self.adapter()
        self.capture(adapter, "Current window", serial=1, render_revision=10)
        self.capture(adapter, "Current window", serial=1, render_revision=12)
        self.capture(adapter, "Current window", serial=1, render_revision=14)
        self.assertEqual(adapter.journal.status()["counts"], {"pending": 1})
        adapter.journal.new_run("Older save loaded")
        self.capture(adapter, "Loaded older window", serial=1, render_revision=16)
        self.capture(adapter, "Loaded older window", serial=1, render_revision=18)
        self.assertEqual(adapter.journal.status()["counts"], {"pending": 2})
        self.assertEqual(adapter.journal.latest_capture()["original"], "Loaded older window")
        self.assertFalse(adapter._capture_fault)
        self.assertEqual(len(self.ui.displayraw1.values), 2)

    def test_changed_text_with_same_identity_is_retained_as_a_fault_and_pauses_capture(self):
        adapter = self.adapter()
        self.capture(adapter, "Original window", serial=1)
        self.capture(adapter, "Unexpected replacement", serial=1)
        self.assertTrue(adapter._capture_fault)
        retained = json.loads((self.home / "capture-fault.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(retained["code"], "window_identity_collision")
        self.assertEqual(json.loads(retained["packet"])["text"], "Unexpected replacement")
        self.assertEqual(adapter.journal.status()["counts"], {"pending": 1})
        self.assertEqual(adapter.journal.latest_capture()["original"], "Original window")
        self.assertEqual(len(self.ui.displayraw1.values), 1)

    def test_native_duplicate_is_suppressed_after_adapter_restart(self):
        adapter = self.adapter()
        self.capture(adapter, "Retained window", serial=1)
        adapter.journal.close()
        replacement = self.adapter()
        self.capture(replacement, "Retained window", serial=1)
        self.assertEqual(replacement.journal.status()["counts"], {"pending": 1})

    def test_capture_fault_survives_restart_and_later_windows_are_retained(self):
        adapter = self.adapter()
        self.assertTrue(adapter.capture_hook_event("game", self.hook, "GrisaiaWindows", self.tp, "invalid packet"))
        self.assertTrue(adapter._capture_fault)
        self.capture(adapter, "Captured after fault")
        adapter.journal.close()
        replacement = self.adapter()
        self.assertTrue(replacement._capture_fault)
        self.assertEqual(replacement.journal.status()["counts"], {"pending": 1})

    def test_stopped_worker_cannot_replace_newer_overlay(self):
        adapter = self.adapter()
        self.capture(adapter, "Older window")
        older_id = adapter._latest
        adapter.stop_lossless()
        replacement = self.adapter()
        self.capture(replacement, "Newer window")
        self.base.currenttranslate = "Newer translation"
        adapter._publish({"id": older_id, "original": "Older window", "translation": "Older translation"})
        self.assertEqual(self.base.currenttranslate, "Newer translation")
        self.assertEqual(self.ui.displayres.values, [])

    def test_pending_window_is_recovered_and_published_after_restart(self):
        adapter = self.adapter()
        self.capture(adapter, "Pending before restart")
        entry_id = adapter._latest
        adapter.journal.close()
        replacement = self.adapter()
        self.assertEqual(replacement._latest, entry_id)
        client = SimpleNamespace(translate=lambda messages, key: TranslationResult("Restored translation", {}))
        result = replacement.journal.process_one(client)
        replacement._publish(result)
        self.assertEqual(self.base.currenttext, "Pending before restart")
        self.assertEqual(self.base.currenttranslate, "Restored translation")
        self.assertEqual(replacement.journal.status()["counts"], {"completed": 1})

    def test_stop_waits_for_publication_already_past_its_guard(self):
        adapter = self.adapter()
        self.capture(adapter, "Older window")
        entered, release, stopping, stopped = (threading.Event() for _ in range(4))
        original_emit = self.ui.displayraw1.emit

        def slow_emit(*values):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Publication barrier timed out")
            original_emit(*values)

        self.ui.displayraw1.emit = slow_emit
        publisher = threading.Thread(target=adapter._publish,
            args=({"id": adapter._latest, "original": "Older window", "translation": "Older translation"},))

        def stop():
            stopping.set()
            adapter.stop_lossless()
            stopped.set()

        stopper = threading.Thread(target=stop)
        publisher.start()
        self.assertTrue(entered.wait(5))
        stopper.start()
        self.assertTrue(stopping.wait(5))
        try:
            self.assertFalse(stopped.wait(0.1))
        finally:
            release.set()
            publisher.join(5)
            stopper.join(5)
        self.assertFalse(publisher.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertTrue(stopped.is_set())
        self.base.currenttranslate = "Newer translation"
        adapter._publish({"id": adapter._latest, "original": "Older window", "translation": "Late old result"})
        self.assertEqual(self.base.currenttranslate, "Newer translation")


if __name__ == "__main__":
    unittest.main()
