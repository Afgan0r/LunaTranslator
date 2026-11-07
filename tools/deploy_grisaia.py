"""Copy the opt-in bridge and extension into an external matched Luna build."""

import argparse
import hashlib
import io
import json
import shutil
import sys
import uuid
import zipfile
from pathlib import Path

from install_grisaia_patches import digest, save_json

REPO = Path(__file__).resolve().parents[1]
BRIDGES = ("LunaTranslator.py", "main.py", "myutils/config.py",
           "myutils/updater.py", "gui/setting/about.py",
           "translator/selfbuild.py", "textio/textsource/texthook.py")
PYTHON_TLS_SHA256 = "8766a8775746235e23cf5aee5027ab1060bb981d93110577adcf3508aa0cbd55"
PYTHON_TLS_URL = "https://www.python.org/ftp/python/3.13.13/python-3.13.13-embed-amd64.zip"


def install_tls(runtime, archive, manifest):
    """Supply HTTPS dependencies without replacing Luna's interpreter."""
    if digest(archive) != PYTHON_TLS_SHA256:
        raise ValueError("Expected the official Python 3.13.13 amd64 archive.")
    target_dir = runtime / "files/runtime3.13-64"
    with zipfile.ZipFile(archive) as package:
        if hashlib.sha256(package.read("python313.dll")).hexdigest() != digest(target_dir / "python313.dll"):
            raise ValueError("Python runtime does not match the TLS archive exactly.")
        assets = [(name, package.read(name)) for name in
                  ("_ssl.pyd", "libssl-3.dll", "libcrypto-3.dll")]
        # The packaged IDNA codec imports stringprep, which Luna's reduced
        # stdlib omits. http.client encodes CONNECT hostnames through IDNA.
        with zipfile.ZipFile(io.BytesIO(package.read("python313.zip"))) as stdlib:
            assets.append(("stringprep.pyc", stdlib.read("stringprep.pyc")))
        assets.append(("Python-TLS-LICENSE.txt", package.read("LICENSE.txt")))
    records = {}
    for name, content in assets:
        target = target_dir / name
        expected = hashlib.sha256(content).hexdigest()
        current = digest(target) if target.exists() else None
        if current is not None and current != expected:
            raise ValueError("A TLS dependency already exists with different contents.")
        records[name] = {"installed_sha256": expected}
    for name, content in assets:
        target = target_dir / name
        if not target.exists():
            target.write_bytes(content)
        if digest(target) != records[name]["installed_sha256"]:
            raise ValueError("TLS dependency deployment digest mismatch.")
    manifest["python_tls"] = {"version": "3.13.13", "source_url": PYTHON_TLS_URL,
                              "archive_sha256": PYTHON_TLS_SHA256, "files": records}


