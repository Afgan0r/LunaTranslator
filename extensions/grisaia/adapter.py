"""Grisaia-specific capture validation and diagnostic hooks."""

import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol, cast

from integrations.session import Session
from integrations.transport import JsonObject

QUEUE_PAUSED = "Grisaia: native window capture failed. Stop advancing; the API queue is paused."


class ProbeSource(Protocol):
    gameuid: str
    pids: dict[str, set[int]]

    def Luna_InsertHookCode(self, pid: int, hook: str) -> None: ...


class HookThread(Protocol):
    processId: int
    ctx: int
    ctx2: int


class Adapter(Session):
    def configure_capture(
        self,
        gamepath: Callable[[str], str | None],
        source: Callable[[], ProbeSource | None],
        fallback: JsonObject | None = None,
    ) -> None:
        self._gamepath = gamepath
        self._source = source
        self._capture_settings = fallback
        self._instance = uuid.uuid4().hex
        self._sequence = 0
        self._probe_requests: set[tuple[int, str]] = set()
        self.stock_capture = (
            self.current_window and self._settings().get("capture_protocol") == "luna-stock"
        )
        self._capture_fault = (
            not self.current_window and (self.home / "capture-fault.jsonl").exists()
        )

    def not_ready(self, settings: Mapping[str, object]) -> str | None:
        if self.stock_capture:
            return None
        if self._capture_fault:
            return QUEUE_PAUSED
        if (
            not settings.get("hook_validated", False)
            or settings.get("capture_protocol") != "grisaia-windows-v1"
        ):
            self._prepare_probes(settings)
            return "Grisaia: hook validation pending; raw events are retained separately."
        return None

    def _capture_route(self) -> JsonObject | None:
        try:
            current = self._settings()
            game, hook = current["game_exe"], current["hook_code"]
            if (
                not isinstance(game, str)
                or not Path(game).is_absolute()
                or not isinstance(hook, str)
                or not hook
            ):
                raise ValueError("Invalid capture routing")
            self._capture_settings = {
                "game_exe": game,
                "hook_code": hook,
                "hook_validated": current.get("hook_validated", False) is True,
                "capture_protocol": current.get("capture_protocol"),
            }
        except Exception:
            self._notice(
                "Grisaia: request configuration unavailable; using the last approved capture route."
                if self._capture_settings
                else "Grisaia: capture route unavailable. Stop advancing the game."
            )
        return self._capture_settings

    def _retain_capture_fault(self, text: str, code: str = "invalid_packet") -> None:
        # Call under _capture_lock. Only the durable queue needs a persistent pause.
        if self.current_window:
            self.discard_current_window()
            self._notice("Grisaia: waiting for a complete dialogue window.")
        else:
            self._capture_fault = True
            self._notice(QUEUE_PAUSED)
        with (self.home / "capture-fault.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": time.time(), "code": code, "packet": text}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _prepare_probes(self, settings: Mapping[str, object]) -> None:
        """Request opt-in diagnostic hooks only for the fingerprinted game."""
        hooks = settings.get("diagnostic_hooks", [])
        expected = settings.get("diagnostic_exe_sha256")
        if not hooks or not expected or settings.get("hook_validated", False):
            return
        if not isinstance(hooks, list) or not all(
            isinstance(h, str) and h for h in cast(list[object], hooks)
        ):
            raise ValueError("Invalid diagnostic hooks")
        source = self._source()
        if source is None or not hasattr(source, "Luna_InsertHookCode"):
            return
        gamepath = self._gamepath(source.gameuid) or ""
        if os.path.normcase(gamepath) != os.path.normcase(cast(str, settings["game_exe"])):
            return
        pids = source.pids.get(source.gameuid, set()).copy()
        requests = [
            (pid, hook)
            for pid in pids
            for hook in cast(list[str], hooks)
            if (pid, hook) not in self._probe_requests
        ]
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
                stream.write(
                    json.dumps(
                        {
                            "time": time.time(),
                            "process_id": pid,
                            "hook": hook,
                            "exe_sha256": expected,
                        }
                    )
                    + "\n"
                )
                stream.flush()
                os.fsync(stream.fileno())

    def capture_hook_event(
        self, gameuid: str, hookcode: str, hookname: str, tp: HookThread, text: str
    ) -> bool:
        if self.stock_capture:
            return hookname != "CatSystem2"
        settings = self._capture_route()
        if settings is None:
            return False
        gamepath = self._gamepath(gameuid) or ""
        if os.path.normcase(gamepath) != os.path.normcase(settings["game_exe"]):
            return False
        validated = (
            settings.get("hook_validated", False)
            and settings.get("capture_protocol") == "grisaia-windows-v1"
        )
        if not validated:
            # Inspect every stream of this game, including its built-in
            # rendered-text/name hook, until window semantics are verified.
            # Raw probe events are retained separately until their window
            # boundaries have been verified. They never become API requests.
            with self._capture_lock:
                self._sequence += 1
                row = {
                    "time": time.time(),
                    "sequence": self._sequence,
                    "instance": self._instance,
                    "address": getattr(tp, "addr", 0),
                    "hook": hookcode,
                    "name": hookname,
                    "text": text,
                    "process_id": tp.processId,
                    "context": tp.ctx,
                    "context2": tp.ctx2,
                }
                with (self.home / "hook-probe.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            return True
        # Consume this game's other streams before Luna's lossy stock queue.
        if hookname != "GrisaiaWindows":
            return True
        try:
            packet = cast(JsonObject, json.loads(text))
            if (
                packet.get("schema") != 1
                or packet.get("kind") != "window"
                or type(packet.get("serial")) is not int
                or packet["serial"] <= 0
                or not isinstance(packet.get("session"), str)
                or not packet["session"].startswith(str(tp.processId) + ":")
                or not isinstance(packet.get("text"), str)
                or not packet["text"].strip()
                or not isinstance(packet.get("speaker"), str)
            ):
                raise ValueError("Invalid window packet")
            original = (packet["speaker"] + ":\n" if packet["speaker"] else "") + packet["text"]
            occurrence = f"{packet['session']}:{packet['serial']}"
        except (ValueError, TypeError, AttributeError, KeyError):
            with self._capture_lock:
                self._retain_capture_fault(text)
            return True
        with self._capture_lock:
            if not self.capture(original, occurrence):
                self._retain_capture_fault(text, "window_identity_collision")
        return True

    def capture_selected_hook_text(self, text: str, hook_names: tuple[str, ...]) -> bool:
        if not self.stock_capture:
            return False
        with self._capture_lock:
            # Selecting a row can replay its history without an output callback.
            if text.strip() and hook_names and all(name == "CatSystem2" for name in hook_names):
                self._sequence += 1
                self.capture(text, str(self._sequence))
            else:
                self.discard_current_window()
                if self._can_start():
                    self._original_callback("")
        return True
