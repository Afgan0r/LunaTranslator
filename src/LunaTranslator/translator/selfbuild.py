from translator.basetranslator import basetrans
from myutils.utils import checkmd5reloadmodule
import gobject


class TS(basetrans):
    def stop_lossless(self):
        stop = getattr(self.internal, "stop_lossless", None)
        if stop:
            stop()

    def capture_hook_event(self, *args):
        """Let an opt-in extension own durable capture before the normal queue."""
        self.mayreinit()
        capture = getattr(self.internal, "capture_hook_event", None)
        return bool(capture(*args)) if capture else False

    def mayreinit(self):
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
        return self.internal.translate(content)
