"""Luna bridge selecting isolated sessions from the active game's profile."""

import importlib.util
import os
import sqlite3
import threading
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol, cast

import gobject
from myutils.config import uid2gamepath
from translator.basetranslator import basetrans

from .configuration import Workspace
from .glossary import add_glossary_entries
from .glossary_history import journal_speaker_terms
from .transport import JsonObject


class TextSource(Protocol):
    gameuid: str | None
    runonce_line: str


class OverlaySignal(Protocol):
    def emit(self, *args: object) -> None: ...


class Overlay(Protocol):
    displayraw1: OverlaySignal
    displayres: OverlaySignal


class LunaRuntime(Protocol):
    currenttext: str
    currenttext_raw: str
    currenttranslate: str
    currenttranslate_1: str
    currentsignature: uuid.UUID
    translation_ui: Overlay

    def displayinfomessage(self, text: str, infotype: str) -> None: ...


def luna_base() -> LunaRuntime:
    return cast(LunaRuntime, gobject.base)


class ProfileSettings(Protocol):
    def profile_for_game(self, uid: str, gamepath: str | None) -> JsonObject | None: ...
    def profile_home(self, uid: str) -> Path: ...
    def settings_for(self, uid: str) -> JsonObject: ...


class GameSession(Protocol):
    current_window: bool
    stock_capture: bool

    def configure_capture(
        self, gamepath: Callable[[str], str | None], source: Callable[[], TextSource | None]
    ) -> None: ...
    def capture_hook_event(
        self, gameuid: str, hookcode: str, hookname: str, tp: object, text: str
    ) -> bool: ...
    def capture_selected_hook_text(self, text: str, hook_names: tuple[str, ...]) -> bool: ...
    def translate_current(self, original: str, entries: list[dict[str, object]]) -> str: ...
    def start(self) -> None: ...
    def stop_lossless(self) -> None: ...


class AdapterFactory(Protocol):
    def __call__(
        self,
        home: Path,
        settings: Callable[[], Mapping[str, Any]],
        notice: Callable[[str], None],
        original: Callable[[str], None],
        publish: Callable[[JsonObject], None],
        *,
        active: Callable[[], bool],
        current_window: bool = False,
    ) -> GameSession: ...


def adapter_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    if root.name == "src" and (root.parent / "extensions/grisaia/adapter.py").is_file():
        root = root.parent
    return root / "extensions/grisaia/adapter.py"


