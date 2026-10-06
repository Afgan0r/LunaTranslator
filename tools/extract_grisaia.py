"""Extract a bounded, private CatSystem2 opening sample; never modifies the game.

Archive algorithms adapted from morkt/GARbro b09ee4570ccb1daf6ac56710ee8934dc0b8baeb0
(ArcFormats/CatSystem/ArcINT.cs, ArcFormats/MersenneTwister.cs).
CatScene layout: trigger-segfault/catsystem-py
70ad39f9c0f46e74e656b405ec1f0879e9dea3b5 (src/catsys/scene/cst.py).
Copyright (C) 2014 morkt; Copyright (c) 2020 Robert Jordan.
Copyright (C) 1997 Makoto Matsumoto and Takuji Nishimura (MT algorithm).

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import zlib

MASK = 0xFFFFFFFF


def mt_first(seed):
    """First output of CatSystem's original (pre-2002 initialization) MT19937."""
    state = []
    for _ in range(624):
        high = seed & 0xFFFF0000
        seed = (69069 * seed + 1) & MASK
        state.append(high | (seed >> 16))
        seed = (69069 * seed + 1) & MASK
    # Only the first twisted state is required for this archive format.
    y = (state[0] & 0x80000000) | (state[1] & 0x7FFFFFFF)
    y = state[397] ^ (y >> 1) ^ (0x9908B0DF if y & 1 else 0)
    y ^= y >> 11
    y ^= (y << 7) & 0x9D2C5680
    y ^= (y << 15) & 0xEFC60000
    return (y ^ (y >> 18)) & MASK


def name_decode(raw, key):
    alphabet = b"zyxwvutsrqponmlkjihgfedcbaZYXWVUTSRQPONMLKJIHGFEDCBA"
    k = sum(key.to_bytes(4, "little")) & 255
    result = bytearray(raw.split(b"\0", 1)[0])
    for i, value in enumerate(result):
        if value in alphabet:
            result[i] = alphabet[51 - ((alphabet.index(value) - k % 52) % 52)]
        k += 1
    return result.decode("cp932")


def crc_password(data):
    key = MASK
    for value in data:
        crc = ((key >> 24) ^ value) << 24
        for _ in range(8):
            crc = ((crc << 1) ^ (0x04C11DB7 if crc & 0x80000000 else 0)) & MASK
        key = ((~crc) ^ (key << 8)) & MASK
    return key


def blowfish(key):
    try:
        from Crypto.Cipher import Blowfish
    except ImportError as exc:
        raise RuntimeError("Encrypted KIF needs pycryptodome in your private dependency directory") from exc
    return Blowfish.new(key, Blowfish.MODE_ECB)


def decrypt_le(cipher, data):
    size = len(data) // 8 * 8
    # GARbro's byte decrypt treats each uint32 as little-endian; Blowfish is BE.
    swapped = b"".join(data[i:i + 4][::-1] for i in range(0, size, 4))
    decoded = cipher.decrypt(swapped)
    return b"".join(decoded[i:i + 4][::-1] for i in range(0, size, 4)) + data[size:]


def executable_key(path):
    try:
        import pefile
    except ImportError as exc:
        raise RuntimeError("Encrypted KIF needs pefile in your private dependency directory") from exc
    pe = pefile.PE(str(path))
    resources = {}
    try:
        for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            for name in kind.directory.entries:
                if kind.name and name.name:
                    entry = name.directory.entries[0].data.struct
                    resources[(str(kind.name), str(name.name))] = pe.get_data(entry.OffsetToData, entry.Size)
        code = resources[("V_CODE2", "DATA")]
        key = bytes(v ^ 0xCD for v in resources[("KEY_CODE", "KEY")]) if ("KEY_CODE", "KEY") in resources else b"windmill"
        password = decrypt_le(blowfish(key), code).split(b"\0", 1)[0]
        return crc_password(password)
    finally:
        pe.close()


