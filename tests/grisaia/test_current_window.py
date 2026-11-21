"""Synthetic current-window translation over the guarded Responses transport."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from integrations.transport import JsonObject, ResponsesClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/LunaTranslator"))


class CurrentWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        from integrations.session import Session
        from integrations.transport import ResponsesClient

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        home = Path(temp.name)
        key_file = home / "synthetic-key.txt"
        key_file.write_text("synthetic-api-key", encoding="utf-8")
        self.archive = home / "journal.sqlite3"
        self.archive.write_bytes(b"preexisting private journal marker")
        settings = {
            "key_file": str(key_file),
            "expected_country": "PL",
            "proxy": {"host": "synthetic-proxy", "port": 8080},
        }
        self.requests: list[JsonObject] = []
        self.visited: list[str] = []
        self.originals: list[str] = []
        self.reply: JsonObject = {
            "translation": "Серебряный дозор держит осколок души.",
            "new_terms": [{"src": "Soul Shard", "dst": "осколок души"}],
        }
        self.session = Session(
            home,
            lambda: settings,
            lambda _: None,
            self.originals.append,
            lambda _: None,
            current_window=True,
        )
        guard = patch.object(ResponsesClient, "_request", autospec=True, side_effect=self.reply_to)
        guard.start()
        self.addCleanup(guard.stop)
        self.session.start()
        self.addCleanup(self.session.stop_lossless)

    def reply_to(
        self,
        _client: ResponsesClient,
        target: str,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, JsonObject]:
        self.visited.append(target)
        if method == "GET":
            return 200, {"ip": "1.1.1.1", "country_code": "PL"}
        assert body is not None
        assert headers is not None
        self.assertEqual(path, "/v1/responses")
        self.assertEqual(headers.get("Authorization"), "Bearer synthetic-api-key")
        self.requests.append(json.loads(body))
        return 200, {
            "status": "completed",
            "service_tier": "fast",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(self.reply)}],
                }
            ],
        }

    def test_only_current_window_is_sent_when_requested(self) -> None:
        self.session.capture("An earlier scene.", "one")
        original = "The Silver-Ward holds a Soul Shard."
        self.session.capture(original, "two")
        self.assertEqual(self.originals, ["An earlier scene.", original])
        self.assertEqual(self.visited, [])
        self.assertEqual(self.session.translate_current("An earlier scene.", []), "")
        self.assertEqual(self.visited, [])

        terms: list[dict[str, object]] = [
            {"src": "Silver-Ward", "dst": "Серебряный дозор", "info": "Private note"},
            {"src": "Blue Order", "dst": "Синий орден"},
        ]
        translated = self.session.translate_current(original, terms)
        self.assertEqual(translated, self.reply["translation"])
        self.assertEqual(terms[-1]["dst"], "осколок души")
        self.assertEqual(self.visited, ["ipapi.co", "api.openai.com"])

        request = self.requests[0]
        self.assertEqual(request["model"], "gpt-6.2-sol")
        self.assertEqual(request["reasoning"], {"effort": "medium"})
        self.assertEqual(request["service_tier"], "fast")
        self.assertEqual(request["text"]["format"]["type"], "json_schema")
        self.assertEqual([item["role"] for item in request["input"]], ["developer", "user"])
        self.assertEqual(request["input"][-1]["content"], original)
        serialized = json.dumps(request["input"], ensure_ascii=False)
        self.assertIn("Серебряный дозор", serialized)
        self.assertNotIn("An earlier scene", serialized)
        self.assertNotIn("Blue Order", serialized)
        self.assertNotIn("Private note", serialized)
        self.assertEqual(self.archive.read_bytes(), b"preexisting private journal marker")

    def test_invalid_structured_response_does_not_add_new_terms(self) -> None:
        from integrations.engine import TranslationError

        original = "She grabbed a Soul Shard."
        self.session.capture(original, "one")
        self.reply["translation"] = ""
        terms: list[dict[str, object]] = []
        with self.assertRaises(TranslationError):
            self.session.translate_current(original, terms)
        self.assertEqual(terms, [])
        self.assertEqual(len(self.requests), 1)

    def test_imports_only_consistent_repeated_speaker_names_from_history(self) -> None:
        from integrations.glossary import add_glossary_entries
        from integrations.glossary_history import journal_speaker_terms

        self.archive.unlink()
        with closing(sqlite3.connect(self.archive)) as connection:
            connection.execute("CREATE TABLE events (kind, state, original, translation)")
            connection.executemany(
                "INSERT INTO events VALUES ('capture', 'completed', ?, ?)",
                [
                    ("Tess:\nHello.", "Тесс:\nПривет."),
                    ("Tess:\nAgain.", "Тесс:\nСнова."),
                    ("Zed:\nHello.", "Зед:\nПривет."),
                    ("Zed:\nGoodbye.", "Зэт:\nПока."),
                    ("Sera:\nOnce.", "Сэра:\nОднажды."),
                    ("Just narration.", "Просто повествование."),
                ],
            )
            connection.commit()
        before = self.archive.read_bytes()
        suggestions = journal_speaker_terms(self.archive)
        self.assertEqual(suggestions, [{"src": "Tess", "dst": "Тесс"}])
        entries: list[dict[str, object]] = [{"src": "Tess", "dst": "Тэсс"}]
        self.assertEqual(add_glossary_entries(entries, suggestions), 0)
        self.assertEqual(entries, [{"src": "Tess", "dst": "Тэсс"}])
        self.assertEqual(self.archive.read_bytes(), before)
