"""Failure and recovery boundaries using synthetic data and no network."""
import dataclasses
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "LunaTranslator"))
from integrations.engine import Journal, TranslationError
from integrations.prompt import merge_context
from integrations.transport import ClientConfig, ResponsesClient, TranslationResult, estimate_cost, parse_response


class CoreEdges(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = ClientConfig(str(self.home / "key"), "127.0.0.1", 1234, "PL", "gpt-6.1-sol")

    def test_invalid_settings_fail_before_use(self):
        variations = [dict(reasoning_effort="invalid"), dict(key_file="relative"),
                      dict(key_field="OTHER"), dict(timeout=0), dict(max_output_tokens=0),
                      dict(proxy_username="user"), dict(proxy_username=1, proxy_password="pw")]
        for changes in variations:
            with self.subTest(changes=changes), self.assertRaises(TranslationError):
                dataclasses.replace(self.config, **changes).validate()
        data = {"key_file": self.config.key_file, "proxy": {"host": "127.0.0.1", "port": 1234},
                "expected_country": "PL", "model": "gpt-6.1-sol"}
        path = self.home / "config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(ClientConfig.from_file(path), ClientConfig.from_mapping(data))

    def test_proxy_request_bounds_json_and_always_closes(self):
        class Connection:
            def __init__(self, raw):
                self.raw, self.closed = raw, False
            def request(self, *args, **kwargs):
                pass
            def getresponse(self):
                return self
            status = 200
            def read(self, size):
                return self.raw
            def close(self):
                self.closed = True
        client = ResponsesClient(self.config)
        for raw in (b"x" * (8 * 1024 * 1024 + 1), b"not-json", b"[]"):
            connection = Connection(raw)
            with self.subTest(size=len(raw)), patch.object(client, "_connection", return_value=connection):
                with self.assertRaises(TranslationError) as error:
                    client._request("ipapi.co", "GET", "/json/")
                self.assertEqual(error.exception.code, "invalid_response")
                self.assertTrue(connection.closed)
        connection = Connection(b'{"ok": true}')
        with patch.object(client, "_connection", return_value=connection):
            self.assertEqual(client._request("ipapi.co", "GET", "/json/"), (200, {"ok": True}))
            self.assertTrue(connection.closed)

    def test_invalid_protocol_responses_fail_closed(self):
        cases = [([None], "invalid_response"),
                 ([{"type": "message", "role": "user", "status": "completed"}], "incomplete"),
                 ([{"type": "message", "role": "assistant", "content": [None]}], "invalid_response"),
                 ([{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": 1}]}], "invalid_response")]
        for output, code in cases:
            with self.subTest(output=output), self.assertRaises(TranslationError) as error:
                parse_response({"status": "completed", "output": output}, "gpt-6.1-sol", 0)
            self.assertEqual(error.exception.code, code)
        with self.assertRaises(ValueError):
            estimate_cost("unknown", {})
        self.assertTrue(estimate_cost("gpt-6.1-sol", {}, "unknown")["provisional"])
        with self.assertRaises(ValueError):
            merge_context({}, json.dumps({"reference_updates": 4, "events": "event"}))
        with self.assertRaises(ValueError):
            merge_context({}, json.dumps({"reference_updates": {}, "events": " "}))
        response = {"status": "completed", "output": [
            {"type": "reasoning"}, {"type": "message", "role": "assistant",
             "content": [{"type": "other"}, {"type": "output_text", "text": "text"}]}]}
        self.assertEqual(parse_response(response, "gpt-6.1-sol", 0).text, "text")

    def test_proxy_credentials_and_egress_notification(self):
        config = dataclasses.replace(self.config, proxy_username="synthetic", proxy_password="secret")
        client = ResponsesClient(config)
        with patch("integrations.transport.http.client.HTTPSConnection") as connection:
            client._connection("api.openai.com")
            headers = connection.return_value.set_tunnel.call_args.kwargs["headers"]
            self.assertEqual(headers["Proxy-Authorization"], "Basic c3ludGhldGljOnNlY3JldA==")
        notifications = []
        client = ResponsesClient(config, on_egress=notifications.append)
        with patch.object(client, "_request", return_value=(200, {"ip": "8.8.8.8", "country_code": "PL"})):
            self.assertEqual(client.preflight()["country"], "PL")
        self.assertEqual(notifications[0]["country"], "PL")

    def test_remote_and_transport_failures_do_not_expose_private_data(self):
        key = Path(self.config.key_file)
        key.write_text("synthetic-key", encoding="utf-8")
        for outcome in ((500, {"error": {"message": "private-server-data"}}),
                        OSError("private-connection-data")):
            client = ResponsesClient(self.config)
            def request(host, *args, **kwargs):
                if host == "ipapi.co":
                    return 200, {"ip": "8.8.8.8", "country_code": "PL"}
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
            with patch.object(client, "_request", side_effect=request), self.assertRaises(TranslationError) as error:
                client.translate([], "synthetic-cache")
            self.assertEqual(error.exception.code, "request_failed")
            self.assertNotIn("private", str(error.exception))

    def test_switch_during_tls_connect_sends_no_paid_request(self):
        active = [True]
        events = []
        Path(self.config.key_file).write_text("synthetic-key", encoding="utf-8")

        class Connection:
            status = 200
            def __init__(self, target):
                self.target = target
            def connect(self):
                events.append("tls-connected")
                active[0] = False
            def request(self, method, path, **kwargs):
                events.append((self.target, method))
            def getresponse(self):
                return self
            def read(self, size):
                return b'{"ip":"8.8.8.8","country_code":"PL"}'
            def close(self):
                events.append((self.target, "closed"))

        client = ResponsesClient(self.config, should_continue=lambda: active[0])
        with Journal(self.home / "journal.sqlite3") as journal:
            head = journal.capture("synthetic")
            with patch.object(client, "_connection", side_effect=lambda target, **kwargs: Connection(target)):
                self.assertIsNone(journal.process_one(client, lambda: active[0]))
            self.assertEqual(journal.entry(head)["state"], "pending")
        self.assertIn("tls-connected", events)
        self.assertNotIn(("api.openai.com", "POST"), events)
        self.assertIn(("api.openai.com", "closed"), events)

    def test_journal_guards_and_empty_rebuild_preserve_state(self):
        path = self.home / "journal.sqlite3"
        with Journal(path, prompt="fixed") as journal:
            for value in ("", "  ", None):
                with self.assertRaises(ValueError):
                    journal.capture(value)
            with self.assertRaises(ValueError):
                journal.new_run(None)
            with self.assertRaises(KeyError):
                journal.entry(999)
            with self.assertRaises(ValueError):
                journal.messages_for(1)
            self.assertIsNone(journal.rebuild_context(object()))
            self.assertEqual(journal.status()["context_rebuild_state"], "completed")
            head = journal.capture("synthetic")
            with self.assertRaises(TranslationError):
                journal.rebuild_context(object())
            self.assertEqual(journal.entry(head)["state"], "pending")
        with self.assertRaises(ValueError):
            Journal(path, prompt="changed")
        with Journal(path, prompt="fixed") as journal:
            self.assertEqual(journal.entry(head)["original"], "synthetic")

    def test_empty_output_pauses_until_explicit_retry(self):
        class Client:
            def translate(self, messages, key):
                return TranslationResult(" ", {})
        with Journal(self.home / "journal.sqlite3") as journal:
            head = journal.capture("synthetic")
            with self.assertRaises(TranslationError) as error:
                journal.process_one(Client())
            self.assertEqual(error.exception.code, "empty_output")
            self.assertEqual(journal.entry(head)["state"], "failed")
            self.assertTrue(journal.retry())
            self.assertEqual(journal.entry(head)["state"], "pending")