class Archive:
    def __init__(self, path, main_key=None):
        self.path = Path(path)
        self.entries = {}
        self.cipher = None
        with self.path.open("rb") as stream:
            signature, count = struct.unpack("<4sI", stream.read(8))
            if signature != b"KIF\0" or not 0 < count < 100000:
                raise ValueError("Invalid KIF header")
            encrypted = stream.read(64).startswith(b"__key__.dat\0")
            stream.seek(8)
            if encrypted:
                if main_key is None:
                    raise ValueError("Encrypted KIF requires executable key")
                table = stream.read(count * 72)
                if len(table) != count * 72:
                    raise ValueError("Truncated encrypted KIF index")
                seed = struct.unpack_from("<I", table, 68)[0]
                self.cipher = blowfish(struct.pack("<I", mt_first(seed)))
                for i in range(1, count):
                    row = table[i * 72:(i + 1) * 72]
                    offset, size = struct.unpack_from("<II", row, 64)
                    offset, size = struct.unpack("<II", decrypt_le(self.cipher, struct.pack("<II", (offset + i) & MASK, size)))
                    self.entries[name_decode(row[:64], mt_first((main_key + i) & MASK))] = (offset, size)
            else:
                for name_size in (64, 32):
                    stream.seek(8)
                    entries = {}
                    for _ in range(count):
                        row = stream.read(name_size + 8)
                        if len(row) != name_size + 8:
                            break
                        try:
                            name = row[:name_size].split(b"\0", 1)[0].decode("cp932")
                        except UnicodeDecodeError:
                            break
                        offset, size = struct.unpack_from("<II", row, name_size)
                        if not name or offset < 8 + count * (name_size + 8) or offset + size > self.path.stat().st_size:
                            break
                        entries[name] = (offset, size)
                    if len(entries) == count:
                        self.entries = entries
                        break
            if not self.entries or any(o + s > self.path.stat().st_size for o, s in self.entries.values()):
                raise ValueError("KIF index decryption or bounds validation failed")

    def read(self, name):
        offset, size = self.entries[name]
        with self.path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(size)
        return decrypt_le(self.cipher, data) if self.cipher else data


def scene_lines(data, encoding="cp932"):
    if data[:8] != b"CatScene":
        raise ValueError("Not a CatScene script")
    packed, unpacked = struct.unpack_from("<II", data, 8)
    body = zlib.decompress(data[16:16 + packed])
    if len(body) != unpacked:
        raise ValueError("CatScene decompressed length mismatch")
    _, inputs, table, strings = struct.unpack_from("<IIII", body)
    if table < inputs * 8 or strings < table or (strings - table) % 4 or 16 + strings > len(body):
        raise ValueError("Invalid CatScene tables")
    for index, (offset,) in enumerate(struct.iter_unpack("<I", body[16 + table:16 + strings])):
        start = 16 + strings + offset
        kind = struct.unpack_from("<H", body, start)[0]
        end = body.index(0, start + 2)
        yield {"line_index": index, "kind": kind, "raw": body[start + 2:end].decode(encoding)}


def display_text(raw):
    """Remove Grisaia font/word grouping controls; retain originals separately."""
    text = raw.removesuffix("\\@").replace("\\n", "\n")
    if "\\fn" in text or "\\fs" in text:
        text = text.replace("\\fn", "").replace("\\fs", "")
        text = re.sub(r"\[([^\[\]]*)\]", r"\1", text)
    return text.replace("\u3000", " ").replace("`", "'")


