"""Responses API over a mandatory, explicit, certificate-verified CONNECT proxy.

No SDK retries, environment proxy lookup, redirects or direct fallback exist.
Schema: https://developers.openai.com/api/reference/python/resources/responses/methods/create
Caching: https://developers.openai.com/api/docs/guides/prompt-caching
"""

import base64
import http.client
import ipaddress
import json
import ssl
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from .engine import TranslationError

ALLOWED_MODELS = ("gpt-6-astra", "gpt-5.6-terra", "gpt-6.1-sol")
# Deliberately conservative subset of the official supported-country list.
SUPPORTED_COUNTRIES = frozenset(("PL", "DE", "NL", "FI", "US", "GB", "UA"))


@dataclass(frozen=True)
class ClientConfig:
    key_file: str
    proxy_host: str
    proxy_port: int
    expected_country: str
    model: str = None
    reasoning_effort: str = "low"
    proxy_username: str = field(default=None, repr=False)
    proxy_password: str = field(default=None, repr=False)
    timeout: float = 120
    max_output_tokens: int = 4096
    geo_host: str = "ipapi.co"
    expected_region: str = None
    key_field: str = None

    @classmethod
    def from_file(cls, path):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            proxy = data["proxy"]
            config = cls(key_file=data["key_file"], proxy_host=proxy["host"],
                         proxy_port=proxy["port"], expected_country=data["expected_country"],
                         model=data.get("model"), reasoning_effort=data.get("reasoning_effort", "low"),
                         proxy_username=proxy.get("username"), proxy_password=proxy.get("password"),
                         timeout=data.get("timeout", 120), max_output_tokens=data.get("max_output_tokens", 4096),
                         geo_host=data.get("geo_host", "ipapi.co"), expected_region=data.get("expected_region"),
                         key_field=data.get("key_field"))
            config.validate()
            return config
        except Exception:
            raise TranslationError("configuration", "Invalid external translation configuration.") from None

    def validate(self):
        if self.model not in ALLOWED_MODELS:
            raise TranslationError("configuration", "Choose a supported translation model before translating.")
        if self.reasoning_effort not in ("low", "medium", "high"):
            raise TranslationError("configuration", "Reasoning effort must be low, medium or high.")
        if (not isinstance(self.proxy_host, str) or not self.proxy_host or
                any(c in self.proxy_host for c in "\r\n/ @") or
                not isinstance(self.proxy_port, int) or isinstance(self.proxy_port, bool) or
                not 1 <= self.proxy_port <= 65535):
            raise TranslationError("configuration", "An explicit HTTP proxy host and port are required.")
        if self.expected_country not in SUPPORTED_COUNTRIES:
            raise TranslationError("configuration", "Configure an allowed non-Russian egress country.")
        # Ukraine has regional exceptions. This deployment permits only the
        # explicitly observed Odessa region, and refuses missing region data.
        if self.expected_country == "UA" and self.expected_region != "Odessa":
            raise TranslationError("configuration", "Ukrainian egress requires the verified Odessa region.")
        if self.geo_host not in ("ipapi.co", "ipinfo.io", "ifconfig.co"):
            raise TranslationError("configuration", "Configure a vetted HTTPS geo endpoint.")
        if not isinstance(self.key_file, str) or not Path(self.key_file).is_absolute():
            raise TranslationError("configuration", "API key file must be an absolute external path.")
        if self.key_field is not None and self.key_field not in (
                "OPENAI_API_KEY_WITH_SHARING", "OPENAI_API_KEY_WITHOUT_SHARING"):
            raise TranslationError("configuration", "Select an explicit OpenAI credential field.")
        if (not isinstance(self.timeout, (float, int)) or isinstance(self.timeout, bool) or
                not 1 <= self.timeout <= 600 or not isinstance(self.max_output_tokens, int) or
                isinstance(self.max_output_tokens, bool) or self.max_output_tokens < 1):
            raise TranslationError("configuration")
        if (self.proxy_username is None) != (self.proxy_password is None):
            raise TranslationError("configuration", "Both proxy credential fields must be supplied together.")
        if self.proxy_username is not None and (
                not isinstance(self.proxy_username, str) or not isinstance(self.proxy_password, str)):
            raise TranslationError("configuration")


