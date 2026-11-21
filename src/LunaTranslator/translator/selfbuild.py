from translator.basetranslator import basetrans
from myutils.utils import checkmd5reloadmodule
import gobject
import os


class TS(basetrans):
    @property
    def onlymanual(self):
        return getattr(self.internal, "current_window", False) or super().onlymanual

    @property
    def using_gpt_dict(self):
        return getattr(self.internal, "current_window", False) or super().using_gpt_dict

    def suspend_game(self):
        suspend = getattr(self.internal, "suspend_game", None)
        if suspend:
            suspend()

    def active_game_changed(self):
        changed = getattr(self.internal, "active_game_changed", None)
        if changed:
            changed()

    def stop_lossless(self):
        stop = getattr(self.internal, "stop_lossless", None)
        if stop:
            stop()

    def capture_hook_event(self, *args):
        """Let an opt-in extension own durable capture before the normal queue."""
        self.mayreinit()
        capture = getattr(self.internal, "capture_hook_event", None)
        return bool(capture(*args)) if capture else False

    def capture_selected_hook_text(self, gameuid, text, hook_names):
        capture = getattr(self.internal, "capture_selected_hook_text", None)
        return bool(capture(gameuid, text, hook_names)) if capture else False

    def mayreinit(self):
        if os.environ.get("LUNA_WORKSPACE_HOME"):
            from integrations import luna as module
        else:
            module = checkmd5reloadmodule(gobject.getconfig("selfbuild.py"), "selfbuild")
        if module and (module.TS != self.__lastm):
            previous = self.internal
            self.__lastm = module.TS
            self.internal: basetrans = module.TS("selfbuild")
            self.internal.init()
            stop = getattr(previous, "stop_lossless", None)
            if stop:
                stop()

    def init(self):
        self.internal = None
        self.__lastm = None
        self.mayreinit()

    def langmap(self):
        self.mayreinit()
        if not self.internal:
            return {}
        return self.internal.langmap()

    def translate(self, content):
        self.mayreinit()
        if not self.internal:
            return ""
        if getattr(self.internal, "current_window", False):
            return self.internal.translate_current(content)
        return self.internal.translate(content)
