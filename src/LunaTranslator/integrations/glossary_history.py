"""Recover stable speaker spellings from the private, read-only journal."""

import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path


def _speaker(text: str) -> str:
    name, separator, _ = text.partition(":\n")
    if separator and len(name) <= 80 and "\n" not in name and name.isprintable():
        name = name.strip()
        if any(character.isalpha() for character in name):
            return name
    return ""


def journal_speaker_terms(path: Path) -> list[dict[str, object]]:
    """Return frequently repeated, unambiguous speaker spelling pairs."""
    if not path.is_file():
        return []

    candidates: dict[str, Counter[str]] = {}
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        for original, translated in connection.execute(
            "SELECT original, translation FROM events WHERE kind='capture' AND state='completed'"
        ):
            if not isinstance(original, str) or not isinstance(translated, str):
                continue
            source, target = _speaker(original), _speaker(translated)
            if source and target:
                candidates.setdefault(source, Counter())[target] += 1

    return [
        {"src": source, "dst": target}
        for source, forms in candidates.items()
        if len(forms) == 1
        for target, occurrences in forms.items()
        if occurrences >= 2
    ]