@dataclass(frozen=True)
class TranslationResult:
    text: str
    metadata: dict


def build_payload(messages, config, cache_key):
    config.validate()
    return {"model": config.model, "reasoning": {"effort": config.reasoning_effort},
            "input": messages, "truncation": "disabled", "store": False,
            "max_output_tokens": config.max_output_tokens, "service_tier": "default",
            "prompt_cache_key": cache_key, "prompt_cache_options": {"mode": "implicit"}}


def usage_counters(response):
    usage = response.get("usage") or {}
    inputs = usage.get("input_tokens_details") or {}
    outputs = usage.get("output_tokens_details") or {}
    def count(value):
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    return {"input_tokens": count(usage.get("input_tokens")),
            "cached_tokens": count(inputs.get("cached_tokens")),
            "cache_write_tokens": count(inputs.get("cache_write_tokens")),
            "output_tokens": count(usage.get("output_tokens")),
            "reasoning_tokens": count(outputs.get("reasoning_tokens"))}


def estimate_cost(model, usage):
    """Standard USD estimate, never an invoice or assumption of free credit.

    Cache writes replace the normal input charge for those tokens. Missing
    counters remain explicit; their absence makes the estimate provisional.
    """
    rates = {"gpt-6-astra": (10, 1, 12.5, 50), "gpt-5.6-terra": (2, .2, 2.5, 12),
             "gpt-6.1-sol": (2, .1, 2.5, 10)}
    if model not in rates:
        raise ValueError("Unsupported pricing model.")
    missing = [name for name in ("input_tokens", "cached_tokens", "cache_write_tokens", "output_tokens") if usage.get(name) is None]
    incoming = usage.get("input_tokens") or 0
    cached = usage.get("cached_tokens") or 0
    written = usage.get("cache_write_tokens") or 0
    output = usage.get("output_tokens") or 0
    normal = max(0, incoming - cached - written)
    ir, cr, wr, out = rates[model]
    long_context = incoming > 272000
    if long_context:
        ir, cr, wr, out = ir * 2, cr * 2, wr * 2, out * 1.5
    return {"usd": (normal * ir + cached * cr + written * wr + output * out) / 1e6,
            "provisional": bool(missing), "missing_counters": missing,
            "long_context": long_context, "basis": "standard_price_estimate_not_invoice"}


