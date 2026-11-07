"""Deployment profile regression using synthetic private installations."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
import deploy_grisaia


class DeploymentTests(unittest.TestCase):
    def test_redeployment_preserves_automatic_capture_without_inserting_sentinel(self):
        for protocol, hook, expected in (
            ("grisaia-windows-v1", "auto:GrisaiaWindows", []),
            (None, "HSFN932#-4@B2721:Grisaia.exe", ["HSFN932#-4@B2721:Grisaia.exe"]),
        ):
            with self.subTest(protocol=protocol), tempfile.TemporaryDirectory() as folder:
                home = Path(folder) / "private"
                game = Path(folder) / "game"
                runtime = home / "runtime" / "LunaTranslator_x64"
                runtime.mkdir(parents=True)
                game.mkdir()
                (runtime / "LunaTranslator.exe").write_bytes(b"synthetic runtime")
                (home / "settings.json").write_text(json.dumps({
                    "capture_protocol": protocol, "hook_code": hook,
                    "hook_validated": True,
                }), encoding="utf-8")
                for _ in range(2):
                    with contextlib.redirect_stdout(io.StringIO()):
                        deploy_grisaia.deploy(home, game)
                    games = json.loads((runtime / "userconfig" / "savegamedata_5.3.1.json").read_text())
                    self.assertEqual(len(games[1]), 1)
                    profile = next(iter(games[1].values()))
                    self.assertEqual(profile["needinserthookcode"], expected)
                    settings = json.loads((home / "settings.json").read_text(encoding="utf-8"))
                    self.assertTrue(settings["hook_validated"])
                    self.assertEqual(settings["hook_code"], hook)


if __name__ == "__main__":
    unittest.main()
