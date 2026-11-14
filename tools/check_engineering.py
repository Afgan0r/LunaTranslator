"""Check affected owned modules without migrating unchanged upstream code."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict, cast

ROOT = Path(__file__).resolve().parents[1]


class Policy(TypedDict):
    python: list[str]
    native: list[str]
    scripts: list[str]
    max_lines: int


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    ).stdout


def matches(name: str, patterns: Sequence[str]) -> bool:
    # **/ also includes files directly in the selected directory.
    return any(
        fnmatch.fnmatchcase(name, pattern) or fnmatch.fnmatchcase(name, pattern.replace("**/", ""))
        for pattern in patterns
    )


def affected(root: Path, base: str) -> list[str]:
    git(root, "rev-parse", "--verify", base + "^{commit}")
    changed = git(root, "diff", "--name-only", "--diff-filter=ACMR", "-z", base, "--")
    added = git(root, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted({name for name in (changed + added).split("\0") if name})


def size_errors(root: Path, names: Sequence[str], limit: int) -> list[str]:
    errors: list[str] = []
    for name in names:
        count = len((root / name).read_bytes().splitlines())
        if count > limit:
            errors.append(f"{name}: {count} physical lines exceeds {limit}")
    return errors


def tool(root: Path, name: str) -> str:
    directory = root / "build/engineering-venv" / ("Scripts" if os.name == "nt" else "bin")
    path = directory / (name + (".exe" if os.name == "nt" else ""))
    if not path.is_file():
        raise RuntimeError("Missing engineering environment; see docs/engineering/verification.md")
    return str(path)


def run(root: Path, command: list[str]) -> None:
    subprocess.run(command, cwd=root, check=True, timeout=180)


def check(root: Path, base: str) -> None:
    with (root / "pyproject.toml").open("rb") as stream:
        config = cast(Policy, tomllib.load(stream)["tool"]["luna-engineering"])
    python_patterns: list[str] = config["python"]
    native_patterns: list[str] = config["native"]
    script_patterns: list[str] = config["scripts"]
    names = affected(root, base)
    python = [name for name in names if matches(name, python_patterns)]
    native = [name for name in names if matches(name, native_patterns)]
    scripts = [name for name in names if matches(name, script_patterns)]
    print(
        f"Affected owned files: Python={len(python)}, native={len(native)}, scripts={len(scripts)}",
        flush=True,
    )
    if python or native:
        interpreter = tool(root, "python")
        # The environment, not a user's unrelated global installation, owns pins.
        probe = (
            "import importlib.metadata as m,json; "
            "print(json.dumps({n:m.version(n) for n in ['ruff','pyright','clang-format']}))"
        )
        versions: dict[str, str] = json.loads(
            subprocess.run(
                [interpreter, "-c", probe],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
        )
        for line in (root / "requirements-engineering.txt").read_text().splitlines():
            package, version = line.split("==")
            if versions.get(package) != version:
                raise RuntimeError(f"Engineering tool version mismatch: {package}")
    if python:
        run(root, [tool(root, "ruff"), "format", "--check", *python])
        run(root, [tool(root, "ruff"), "check", *python])
        run(root, [tool(root, "pyright"), "--project", "pyproject.toml", *python])
    if native:
        run(
            root,
            [
                tool(root, "clang-format"),
                "--style=file:" + str(root / ".clang-format"),
                "--dry-run",
                "--Werror",
                *native,
            ],
        )
    errors = size_errors(root, [*python, *native, *scripts], config["max_lines"])
    if errors:
        raise RuntimeError("\n".join(errors))
    if native:
        print("Native formatting/size passed; matching MSVC/ATL builds remain required separately.")


def push_bases(root: Path, lines: Sequence[str]) -> list[str]:
    head = git(root, "rev-parse", "HEAD").strip()
    bases: list[str] = []
    for line in lines:
        local_ref, local_sha, _remote_ref, remote_sha = line.split()
        if set(local_sha) == {"0"}:  # A deletion has no candidate tree.
            continue
        if local_sha != head or not local_ref.startswith("refs/heads/"):
            raise RuntimeError("Push only the checked-out, reviewed HEAD branch.")
        if set(remote_sha) == {"0"}:
            remote_sha = git(root, "merge-base", "HEAD", "origin/main").strip()
        bases.append(remote_sha)
    return sorted(set(bases))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--base", help="Fixed task base; includes current working-tree changes")
    mode.add_argument(
        "--pre-push", action="store_true", help="Read actual outgoing Git refs from stdin"
    )
    args = parser.parse_args()
    try:
        if args.pre_push:
            bases = push_bases(ROOT, sys.stdin.read().splitlines())
        elif isinstance(args.base, str):
            bases = [args.base]
        else:
            raise ValueError("A fixed comparison base is required.")
        for base in bases:
            check(ROOT, base)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
