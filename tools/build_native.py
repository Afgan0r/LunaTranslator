"""Build the Windows runtime dependencies for the current working source."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_hooks(repo, config, cmake, output):
    for arch, suffix in (("Win32", "32"), ("x64", "64")):
        directory = repo / ("build/native/hook" + suffix)
        command = [cmake, "-S", str(repo / "src/NativeImpl/LunaHook"),
                   "-B", str(directory), "-G", "Visual Studio 17 2022", "-A", arch,
                   "-DBUILD_HOST=ON", "-DBUILD_HOOK=ON",
                   "-DLUNA_OUTPUT_DIRECTORY=" + output.as_posix()]
        include = config.get("atl_include")
        command.append("-DCMAKE_CXX_FLAGS=/EHsc" + (' /I"' + include + '"' if include else ""))
        library = config.get("atl_lib_x86" if suffix == "32" else "atl_lib")
        if library:
            command.append('-DCMAKE_MODULE_LINKER_FLAGS=/LIBPATH:"' + library + '"')
        for name, source in config.get("dependency_sources", {}).items():
            command.append("-DFETCHCONTENT_SOURCE_DIR_" + name.upper() + "=" + source)
        for stage, arguments in (("configure", command), ("compile", [cmake, "--build",
                str(directory), "--config", "Release", "--parallel", "4",
                "--target", "LunaHook", "LunaHostDll"])):
            log = repo / ("build/native/hook" + suffix + "-" + stage + ".log")
            print("Hook " + suffix + " " + stage + ": " + str(log), flush=True)
            with log.open("w", encoding="utf-8") as stream:
                subprocess.run(arguments, cwd=repo, stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=1200)


def build(repo=REPO):
    from workspace_build import inventory

    repo = Path(repo).resolve()
    home = repo / ".local"
    config_path = home / "native-toolchain.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    cmake = config.get("cmake", "cmake")
    output = repo / "build/native/bin"
    directory = repo / "build/native/x64"
    stamp = output / "workspace-native.json"
    sources = inventory(repo / "src/NativeImpl")
    python_inputs = inventory(repo / "src/LunaTranslator")
    hook_names = ("LunaHook32.dll", "LunaHook64.dll", "LunaHost32.dll", "LunaHost64.dll")
    names = ("LunaTranslator.exe", "LunaTranslator_admin.exe", "NativeUtils.dll", "CVUtils.dll") + hook_names
    previous = {}
    if stamp.exists():
        previous = json.loads(stamp.read_text(encoding="utf-8"))
        files = previous.get("output_files", {})
        if (previous.get("source_files") == sources and
                previous.get("python_inputs") == python_inputs and set(names) <= set(files) and
                all((output / name).is_file() and digest(output / name) == value
                    for name, value in files.items())):
            print("Native outputs match the current source.")
            return
    output.mkdir(parents=True, exist_ok=True)
    header = repo / "build/native/checksigs.hpp"
    subprocess.run([sys.executable, "-X", "utf8", str(repo / "src/scripts/createsigexe.py"),
                    "header", str(header)], cwd=repo, check=True, timeout=60)
    command = [cmake, "-S", str(repo / "src/NativeImpl"), "-B", str(directory),
               "-G", "Visual Studio 17 2022", "-A", "x64",
               "-DLUNA_OUTPUT_DIRECTORY=" + output.as_posix(),
               "-DLUNA_CHECKSIGS_HEADER=" + header.as_posix()]
    include = config.get("atl_include")
    flags = "/EHsc" + (' /I"' + str(include) + '"' if include else "")
    command.append("-DCMAKE_CXX_FLAGS=" + flags)
    if config.get("atl_lib"):
        for kind in ("EXE", "SHARED", "MODULE"):
            command.append("-DCMAKE_" + kind + '_LINKER_FLAGS=/LIBPATH:"' + config["atl_lib"] + '"')
    if config.get("magic_enum_source"):
        command.append("-DFETCHCONTENT_SOURCE_DIR_MAGIC_ENUM=" + config["magic_enum_source"])
    for name, source in config.get("dependency_sources", {}).items():
        command.append("-DFETCHCONTENT_SOURCE_DIR_" + name.upper() + "=" + source)
    for stage, arguments in (("configure", command), ("compile", [cmake, "--build", str(directory),
                              "--config", "Release", "--parallel", str(config.get("parallel", 4)),
                              "--target", "LunaTranslator", "LunaTranslator_admin", "NativeUtils", "CVUtils"])):
        log = repo / ("build/native/" + stage + ".log")
        print("Native " + stage + ": " + str(log), flush=True)
        with log.open("w", encoding="utf-8") as stream:
            result = subprocess.run(arguments, cwd=repo, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=1200, check=False)
        if result.returncode:
            raise RuntimeError("Native " + stage + " failed; inspect " + str(log))
    hook_files = previous.get("output_files", {})
    if not (previous.get("source_files") == sources and
            all(name in hook_files and (output / name).is_file() and
                digest(output / name) == hook_files[name] for name in hook_names)):
        build_hooks(repo, config, cmake, output)
    outputs = {name: digest(output / name) for name in names}
    payload = {"schema": 1, "source_files": sources, "python_inputs": python_inputs,
               "output_files": outputs}
    temporary = stamp.with_suffix(".new")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, stamp)
    print("Native build verified for the current source.")


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        build()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
