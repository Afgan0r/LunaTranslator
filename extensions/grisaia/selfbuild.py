"""Legacy private-home bridge; new launches use integrations.luna."""

import importlib.util
import json
import os
from pathlib import Path

import gobject
from myutils.config import uid2gamepath
from translator.basetranslator import basetrans
from integrations.session import Session


def load_adapter(path):
    spec = importlib.util.spec_from_file_location("luna_grisaia_capture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Adapter


Adapter = load_adapter(Path(__file__).with_name("adapter.py"))


class TS(Adapter, basetrans):
    def __init__(self, *args, **kwargs):
        if args or kwargs:
            basetrans.__init__(self, *args, **kwargs)

    def init(self):
        if getattr(self, "_grisaia_initialized", False):
            return
        home = Path(os.environ.get("LUNA_GRISAIA_HOME", ""))
        if not home.is_absolute():
            raise RuntimeError("Launch with an absolute LUNA_GRISAIA_HOME outside Git.")
        self.settings_path = home / "settings.json"
        Session.__init__(self, home, self._read_settings, self._notice_ui,
                         self._original_ui, self._publish_ui)
        game = os.environ.get("LUNA_GRISAIA_GAME_EXE")
        hook = os.environ.get("LUNA_GRISAIA_HOOK_CODE")
        fallback = {"game_exe": game, "hook_code": hook, "hook_validated": False} if (
            game and Path(game).is_absolute() and hook) else None
        self.configure_capture(lambda uid: uid2gamepath[uid],
                               lambda: getattr(gobject.base, "textsource", None), fallback)
        self._grisaia_initialized = True
        self.start()

    def _read_settings(self):
        return json.loads(self.settings_path.read_text(encoding="utf-8-sig"))

    def _notice_ui(self, text):
        gobject.base.displayinfomessage(text, "<msg_error_Translator>")

    def _original_ui(self, original):
        base = gobject.base
        base.currenttext = original
        base.currenttext_raw = original
        base.currenttranslate = ""
        base.currenttranslate_1 = ""
        base.translation_ui.displayraw1.emit(original, True, True)

    def _publish_ui(self, entry):
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

    def translate(self, content):
        raise RuntimeError("Select the configured Grisaia full-window hook. Use the external Retry control.")
