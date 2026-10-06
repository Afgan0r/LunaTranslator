"""Synthetic archive/parser cases; no copyrighted game text fixtures."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

SOURCE = Path(__file__).resolve().parents[2] / "tools" / "extract_grisaia.py"
spec = importlib.util.spec_from_file_location("extract_grisaia", SOURCE)
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)


def cst(records):
    strings = bytearray()
    offsets = []
    for kind, text in records:
        offsets.append(len(strings))
        strings.extend(struct.pack("<H", kind) + text.encode("cp932") + b"\0")
    table = b"".join(struct.pack("<I", x) for x in offsets)
    body = struct.pack("<IIII", len(table) + len(strings), 0, 0, len(table)) + table + strings
    packed = zlib.compress(body)
    return b"CatScene" + struct.pack("<II", len(packed), len(body)) + packed


class ExtractionTests(unittest.TestCase):
    def test_windows_join_fragments_clear_speaker_and_skip_commands(self):
        data = cst([(0x2101, "Speaker"), (0x2001, "First\\@"),
                    (0x3001, "voice clip"), (0x2001, "second"),
                    (0x0201, ""), (0x2001, "Narration"), (0x0301, "")])
        rows = list(extract.windows(extract.scene_lines(data)))
        self.assertEqual([x["text"] for x in rows], ["First\nsecond", "Narration"])
        self.assertEqual([x["speaker"] for x in rows], ["Speaker", ""])
        self.assertEqual(rows[0]["line_indices"], [0, 1, 3])
        self.assertEqual([x["window_index"] for x in rows], [0, 1])

    def test_plain_archive_both_name_sizes(self):
        for width in (32, 64):
            with self.subTest(width=width), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "sample.int"
                payload = b"synthetic"
                path.write_bytes(b"KIF\0" + struct.pack("<I", 1) + b"open.cst".ljust(width, b"\0")
                                 + struct.pack("<II", 8 + width + 8, len(payload)) + payload)
                self.assertEqual(extract.Archive(path).read("open.cst"), payload)

    def test_corrupt_scene_length_is_rejected(self):
        data = bytearray(cst([(0x2001, "Example")]))
        struct.pack_into("<I", data, 12, 999)
        with self.assertRaisesRegex(ValueError, "length mismatch"):
            list(extract.scene_lines(data))

    def test_grisaia_font_wrapping_keeps_raw_provenance(self):
        data = cst([(0x2101, "Young\\fs\u3000\\fnWoman"),
                    (0x2001, "\\fnIt`s [an] [example.]\\@"),
                    (0x2001, ""), (0x0201, "")])
        row = next(extract.windows(extract.scene_lines(data)))
        self.assertEqual(row["speaker"], "Young Woman")
        self.assertEqual(row["text"], "It's an example.")
        self.assertEqual(row["raw_fragments"][1], "\\fnIt`s [an] [example.]\\@")

    def test_window_iterator_stops_before_later_story(self):
        def lines():
            yield {"kind": 0x2001, "raw": "Example", "line_index": 0}
            yield {"kind": 0x0201, "raw": "", "line_index": 1}
            raise AssertionError("Later scene data must not be decoded")
        self.assertEqual(next(extract.windows(lines()))["text"], "Example")


if __name__ == "__main__":
    unittest.main()