def windows(lines):
    current = None
    index = 0
    for line in lines:
        kind = line["kind"]
        if kind in (0x0201, 0x0301):
            if current and current["text"]:
                current["window_index"] = index
                yield current
                index += 1
            current = None
        elif kind in (0x2001, 0x2101):
            if current is None:
                current = {"speaker": "", "text": "", "line_indices": [], "raw_fragments": []}
            current["line_indices"].append(line["line_index"])
            current["raw_fragments"].append(line["raw"])
            if kind == 0x2101:
                current["speaker"] += display_text(line["raw"])
            else:
                text = display_text(line["raw"])
                if text:
                    current["text"] += ("\n" if current["text"] else "") + text
    if current and current["text"]:
        current["window_index"] = index
        yield current


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--deps", type=Path)
    parser.add_argument("--archive", default="scene.int")
    parser.add_argument("--scene", help="Explicit startup-confirmed opening CST name")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=15)
    parser.add_argument("--encoding", default="cp932")
    parser.add_argument("--output", type=Path, help="Private JSON path outside the repository; stdout if omitted")
    parser.add_argument("--inspect-startup", action="store_true", help="Print bounded main.kcs startup references (no scene text)")
    args = parser.parse_args()
    if args.deps:
        sys.path.insert(0, str(args.deps.resolve()))
    if args.start < 0 or not 10 <= args.count <= 15:
        parser.error("--start must be nonnegative; --count must be 10..15")
    exe = args.game_dir / "Grisaia.exe"
    archive_path = args.game_dir / args.archive
    with archive_path.open("rb") as stream:
        stream.seek(8)
        encrypted = stream.read(12).startswith(b"__key__.dat")
    key = executable_key(exe) if encrypted or args.inspect_startup else None
    if args.inspect_startup:
        arc = Archive(args.game_dir / "kcs.int", key)
        data = arc.read("main.kcs")
        print("main.kcs header", data[:16].hex(), "sha256", hashlib.sha256(data).hexdigest())
        if data[:4] == b"KCS\0":
            offset = struct.unpack_from("<I", data, 12)[0]
            data = zlib.decompress(data[offset:])
        refs = re.findall(rb"[ -~]{4,}", data)
        print("startup references", [x.decode("ascii") for x in refs if re.search(rb"start|\.cst|scene|newgame", x, re.I)][:20])
        scene = Archive(archive_path, key)
        if "start.cst" in scene.entries:
            start = scene.read("start.cst")
            print("start.cst sha256", hashlib.sha256(start).hexdigest())
            print("opening jumps", [(x["line_index"], x["raw"]) for x in scene_lines(start, args.encoding)
                                    if x["kind"] == 0x3001 and x["raw"].lower().startswith("next ")])
        return
    if not args.scene:
        parser.error("--scene is required; identify the opening via --inspect-startup first")
    if args.output and args.output.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("Private game text must be stored outside the repository")
    arc = Archive(archive_path, key)
    data = arc.read(args.scene)
    opening_selector = None
    if "start.cst" in arc.entries:
        start_data = arc.read("start.cst")
        jumps = [{"line_index": row["line_index"], "command": row["raw"]}
                 for row in scene_lines(start_data, args.encoding)
                 if row["kind"] == 0x3001 and row["raw"].lower().startswith("next ")]
        opening_selector = {"scene": "start.cst", "sha256": hashlib.sha256(start_data).hexdigest(),
                            "jumps": jumps,
                            "selected_scene_matches": any(row["command"][5:].strip().lower() + ".cst" == args.scene.lower() for row in jumps)}
    # Consume only prior context and sample; do not decode the scene's later story.
    selected = []
    for window in windows(scene_lines(data, args.encoding)):
        selected.append(window)
        if len(selected) == args.start + args.count:
            break
    if len(selected) < args.start + args.count:
        raise ValueError("Scene has too few dialogue windows for requested consecutive sample")
    payload = {"schema_version": 1, "index_base": 0, "source_archive": args.archive,
               "source_archive_sha256": digest(archive_path), "source_executable": exe.name,
               "source_executable_sha256": digest(exe), "scene": args.scene,
               "scene_sha256": hashlib.sha256(data).hexdigest(), "encoding": args.encoding,
               "opening_selector": opening_selector,
               "display_normalization": "Remove font controls and word grouping brackets; map full-width spaces and apostrophe glyph backticks. Original fragments preserved.",
               "prior_context": selected[:args.start], "sample": selected[args.start:]}
    output = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(json.dumps({"windows": len(payload["sample"]), "spoken": sum(bool(x["speaker"]) for x in payload["sample"]), "prior_context": len(payload["prior_context"]), "output_sha256": digest(args.output)}))
    else:
        print(output)


if __name__ == "__main__":
    main()