def load_adapter() -> AdapterFactory:
    spec = importlib.util.spec_from_file_location("luna_profile_grisaia", adapter_path())
    if spec is None or spec.loader is None:
        raise ImportError("Could not load the Grisaia adapter.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(AdapterFactory, module.Adapter)


class TS(basetrans):
    def init(self) -> None:
        if getattr(self, "_profile_initialized", False):
            return
        self.workspace = cast(ProfileSettings, Workspace(os.environ.get("LUNA_WORKSPACE_HOME", "")))
        self._switch_lock = threading.RLock()
        self._session: GameSession | None = None
        self._uid: str | None = None
        self._refused = False
        self._stopped = False
        self._last_notice: str | None = None
        self._profile_initialized = True
        self.active_game_changed()

    @staticmethod
    def _source() -> TextSource | None:
        return cast(TextSource | None, getattr(gobject.base, "textsource", None))

    def _active_uid(self) -> str | None:
        source = self._source()
        return source.gameuid if source is not None else None

    @property
    def current_window(self) -> bool:
        session = self._session
        return session is not None and session.current_window

    def _notice(self, text: str) -> None:
        if self._last_notice != text:
            luna_base().displayinfomessage(text, "<msg_error_Translator>")
            self._last_notice = text

    def active_game_changed(self) -> None:
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

                def gamepath(key: str) -> str | None:
                    return cast(str | None, uid2gamepath[key])

                profile = self.workspace.profile_for_game(uid, gamepath(uid))
                if profile is None:
                    return
                if profile["adapter"] != "grisaia":
                    raise ValueError("Unsupported adapter")
                current_window = profile["settings"].get("translation_mode") == "current_window"
                adapter = load_adapter()
                session = adapter(
                    self.workspace.profile_home(uid),
                    lambda: self.workspace.settings_for(uid),
                    self._notice,
                    self._current_original if current_window else self._original,
                    self._publish,
                    active=lambda: (
                        not self._stopped and self._session is session and self._active_uid() == uid
                    ),
                    current_window=current_window,
                )
                session.configure_capture(gamepath, self._source)
                self._session = session
                session.start()
            except Exception:
                self._refused = True
                self._notice(
                    "Integration: game profile unavailable. Stop advancing; custom capture is blocked."
                )

    def suspend_game(self) -> None:
        # Finish publication already inside its guard before the host changes UID.
        with self._switch_lock:
            previous = self._session
            self._session = None
            self._uid = None
            if previous is not None:
                previous.stop_lossless()

    def capture_hook_event(
        self, gameuid: str, hookcode: str, hookname: str, tp: object, text: str
    ) -> bool:
        self.active_game_changed()
        if gameuid != self._active_uid():
            return bool(self._session or self._refused)
        if self._refused:
            return True
        session = self._session
        if session:
            handled = session.capture_hook_event(gameuid, hookcode, hookname, tp, text)
            return handled or not session.stock_capture
        return False

    def capture_selected_hook_text(
        self, gameuid: str, text: str, hook_names: tuple[str, ...]
    ) -> bool:
        session = self._session
        return bool(
            session is not None
            and gameuid == self._active_uid() == self._uid
            and session.capture_selected_hook_text(text, hook_names)
        )

    def _current_original(self, original: str) -> None:
        self._last_notice = None
        source = self._source()
        if source is not None:
            source.runonce_line = original
        luna_base().currentsignature = uuid.uuid4()
        self._original(original)

    @staticmethod
    def _original(original: str) -> None:
        base = luna_base()
        base.currenttext = original
        base.currenttext_raw = original
        base.currenttranslate = ""
        base.currenttranslate_1 = ""
        base.translation_ui.displayraw1.emit(original, True, True)

    def _publish(self, entry: JsonObject) -> None:
        from gui.rendertext.texttype import TranslateColor

        base = luna_base()
        self._original(entry["original"])
        base.currenttranslate = entry["translation"]
        base.currenttranslate_1 = entry["translation"]
        base.translation_ui.displayres.emit(
            dict(
                name="Grisaia · OpenAI",
                color=TranslateColor("selfbuild"),
                res=entry["translation"],
                iter_context=(0, "selfbuild"),
                klass="selfbuild",
                is_auto_run=True,
            )
        )
        self._last_notice = None

    def translate_current(self, content: object) -> str:
        self.active_game_changed()
        session = self._session
        uid = self._uid
        if session is not None and session.current_window and uid is not None:
            original = getattr(content, "rawtext", content)
            if not isinstance(original, str):
                return ""
            from myutils import config as luna_config

            games = cast(dict[str, JsonObject], vars(luna_config)["savehook_new_data"])
            game = games[uid]
            raw_entries = game.setdefault("noundictconfig_ex", [])
            if not isinstance(raw_entries, list):
                raise RuntimeError("Invalid game glossary.")
            entries = cast(list[dict[str, object]], raw_entries)
            if not game.get("current_window_glossary_seeded"):
                try:
                    for pair in journal_speaker_terms(
                        self.workspace.profile_home(uid) / "journal.sqlite3"
                    ):
                        add_glossary_entries(entries, [pair])
                except (OSError, sqlite3.Error):
                    self._notice("Integration: Earlier speaker forms could not be imported.")
                else:
                    game["current_window_glossary_seeded"] = True
            return session.translate_current(original, entries)
        return ""

    def translate(self, content: object):
        self.active_game_changed()
        if self._session is not None or self._refused:
            raise RuntimeError(
                "Select the configured full-window hook; use the Retry control for recovery."
            )
        return ""

    def stop_lossless(self) -> None:
        self._stopped = True
        if self._session is not None:
            self._session.stop_lossless()
