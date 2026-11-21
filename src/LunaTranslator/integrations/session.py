"""Game-independent durable session; UI and capture policy are callbacks."""

import json
import os
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol, cast

from .engine import Journal, TranslationError
from .transport import ClientConfig, JsonObject, ResponsesClient


class JournalPort(Protocol):
    def latest_capture(self) -> JsonObject | None: ...
    def capture(self, text: str, *, window_id: str, deduplicate_all: bool) -> int: ...
    def entry(self, entry_id: int) -> JsonObject: ...
    def claim_worker(self) -> None: ...
    def process_one(
        self, client: ResponsesClient, *, should_continue: Callable[[], bool]
    ) -> JsonObject | None: ...
    def close(self) -> None: ...


class Session:
    def __init__(
        self,
        home: str | Path,
        settings: Callable[[], Mapping[str, Any]],
        notice: Callable[[str], None],
        original: Callable[[str], None],
        publish: Callable[[JsonObject], None],
        active: Callable[[], bool] = lambda: True,
        *,
        current_window: bool = False,
    ) -> None:
        self.home = Path(home)
        self.current_window = current_window
        self._window: tuple[str, str] | None = None
        self._manual_lock = threading.Lock()
        self._manual_client: ResponsesClient | None = None
        if current_window:
            self.home.mkdir(parents=True, exist_ok=True)
        self.journal = (
            None if current_window else cast(JournalPort, Journal(self.home / "journal.sqlite3"))
        )
        self._settings = settings
        self._notice_callback = notice
        self._original_callback = original
        self._publish_callback = publish
        self._active = active
        self._capture_lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        latest = self.journal.latest_capture() if self.journal else None
        self._latest: int | None = latest["id"] if latest else None
        self._last_notice = None
        self._worker = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        if not self.current_window:
            self._worker.start()

    def _notice(self, text: str) -> None:
        if text != self._last_notice and self._active() and not self._stop.is_set():
            self._notice_callback(text)
            self._last_notice = text

    def _record_egress(self, public: JsonObject) -> None:
        # This callback runs after guarded egress and before credential access.
        with (self.home / "egress.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": time.time(), **public}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def capture(self, original: str, occurrence: str) -> bool:
        with self._capture_lock:
            if self._stop.is_set() or not self._active():
                return True
            journal = self.journal
            if journal is None:
                if self._window is not None and self._window[0] == occurrence:
                    return self._window[1] == original
                self._window = occurrence, original
                self._last_notice = None
                self._original_callback(original)
                return True
            entry_id = journal.capture(original, window_id=occurrence, deduplicate_all=True)
            if journal.entry(entry_id)["original"] != original:
                return False
            if self._latest is not None and entry_id <= self._latest:
                return True
            self._latest = entry_id
            self._original_callback(original)
            self._wake.set()
            return True

    def discard_current_window(self) -> None:
        with self._capture_lock:
            self._window = None

    def translate_current(self, original: str, entries: list[dict[str, object]]) -> str:
        from .glossary import (
            GLOSSARY_FORMAT,
            add_glossary_entries,
            glossary_messages,
            parse_glossary_response,
        )

        with self._manual_lock:
            with self._capture_lock:
                window = self._window
                if not self.current_window or not self._can_start() or window is None:
                    return ""
                if original.strip() != window[1].strip():
                    return ""
            settings = self._settings()
            reason = self.not_ready(settings)
            if reason:
                raise TranslationError("capture_unavailable", reason)
            config = ClientConfig.from_mapping(
                {**settings, "model": "gpt-6.2-sol", "reasoning_effort": "medium"}
            )
            client = self._manual_client
            if client is None or client.config != config:
                client = ResponsesClient(
                    config,
                    on_egress=self._record_egress,
                    should_continue=lambda: self._can_start(),
                )
                self._manual_client = client
            with self._capture_lock:
                if window != self._window or not self._can_start():
                    return ""
                messages = glossary_messages(window[1], entries)
            result = client.translate(
                messages,
                "luna-current-window",
                response_format=GLOSSARY_FORMAT,
                service_tier="fast",
            )
            try:
                translation, suggestions = parse_glossary_response(result.text, window[1])
            except ValueError:
                raise TranslationError(
                    "invalid_response", "Invalid translation response."
                ) from None
            with self._capture_lock:
                if not self._can_start():
                    return ""
                add_glossary_entries(entries, suggestions)
                return translation if self._window == window else ""

    def not_ready(self, settings: Mapping[str, Any]) -> str | None:
        return None

    def _publish(self, entry: JsonObject) -> None:
        # Persistence has committed; publication remains conditional on ownership.
        with self._capture_lock:
            if self._stop.is_set() or not self._active() or entry["id"] != self._latest:
                return
            self._publish_callback(entry)
            self._last_notice = None

    def _can_start(self) -> bool:
        return not self._stop.is_set() and self._active()

    def _run(self) -> None:
        journal = self.journal
        if journal is None:
            return
        client: ResponsesClient | None = None
        previous_config: ClientConfig | None = None
        try:
            while self._can_start():
                try:
                    journal.claim_worker()
                    latest = journal.latest_capture()
                    if latest and latest["state"] == "completed":
                        self._publish(latest)
                    break
                except TranslationError as error:
                    if error.code != "worker_busy":
                        raise
                    self._notice("Integration: waiting for the previous worker to finish.")
                    self._stop.wait(0.5)
            while self._can_start():
                try:
                    settings = self._settings()
                    reason = self.not_ready(settings)
                    if reason:
                        self._notice(reason)
                    elif not settings.get("model"):
                        self._notice("Integration: choose a model; captures are retained.")
                    else:
                        config = ClientConfig.from_mapping(settings)
                        if client is None or config != previous_config:
                            client = ResponsesClient(
                                config,
                                on_egress=self._record_egress,
                                should_continue=self._can_start,
                            )
                            previous_config = config
                        result = journal.process_one(client, should_continue=self._can_start)
                        if result:
                            self._publish(result)
                            continue
                except TranslationError as error:
                    self._notice(f"Integration: {error.code}. Queue stopped; use Retry.")
                except Exception:
                    self._notice(
                        "Integration: request configuration unavailable; captures remain retained."
                    )
                self._wake.wait(0.5)
                self._wake.clear()
        finally:
            journal.close()

    def stop_lossless(self) -> None:
        with self._capture_lock:
            self._stop.set()
        self._wake.set()
