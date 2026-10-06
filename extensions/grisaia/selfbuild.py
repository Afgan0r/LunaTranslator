"""Install as userconfig/selfbuild.py; all private state lives outside Git."""

import json
import os
import threading
import time
import uuid
from pathlib import Path

import gobject
from myutils.config import uid2gamepath
from translator.basetranslator import basetrans
from translator.grisaia.engine import Journal, TranslationError
from translator.grisaia.transport import ClientConfig, ResponsesClient


class TS(basetrans):
    def init(self):
        # Luna calls this once from the constructor and again from its wrapper.
        if getattr(self, "_grisaia_initialized", False):
            return
        self.home = Path(os.environ.get("LUNA_GRISAIA_HOME", ""))
        if not self.home.is_absolute():
            raise RuntimeError("Launch with an absolute LUNA_GRISAIA_HOME outside Git.")
        self.settings_path = self.home / "settings.json"
        self.journal = Journal(self.home / "journal.sqlite3")
        self._capture_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._instance = uuid.uuid4().hex
        self._sequence = 0
        latest = self.journal.latest_capture()
        self._latest = latest["id"] if latest else None
        self._last_notice = None
        self._capture_settings = None
        game = os.environ.get("LUNA_GRISAIA_GAME_EXE")
        hook = os.environ.get("LUNA_GRISAIA_HOOK_CODE")
        if game and Path(game).is_absolute() and hook:
            self._capture_settings = {"game_exe": game, "hook_code": hook, "hook_validated": False}
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._grisaia_initialized = True
        self._worker.start()

    def _settings(self):
        return json.loads(self.settings_path.read_text(encoding="utf-8-sig"))

    def _capture_route(self):
        try:
            current = self._settings()
            game, hook = current["game_exe"], current["hook_code"]
            if not isinstance(game, str) or not Path(game).is_absolute() or not isinstance(hook, str) or not hook:
                raise ValueError("Invalid capture routing")
            self._capture_settings = {"game_exe": game, "hook_code": hook,
                                      "hook_validated": current.get("hook_validated", False) is True}
        except Exception:
            self._notice("Grisaia: request configuration unavailable; using the last approved capture route."
                         if self._capture_settings else
                         "Grisaia: capture route unavailable. Stop advancing the game.")
        return self._capture_settings

    def _notice(self, text):
        if text != self._last_notice:
            gobject.base.displayinfomessage(text, "<msg_error_Translator>")
            self._last_notice = text

    def capture_hook_event(self, gameuid, hookcode, hookname, tp, text):
        settings = self._capture_route()
        if settings is None:
            return False
        gamepath = uid2gamepath[gameuid] or ""
        if os.path.normcase(gamepath) != os.path.normcase(settings["game_exe"]):
            return False
        if hookcode != settings.get("hook_code"):
            return False
        if not settings.get("hook_validated", False):
            # Raw probe events are retained separately until their window
            # boundaries have been verified. They never become API requests.
            with self._capture_lock:
                self._sequence += 1
                row = {"time": time.time(), "sequence": self._sequence,
                       "hook": hookcode, "name": hookname, "text": text,
                       "process_id": tp.processId, "context": tp.ctx,
                       "context2": tp.ctx2}
                with (self.home / "hook-probe.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            return True
        # The configured FULL_STRING script hook emits completed occurrences.
        # An occurrence is not a text hash: identical script lines stay distinct.
        with self._capture_lock:
            self._sequence += 1
            occurrence = "%s:%s" % (self._instance, self._sequence)
            self._latest = self.journal.capture(text, window_id=occurrence)
            base = gobject.base
            base.currenttext = text
            base.currenttext_raw = text
            base.currenttranslate = ""
            base.currenttranslate_1 = ""
            base.translation_ui.displayraw1.emit(text, True, True)
            self._wake.set()
        return True

    def _publish(self, entry):
        # Commit happened before this call. Advancing the game hides old results,
        # but never discards them from the occurrence journal or API history.
        with self._capture_lock:
            if self._stop.is_set() or entry["id"] != self._latest:
                return
            from gui.rendertext.texttype import TranslateColor

            base = gobject.base
            text = entry["translation"]
            base.currenttext = entry["original"]
            base.currenttext_raw = entry["original"]
            base.translation_ui.displayraw1.emit(entry["original"], True, True)
            base.currenttranslate = text
            base.currenttranslate_1 = text
            base.translation_ui.displayres.emit(
                dict(name="Grisaia · OpenAI", color=TranslateColor("selfbuild"),
                     res=text, iter_context=(0, "selfbuild"), klass="selfbuild",
                     is_auto_run=True)
            )
            self._last_notice = None

    def _run(self):
        client = None
        previous_config = None
        try:
            while not self._stop.is_set():
                try:
                    self.journal.claim_worker()
                    latest = self.journal.latest_capture()
                    if latest and latest["state"] == "completed":
                        self._publish(latest)
                    break
                except TranslationError as error:
                    if error.code != "worker_busy":
                        raise
                    self._notice("Grisaia: waiting for the previous worker to finish.")
                    self._stop.wait(0.5)
            while not self._stop.is_set():
                try:
                    settings = self._settings()
                    if not settings.get("hook_validated", False):
                        self._notice("Grisaia: hook validation pending; raw events are retained separately.")
                    elif not settings.get("model"):
                        self._notice("Grisaia: choose a model after the benchmark; captures are retained.")
                    else:
                        config = ClientConfig.from_file(self.settings_path)
                        if config != previous_config:
                            client = ResponsesClient(config)
                            previous_config = config
                        result = self.journal.process_one(client)
                        if result:
                            self._publish(result)
                            continue
                except TranslationError as error:
                    self._notice("Grisaia: %s. Queue stopped; use Retry." % error)
                except Exception:
                    # Config/key/route errors must not leak file contents.
                    self._notice("Grisaia: request configuration is unavailable; captures use the approved route."
                                 if self._capture_settings else
                                 "Grisaia: capture route unavailable. Stop advancing the game.")
                self._wake.wait(0.5)
                self._wake.clear()
        finally:
            self.journal.close()

    def translate(self, content):
        raise RuntimeError("Select the configured Grisaia full-window hook. Use the external Retry control.")

    def stop_lossless(self):
        # A replacement must wait for any publication already past its guard.
        with self._capture_lock:
            self._stop.set()
        self._wake.set()
