import os
import sys, hashlib
from pathlib import Path


def getpyfiles(source_root="LunaTranslator"):
    res = {}
    for _dir, _, _fs in os.walk(source_root):
        for _f in _fs:
            if not _f.endswith(".py"):
                continue
            path = os.path.normpath(os.path.join(_dir, _f))
            with open(path, "rb") as ff:
                code = ff.read()
            hs = hashlib.sha256(code).hexdigest()
            res["LunaTranslator/" + os.path.relpath(path, source_root).replace("\\", "/")] = hs
    s = ""
    for k, v in res.items():
        s += '{L"' + k + '", {parse_hex_string("' + v + '")}},'
    return s


def getpefiles(targetdir):
    from build_lunatranslator import myfiles

    s = ""
    for _ in myfiles:
        if not os.path.exists(os.path.join(targetdir, _)):
            continue
        s += '{L"' + _ + '"},'
    return s


def create_header(output, source_root="LunaTranslator", targetdir=None):
    template = Path(__file__).resolve().parents[1] / "NativeImpl/exec/checksigs.hpp"
    code = template.read_text(encoding="utf-8")
    code = code.replace("CHECK_DIGEST_LIST", "\n" + getpyfiles(source_root))
    code = code.replace("CHECK_CERT_LIST", "\n" + (getpefiles(targetdir) if targetdir else ""))
    Path(output).write_text(code, encoding="utf-8")


def buildexe(arch, target, targetdir):
    from build_lunatranslator import buildPlugins

    create_header(r"NativeImpl\exec\checksigs.hpp", targetdir=targetdir)
    buildPlugins(arch, target, " -DBUILD_EXEC_ONLY=ON")


if __name__ == "__main__":
    if sys.argv[1] == "header":
        create_header(sys.argv[2], Path(__file__).resolve().parents[1] / "LunaTranslator")
    else:
        buildexe(*sys.argv[1:])