class ResponsesClient:
    compact_every = 100

    def __init__(self, config, on_egress=None):
        config.validate()
        self.config = config
        self._on_egress = on_egress
        self._egress = None
        self._mutex = threading.Lock()
        self._context = ssl.create_default_context()

    def _connection(self, target):
        if target not in ("api.openai.com", "ipapi.co", "ipinfo.io", "ifconfig.co"):
            raise TranslationError("configuration")
        cfg = self.config
        headers = {}
        if cfg.proxy_username is not None:
            token = base64.b64encode((cfg.proxy_username + ":" + cfg.proxy_password).encode("utf-8")).decode("ascii")
            headers["Proxy-Authorization"] = "Basic " + token
        connection = http.client.HTTPSConnection(cfg.proxy_host, cfg.proxy_port,
                                                timeout=cfg.timeout, context=self._context)
        # HTTPSConnection connects plaintext to the configured HTTP proxy,
        # performs CONNECT, then wraps the target socket with target SNI/TLS.
        connection.set_tunnel(target, 443, headers=headers)
        return connection

    def _request(self, target, method, path, body=None, headers=None):
        connection = self._connection(target)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            # Refuse unbounded error bodies, redirects, and malformed JSON.
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise TranslationError("invalid_response")
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                raise TranslationError("invalid_response") from None
            if not isinstance(data, dict):
                raise TranslationError("invalid_response")
            return response.status, data
        finally:
            connection.close()

    def _preflight(self):
        if self._egress is not None:
            return dict(self._egress)
        try:
            host = self.config.geo_host
            path = "/json/" if host == "ipapi.co" else "/json"
            status, data = self._request(host, "GET", path, headers={"Accept": "application/json"})
            country = data.get({"ipapi.co": "country_code", "ipinfo.io": "country", "ifconfig.co": "country_iso"}[host])
            ip = ipaddress.ip_address(data.get("ip"))
            region = data.get("region_name", data.get("region"))
            if (status != 200 or country not in SUPPORTED_COUNTRIES or
                    country != self.config.expected_country or not ip.is_global or
                    (country == "UA" and region != self.config.expected_region)):
                raise ValueError("Invalid egress")
            public = {"ip": str(ip), "country": country, "source": "https://" + host + path}
            if country == "UA":
                public["region"] = region
            # No raw city/org field is echoed: only validated public fields.
            if self._on_egress:
                self._on_egress(dict(public))
            self._egress = public
            return dict(public)
        except Exception:
            raise TranslationError("egress_failed", "Proxy egress verification failed; no OpenAI request was sent.") from None

    def preflight(self):
        with self._mutex:
            return self._preflight()

    def _read_key(self):
        try:
            raw = Path(self.config.key_file).read_text(encoding="utf-8-sig")
            key = json.loads(raw)[self.config.key_field] if self.config.key_field else raw.strip()
            if not isinstance(key, str) or not key or any(c.isspace() for c in key):
                raise ValueError("Invalid credential")
            return key
        except Exception:
            raise TranslationError("configuration", "Selected API credential is unavailable.") from None

    def translate(self, messages, cache_key):
        return self._respond(messages, cache_key, self.config)

    def compact(self, messages, cache_key):
        config = replace(self.config, model="gpt-6.1-sol", reasoning_effort="high",
                         max_output_tokens=16384)
        return self._respond(messages, cache_key + "-summary", config)

    def _respond(self, messages, cache_key, config):
        with self._mutex:
            self._preflight()
            started = time.monotonic()
            try:
                key = self._read_key()
                body = json.dumps(build_payload(messages, config, cache_key), ensure_ascii=False,
                                  separators=(",", ":")).encode("utf-8")
                status, data = self._request("api.openai.com", "POST", "/v1/responses", body,
                    {"Content-Type": "application/json", "Authorization": "Bearer " + key,
                     "Accept": "application/json"})
                if status != 200:
                    error = data.get("error")
                    code = error.get("code") if isinstance(error, dict) else None
                    if code in ("context_length_exceeded", "context_window_exceeded"):
                        raise TranslationError("context_overflow")
                    raise TranslationError("request_failed")
                return parse_response(data, config.model, time.monotonic() - started)
            except TranslationError:
                raise
            except Exception:
                # Do not surface OS paths, raw headers, reflected API errors or
                # proxy credentials from ssl/http/client exceptions.
                raise TranslationError("request_failed") from None


def parse_response(data, pricing_model, latency_seconds):
    if data.get("status") != "completed":
        raise TranslationError("incomplete")
    texts = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            raise TranslationError("invalid_response")
        if item.get("type") == "message":
            if item.get("role") != "assistant" or item.get("status") not in (None, "completed"):
                raise TranslationError("incomplete")
            for block in item.get("content") or []:
                if not isinstance(block, dict):
                    raise TranslationError("invalid_response")
                if block.get("type") == "refusal":
                    raise TranslationError("refusal")
                if block.get("type") == "output_text":
                    text = block.get("text")
                    if not isinstance(text, str):
                        raise TranslationError("invalid_response")
                    texts.append(text)
        elif item.get("type") != "reasoning":
            # Tools must never enter this translation workflow.
            raise TranslationError("invalid_response")
    text = "".join(texts)
    if not text.strip():
        raise TranslationError("empty_output")
    counters = usage_counters(data)
    # IDs/model/tier are deliberately filtered against the API's restricted
    # identifier alphabet; no untrusted error text is persisted.
    def safe_identifier(value):
        if isinstance(value, str) and 0 < len(value) <= 160 and all(c.isascii() and (c.isalnum() or c in "-_.") for c in value):
            return value
        return None
    metadata = {"usage": counters, "latency_seconds": latency_seconds,
                "response_id": safe_identifier(data.get("id")),
                "model": safe_identifier(data.get("model")),
                "service_tier": safe_identifier(data.get("service_tier")),
                "cost_estimate": estimate_cost(pricing_model, counters)}
    return TranslationResult(text, metadata)
