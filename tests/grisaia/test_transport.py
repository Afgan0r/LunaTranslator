"""Fail-closed transport/parser/cost behavior with no external network calls."""

import dataclasses
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "LunaTranslator"))
from translator.grisaia import (ClientConfig, ResponsesClient, TranslationError,
    build_payload, estimate_cost, parse_response, usage_counters)


def completed(text="Привет"):
    return {"id": "resp_test", "status": "completed", "model": "gpt-6-astra",
            "service_tier": "default", "output": [{"type": "message", "role": "assistant",
            "status": "completed", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 100, "input_tokens_details": {"cached_tokens": 60, "cache_write_tokens": 20},
                      "output_tokens": 10, "output_tokens_details": {"reasoning_tokens": 4}}}


class ScriptedClient(ResponsesClient):
    def __init__(self, config, replies):
        super().__init__(config)
        self.replies = list(replies)
        self.calls = []

    def _request(self, host, method, path, body=None, headers=None):
        self.calls.append((host, method, path, body))
        result = self.replies.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.key = Path(self.temp.name) / "synthetic-key.txt"
        self.key.write_text("synthetic-unit-test-key", encoding="utf-8")
        self.config = ClientConfig(str(self.key), "127.0.0.1", 8118, "PL", "gpt-6-astra")
        self.geo = (200, {"ip": "8.8.8.8", "country_code": "PL"})

    def tearDown(self):
        self.temp.cleanup()

    def test_success_requires_geo_first_then_sends_complete_input(self):
        messages = [{"role": "developer", "content": "Rules"}, {"role": "user", "content": "Hello"}]
        client = ScriptedClient(self.config, [self.geo, (200, completed()), (200, completed())])
        result = client.translate(messages, "stable-key")
        client.translate(messages, "stable-key")
        self.assertEqual([c[0] for c in client.calls], ["ipapi.co", "api.openai.com", "api.openai.com"])
        payload = json.loads(client.calls[1][3])
        self.assertEqual(payload["input"], messages)
        self.assertEqual(payload["truncation"], "disabled")
        self.assertFalse(payload["store"])
        self.assertNotIn("tools", payload)
        self.assertEqual(payload["prompt_cache_options"], {"mode": "implicit"})
        self.assertEqual(payload["service_tier"], "default")
        self.assertEqual(result.text, "Привет")
        self.assertEqual(result.metadata["usage"]["cached_tokens"], 60)
        self.assertEqual(client.preflight()["source"], "https://ipapi.co/json/")

    def test_each_new_client_requires_fresh_egress_gate(self):
        for _ in range(2):
            client = ScriptedClient(self.config, [self.geo, (200, completed())])
            client.translate([], "key")
            self.assertEqual(client.calls[0][0], "ipapi.co")

    def test_failed_russian_or_disagreeing_geo_never_calls_openai(self):
        for reply in (OSError("proxy password reflected"),
                      (503, {}), (200, {"ip": "8.8.8.8", "country_code": "RU"}),
                      (200, {"ip": "8.8.8.8", "country_code": "US"}),
                      (200, {"ip": "127.0.0.1", "country_code": "PL"})):
            client = ScriptedClient(self.config, [reply])
            with self.assertRaises(TranslationError) as failure:
                client.translate([], "key")
            self.assertEqual(failure.exception.code, "egress_failed")
            self.assertNotIn("password", str(failure.exception))
            self.assertEqual(len(client.calls), 1)

    def test_context_error_redacts_reflected_key_and_has_no_retry(self):
        client = ScriptedClient(self.config, [self.geo, (400, {"error": {"code": "context_length_exceeded", "message": "synthetic-unit-test-key"}})])
        with self.assertRaises(TranslationError) as failure:
            client.translate([], "key")
        self.assertEqual(failure.exception.code, "context_overflow")
        self.assertNotIn("synthetic", str(failure.exception))
        self.assertEqual(len(client.calls), 2)

    def test_ukrainian_route_requires_explicit_verified_region(self):
        config = dataclasses.replace(self.config, expected_country="UA", expected_region="Odessa", geo_host="ifconfig.co")
        for region in (None, "Crimea", "Odessa"):
            geo = (200, {"ip": "8.8.8.8", "country_iso": "UA", "region_name": region})
            client = ScriptedClient(config, [geo, (200, completed())])
            if region == "Odessa":
                self.assertEqual(client.translate([], "key").text, "Привет")
            else:
                with self.assertRaises(TranslationError):
                    client.translate([], "key")
                self.assertEqual(len(client.calls), 1)
        with self.assertRaises(TranslationError):
            ResponsesClient(dataclasses.replace(config, expected_region=None))

    def test_connection_target_stays_proxy_when_no_proxy_star(self):
        # Inspect a real stdlib connection before I/O: its TCP host is always
        # the proxy, while TLS/CONNECT destination is the fixed target.
        with patch.dict(os.environ, {"NO_PROXY": "*", "HTTPS_PROXY": "http://evil.invalid:9"}):
            client = ResponsesClient(self.config)
            for host in ("api.openai.com", "ipapi.co"):
                connection = client._connection(host)
                self.assertEqual((connection.host, connection.port), ("127.0.0.1", 8118))
                self.assertEqual((connection._tunnel_host, connection._tunnel_port), (host, 443))
                self.assertTrue(connection._context.check_hostname)
                self.assertEqual(connection._context.verify_mode, 2)
                connection.close()
            with self.assertRaises(TranslationError):
                client._connection("unexpected.invalid")

    def test_missing_model_rejected_before_egress_or_key_read(self):
        with self.assertRaises(TranslationError):
            ResponsesClient(dataclasses.replace(self.config, model=None))
        for replacement in ({"proxy_host": ""}, {"proxy_port": 0}, {"expected_country": "RU"}, {"geo_host": "evil.invalid"}):
            with self.assertRaises(TranslationError):
                ResponsesClient(dataclasses.replace(self.config, **replacement))

    def test_incomplete_refusal_empty_and_tool_output_rejected(self):
        cases = []
        response = completed()
        response["status"] = "incomplete"
        cases.append((response, "incomplete"))
        response = completed()
        response["output"][0]["content"] = [{"type": "refusal", "refusal": "private explanation"}]
        cases.append((response, "refusal"))
        cases.append((completed(" "), "empty_output"))
        response = completed()
        response["output"].append({"type": "function_call", "name": "unexpected"})
        cases.append((response, "invalid_response"))
        for response, code in cases:
            with self.assertRaises(TranslationError) as failure:
                parse_response(response, self.config.model, 1)
            self.assertEqual(failure.exception.code, code)

    def test_cost_has_all_counters_and_long_context_threshold(self):
        usage = usage_counters(completed())
        self.assertEqual(usage["reasoning_tokens"], 4)
        self.assertAlmostEqual(estimate_cost("gpt-6-astra", usage)["usd"], .00101)
        self.assertFalse(estimate_cost("gpt-6-astra", usage)["provisional"])
        missing = usage_counters({})
        self.assertEqual(set(missing), {"input_tokens", "cached_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens"})
        self.assertTrue(estimate_cost("gpt-5.6-terra", missing)["provisional"])
        usage.update(input_tokens=272000, cached_tokens=0, cache_write_tokens=0, output_tokens=0)
        self.assertFalse(estimate_cost("gpt-6-astra", usage)["long_context"])
        usage["input_tokens"] += 1
        self.assertAlmostEqual(estimate_cost("gpt-6-astra", usage)["usd"], 5.44002)


if __name__ == "__main__":
    unittest.main()
