"""Observable durable queue/recovery behavior; synthetic dialogue only."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "LunaTranslator"))
from translator.grisaia import Journal, TranslationError, TranslationResult


class RecordingClient:
    def __init__(self):
        self.requests = []
        self.error = None

    def translate(self, messages, cache_key):
        self.requests.append(json.loads(json.dumps(messages)))
        if self.error:
            raise self.error
        return TranslationResult("Перевод " + messages[-1]["content"][0]["text"], {"usage": {"input_tokens": 1}})


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "history.sqlite3"
        self.journals = []
        self.j = self.open()

    def open(self):
        journal = Journal(self.path)
        self.journals.append(journal)
        return journal

    def tearDown(self):
        for j in self.journals:
            j.close()
        self.temp.cleanup()

    def test_three_captures_fifo_and_byte_equal_history_prefix(self):
        ids = [self.j.capture(t) for t in ("First", "Second", "Third")]
        client = RecordingClient()
        for entry_id in ids:
            self.assertEqual(self.j.process_one(client)["id"], entry_id)
        self.assertIsNone(self.j.process_one(client))
        for index in range(2):
            before, after = client.requests[index:index + 2]
            self.assertEqual(json.dumps(before, ensure_ascii=False), json.dumps(after[:len(before)], ensure_ascii=False))
        self.assertEqual([r[-1]["content"][0]["text"] for r in client.requests], ["First", "Second", "Third"])
        self.assertNotIn("Second", json.dumps(client.requests[0]))
        self.assertNotIn("Third", json.dumps(client.requests[1]))
        self.assertEqual(self.j.status()["counts"], {"completed": 3})

    def test_slow_request_allows_durable_capture_and_control_connection(self):
        first = self.j.capture("First")
        entered, release = threading.Event(), threading.Event()
        client = RecordingClient()
        translate = client.translate
        def slow(messages, key):
            entered.set()
            self.assertTrue(release.wait(5))
            return translate(messages, key)
        client.translate = slow
        errors = []
        def worker():
            try:
                self.j.process_one(client)
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(entered.wait(5))
        control = self.open()
        second = control.capture("Second")
        run = control.new_run("Manual boundary")
        third = control.capture("Third")
        self.assertEqual(control.entry(first)["state"], "inflight")
        self.assertFalse(control.retry())
        self.assertEqual(control.entry(second)["run_id"], 1)
        self.assertEqual(control.entry(third)["run_id"], run)
        release.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertNotIn("Second", json.dumps(client.requests[0]))
        self.assertNotIn("Third", json.dumps(client.requests[0]))
        self.assertNotIn("BEGIN CURRENT RUN 2", json.dumps(client.requests[0]))
        self.j.process_one(RecordingClient())
        third_messages = self.j.messages_for(third)
        self.assertIn("BEGIN CURRENT RUN 2", third_messages[-2]["content"][0]["text"])

    def test_failed_pause_survives_restart_and_exact_request_retry(self):
        first = self.j.capture("First")
        self.j.capture("Future must remain queued")
        client = RecordingClient()
        client.error = RuntimeError("sk-private-test-value reflected unsafe error")
        with self.assertRaises(TranslationError) as failure:
            self.j.process_one(client)
        self.assertNotIn("private", str(failure.exception))
        self.j.close()
        reopened = self.open()
        self.assertEqual(reopened.entry(first)["state"], "failed")
        good = RecordingClient()
        with self.assertRaises(TranslationError):
            reopened.process_one(good)
        self.assertEqual(good.requests, [])
        self.assertTrue(reopened.retry())
        reopened.process_one(good)
        self.assertEqual(client.requests[0], good.requests[0])
        self.assertEqual(reopened.entry(first)["attempts"], 2)
        self.assertNotIn("Future must remain queued", json.dumps(good.requests[0]))

    def test_interrupted_inflight_never_silently_repeats(self):
        first = self.j.capture("First")
        client = RecordingClient()
        client.error = SystemExit("Simulated process interruption")
        with self.assertRaises(SystemExit):
            self.j.process_one(client)
        self.j.close()
        reopened = self.open()
        good = RecordingClient()
        self.assertEqual(reopened.claim_worker()["head"]["state"], "uncertain")
        with self.assertRaises(TranslationError) as failure:
            reopened.process_one(good)
        self.assertEqual(failure.exception.code, "uncertain")
        self.assertEqual(good.requests, [])
        self.assertEqual(reopened.entry(first)["state"], "uncertain")
        self.assertTrue(reopened.retry())
        reopened.process_one(good)
        self.assertEqual(len(good.requests), 1)

    def test_second_worker_cannot_claim_even_when_idle(self):
        self.j.process_one(RecordingClient())
        second = self.open()
        captured = second.capture("Later")
        with self.assertRaises(TranslationError) as failure:
            second.process_one(RecordingClient())
        self.assertEqual(failure.exception.code, "worker_busy")
        self.assertEqual(second.entry(captured)["state"], "pending")

    def test_other_process_can_control_but_cannot_steal_worker(self):
        self.j.process_one(RecordingClient())
        source = "\n".join((
            "import json, sys",
            "sys.path.insert(0, sys.argv[1])",
            "from translator.grisaia import Journal, TranslationError",
            "with Journal(sys.argv[2]) as j:",
            "    run = j.new_run('Other process control')",
            "    captured = j.capture('Other process capture')",
            "    try:",
            "        j.process_one(None)",
            "    except TranslationError as exc:",
            "        print(json.dumps({'run': run, 'id': captured, 'code': exc.code, 'counts': j.status()['counts']}))",
        ))
        completed = subprocess.run([sys.executable, "-c", source,
            str(Path(__file__).resolve().parents[2] / "src" / "LunaTranslator"), str(self.path)],
            capture_output=True, text=True, timeout=10, check=True)
        result = json.loads(completed.stdout)
        self.assertEqual(result["code"], "worker_busy")
        self.assertEqual(result["run"], 2)
        self.assertEqual(result["counts"], {"pending": 1})
        self.assertEqual(self.j.entry(result["id"])["original"], "Other process capture")

    def test_true_repeats_and_run_boundaries_retained(self):
        a = self.j.capture("Repeat", "window-a")
        self.assertEqual(self.j.capture("Repeat", "window-a"), a)
        b = self.j.capture("Other", "window-b")
        c = self.j.capture("Repeat", "window-a")
        self.j.new_run("Restart")
        d = self.j.capture("Repeat", "window-a")
        e = self.j.capture("Repeat")
        self.assertEqual(len(set((a, b, c, d, e))), 5)
        client = RecordingClient()
        for _ in range(5):
            self.j.process_one(client)
        messages = client.requests[3]
        self.assertIn("archived", messages[-2]["content"][0]["text"])
        self.assertEqual(sum(m["role"] == "assistant" for m in messages), 3)

    def test_context_pause_distinguished_and_no_automatic_shortening(self):
        entry_id = self.j.capture("Current")
        client = RecordingClient()
        client.error = TranslationError("context_overflow")
        with self.assertRaises(TranslationError) as failure:
            self.j.process_one(client)
        self.assertEqual(failure.exception.code, "context_overflow")
        self.assertEqual(self.j.entry(entry_id)["error_code"], "context_overflow")
        with self.assertRaises(TranslationError):
            self.j.process_one(client)
        self.assertEqual(len(client.requests), 1)

    def test_partial_translation_is_not_committed_and_blocks_backlog(self):
        first = self.j.capture("Current")
        second = self.j.capture("Next")
        client = RecordingClient()
        client.error = TranslationError("incomplete")
        with self.assertRaises(TranslationError):
            self.j.process_one(client)
        self.assertIsNone(self.j.entry(first)["translation"])
        self.assertEqual(self.j.entry(second)["state"], "pending")
        with self.assertRaises(TranslationError):
            self.j.messages_for(second)

    def test_prompt_immutable_and_sqlite_durability_settings(self):
        with self.assertRaises(ValueError):
            Journal(self.path, "Different prompt")
        self.assertEqual(self.j._db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(self.j._db.execute("PRAGMA synchronous").fetchone()[0], 2)
        self.assertEqual(self.j._db.execute("PRAGMA integrity_check").fetchone()[0], "ok")


if __name__ == "__main__":
    unittest.main()
