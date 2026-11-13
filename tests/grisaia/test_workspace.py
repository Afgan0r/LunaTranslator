"""Synthetic workspace lifecycle checks; no real runtime or private corpus."""

import json
import contextlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from workspace_build import build, digest, inventory, launch, native_files
from workspace_migrate import backup_journal, migrate, restrict_private, snapshot
from workspace_migrate import game_identity
import workspace
import workspace_build
import workspace_migrate


class WorkspaceTests(unittest.TestCase):
    def test_runtime_standalone_bytecode_survives_assembly_and_offline_seed(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(Path(folder))
            runtime = paths[1] / "files/runtime3.13-64"
            (runtime / "stringprep.pyc").write_bytes(b"synthetic runtime dependency")
            (runtime / "__pycache__").mkdir()
            (runtime / "__pycache__/discard.pyc").write_bytes(b"disposable cache")
            self.assemble(paths)
            for target in (paths[0] / "dist", paths[0] / "build/runtime-template"):
                self.assertEqual((target / "files/runtime3.13-64/stringprep.pyc").read_bytes(), b"synthetic runtime dependency")
                self.assertFalse((target / "files/runtime3.13-64/__pycache__").exists())

    def test_independent_dist_edit_during_staging_refuses_activation(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(Path(folder))
            self.assemble(paths)
            source_copy = workspace_build.copy_tree
            target = paths[0] / "dist/LunaTranslator/LunaTranslator.py"

            def edit_while_staging(source, destination):
                source_copy(source, destination)
                if source == paths[0] / "src/LunaTranslator":
                    target.write_text("independently changed during build")

            with patch("workspace_build.copy_tree", side_effect=edit_while_staging), self.assertRaisesRegex(ValueError, "changed independently"):
                self.assemble((paths[0], None, None, None))
            self.assertEqual(target.read_text(), "independently changed during build")
            self.assertFalse(list((paths[0] / "build").glob("runtime-stage-*")))

    def test_destination_appearing_during_migration_preserved_and_stage_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            repo, legacy, _, _ = self.legacy_fixture(Path(folder))
            copy = workspace_migrate.shutil.copytree

            def concurrent_destination(source, destination, **kwargs):
                result = copy(source, destination, **kwargs)
                (repo / ".local").mkdir()
                (repo / ".local/sentinel").write_text("independent state")
                return result

            with patch("workspace_migrate.shutil.copytree", side_effect=concurrent_destination), self.assertRaisesRegex(ValueError, "appeared during"):
                migrate(repo, legacy)
            self.assertEqual((repo / ".local/sentinel").read_text(), "independent state")
            self.assertFalse(list(repo.glob(".local-migrate-*")))

    def legacy_fixture(self, root):
        repo, legacy = root / "repo", root / "legacy"
        repo.mkdir()
        user = legacy / "runtime/LunaTranslator_x64/userconfig"
        user.mkdir(parents=True)
        settings = {"game_exe": str(root / "game.exe"), "game_uid": "retained-uid"}
        (legacy / "settings.json").write_text(json.dumps(settings))
        with closing(sqlite3.connect(legacy / "journal.sqlite3")) as db:
            db.execute("CREATE TABLE meta(k TEXT,v TEXT)")
            db.commit()
        return repo, legacy, user, settings

    def test_migration_rejects_invalid_uid_missing_userconfig_and_acl_denial(self):
        for failure in ("uid", "userconfig", "acl"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                repo, legacy, user, settings = self.legacy_fixture(Path(folder))
                if failure == "uid":
                    settings["game_uid"] = "../escape"
                    (legacy / "settings.json").write_text(json.dumps(settings))
                elif failure == "userconfig":
                    user.rmdir()
                before = inventory(legacy)
                with patch("workspace_migrate.restrict_private", side_effect=ValueError("ACL denied")) if failure == "acl" else contextlib.nullcontext():
                    with self.assertRaises(ValueError):
                        migrate(repo, legacy)
                self.assertFalse((repo / ".local").exists())
                self.assertFalse(list(repo.glob(".local-migrate-*")))
                self.assertEqual(before, inventory(legacy))

    def test_game_uid_conflicts_ambiguity_and_absolute_path_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            user = Path(folder)
            executable = str(user / "game.exe")
            for settings, profiles in (({"game_exe": "relative"}, {}),
                    ({"game_exe": executable}, {}),
                    ({"game_exe": executable, "game_uid": "other"}, {"uid": {"gamepath": executable}}),
                    ({"game_exe": executable}, {uid: {"gamepath": executable} for uid in ("one", "two")})):
                (user / "savegamedata_5.3.1.json").write_text(json.dumps([[], profiles]))
                with self.assertRaises(ValueError):
                    game_identity(settings, user)

    def test_invalid_legacy_home_rejected_without_state(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            with self.assertRaises(ValueError):
                migrate(repo, Path("relative"))
            self.assertEqual(list(repo.iterdir()), [])

    def test_permission_setup_failures_are_safe_and_stop(self):
        if os.name != "nt":
            self.skipTest("Windows ACL failure boundary")
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            with patch.dict(os.environ, {"USERNAME": ""}), self.assertRaisesRegex(ValueError, "current account"):
                restrict_private(directory)
            with patch("workspace_migrate.subprocess.run", side_effect=subprocess.CalledProcessError(1, "icacls", output="PRIVATE_SENTINEL")), self.assertRaises(ValueError) as raised:
                restrict_private(directory)
            self.assertNotIn("PRIVATE_SENTINEL", str(raised.exception))

    def test_invalid_build_inputs_and_missing_components_leave_no_dist(self):
        for failure in ("relative", "native", "interpreter", "source"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                paths = list(self.fixture(Path(folder)))
                if failure == "relative":
                    paths[1] = Path("relative")
                elif failure == "native":
                    (paths[2] / "NativeUtils.dll").unlink()
                elif failure == "interpreter":
                    (paths[1] / "files/runtime3.13-64/python3.dll").unlink()
                else:
                    (paths[0] / "src/LunaTranslator/LunaTranslator.py").unlink()
                    for directory in paths[2:]:
                        stamp = json.loads((directory / "workspace-native.json").read_text())
                        stamp["python_inputs"] = inventory(paths[0] / "src/LunaTranslator")
                        (directory / "workspace-native.json").write_text(json.dumps(stamp))
                with self.assertRaises(ValueError):
                    self.assemble(paths)
                self.assertFalse((paths[0] / "dist").exists())
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "Build the workspace"):
                launch(Path(folder))

    def test_optional_native_components_map_and_license_survives(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(Path(folder))
            (paths[1] / "LICENSE.txt").write_text("synthetic license")
            (paths[2] / "LunaSubprocess64.exe").write_bytes(b"subprocess")
            (paths[3] / "LunaHost64.dll").write_bytes(b"host")
            for directory in paths[2:]:
                stamp = json.loads((directory / "workspace-native.json").read_text())
                stamp["output_files"] = {p.name: digest(p) for p in directory.iterdir() if p.name != "workspace-native.json"}
                (directory / "workspace-native.json").write_text(json.dumps(stamp))
            self.assemble(paths)
            self.assertEqual((paths[0] / "dist/LICENSE.txt").read_text(), "synthetic license")
            self.assertEqual((paths[0] / "dist/files/LunaSubprocess64.exe").read_bytes(), b"subprocess")
            self.assertEqual((paths[0] / "dist/files/LunaHook/LunaHost64.dll").read_bytes(), b"host")
            (paths[0] / "build/runtime-template/LICENSE.txt").write_text("changed")
            with self.assertRaisesRegex(ValueError, "template changed"):
                self.assemble((paths[0], None, None, None))

    def test_workspace_main_build_migrate_and_safe_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(Path(folder))
            arguments = ["workspace", "build", "--runtime-template", str(paths[1]),
                         "--native-dir", str(paths[2]), "--hook-dir", str(paths[3])]
            with patch.object(workspace, "REPO", paths[0]), patch.object(sys, "argv", arguments), patch("workspace_build.subprocess.run") as run, contextlib.redirect_stdout(io.StringIO()) as output:
                run.return_value.stdout = "synthetic-revision"
                workspace.main()
            self.assertIn("Workspace built", output.getvalue())
            for failure in (ValueError("controlled validation"), OSError("PRIVATE_PATH_SENTINEL")):
                with patch.object(sys, "argv", ["workspace", "launch"]), patch("workspace.launch", side_effect=failure), contextlib.redirect_stderr(io.StringIO()) as errors, self.assertRaises(SystemExit):
                    workspace.main()
                self.assertNotIn("PRIVATE_PATH_SENTINEL", errors.getvalue())
            with patch.object(sys, "argv", ["workspace", "launch"]), patch("workspace.launch", return_value=None):
                workspace.main()
        with tempfile.TemporaryDirectory() as folder:
            repo, legacy, _, _ = self.legacy_fixture(Path(folder))
            with patch.object(workspace, "REPO", repo), patch.object(sys, "argv", ["workspace", "migrate", "--legacy-home", str(legacy)]), contextlib.redirect_stdout(io.StringIO()) as output:
                workspace.main()
            self.assertIn("Workspace migrated", output.getvalue())
            self.assertTrue((repo / ".local/config.json").exists())

    def test_private_stage_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "private"
            directory.mkdir()
            restrict_private(directory)
            if os.name == "nt":
                import subprocess
                try:
                    result = subprocess.run(["icacls", str(directory)], check=True,
                                            capture_output=True, text=True,
                                            creationflags=subprocess.CREATE_NO_WINDOW)
                    self.assertNotIn("(I)", result.stdout)
                    self.assertIn(os.environ["USERNAME"].lower(), result.stdout.lower())
                    self.assertEqual(result.stdout.count("(OI)(CI)(F)"), 2)
                finally:
                    # The restricted test runner requires its inherited sandbox
                    # ACE for cleanup; restore it only on this empty fixture.
                    subprocess.run(["icacls", str(directory), "/inheritance:e"],
                                   check=True, capture_output=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                self.assertEqual(directory.stat().st_mode & 0o777, 0o700)

    def fixture(self, root):
        repo, template, native, hook = [root / name for name in ("repo", "template", "native", "hook")]
        for directory in (repo / "src/LunaTranslator/sub", repo / "src/files/lang",
                          repo / "extensions/grisaia", template / "files/runtime3.13-64",
                          template / "userconfig", template / "cache", native, hook):
            directory.mkdir(parents=True)
        (repo / "src/LunaTranslator/LunaTranslator.py").write_text("# current main")
        (repo / "src/LunaTranslator/sub/other.py").write_text("# full source")
        (repo / "src/files/lang/en.json").write_text("{}")
        (repo / "extensions/grisaia/adapter.py").write_text("# adapter")
        (template / "files/runtime3.13-64/python3.dll").write_bytes(b"dependency")
        (template / "userconfig/private.json").write_text("private")
        (template / "cache/translation.json").write_text("private")
        for name in ("NativeUtils.dll", "CVUtils.dll", "LunaTranslator.exe", "LunaTranslator_admin.exe"):
            (native / name).write_bytes(b"new native " + name.encode())
        (hook / "LunaHook32.dll").write_bytes(b"hook")
        (repo / "src/NativeImpl").mkdir()
        (repo / "src/NativeImpl/source.cpp").write_text("// native")
        for directory in (native, hook):
            stamp = {"schema": 1, "source_files": inventory(repo / "src/NativeImpl"),
                     "python_inputs": inventory(repo / "src/LunaTranslator"),
                     "output_files": {p.name: digest(p) for p in directory.iterdir()}}
            (directory / "workspace-native.json").write_text(json.dumps(stamp))
        return repo, template, native, hook

    def assemble(self, paths):
        with patch("workspace_build.subprocess.run") as run:
            run.return_value.stdout = "synthetic-revision\n"
            return build(*paths)

    def test_complete_source_native_mapping_and_private_exclusion(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(Path(folder))
            repo = paths[0]
            (repo / ".local").mkdir()
            (repo / ".local/sentinel").write_text("persistent")
            manifest = self.assemble(paths)
            runtime = repo / "dist"
            self.assertEqual((runtime / "LunaTranslator/sub/other.py").read_text(), "# full source")
            self.assertTrue((runtime / "extensions/grisaia/adapter.py").is_file())
            self.assertEqual((runtime / "files/DLL64/NativeUtils.dll").read_bytes(), b"new native NativeUtils.dll")
            self.assertFalse((runtime / "userconfig").exists())
            self.assertFalse((runtime / "cache").exists())
            self.assertEqual((repo / ".local/sentinel").read_text(), "persistent")
            self.assertEqual(manifest["files"], inventory(runtime))
            self.assertIn("sub/other.py", manifest["source_files"])

    def test_changed_dist_refused_before_replacing_anything(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(Path(folder))
            self.assemble(paths)
            runtime = paths[0] / "dist"
            changed = runtime / "LunaTranslator/sub/other.py"
            changed.write_text("independent change")
            before = inventory(runtime)
            with self.assertRaises(ValueError):
                self.assemble(paths)
            self.assertEqual(inventory(runtime), before)

    def test_successful_rebuild_retains_previous_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(Path(folder))
            self.assemble(paths)
            (paths[0] / "src/LunaTranslator/sub/other.py").write_text("# next")
            for directory in paths[2:]:
                stamp = json.loads((directory / "workspace-native.json").read_text())
                stamp["python_inputs"] = inventory(paths[0] / "src/LunaTranslator")
                (directory / "workspace-native.json").write_text(json.dumps(stamp))
            self.assemble((paths[0], None, None, None))
            backups = list((paths[0] / "build/runtime-backups").iterdir())
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "LunaTranslator/sub/other.py").read_text(), "# full source")
            self.assertEqual((paths[0] / "dist/LunaTranslator/sub/other.py").read_text(), "# next")

    def test_launch_only_starts_dist_and_sets_generic_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            (repo / "dist").mkdir()
            (repo / "dist/LunaTranslator.exe").write_bytes(b"synthetic")
            before = inventory(repo)
            with patch.dict(os.environ, {"LUNA_GRISAIA_HOME": "old"}), patch("workspace_build.subprocess.Popen") as start:
                launch(repo)
            args, kwargs = start.call_args
            self.assertEqual(args[0], [str(repo / "dist/LunaTranslator.exe")])
            self.assertEqual(kwargs["env"]["LUNA_WORKSPACE_HOME"], str(repo / ".local"))
            self.assertEqual(kwargs["env"]["LUNA_USERCONFIG_HOME"], str(repo / ".local/userconfig"))
            self.assertNotIn("LUNA_GRISAIA_HOME", kwargs["env"])
            self.assertEqual(before, inventory(repo))

    def test_stale_native_source_and_tampered_outputs_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(Path(folder))
            source = paths[0] / "src/NativeImpl/source.cpp"
            source.write_text("// changed after build")
            with self.assertRaisesRegex(ValueError, "provenance"):
                self.assemble(paths)
            self.assertFalse((paths[0] / "dist").exists())
            source.write_text("// native")
            (paths[2] / "NativeUtils.dll").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "provenance"):
                self.assemble(paths)

    def test_failed_activation_restores_previous_dist(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(Path(folder))
            self.assemble(paths)
            old = inventory(paths[0] / "dist")
            rename = Path.rename

            def refuse_stage(path, target):
                if path.name.startswith("runtime-stage-"):
                    raise PermissionError("synthetic activation failure")
                return rename(path, target)

            with patch.object(Path, "rename", refuse_stage), self.assertRaises(PermissionError):
                self.assemble((paths[0], None, None, None))
            self.assertEqual(inventory(paths[0] / "dist"), old)

    def test_hook_requires_provenance_and_exact_output_digest(self):
        for failure in ("missing_stamp", "tampered_hook", "missing_output"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                paths = self.fixture(Path(folder))
                hook = paths[3]
                stamp_path = hook / "workspace-native.json"
                if failure == "missing_stamp":
                    stamp_path.unlink()
                elif failure == "tampered_hook":
                    (hook / "LunaHook32.dll").write_bytes(b"tampered hook")
                else:
                    stamp = json.loads(stamp_path.read_text())
                    stamp["output_files"] = {}
                    stamp_path.write_text(json.dumps(stamp))
                with self.assertRaisesRegex(ValueError, "provenance"):
                    self.assemble(paths)
                self.assertFalse((paths[0] / "dist").exists())

    def test_stale_launcher_python_input_map_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixture(Path(folder))
            (paths[0] / "src/LunaTranslator/new_required.py").write_text("# new required file")
            with self.assertRaisesRegex(ValueError, "provenance"):
                self.assemble(paths)
            self.assertFalse((paths[0] / "dist").exists())

    def test_sqlite_backup_preserves_committed_wal_all_tables_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "journal.sqlite3"
            with closing(sqlite3.connect(source)) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, original TEXT, translation TEXT)")
                db.execute("CREATE TABLE context_checkpoints(id INTEGER PRIMARY KEY, text TEXT)")
                db.execute("CREATE TABLE meta(key TEXT, value BLOB)")
                db.execute("INSERT INTO events VALUES(1,'synthetic original','synthetic translation')")
                db.execute("INSERT INTO context_checkpoints VALUES(1,'synthetic checkpoint')")
                db.executemany("INSERT INTO meta VALUES(?,?)", [("prompt", "immutable"), ("cache_key", b"key")])
                db.commit()
                self.assertTrue(Path(str(source) + "-wal").is_file())
                backup_journal(source, root / "copy.sqlite3")
                with closing(sqlite3.connect(root / "copy.sqlite3")) as copied:
                    self.assertEqual(snapshot(copied), snapshot(db))

    def test_migration_pins_nested_settings_uid_and_keeps_legacy_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo, legacy = root / "repo", root / "legacy"
            repo.mkdir()
            user = legacy / "runtime/LunaTranslator_x64/userconfig"
            user.mkdir(parents=True)
            executable = str(root / "game/Grisaia.exe")
            settings = {"game_exe": executable, "model": "gpt-6.1-sol", "reasoning_effort": "low",
                        "proxy": {"host": "localhost", "port": 3210}, "key_file": "unopened-key-file",
                        "key_field": "OPENAI_API_KEY_WITH_SHARING", "hook_validated": True}
            (legacy / "settings.json").write_text(json.dumps(settings))
            (user / "savegamedata_5.3.1.json").write_text(json.dumps([[], {"saved-uid": {"gamepath": executable}}]))
            (user / "selfbuild.py").write_text("# obsolete dispatcher")
            (user / "config.json").write_text('{"theme": "dark"}')
            (legacy / "capture-fault.jsonl").write_text("synthetic fault")
            with closing(sqlite3.connect(legacy / "journal.sqlite3")) as db:
                db.execute("CREATE TABLE meta(key TEXT, value TEXT)")
                db.execute("INSERT INTO meta VALUES('cache_key','retained')")
                db.commit()
            before = inventory(legacy)
            self.assertEqual(migrate(repo, legacy), "saved-uid")
            config = json.loads((repo / ".local/config.json").read_text())
            self.assertEqual(config["profiles"]["saved-uid"]["settings"], settings)
            self.assertEqual(config["defaults"], {})
            self.assertFalse((repo / ".local/userconfig/selfbuild.py").exists())
            self.assertTrue((repo / ".local/games/saved-uid/capture-fault.jsonl").exists())
            self.assertEqual(before, inventory(legacy))
            with self.assertRaises(ValueError):
                migrate(repo, legacy)


if __name__ == "__main__":
    unittest.main()
