"""Install as userconfig/selfbuild.py; all private state lives outside Git."""

import hashlib
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
        self._probe_requests = set()
        self._capture_fault = (self.home / "capture-fault.jsonl").exists()
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

    def _record_egress(self, public):
        # Called only after this client's route passed, before reading its key.
        with (self.home / "egress.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": time.time(), **public}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _capture_route(self):
        try:
            current = self._settings()
            game, hook = current["game_exe"], current["hook_code"]
            if not isinstance(game, str) or not Path(game).is_absolute() or not isinstance(hook, str) or not hook:
                raise ValueError("Invalid capture routing")
            self._capture_settings = {"game_exe": game, "hook_code": hook,
                                      "hook_validated": current.get("hook_validated", False) is True,
                                      "capture_protocol": current.get("capture_protocol")}
        except Exception:
            self._notice("Grisaia: request configuration unavailable; using the last approved capture route."
                         if self._capture_settings else
                         "Grisaia: capture route unavailable. Stop advancing the game.")
        return self._capture_settings

    def _notice(self, text):
        if text != self._last_notice:
            gobject.base.displayinfomessage(text, "<msg_error_Translator>")
            self._last_notice = text

    def _retain_capture_fault(self, text, code="invalid_packet"):
        # Call under _capture_lock; retain the rejected original before pausing.
        self._capture_fault = True
        with (self.home / "capture-fault.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": time.time(), "code": code, "packet": text}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _prepare_probes(self, settings):
        """Request opt-in diagnostic hooks only for the fingerprinted game."""
        hooks = settings.get("diagnostic_hooks", [])
        expected = settings.get("diagnostic_exe_sha256")
        if not hooks or not expected or settings.get("hook_validated", False):
            return
        if not isinstance(hooks, list) or not all(isinstance(h, str) and h for h in hooks):
            raise ValueError("Invalid diagnostic hooks")
        source = getattr(gobject.base, "textsource", None)
        if source is None or not hasattr(source, "Luna_InsertHookCode"):
            return
        gamepath = uid2gamepath[source.gameuid] or ""
        if os.path.normcase(gamepath) != os.path.normcase(settings["game_exe"]):
            return
        pids = source.pids.get(source.gameuid, set()).copy()
        requests = [(pid, hook) for pid in pids for hook in hooks
                    if (pid, hook) not in self._probe_requests]
        if not requests:
            return
        if hashlib.sha256(Path(gamepath).read_bytes()).hexdigest() != expected:
            self._notice("Grisaia: diagnostic hooks blocked; executable fingerprint changed.")
            return
        for pid, hook in requests:
            # The host call is void: this records a request, not proof of capture.
            source.Luna_InsertHookCode(pid, hook)
            self._probe_requests.add((pid, hook))
            with (self.home / "hook-probe-insertions.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"time": time.time(), "process_id": pid,
                                         "hook": hook, "exe_sha256": expected}) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

    def capture_hook_event(self, gameuid, hookcode, hookname, tp, text):
        settings = self._capture_route()
        if settings is None:
            return False
        gamepath = uid2gamepath[gameuid] or ""
        if os.path.normcase(gamepath) != os.path.normcase(settings["game_exe"]):
            return False
        validated = (settings.get("hook_validated", False) and
                     settings.get("capture_protocol") == "grisaia-windows-v1")
        if not validated:
            # Inspect every stream of this game, including its built-in
            # rendered-text/name hook, until window semantics are verified.
            # Raw probe events are retained separately until their window
            # boundaries have been verified. They never become API requests.
            with self._capture_lock:
                self._sequence += 1
                row = {"time": time.time(), "sequence": self._sequence,
                       "instance": self._instance, "address": getattr(tp, "addr", 0),
                       "hook": hookcode, "name": hookname, "text": text,
                       "process_id": tp.processId, "context": tp.ctx,
                       "context2": tp.ctx2}
                with (self.home / "hook-probe.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            return True
        # Consume this game's other streams before Luna's lossy stock queue.
        if hookname != "GrisaiaWindows":
            return True
        try:
            packet = json.loads(text)
            if (packet.get("schema") != 1 or packet.get("kind") != "window" or
                    type(packet.get("serial")) is not int or packet["serial"] <= 0 or
                    not isinstance(packet.get("session"), str) or
                    not packet["session"].startswith(str(tp.processId) + ":") or
                    not isinstance(packet.get("text"), str) or not packet["text"].strip() or
                    not isinstance(packet.get("speaker"), str)):
                raise ValueError("Invalid window packet")
            original = (packet["speaker"] + ":\n" if packet["speaker"] else "") + packet["text"]
            occurrence = "%s:%s" % (packet["session"], packet["serial"])
        except (ValueError, TypeError, AttributeError, KeyError):
            with self._capture_lock:
                self._retain_capture_fault(text)
            self._notice("Grisaia: native window capture failed. Stop advancing; the API queue is paused.")
            return True
        with self._capture_lock:
            entry_id = self.journal.capture(original, window_id=occurrence, deduplicate_all=True)
            if self.journal.entry(entry_id)["original"] != original:
                self._retain_capture_fault(text, "window_identity_collision")
                self._notice("Grisaia: native window capture failed. Stop advancing; the API queue is paused.")
                return True
            if self._latest is not None and entry_id <= self._latest:
                return True
            self._latest = entry_id
            base = gobject.base
            base.currenttext = original
            base.currenttext_raw = original
            base.currenttranslate = ""
            base.currenttranslate_1 = ""
            base.translation_ui.displayraw1.emit(original, True, True)
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
                    if self._capture_fault:
                        self._notice("Grisaia: native window capture failed. Stop advancing; the API queue is paused.")
                    elif (not settings.get("hook_validated", False) or
                          settings.get("capture_protocol") != "grisaia-windows-v1"):
                        self._prepare_probes(settings)
                        self._notice("Grisaia: hook validation pending; raw events are retained separately.")
                    elif not settings.get("model"):
                        self._notice("Grisaia: choose a model after the benchmark; captures are retained.")
                    else:
                        config = ClientConfig.from_file(self.settings_path)
                        if config != previous_config:
                            client = ResponsesClient(config, on_egress=self._record_egress)
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
