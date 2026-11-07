"""Synthetic checkpoints exercise actual SQLite history and FIFO recovery."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "LunaTranslator"))
from translator.grisaia import Journal, TranslationError, TranslationResult
from translator.grisaia.prompt import merge_context


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
        return TranslationResult(json.dumps({"reference_updates": {
            "character": "Names and unresolved references retained."},
            "events": "Events of the current run."}), {"model": "gpt-6.1-sol"})

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
        self.assertEqual(len(request), 45)  # context plus 20 recent original/translation pairs
        self.assertEqual(request[1]["role"], "developer")
        self.assertIn("permitted", request[1]["content"][0]["text"])
        self.assertEqual(request[-1]["content"][0]["text"], "Current window")
        self.assertNotIn('Synthetic window 0"', json.dumps(request))
        self.assertIn("Synthetic window 99", json.dumps(request))
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
        self.assertNotIn('Synthetic window 0"', json.dumps(self.client.translations[-1]))

    def test_reference_notes_survive_omission_and_corrections_are_appended(self):
        previous = {"reference": {"person": ["Identity unknown"], "term": ["Russian form"]},
                    "events": "Old events"}
        merged = json.loads(merge_context(previous, json.dumps({
            "reference_updates": {"person": "Identity revealed: Mira"}, "events": "Later events"})))
        self.assertEqual(merged["reference"]["term"], ["Russian form"])
        self.assertEqual(merged["reference"]["person"], ["Identity unknown", "Identity revealed: Mira"])
        self.assertEqual(merged["events"], "Later events")
        repeated = json.loads(merge_context(merged, json.dumps({
            "reference_updates": {"person": "Identity revealed: Mira"}, "events": "Latest"})))
        self.assertEqual(repeated["reference"], merged["reference"])
        self.assertEqual(previous["reference"]["person"], ["Identity unknown"])

    def test_multiple_notes_per_subject_and_strict_array_format(self):
        previous = {"reference": {"person": ["Earlier fact"]}, "events": "Earlier events"}
        for updates in ({"person": ["New fact", "Correction", "Earlier fact"]},
                        [{"subject": "person", "notes": ["New fact", "Correction", "Earlier fact"]}]):
            with self.subTest(updates=updates):
                result = json.loads(merge_context(previous, json.dumps({
                    "reference_updates": updates, "events": "Later events"})))
                self.assertEqual(result["reference"]["person"],
                                 ["Earlier fact", "New fact", "Correction"])
        self.assertEqual(previous["reference"]["person"], ["Earlier fact"])

    def test_incremental_list_response_commits_then_translates_fifo_head(self):
        self.fill(200)
        original = self.client.compact
        def list_response(messages, key):
            original(messages, key)
            return TranslationResult(json.dumps({"reference_updates": {
                "character": ["First additional fact", "Second additional fact"]},
                "events": "Updated events"}), {})
        self.client.compact = list_response
        head = self.j.capture("Current after second compact")
        self.assertEqual(self.j.process_one(self.client)["id"], head)
        self.assertFalse(self.j.status()["paused"])
        saved = json.loads(self.j._db.execute(
            "SELECT text FROM context_checkpoints ORDER BY id DESC LIMIT 1").fetchone()[0])
        self.assertEqual(saved["reference"]["character"], [
            "Names and unresolved references retained.",
            "First additional fact", "Second additional fact"])

    def test_malformed_notes_still_rejected_without_mutating_reference(self):
        previous = {"reference": {"person": ["Earlier fact"]}, "events": "Earlier events"}
        for updates in ({"person": ["Good", None]}, {"person": {"nested": "bad"}}, {"person": []},
                        [{"subject": "person", "notes": [3]}], ["bad"],
                        [{"subject": "person", "notes": "scalar only allowed in legacy map"}],
                        [{"subject": "person", "notes": [], "extra": "bad"}]):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                merge_context(previous, json.dumps({"reference_updates": updates, "events": "Later"}))
        self.assertEqual(previous["reference"]["person"], ["Earlier fact"])

    def test_rebuild_uses_full_originals_without_previous_summary_and_preserves_versions(self):
        ids = self.fill(103)
        before = [self.j.entry(i) for i in ids]
        result = self.j.rebuild_context(self.client)
        self.assertEqual(result["source_windows"], 103)
        request = json.dumps(self.client.compactions[-1])
        self.assertIn("Synthetic window 0", request)
        self.assertIn("Synthetic window 102", request)
        self.assertNotIn("Names and unresolved references retained.", request)
        self.assertEqual([self.j.entry(i) for i in ids], before)
        self.assertEqual(self.j._db.execute("SELECT count(*) FROM context_checkpoints").fetchone()[0], 2)
        self.j.capture("Next")
        self.j.process_one(self.client)
        self.assertEqual(len(self.client.compactions), 2)

    def test_invalid_json_does_not_commit_and_rebuild_needs_explicit_retry(self):
        self.fill(2)
        original = self.client.compact
        self.client.compact = lambda *args: TranslationResult('{"events":"missing reference_updates"}', {})
        with self.assertRaises(TranslationError):
            self.j.rebuild_context(self.client)
        self.assertEqual(self.j._db.execute("SELECT count(*) FROM context_checkpoints").fetchone()[0], 0)
        self.assertTrue(self.j.status()["paused"])
        with self.assertRaises(TranslationError) as blocked:
            self.j.process_one(self.client)
        self.assertEqual(blocked.exception.code, "context_rebuild")
        self.client.compact = original
        with self.assertRaises(TranslationError) as caught:
            self.j.rebuild_context(self.client)
        self.assertEqual(caught.exception.code, "uncertain")
        pending = self.j.capture("Queued during failed rebuild")
        result = self.j.rebuild_context(self.client, retry=True)
        self.assertEqual(result["source_windows"], 2)
        self.assertNotIn("Queued during failed rebuild", json.dumps(self.client.compactions[-1]))
        self.assertEqual(self.j.entry(pending)["state"], "pending")
        self.assertEqual(self.j.process_one(self.client)["id"], pending)
        self.assertEqual(len(self.client.compactions), 1)

    def test_legacy_summary_is_preserved_but_upgrade_reads_original_pairs(self):
        self.client.compact_every = 0
        ids = self.fill(100)
        self.j._db.execute("INSERT INTO summaries VALUES(1,?,'Legacy lossy summary','{}',1)", (ids[-1],))
        self.j.close()
        self.j = Journal(self.path)
        self.client.compact_every = 100
        self.j.capture("Next")
        self.j.process_one(self.client)
        request = json.dumps(self.client.compactions[0])
        self.assertIn("Synthetic window 0", request)
        self.assertNotIn("Legacy lossy summary", request)
        self.assertEqual(self.j._db.execute("SELECT text FROM summaries").fetchone()[0], "Legacy lossy summary")

    def test_rebuild_checkpoint_and_success_state_commit_together(self):
        self.fill(2)
        original = self.j._set_meta
        def fail_commit(key, value):
            if key == "context_rebuild_state" and value == "completed":
                raise OSError("Synthetic failed commit")
            original(key, value)
        with patch.object(self.j, "_set_meta", side_effect=fail_commit):
            with self.assertRaises(TranslationError):
                self.j.rebuild_context(self.client)
        self.assertEqual(self.j._db.execute("SELECT count(*) FROM context_checkpoints").fetchone()[0], 0)
        self.assertEqual(self.j.status()["context_rebuild_state"], "failed")
        self.j.rebuild_context(self.client, retry=True)
        self.assertEqual(self.j.status()["context_rebuild_state"], "completed")
        self.assertEqual(self.j._db.execute("SELECT count(*) FROM context_checkpoints").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
