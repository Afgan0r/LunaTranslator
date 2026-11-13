"""Game-independent durable session; UI and capture policy are callbacks."""

import json
import os
import threading
import time
from pathlib import Path

from .engine import Journal, TranslationError
from .transport import ClientConfig, ResponsesClient


class Session:
    def __init__(self, home, settings, notice, original, publish, active=lambda: True):
        self.home = Path(home)
        self.journal = Journal(self.home / "journal.sqlite3")
        self._settings = settings
        self._notice_callback = notice
        self._original_callback = original
        self._publish_callback = publish
        self._active = active
        self._capture_lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        latest = self.journal.latest_capture()
        self._latest = latest["id"] if latest else None
        self._last_notice = None
        self._worker = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._worker.start()

    def _notice(self, text):
        if text != self._last_notice and self._active() and not self._stop.is_set():
            self._notice_callback(text)
            self._last_notice = text

    def _record_egress(self, public):
        # This callback runs after guarded egress and before credential access.
        with (self.home / "egress.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": time.time(), **public}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def capture(self, original, occurrence):
        with self._capture_lock:
            if self._stop.is_set() or not self._active():
                return True
            entry_id = self.journal.capture(original, window_id=occurrence, deduplicate_all=True)
            if self.journal.entry(entry_id)["original"] != original:
                return False
            if self._latest is not None and entry_id <= self._latest:
                return True
            self._latest = entry_id
            self._original_callback(original)
            self._wake.set()
            return True

    def not_ready(self, settings):
        return None

    def _publish(self, entry):
        # Persistence has committed; publication remains conditional on ownership.
        with self._capture_lock:
            if self._stop.is_set() or not self._active() or entry["id"] != self._latest:
                return
            self._publish_callback(entry)
            self._last_notice = None

    def _can_start(self):
        return not self._stop.is_set() and self._active()

    def _run(self):
        client = None
        previous_config = None
        try:
            while self._can_start():
                try:
                    self.journal.claim_worker()
                    latest = self.journal.latest_capture()
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
                        if config != previous_config:
                            client = ResponsesClient(config, on_egress=self._record_egress,
                                                     should_continue=self._can_start)
                            previous_config = config
                        result = self.journal.process_one(client, should_continue=self._can_start)
                        if result:
                            self._publish(result)
                            continue
                except TranslationError as error:
                    self._notice("Integration: %s. Queue stopped; use Retry." % error.code)
                except Exception:
                    self._notice("Integration: request configuration unavailable; captures remain retained.")
                self._wake.wait(0.5)
                self._wake.clear()
        finally:
            self.journal.close()

    def stop_lossless(self):
        with self._capture_lock:
            self._stop.set()
        self._wake.set()
