"""Packaged translations remain authoritative over the mutable local cache."""

import ast
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class WorkspaceLanguageTests(unittest.TestCase):
    def test_packaged_updates_win_and_discovered_entries_survive(self):
        source = Path(__file__).resolve().parents[2] / "src/LunaTranslator/myutils/config.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in ("langfile", "loadlanguage")]
        module = ast.Module(body=functions, type_ignores=[])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packaged = root / "files/lang"
            local = root / "userconfig/lang"
            packaged.mkdir(parents=True)
            local.mkdir(parents=True)
            (packaged / "en.json").write_text(json.dumps({"old": "updated", "new": "new value"}))
            (local / "en.json").write_text(json.dumps({"old": "stale", "discovered": "kept"}))
            namespace = {"os": os, "json": json, "language_last": None,
                         "getlanguse": lambda: "en", "languageshow": {},
                         "gobject": SimpleNamespace(getconfig=lambda name: str(root / "userconfig" / name))}
            exec(compile(module, str(source), "exec"), namespace)
            previous = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(os.environ, {"LUNA_WORKSPACE_HOME": str(root)}):
                    namespace["loadlanguage"]()
                    self.assertEqual(namespace["languageshow"],
                                     {"old": "updated", "new": "new value", "discovered": "kept"})
                    (local / "en.json").write_text("not JSON")
                    namespace["language_last"] = None
                    namespace["loadlanguage"]()
                    self.assertEqual(namespace["languageshow"], {"old": "updated", "new": "new value"})
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