def deploy(home, game, python_embed=None, native_hook=None, launcher_dir=None):
    if home.is_relative_to(REPO):
        raise ValueError("Runtime, configuration and journals must live outside Git.")
    runtime = home / "runtime" / "LunaTranslator_x64"
    if not (runtime / "LunaTranslator.exe").is_file():
        raise ValueError("Extract the matched x64 ZIP into the private runtime directory first.")
    code = runtime / "LunaTranslator"
    user = runtime / "userconfig"
    user.mkdir(exist_ok=True)
    files = [(REPO / "src/LunaTranslator" / name, code / name) for name in BRIDGES]
    files.extend((path, code / "translator/grisaia" / path.name)
                 for path in (REPO / "src/LunaTranslator/translator/grisaia").glob("*.py"))
    files.append((REPO / "extensions/grisaia/selfbuild.py", user / "selfbuild.py"))
    if native_hook:
        native_hook = native_hook.resolve()
        if native_hook.is_relative_to(REPO) or not native_hook.is_file():
            raise ValueError("Keep the compiled native hook outside Git.")
        files.append((native_hook, runtime / "files/LunaHook/LunaHook32.dll"))
    if launcher_dir:
        launcher_dir = launcher_dir.resolve()
        if launcher_dir.is_relative_to(REPO):
            raise ValueError("Keep compiled launchers outside Git.")
        for name in ("LunaTranslator.exe", "LunaTranslator_admin.exe"):
            source = launcher_dir / name
            data = source.read_bytes()
            if len(data) < 64 or data[:2] != b"MZ":
                raise ValueError("Expected a compiled Windows launcher.")
            offset = int.from_bytes(data[60:64], "little")
            if data[offset:offset + 6] != b"PE\0\0d\x86":
                raise ValueError("Expected an x64 Windows launcher.")
            files.append((source, runtime / name))
    manifest_path = home / "runtime-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"schema": 1, "files": {}}
    if python_embed:
        install_tls(runtime, python_embed, manifest)
        save_json(manifest_path, manifest)
    for source, target in files:
        relative = str(target.relative_to(runtime))
        record = manifest["files"].get(relative)
        current = digest(target) if target.exists() else None
        if record is None:
            backup = home / "runtime-originals" / relative
            if current:
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                if digest(backup) != current:
                    raise ValueError("Runtime backup digest mismatch.")
            record = {"original_sha256": current, "installed_sha256": current}
            manifest["files"][relative] = record
        elif current != record["installed_sha256"]:
            raise ValueError("A deployed runtime file changed independently; inspect before updating.")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        record["installed_sha256"] = digest(source)
        if digest(target) != record["installed_sha256"]:
            raise ValueError("Runtime deployment digest mismatch.")
        save_json(manifest_path, manifest)

    config_path = user / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else json.loads((REPO / "src/LunaTranslator/defaultconfig/config.json").read_text(encoding="utf-8"))
    for translator in config["fanyi"].values():
        translator["use"] = False
    config["fanyi"]["selfbuild"].update(use=True, use_trans_cache=False, name_self_set="Grisaia · OpenAI")
    config.update(srclang4="en", tgtlang4="ru", languageuse2="en", autorun=True,
                  autoupdate=False, textthreaddelay=0, codepage_value=932,
                  maxBufferSize=65536, maxHistorySize=1000000)
    for name, settings in config["sourcestatus2"].items():
        settings["use"] = name == "texthook"
    save_json(config_path, config)

    games_path = user / "savegamedata_5.3.1.json"
    games = json.loads(games_path.read_text(encoding="utf-8")) if games_path.exists() else [[], {}, [None], None, {}]
    game_exe = str(game / "Grisaia.exe")
    uid = next((uid for uid, data in games[1].items() if Path(data.get("gamepath", "")).resolve() == Path(game_exe)), str(uuid.uuid4()))
    if uid not in games[0]:
        games[0].append(uid)
    settings_path = home / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    if native_hook:
        settings.update(capture_protocol="grisaia-windows-v1", hook_code="auto:GrisaiaWindows",
                        hook_validated=False, diagnostic_hooks=[])
    hook = settings["hook_code"]
    game_config = games[1].setdefault(uid, {})
    game_config.update(gamepath=game_exe, title="The Fruit of Grisaia", steamid=345610,
                       lang_follow_default=False, private_srclang_2="en", private_tgtlang_2="ru",
                       hooksetting_follow_default=False,
                       hooksetting_private={"textthreaddelay": 0, "codepage_value": 932,
                                            "maxBufferSize": 65536, "maxHistorySize": 1000000},
                       needinserthookcode=[] if native_hook else [hook], inserthooktimeout=500,
                       embedablehook=[])
    save_json(games_path, games)
    settings.update(runtime_dir=str(runtime), game_uid=uid)
    save_json(settings_path, settings)
    launcher = home / "Start Luna.cmd"
    launcher.write_text('@echo off\nset "LUNA_GRISAIA_HOME=' + str(home) + '"\nset "LUNA_GRISAIA_GAME_EXE=' + game_exe + '"\nset "LUNA_GRISAIA_HOOK_CODE=' + hook + '"\ncd /d "' + str(runtime) + '"\nstart "" "LunaTranslator.exe"\n', encoding="utf-8")
    controls = home / "tools"
    controls.mkdir(exist_ok=True)
    for name in ("grisaia_control.py", "install_grisaia_patches.py"):
        shutil.copy2(REPO / "tools" / name, controls / name)
    for title, command in (("Retry", "retry"), ("New Run", "new-run"), ("Status", "status")):
        (home / (title + ".cmd")).write_text('@echo off\n"' + sys.executable + '" -X utf8 "' +
            str(controls / "grisaia_control.py") + '" --home "' + str(home) + '" ' + command + '\npause\n', encoding="utf-8")
    (home / "Rollback Patches.cmd").write_text('@echo off\n"' + sys.executable + '" -X utf8 "' +
        str(controls / "install_grisaia_patches.py") + '" --home "' + str(home) + '" --rollback\npause\n', encoding="utf-8")
    print("Deployed bridge, custom translator and English-to-Russian game profile:", runtime)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--python-embed", type=Path,
                        help="Official matching Python archive supplying missing TLS extensions")
    parser.add_argument("--native-hook", type=Path,
                        help="Private matching 32-bit LunaHook DLL; close Luna and the game first")
    parser.add_argument("--launcher-dir", type=Path,
                        help="Private x64 local launcher build directory")
    args = parser.parse_args()
    deploy(args.home.resolve(), args.game_dir.resolve(), args.python_embed, args.native_hook, args.launcher_dir)


if __name__ == "__main__":
    main()
