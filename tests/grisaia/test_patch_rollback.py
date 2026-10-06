"""Rollback preserves unrelated files and refuses changed assets atomically."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from install_grisaia_patches import digest, rollback, save_json


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "private"
        self.game = Path(self.temp.name) / "game"
        self.game.mkdir()
        self.private = self.home / "patches"
        (self.private / "originals").mkdir(parents=True)
        (self.game / "Grisaia.exe").write_bytes(b"unchanged executable")
        (self.game / "scene.int").write_bytes(b"English base script")
        self.assets = []
        for name, original in (("update98.int", b"original HCG file"), ("update97.int", None)):
            target = self.game / name
            backup = self.private / "originals" / name
            if original:
                backup.write_bytes(original)
            target.write_bytes(b"installed " + name.encode())
            self.assets.append({"name": name, "original_sha256": digest(backup) if original else None,
                                "installed_sha256": digest(target),
                                "backup": str(backup) if original else None})
        self.manifest_path = self.private / "install-manifest.json"
        save_json(self.manifest_path, {"schema": 1, "state": "installed", "game": str(self.game),
                                     "game_exe_sha256": digest(self.game / "Grisaia.exe"),
                                     "assets": self.assets})

    def test_exact_original_restored_and_added_file_removed(self):
        rollback(self.home)
        self.assertEqual((self.game / "update98.int").read_bytes(), b"original HCG file")
        self.assertFalse((self.game / "update97.int").exists())
        self.assertEqual((self.game / "scene.int").read_bytes(), b"English base script")
        self.assertEqual(json.loads(self.manifest_path.read_text())["state"], "rolled_back")

    def test_changed_second_target_prevents_any_restore(self):
        first = (self.game / "update98.int").read_bytes()
        (self.game / "update97.int").write_bytes(b"user changed movie")
        with self.assertRaises(ValueError):
            rollback(self.home)
        self.assertEqual((self.game / "update98.int").read_bytes(), first)
        self.assertEqual((self.game / "update97.int").read_bytes(), b"user changed movie")

    def test_changed_backup_prevents_any_restore(self):
        first = (self.game / "update98.int").read_bytes()
        (self.private / "originals/update98.int").write_bytes(b"bad backup")
        with self.assertRaises(ValueError):
            rollback(self.home)
        self.assertEqual((self.game / "update98.int").read_bytes(), first)
        self.assertTrue((self.game / "update97.int").exists())


if __name__ == "__main__":
    unittest.main()
