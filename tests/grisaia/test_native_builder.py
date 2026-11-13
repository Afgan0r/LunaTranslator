"""Native build lifecycle using deterministic synthetic compiler artifacts."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import build_native
import test_workspace
import workspace_build
from workspace_build import digest, inventory


class NativeBuilderTests(unittest.TestCase):
    def fixture(self, root):
        for path in ("src/NativeImpl/LunaHook", "src/LunaTranslator", ".local"):
            (root / path).mkdir(parents=True)
        (root / "src/NativeImpl/source.cpp").write_text("// synthetic source")
        (root / "src/LunaTranslator/main.py").write_text("# synthetic Python")
        (root / ".local/native-toolchain.json").write_text(json.dumps({
            "cmake": "synthetic-cmake", "atl_include": "synthetic-include",
            "atl_lib": "synthetic-lib64", "atl_lib_x86": "synthetic-lib32",
            "magic_enum_source": "synthetic-magic", "dependency_sources": {"AES": "synthetic-aes"},
            "parallel": 2}))
        return root

    def compiler(self, root, failure=None):
        """Produce files like the external toolchain, without compiling native code."""
        output = root / "build/native/bin"

        def execute(arguments, **kwargs):
            stage = "header" if "header" in arguments else ("compile" if "--build" in arguments else "configure")
            if stage == failure:
                if kwargs.get("stdout"):
                    kwargs["stdout"].write("synthetic compiler failure\n")
                if kwargs.get("check"):
                    raise subprocess.CalledProcessError(1, arguments)
                return subprocess.CompletedProcess(arguments, 1)
            if stage == "header":
                Path(arguments[-1]).write_text("// required: " + ",".join(inventory(root / "src/LunaTranslator")))
            elif stage == "compile":
                directory = Path(arguments[arguments.index("--build") + 1])
                if directory.name == "x64":
                    names = ("LunaTranslator.exe", "LunaTranslator_admin.exe", "NativeUtils.dll", "CVUtils.dll")
                else:
                    suffix = directory.name.removeprefix("hook")
                    names = ("LunaHook" + suffix + ".dll", "LunaHost" + suffix + ".dll")
                for name in names:
                    (output / name).write_text(name + json.dumps(inventory(root / "src/NativeImpl"))
                                               + json.dumps(inventory(root / "src/LunaTranslator")))
            return subprocess.CompletedProcess(arguments, 0)
        return execute

    def run_build(self, root, failure=None):
        with patch("build_native.subprocess.run", self.compiler(root, failure)), contextlib.redirect_stdout(io.StringIO()):
            build_native.build(root)

    def test_complete_build_records_actual_source_and_required_output_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.fixture(Path(folder))
            self.run_build(root)
            output = root / "build/native/bin"
            stamp = json.loads((output / "workspace-native.json").read_text())
            self.assertEqual(stamp["source_files"], inventory(root / "src/NativeImpl"))
            self.assertEqual(stamp["python_inputs"], inventory(root / "src/LunaTranslator"))
            self.assertEqual(set(stamp["output_files"]), {"LunaTranslator.exe", "LunaTranslator_admin.exe",
                "NativeUtils.dll", "CVUtils.dll", "LunaHook32.dll", "LunaHook64.dll",
                "LunaHost32.dll", "LunaHost64.dll"})
            self.assertTrue(all(digest(output / name) == sha for name, sha in stamp["output_files"].items()))
            self.assertIn("main.py", (root / "build/native/checksigs.hpp").read_text())
            before = inventory(root / "build")
            # A verified current build must not require a working compiler.
            self.run_build(root, failure="header")
            self.assertEqual(inventory(root / "build"), before)

    def test_stale_source_python_and_tampered_output_rebuilt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.fixture(Path(folder))
            self.run_build(root)
            output = root / "build/native/bin"
            original = digest(output / "LunaHook32.dll")
            (root / "src/NativeImpl/source.cpp").write_text("// changed source")
            self.run_build(root)
            self.assertNotEqual(digest(output / "LunaHook32.dll"), original)
            hook_after_native = digest(output / "LunaHook32.dll")
            (root / "src/LunaTranslator/new.py").write_text("# new required file")
            self.run_build(root)
            self.assertIn("new.py", (root / "build/native/checksigs.hpp").read_text())
            self.assertEqual(digest(output / "LunaHook32.dll"), hook_after_native)
            expected = digest(output / "NativeUtils.dll")
            (output / "NativeUtils.dll").write_text("tampered")
            self.run_build(root)
            self.assertEqual(digest(output / "NativeUtils.dll"), expected)
            (output / "LunaHook32.dll").unlink()
            self.run_build(root)
            self.assertTrue((output / "LunaHook32.dll").is_file())

    def test_failed_header_configure_or_compile_never_publishes_success_stamp(self):
        for stage in ("header", "configure", "compile"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as folder:
                root = self.fixture(Path(folder))
                with self.assertRaises((RuntimeError, subprocess.CalledProcessError)):
                    self.run_build(root, failure=stage)
                self.assertFalse((root / "build/native/bin/workspace-native.json").exists())
                self.assertFalse((root / "build/native/bin/workspace-native.new").exists())

    def test_failed_rebuild_preserves_last_success_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.fixture(Path(folder))
            self.run_build(root)
            stamp = root / "build/native/bin/workspace-native.json"
            before = stamp.read_bytes()
            (root / "src/NativeImpl/source.cpp").write_text("// rebuild required")
            with self.assertRaises(RuntimeError):
                self.run_build(root, failure="compile")
            self.assertEqual(stamp.read_bytes(), before)
            self.assertNotEqual(json.loads(before)["source_files"], inventory(root / "src/NativeImpl"))

    def test_builder_outputs_assemble_together_and_host_tampering_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root, template, _, _ = test_workspace.WorkspaceTests().fixture(Path(folder))
            self.run_build(root)
            output = root / "build/native/bin"
            with patch("workspace_build.subprocess.run") as git:
                git.return_value.stdout = "synthetic-revision"
                manifest = workspace_build.build(root, template, output, output)
            for name in ("LunaHook32.dll", "LunaHook64.dll", "LunaHost32.dll", "LunaHost64.dll"):
                relative = "files/LunaHook/" + name
                self.assertEqual(manifest["native_files"][relative], digest(output / name))
                self.assertEqual(digest(root / "dist" / relative), digest(output / name))
            before = inventory(root / "dist")
            (output / "LunaHost32.dll").write_text("independent modification")
            with self.assertRaisesRegex(ValueError, "provenance"):
                workspace_build.build(root)
            self.assertEqual(inventory(root / "dist"), before)

    def test_main_reports_build_failure_with_nonzero_exit(self):
        with patch.object(sys, "argv", ["build_native"]), patch("build_native.build", side_effect=RuntimeError("synthetic failure")), contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(build_native.main(), 1)
        self.assertIn("synthetic failure", errors.getvalue())
        with patch.object(sys, "argv", ["build_native"]), patch("build_native.build", return_value=None):
            self.assertEqual(build_native.main(), 0)


if __name__ == "__main__":
    unittest.main()
