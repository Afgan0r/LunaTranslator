import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "LunaTranslator"))

from integrations.glossary import (  # noqa: E402
    add_glossary_entries,
    glossary_messages,
    parse_glossary_response,
)


class GlossaryTests(unittest.TestCase):
    def test_prompt_selects_whole_phrases_and_only_public_fields(self):
        entries = [
            {"src": "Silver-Hawk", "dst": "Серебряный ястреб", "info": "secret plot"},
            {"src": "hawk", "dst": "ястреб", "info": ""},
            {"src": "cat", "dst": "кот", "info": ""},
            {"src": "missing", "dst": "нет", "info": ""},
        ]
        messages = glossary_messages("Silver—Hawk meets a catfish.", entries)
        self.assertEqual(messages[1], {"role": "user", "content": "Silver—Hawk meets a catfish."})
        prompt = messages[0]["content"]
        self.assertIn("Серебряный ястреб", prompt)
        self.assertIn("ястреб", prompt)
        self.assertNotIn("кот", prompt)
        self.assertNotIn("secret plot", prompt)
        self.assertNotIn("missing", prompt)

    def test_parse_filters_invented_empty_and_duplicate_suggestions_and_caps(self):
        terms = [
            {"src": name, "dst": "имя"}
            for name in ["Alice", "BOB", "bob", "ghost", "", "Carol", "Dave", "Eve", "Frank"]
        ]
        raw = json.dumps({"translation": "Привет.", "new_terms": terms})
        translation, suggestions = parse_glossary_response(
            raw, "Alice, Bob, Carol, Dave, Eve and Frank."
        )
        self.assertEqual(translation, "Привет.")
        self.assertEqual(
            [item["src"] for item in suggestions], ["Alice", "BOB", "Carol", "Dave", "Eve"]
        )
        self.assertTrue(
            all(item["whole-word"] is True and item["info"] == "" for item in suggestions)
        )

    def test_malformed_response_has_fixed_safe_error(self):
        for raw in (
            "private text",
            '{"translation":" ","new_terms":[]}',
            '{"translation":"ok","new_terms":[{"src":42,"dst":"x"}]}',
        ):
            with (
                self.subTest(raw=raw),
                self.assertRaisesRegex(ValueError, r"^Invalid glossary response\.$"),
            ):
                parse_glossary_response(raw, "text")

    def test_source_matching_normalizes_dashes_but_preserves_punctuation(self):
        raw = json.dumps(
            {
                "translation": "Перевод",
                "new_terms": [
                    {"src": "Silver-Ward", "dst": "Серебряный страж"},
                    {"src": "C++", "dst": "Си плюс плюс"},
                    {"src": "Alice's", "dst": "Алисы"},
                    {"src": "cat", "dst": "кот"},
                ],
            }
        )
        _, terms = parse_glossary_response(raw, "Silver Ward uses C++ and Alice's catfish.")
        self.assertEqual([item["src"] for item in terms], ["Silver-Ward", "C++", "Alice's"])

    def test_existing_manual_and_blank_entries_are_never_replaced(self):
        entries: list[dict[str, object]] = [
            {"src": "Silver—Hawk", "dst": "", "info": "manual", "whole-word": False},
            {"src": "Alice", "dst": "Алиса", "info": "note"},
        ]
        original = [entry.copy() for entry in entries]
        suggestions = [
            {"src": "silver hawk", "dst": "Ястреб"},
            {"src": "ALICE", "dst": "Алисой"},
            {"src": "Bob", "dst": "Бобом"},
        ]
        self.assertEqual(add_glossary_entries(entries, suggestions), 1)
        self.assertEqual(entries[:2], original)
        self.assertEqual(entries[2], {"src": "Bob", "dst": "Бобом", "info": "", "whole-word": True})


if __name__ == "__main__":
    unittest.main()
