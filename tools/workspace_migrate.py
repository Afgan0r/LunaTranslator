"""One-time non-destructive migration of an explicitly selected legacy home."""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path


def restrict_private(directory):
    """Restrict an empty staging directory before it receives private data."""
    if os.name != "nt":
        directory.chmod(0o700)
        return
    domain, username = os.environ.get("USERDOMAIN"), os.environ.get("USERNAME")
    if not domain or not username:
        raise ValueError("Cannot determine the current account for private workspace permissions.")
    try:
        subprocess.run(["icacls", str(directory), "/inheritance:r", "/grant:r",
                        domain + "\\" + username + ":(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                       check=True, capture_output=True, timeout=30,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        raise ValueError("Could not restrict private workspace permissions; migration stopped.") from None


def snapshot(connection):
    """Exact schema and rows, including prompt/cache metadata and checkpoints."""
    schema = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    rows = {}
    for kind, name, _, _ in schema:
        if kind == "table":
            escaped = name.replace('"', '""')
            rows[name] = connection.execute('SELECT * FROM "' + escaped + '"').fetchall()
    return schema, rows


def backup_journal(source, target):
    # mode=ro still sees a committed WAL. Use SQLite's transaction-consistent
    # backup API rather than copying the database file and losing WAL rows.
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original:
        original.execute("BEGIN")
        expected = snapshot(original)
        with closing(sqlite3.connect(target)) as destination:
            original.backup(destination)
            if snapshot(destination) != expected:
                raise ValueError("Journal migration failed exact schema/table/row validation.")
            if destination.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Migrated journal failed integrity validation.")
        original.rollback()


def game_identity(settings, userconfig, game_exe=None):
    executable = Path(game_exe or settings.get("game_exe", ""))
    if not executable.is_absolute():
        raise ValueError("Legacy settings must identify an absolute game executable.")
    uid = settings.get("game_uid")
    games = userconfig / "savegamedata_5.3.1.json"
    matches = []
    if games.is_file():
        saved = json.loads(games.read_text(encoding="utf-8-sig"))
        for candidate, profile in saved[1].items():
            if os.path.normcase(str(Path(profile.get("gamepath", "")).resolve())) == os.path.normcase(str(executable.resolve())):
                matches.append(candidate)
    if uid:
        if matches and (len(matches) != 1 or matches[0] != uid):
            raise ValueError("Legacy game UID conflicts with saved game mapping.")
    elif len(matches) == 1:
        uid = matches[0]
    else:
        raise ValueError("Cannot uniquely identify the existing saved game profile.")
    if not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", uid):
        raise ValueError("Invalid legacy game UID.")
    return uid, str(executable)


def migrate(repo, legacy, game_exe=None):
    repo, legacy = Path(repo).resolve(), Path(legacy)
    if not legacy.is_absolute() or not legacy.is_dir():
        raise ValueError("Legacy home must be an absolute existing directory.")
    destination = repo / ".local"
    if destination.exists():
        raise ValueError("Workspace state already exists; migration refuses conflicts.")
    settings = json.loads((legacy / "settings.json").read_text(encoding="utf-8-sig"))
    runtime = Path(settings.get("runtime_dir", legacy / "runtime/LunaTranslator_x64"))
    userconfig = runtime / "userconfig"
    if not userconfig.is_dir():
        raise ValueError("Legacy portable userconfig is missing.")
    uid, executable = game_identity(settings, userconfig, game_exe)
    # Stage private state beside its destination, outside disposable build/.
    stage = Path(tempfile.mkdtemp(prefix=".local-migrate-", dir=repo))
    try:
        restrict_private(stage)
        profile_home = stage / "games" / uid
        profile_home.mkdir(parents=True)
        backup_journal(legacy / "journal.sqlite3", profile_home / "journal.sqlite3")
        for name in ("capture-fault.jsonl", "hook-probe.jsonl", "hook-probe-insertions.jsonl", "egress.jsonl"):
            if (legacy / name).is_file():
                shutil.copy2(legacy / name, profile_home / name)
        # Preserve all portable settings/assets except the old custom entrypoint.
        shutil.copytree(userconfig, stage / "userconfig",
                        ignore=shutil.ignore_patterns("selfbuild.py", "__pycache__", "*.pyc"))
        config = {"schema": 1, "defaults": {}, "profiles": {
            uid: {"adapter": "grisaia", "game_exe": executable, "settings": settings}}}
        (stage / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if destination.exists():
            raise ValueError("Workspace state appeared during migration; refusing replacement.")
        stage.rename(destination)
        return uid
    finally:
        if stage.exists():
            shutil.rmtree(stage)
