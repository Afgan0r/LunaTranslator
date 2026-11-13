"""Luna bridge selecting isolated sessions from the active game's profile."""

import importlib.util
import os
import threading
from pathlib import Path

import gobject
from myutils.config import uid2gamepath
from translator.basetranslator import basetrans

from .configuration import Workspace


def adapter_path():
    root = Path(__file__).resolve().parents[2]
    if root.name == "src" and (root.parent / "extensions/grisaia/adapter.py").is_file():
        root = root.parent
    return root / "extensions/grisaia/adapter.py"


def load_adapter():
    spec = importlib.util.spec_from_file_location("luna_profile_grisaia", adapter_path())
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Adapter


class TS(basetrans):
    def init(self):
        if getattr(self, "_profile_initialized", False):
            return
        self.workspace = Workspace(os.environ.get("LUNA_WORKSPACE_HOME", ""))
        self._switch_lock = threading.RLock()
        self._session = None
        self._uid = None
        self._refused = False
        self._stopped = False
        self._last_notice = None
        self._profile_initialized = True
        self.active_game_changed()

    @staticmethod
    def _source():
        return getattr(gobject.base, "textsource", None)

    def _active_uid(self):
        return getattr(self._source(), "gameuid", None)

    def _notice(self, text):
        if self._last_notice != text:
            gobject.base.displayinfomessage(text, "<msg_error_Translator>")
            self._last_notice = text

    def active_game_changed(self):
        if self._stopped:
            return
        uid = self._active_uid()
        with self._switch_lock:
            if self._session is not None and uid == self._uid:
                return
            previous = self._session
            self._session = None
            self._uid = uid
            self._refused = False
            if previous is not None:
                previous.stop_lossless()
            if not uid:
                return
            try:
                profile = self.workspace.profile_for_game(uid, uid2gamepath[uid])
                if profile is None:
                    return
                if profile["adapter"] != "grisaia":
                    raise ValueError("Unsupported adapter")
                adapter = load_adapter()
                session = adapter(
                    self.workspace.profile_home(uid), lambda: self.workspace.settings_for(uid),
                    self._notice, self._original, self._publish,
                    active=lambda: (not self._stopped and self._session is session
                                    and self._active_uid() == uid),
                )
                session.configure_capture(lambda key: uid2gamepath[key], self._source)
                self._session = session
                session.start()
            except Exception:
                self._refused = True
                self._notice("Integration: game profile unavailable. Stop advancing; custom capture is blocked.")

    def suspend_game(self):
        # Finish publication already inside its guard before the host changes UID.
        with self._switch_lock:
            previous = self._session
            self._session = None
            self._uid = None
            if previous is not None:
                previous.stop_lossless()

    def capture_hook_event(self, gameuid, *args):
        self.active_game_changed()
        if gameuid != self._active_uid():
            return bool(self._session or self._refused)
        if self._refused:
            return True
        session = self._session
        if session:
            session.capture_hook_event(gameuid, *args)
            return True
        return False

    @staticmethod
    def _original(original):
        base = gobject.base
        base.currenttext = original
        base.currenttext_raw = original
        base.currenttranslate = ""
        base.currenttranslate_1 = ""
        base.translation_ui.displayraw1.emit(original, True, True)

    def _publish(self, entry):
        from gui.rendertext.texttype import TranslateColor

        base = gobject.base
        self._original(entry["original"])
        base.currenttranslate = entry["translation"]
        base.currenttranslate_1 = entry["translation"]
        base.translation_ui.displayres.emit(
            dict(name="Grisaia · OpenAI", color=TranslateColor("selfbuild"),
                 res=entry["translation"], iter_context=(0, "selfbuild"),
                 klass="selfbuild", is_auto_run=True)
        )
        self._last_notice = None

    def translate(self, content):
        self.active_game_changed()
        if self._session or self._refused:
            raise RuntimeError("Select the configured full-window hook; use the Retry control for recovery.")
        return ""

    def stop_lossless(self):
        self._stopped = True
        if self._session is not None:
            self._session.stop_lossless()
