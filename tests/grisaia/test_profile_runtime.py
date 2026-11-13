"""Profile lifecycle against real isolated journals and a synthetic client."""

import importlib.util
import ast
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src/LunaTranslator"))
from integrations.engine import Journal
from integrations import TranslationResult


class Signal:
    def __init__(self):
        self.values = []

    def emit(self, *args):
        self.values.append(args)


class ProfileRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.paths = {uid: str(self.home / (uid + ".exe")) for uid in ("A", "B", "stock")}
        self.base = SimpleNamespace(textsource=None, translation_ui=SimpleNamespace(
            displayraw1=Signal(), displayres=Signal()), displayinfomessage=lambda *args: None)
        modules = {}
        for name, values in {
            "gobject": {"base": self.base},
            "myutils.config": {"uid2gamepath": self.paths},
            "translator.basetranslator": {"basetrans": object},
            "gui.rendertext.texttype": {"TranslateColor": lambda name: name},
        }.items():
            module = ModuleType(name)
            module.__dict__.update(values)
            modules[name] = module
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, modules).start()
        patch.dict(os.environ, {"LUNA_WORKSPACE_HOME": str(self.home)}).start()
        spec = importlib.util.spec_from_file_location("integrations.profile_test_luna",
            REPO / "src/LunaTranslator/integrations/luna.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.runtime_type = module.TS
        self.config = {"schema": 1, "defaults": {"hook_code": "test",
            "hook_validated": True, "capture_protocol": "grisaia-windows-v1",
            "model": "gpt-6.1-sol", "reasoning_effort": "low",
            "key_file": str(self.home / "unused-key"), "proxy": {"host": "127.0.0.1", "port": 1},
            "expected_country": "DE"}, "profiles": {uid: {
                "adapter": "grisaia", "game_exe": self.paths[uid], "settings": {}}
                for uid in ("A", "B")}}
        self.write_config()
        self.workers = []
        self.addCleanup(self.finish_workers)

    def write_config(self):
        (self.home / "config.json").write_text(json.dumps(self.config), encoding="utf-8")

    def finish_workers(self):
        for session in self.workers:
            session.stop_lossless()
        for session in self.workers:
            session._worker.join(5)
            self.assertFalse(session._worker.is_alive())

    def runtime(self):
        runtime = self.runtime_type()
        runtime.init()
        self.addCleanup(runtime.stop_lossless)
        return runtime

    def switch(self, runtime, uid):
        runtime.suspend_game()
        self.base.textsource = SimpleNamespace(gameuid=uid) if uid else None
        runtime.active_game_changed()
        if runtime._session is not None:
            self.workers.append(runtime._session)
        return runtime._session

    def capture(self, runtime, uid, serial, text):
        packet = json.dumps({"schema": 1, "kind": "window", "session": "1:synthetic",
                             "serial": serial, "speaker": "", "text": text})
        return runtime.capture_hook_event(uid, "test", "GrisaiaWindows",
                                         SimpleNamespace(processId=1, ctx=2, ctx2=3), packet)

    def wait_for(self, predicate):
        limit = time.monotonic() + 5
        while not predicate() and time.monotonic() < limit:
            threading.Event().wait(.01)
        self.assertTrue(predicate())

    def test_switch_commits_inflight_without_publishing_or_sending_next_and_resumes(self):
        entered, release = threading.Event(), threading.Event()
        calls = []

        class Client:
            def __init__(client, *args, **kwargs):
                pass

            def translate(client, messages, key):
                text = messages[-1]["content"][0]["text"]
                calls.append(text)
                if text == "A first":
                    entered.set()
                    if not release.wait(5):
                        raise RuntimeError("Test barrier timed out")
                return TranslationResult("translated " + text, {})

        patch("integrations.session.ResponsesClient", Client).start()
        runtime = self.runtime()
        first = self.switch(runtime, "A")
        self.capture(runtime, "A", 1, "A first")
        self.assertTrue(entered.wait(5))
        self.capture(runtime, "A", 2, "A queued")
        second = self.switch(runtime, "B")
        self.capture(runtime, "B", 1, "B first")
        self.wait_for(lambda: self.base.currenttranslate == "translated B first")
        release.set()
        first._worker.join(5)
        self.assertFalse(first._worker.is_alive())
        with Journal(self.home / "games/A/journal.sqlite3") as journal:
            self.assertEqual(journal.status()["counts"], {"completed": 1, "pending": 1})
            self.assertEqual(journal.latest_capture()["original"], "A queued")
        self.assertEqual(self.base.currenttranslate, "translated B first")
        self.assertNotIn("A queued", calls)
        self.switch(runtime, "A")
        self.wait_for(lambda: "A queued" in calls)
        self.wait_for(lambda: self.base.currenttranslate == "translated A queued")
        self.assertEqual(calls, ["A first", "B first", "A queued"])
        second.stop_lossless()

    def test_unconfigured_game_and_no_textsource_preserve_stock_capture(self):
        runtime = self.runtime()
        self.assertIsNone(runtime._session)
        self.switch(runtime, "stock")
        self.assertFalse(self.capture(runtime, "stock", 1, "Stock text"))
        self.assertEqual(runtime.translate("Stock text"), "")
        self.assertFalse((self.home / "games/stock").exists())

    def test_malformed_recognized_profile_refuses_stock_fallback(self):
        runtime = self.runtime()
        self.config["profiles"]["A"]["settings"] = []
        self.write_config()
        self.switch(runtime, "A")
        self.assertTrue(runtime._refused)
        self.assertTrue(self.capture(runtime, "A", 1, "Retained by native source"))
        with self.assertRaises(RuntimeError):
            runtime.translate("Unsafe stock fallback")
        self.assertFalse((self.home / "games/A").exists())

    def test_malformed_other_profile_does_not_block_unconfigured_stock_game(self):
        self.config["profiles"]["A"]["settings"] = []
        self.write_config()
        runtime = self.runtime()
        self.switch(runtime, "stock")
        self.assertFalse(runtime._refused)
        self.assertFalse(self.capture(runtime, "stock", 1, "Ordinary stock window"))
        self.assertEqual(runtime.translate("Ordinary stock window"), "")
        self.assertFalse((self.home / "games/stock").exists())

    def test_repeated_activation_keeps_session_and_stale_capture_cannot_cross_games(self):
        self.config["defaults"].pop("model")
        self.write_config()
        runtime = self.runtime()
        runtime.init()
        session = self.switch(runtime, "A")
        runtime.active_game_changed()
        self.assertIs(runtime._session, session)
        self.assertTrue(self.capture(runtime, "B", 1, "Stale B event"))
        self.assertEqual(session.journal.status()["counts"], {})
        with self.assertRaises(RuntimeError):
            runtime.translate("Captured through the ordinary queue")
        self.switch(runtime, "stock")
        self.assertFalse(self.capture(runtime, "A", 1, "Stale inactive A event"))
        runtime.stop_lossless()
        runtime.active_game_changed()
        self.assertIsNone(runtime._session)

    def test_unsupported_profile_refuses_then_valid_profile_recovers(self):
        self.config["profiles"]["A"]["adapter"] = "unsupported"
        self.config["defaults"].pop("model")
        self.write_config()
        runtime = self.runtime()
        self.switch(runtime, "A")
        self.assertTrue(runtime._refused)
        self.config["profiles"]["A"]["adapter"] = "grisaia"
        self.write_config()
        runtime.active_game_changed()
        self.workers.append(runtime._session)
        self.assertFalse(runtime._refused)
        self.assertTrue(self.capture(runtime, "A", 1, "Recovered capture"))
        self.assertEqual(runtime._session.journal.status()["counts"], {"pending": 1})

    def test_lifecycle_notification_retires_session_even_without_preswitch_forwarding(self):
        self.config["defaults"].pop("model")
        self.write_config()
        runtime = self.runtime()
        old = self.switch(runtime, "A")
        self.base.textsource = SimpleNamespace(gameuid="stock")
        runtime.active_game_changed()
        self.assertTrue(old._stop.is_set())
        self.assertIsNone(runtime._session)
        self.assertFalse(self.capture(runtime, "stock", 1, "Stock window"))

    def test_built_dispatcher_resolves_adapter_from_its_assembled_tree(self):
        globals_ = self.runtime_type.init.__globals__
        location = self.home / "dist/LunaTranslator/integrations/luna.py"
        with patch.dict(globals_, {"__file__": str(location)}):
            self.assertEqual(globals_["adapter_path"](), self.home / "dist/extensions/grisaia/adapter.py")

    def test_switch_to_stock_stops_queue_before_any_stock_hook_event(self):
        self.config["defaults"].pop("model")
        self.write_config()
        runtime = self.runtime()
        session = self.switch(runtime, "A")
        self.capture(runtime, "A", 1, "Waiting for model")
        self.switch(runtime, "stock")
        session._worker.join(5)
        self.assertTrue(session._stop.is_set())
        with Journal(self.home / "games/A/journal.sqlite3") as journal:
            self.assertEqual(journal.status()["counts"], {"pending": 1})
        self.assertIsNone(runtime._session)

    def test_real_hook_uid_setter_finishes_guarded_publication_before_switch(self):
        self.config["defaults"].pop("model")
        self.write_config()
        tree = ast.parse((REPO / "src/LunaTranslator/textio/textsource/texthook.py").read_text(encoding="utf-8"))
        host = next(node for node in tree.body if isinstance(node, ast.ClassDef) and
                    any(isinstance(method, ast.FunctionDef) and method.name == "gameuid"
                        for method in node.body))
        methods = [node for node in host.body if isinstance(node, ast.FunctionDef) and node.name == "gameuid"]
        narrow = ast.Module(body=[ast.ClassDef(name="Hook", bases=[], keywords=[], body=methods,
                                              decorator_list=[])], type_ignores=[])
        ast.fix_missing_locations(narrow)
        namespace = {"gobject": SimpleNamespace(base=self.base)}
        exec(compile(narrow, "real_hook_uid_property", "exec"), namespace)
        source = namespace["Hook"]()
        self.base.gameuid = "A"
        self.base.textsource = source
        runtime = self.runtime()
        session = runtime._session
        self.workers.append(session)
        self.base.translators = {"selfbuild": runtime}
        self.capture(runtime, "A", 1, "A publication")
        entered, release, switched = (threading.Event() for _ in range(3))
        original_emit = self.base.translation_ui.displayraw1.emit

        def emit(*args):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Test publication barrier timed out")
            original_emit(*args)

        self.base.translation_ui.displayraw1.emit = emit
        publisher = threading.Thread(target=session._publish, args=({"id": session._latest,
            "original": "A publication", "translation": "A result"},))

        def switch():
            source.gameuid = "stock"
            switched.set()

        switcher = threading.Thread(target=switch)
        publisher.start()
        self.assertTrue(entered.wait(5))
        switcher.start()
        try:
            self.assertFalse(switched.wait(.05))
            self.assertEqual(source.gameuid, "A")
        finally:
            release.set()
            publisher.join(5)
            switcher.join(5)
        self.assertTrue(switched.is_set())
        self.assertEqual(source.gameuid, "stock")
        self.assertIsNone(runtime._session)


if __name__ == "__main__":
    unittest.main()
