"""Offline, staged assembly of a complete runnable workspace."""

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

MANIFEST = "workspace-manifest.json"
EXCLUDED = {"__pycache__", "userconfig", "cache", "chrome_cache", "translation_record"}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inventory(root):
    return {p.relative_to(root).as_posix(): digest(p)
            for p in sorted(root.rglob("*")) if p.is_file()
            and not {"__pycache__", ".git"}.intersection(p.relative_to(root).parts)
            and p.relative_to(root).as_posix() != MANIFEST}


def copy_tree(source, target):
    def ignore(directory, names):
        # Standalone bytecode can be a required embedded-stdlib dependency
        # (for example stringprep.pyc); only __pycache__ is disposable.
        return [name for name in names if name in EXCLUDED]
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=ignore)


def validate_existing(runtime):
    if not runtime.exists():
        return
    try:
        manifest = json.loads((runtime / MANIFEST).read_text(encoding="utf-8"))
        expected = manifest["files"]
        if manifest["schema"] != 1 or inventory(runtime) != expected:
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("Deployed runtime changed independently or lacks a valid manifest.") from None


def native_files(native, hook):
    required = {"LunaTranslator.exe": "LunaTranslator.exe",
                "LunaTranslator_admin.exe": "LunaTranslator_admin.exe",
                "NativeUtils.dll": "files/DLL64/NativeUtils.dll",
                "CVUtils.dll": "files/DLL64/CVUtils.dll"}
    pairs = [(native / name, relative) for name, relative in required.items()]
    for name in ("LunaSubprocess.exe", "LunaSubprocess64.exe"):
        if (native / name).is_file():
            pairs.append((native / name, "files/LunaSubprocess64.exe"))
    for name in ("LunaHook32.dll", "LunaHook64.dll", "LunaHost32.dll", "LunaHost64.dll"):
        source = hook / name
        if name == "LunaHook32.dll" or source.is_file():
            pairs.append((source, "files/LunaHook/" + name))
    for source, _ in pairs:
        if not source.is_file():
            raise ValueError("Missing required build-produced native output: " + source.name)
    return pairs


def build(repo, template=None, native=None, hook=None):
    repo = Path(repo).resolve()
    runtime = repo / "dist"
    validate_existing(runtime)
    previous = json.loads((runtime / MANIFEST).read_text(encoding="utf-8")) if runtime.exists() else {}
    inputs = previous.get("build_inputs", {})
    template = Path(template or inputs.get("runtime_template", repo / "build/runtime-template"))
    native = Path(native or inputs.get("native_dir", repo / "build/native/bin"))
    hook = Path(hook or inputs.get("hook_dir", repo / "build/native/hook"))
    if previous and inventory(template) != previous.get("template_files"):
        raise ValueError("The local dependency template changed independently.")
    if not all(path.is_absolute() and path.is_dir() for path in (template, native, hook)):
        raise ValueError("Runtime template and native output directories must be absolute directories.")
    if template.resolve().is_relative_to(runtime.resolve()):
        raise ValueError("The runtime template must be independent of dist.")
    pairs = native_files(native, hook)
    native_sources = inventory(repo / "src/NativeImpl")
    python_inputs = inventory(repo / "src/LunaTranslator")
    try:
        provenances = {}
        for source, _ in pairs:
            if source.parent not in provenances:
                provenance = json.loads((source.parent / "workspace-native.json").read_text(encoding="utf-8"))
                if (provenance["schema"] != 1 or provenance["source_files"] != native_sources
                        or provenance["python_inputs"] != python_inputs):
                    raise ValueError
                provenances[source.parent] = provenance
            if provenances[source.parent]["output_files"].get(source.name) != digest(source):
                raise ValueError
    except (OSError, KeyError, TypeError, ValueError):
        raise ValueError("Native build provenance is missing or stale; rebuild matched native outputs.") from None
    if not (template / "files/runtime3.13-64/python3.dll").is_file():
        raise ValueError("Runtime template lacks the Python 3.13 x64 interpreter.")
    build_home = repo / "build"
    build_home.mkdir(exist_ok=True)
    stage = build_home / ("runtime-stage-" + uuid.uuid4().hex)
    backup = build_home / "runtime-backups" / uuid.uuid4().hex
    seed = build_home / "runtime-template"
    try:
        stage.mkdir()
        # Only dependency/assets roots and license notices are inherited. Never
        # sweep the legacy runtime's configuration, journals or diagnostics.
        for name in ("files",):
            copy_tree(template / name, stage / name)
        for path in template.iterdir():
            if path.is_file() and path.name.lower().startswith(("license", "copying")):
                shutil.copy2(path, stage / path.name)
        copy_tree(repo / "src/LunaTranslator", stage / "LunaTranslator")
        copy_tree(repo / "src/files", stage / "files")
        if (repo / "extensions").is_dir():
            copy_tree(repo / "extensions", stage / "extensions")
        for source, relative in pairs:
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        if not (stage / "LunaTranslator/LunaTranslator.py").is_file():
            raise ValueError("Incomplete application source tree.")
        files = inventory(stage)
        source_files = inventory(repo / "src/LunaTranslator")
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                                  capture_output=True, text=True, check=True, timeout=10).stdout.strip()
        # Seed offline dependencies locally so later builds have no dependency
        # on the legacy installation. No user state enters this disposable seed.
        if template.resolve() != seed.resolve():
            if seed.exists():
                raise ValueError("A local runtime template already exists; use it or inspect it explicitly.")
            seed_stage = build_home / ("template-stage-" + uuid.uuid4().hex)
            try:
                seed_stage.mkdir()
                copy_tree(template / "files", seed_stage / "files")
                for path in template.iterdir():
                    if path.is_file() and path.name.lower().startswith(("license", "copying")):
                        shutil.copy2(path, seed_stage / path.name)
                seed_stage.rename(seed)
            finally:
                if seed_stage.exists():
                    shutil.rmtree(seed_stage)
        manifest = {"schema": 1, "revision": revision, "source_files": source_files,
                    "source_assets": inventory(repo / "src/files"),
                    "source_extensions": inventory(repo / "extensions") if (repo / "extensions").exists() else {},
                    "template_files": inventory(seed),
                    "files": files, "native_files": {relative: digest(source) for source, relative in pairs},
                    "native_source_files": native_sources,
                    "build_inputs": {"runtime_template": str(seed), "native_dir": str(native), "hook_dir": str(hook)}}
        (stage / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if inventory(stage) != files:
            raise ValueError("Staged runtime failed digest validation.")
        # A second preflight closes the long-copy window. A loaded/locked file
        # makes the directory rename fail before the old runtime is discarded.
        validate_existing(runtime)
        if runtime.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            runtime.rename(backup)
        try:
            stage.rename(runtime)
        except OSError:
            if backup.exists():
                backup.rename(runtime)
            raise
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def launch(repo):
    repo = Path(repo).resolve()
    runtime = repo / "dist"
    executable = runtime / "LunaTranslator.exe"
    if not executable.is_file():
        raise ValueError("Build the workspace before launching Luna.")
    environment = dict(os.environ)
    environment.update(LUNA_WORKSPACE_HOME=str(repo / ".local"),
                       LUNA_USERCONFIG_HOME=str(repo / ".local/userconfig"),
                       LUNA_CACHE_HOME=str(repo / ".local/cache"))
    for name in tuple(environment):
        if name.startswith("LUNA_GRISAIA_"):
            del environment[name]
    return subprocess.Popen([str(executable)], cwd=runtime, env=environment)
