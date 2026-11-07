"""Synthetic checkpoints exercise actual SQLite history and FIFO recovery."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "LunaTranslator"))
from translator.grisaia import Journal, TranslationError, TranslationResult


class Client:
    compact_every = 100

    def __init__(self):
        self.compactions = []
        self.translations = []
        self.fail_compact = False
        self.fail_translate = False

    def compact(self, messages, key):
        self.compactions.append(messages)
        if self.fail_compact:
            raise TranslationError("request_failed")
        return TranslationResult("Names and unresolved references retained.", {"model": "gpt-6.1-sol"})

    def translate(self, messages, key):
        self.translations.append(messages)
        if self.fail_translate:
            raise TranslationError("request_failed")
        return TranslationResult("Translated window", {})


class CompactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "journal.sqlite3"
        self.j = Journal(self.path)
        self.client = Client()

    def tearDown(self):
        self.j.close()
        self.temp.cleanup()

    def fill(self, count):
        ids = []
        for n in range(count):
            ids.append(self.j.capture("Synthetic window %s" % n))
            self.j.process_one(self.client)
        return ids

    def test_threshold_persistence_incremental_summary_and_complete_history(self):
        ids = self.fill(100)
        self.assertEqual(self.client.compactions, [])
        originals = [self.j.entry(i) for i in ids]
        current = self.j.capture("Current window")
        future = self.j.capture("Queued future")
        self.j.process_one(self.client)
        self.assertEqual(len(self.client.compactions), 1)
        compact_input = json.dumps(self.client.compactions[0])
        self.assertIn("Synthetic window 0", compact_input)
        self.assertIn("Synthetic window 99", compact_input)
        self.assertNotIn("Current window", compact_input)
        self.assertNotIn("Queued future", compact_input)
        request = self.client.translations[-1]
        self.assertEqual(len(request), 5)  # prompt, summary rule, boundary, summary, current
        self.assertEqual(request[1]["role"], "developer")
        self.assertIn("permitted", request[1]["content"][0]["text"])
        self.assertEqual(request[-1]["content"][0]["text"], "Current window")
        self.assertNotIn("Synthetic window", json.dumps(request))
        self.assertEqual([self.j.entry(i) for i in ids], originals)
        self.j.close()
        self.j = Journal(self.path)
        self.assertEqual(self.j.messages_for(current), request)
        self.j.process_one(self.client)
        self.assertEqual(len(self.client.compactions), 1)
        self.assertEqual(self.j.entry(future)["state"], "completed")
        self.fill(99)
        self.assertEqual(len(self.client.compactions), 2)
        second = json.dumps(self.client.compactions[1])
        self.assertIn("Names and unresolved references retained.", second)
        self.assertNotIn("Synthetic window 99", second)

    def test_summary_failure_pauses_and_retry_preserves_pending_fifo(self):
        self.fill(100)
        head = self.j.capture("Head")
        tail = self.j.capture("Tail")
        self.client.fail_compact = True
        with self.assertRaises(TranslationError):
            self.j.process_one(self.client)
        self.assertEqual(self.j.entry(head)["state"], "failed")
        self.assertEqual(self.j.entry(tail)["state"], "pending")
        self.assertEqual(len(self.client.translations), 100)
        with self.assertRaises(TranslationError):
            self.j.process_one(self.client)
        self.assertEqual(len(self.client.compactions), 1)
        self.client.fail_compact = False
        self.assertTrue(self.j.retry())
        self.assertEqual(self.j.process_one(self.client)["id"], head)

    def test_committed_summary_is_reused_after_translation_failure(self):
        self.fill(100)
        self.j.capture("Head")
        self.client.fail_translate = True
        with self.assertRaises(TranslationError):
            self.j.process_one(self.client)
        self.j.close()
        self.j = Journal(self.path)
        self.client.fail_translate = False
        self.assertTrue(self.j.retry())
        self.j.process_one(self.client)
        self.assertEqual(len(self.client.compactions), 1)

    def test_new_run_never_summarizes_archived_dialogue_into_current_run(self):
        self.fill(101)
        self.j.new_run()
        self.fill(101)
        self.assertEqual(len(self.client.compactions), 2)
        current_summary_input = json.dumps(self.client.compactions[-1])
        self.assertIn("BEGIN CURRENT RUN 2", current_summary_input)
        self.assertNotIn("BEGIN CURRENT RUN 1", current_summary_input)
        self.assertNotIn("REFERENCE SUMMARY FOR RUN 1", current_summary_input)
        messages = self.client.translations[-1]
        boundary = next(i for i, m in enumerate(messages)
                        if "BEGIN CURRENT RUN 2" in json.dumps(m))
        self.assertIn("REFERENCE SUMMARY FOR RUN 1", json.dumps(messages[:boundary]))
        self.assertNotIn("RUN 1", json.dumps(messages[boundary:]))

    def test_exact_threshold_before_new_run_still_compacts_archived_block(self):
        self.fill(100)
        self.j.new_run()
        self.j.capture("First new run window")
        self.j.process_one(self.client)
        self.assertEqual(len(self.client.compactions), 1)
        self.assertIn("BEGIN CURRENT RUN 1", json.dumps(self.client.compactions[0]))
        self.assertNotIn("First new run window", json.dumps(self.client.compactions[0]))
        self.assertNotIn("Synthetic window", json.dumps(self.client.translations[-1]))


if __name__ == "__main__":
    unittest.main()
