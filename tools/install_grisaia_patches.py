"""Install only the selected Steam/HCG assets, with a verified local rollback."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


ASSETS = (
    ("Grisaia HCG Patch.rar", "update98.int", "hcg", "update98.int"),
    ("Grisaia Movie Patch.rar", "UNRATED & HCG/update97.int", "movie", "update97.int"),
)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_json(path, data):
    temporary = path.with_suffix(".new")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def inside(root, relative):
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("Asset path escapes its intended directory.")
    return target


def install(game, home, downloads, seven_zip):
    if not (game / "Grisaia.exe").is_file() or not (game / "scene.int").is_file():
        raise ValueError("Expected an installed English Steam game directory.")
    private = home / "patches"
    private.mkdir(parents=True, exist_ok=True)
    manifest_path = private / "install-manifest.json"
    if manifest_path.exists():
        raise ValueError("An installation manifest already exists. Inspect or roll it back first.")
    plan = []
    for archive_name, member, stage_name, destination_name in ASSETS:
        archive = downloads / archive_name
        stage = private / stage_name
        stage.mkdir(exist_ok=True)
        # Explicit destination and member names; no bundled saves are extracted.
        subprocess.run([str(seven_zip), "x", "-y", "-bso0", "-bsp0",
                        "-o" + str(stage), str(archive), member.replace("/", "\\"),
                        "Readme.txt"], check=True)
        source = inside(stage, member)
        target = inside(game, destination_name)
        backup = inside(private / "originals", destination_name)
        old_hash = digest(target) if target.exists() else None
        if old_hash:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            if digest(backup) != old_hash:
                raise ValueError("Original backup digest mismatch.")
        plan.append({"name": destination_name, "source": str(source),
                     "archive": str(archive), "archive_sha256": digest(archive),
                     "original_sha256": old_hash, "installed_sha256": digest(source),
                     "backup": str(backup) if old_hash else None, "state": "pending"})
    manifest = {"schema": 1, "game": str(game), "game_exe_sha256": digest(game / "Grisaia.exe"),
                "state": "installing", "assets": plan}
    save_json(manifest_path, manifest)
    for item in plan:
        target = inside(game, item["name"])
        current = digest(target) if target.exists() else None
        if current != item["original_sha256"]:
            raise ValueError("A target changed since backup; installation stopped.")
        shutil.copy2(item["source"], target)
        if digest(target) != item["installed_sha256"]:
            raise ValueError("Installed asset digest mismatch.")
        item["state"] = "installed"
        save_json(manifest_path, manifest)
    manifest["state"] = "installed"
    save_json(manifest_path, manifest)
    print("Installed HCG update98.int and UNRATED & HCG Movie update97.int. Rollback manifest:", manifest_path)


def rollback(home):
    private = home / "patches"
    path = private / "install-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest["state"] == "rolled_back":
        raise ValueError("No active supported patch manifest.")
    game = Path(manifest["game"]).resolve()
    if digest(game / "Grisaia.exe") != manifest["game_exe_sha256"]:
        raise ValueError("Game executable changed since installation; inspect before rollback.")
    # Preflight every file before restoring any of them.
    for item in manifest["assets"]:
        if item["name"] not in {asset[3] for asset in ASSETS}:
            raise ValueError("Unexpected manifest target.")
        target = inside(game, item["name"])
        current = digest(target) if target.exists() else None
        if current not in (item["original_sha256"], item["installed_sha256"]):
            raise ValueError("A patched file was modified; rollback stopped without overwriting it.")
        if item["backup"]:
            backup = inside(private / "originals", item["name"])
            if digest(backup) != item["original_sha256"]:
                raise ValueError("Backup digest mismatch.")
    for item in manifest["assets"]:
        target = inside(game, item["name"])
        if item["backup"]:
            shutil.copy2(inside(private / "originals", item["name"]), target)
        elif target.exists():
            # Only a verified exact file is removed, never a directory/tree.
            target.unlink()
        current = digest(target) if target.exists() else None
        if current != item["original_sha256"]:
            raise ValueError("Rollback digest mismatch.")
    manifest["state"] = "rolled_back"
    save_json(path, manifest)
    print("Original patch-file state restored and verified.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--game-dir", type=Path)
    parser.add_argument("--downloads", type=Path)
    parser.add_argument("--seven-zip", type=Path, default=Path("C:/Program Files/7-Zip/7z.exe"))
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    home = args.home.resolve()
    if args.rollback:
        rollback(home)
    else:
        if not args.game_dir or not args.downloads:
            parser.error("Installation requires --game-dir and --downloads.")
        install(args.game_dir.resolve(), home, args.downloads.resolve(), args.seven_zip)


if __name__ == "__main__":
    main()
