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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Self, cast

from . import engine
from .engine import TranslationError
from .prompt import CONTEXT_FORMAT
from .transport_response import (
    JsonObject as JsonObject,
)
from .transport_response import (
    TranslationResult as TranslationResult,
)
from .transport_response import (
    estimate_cost as estimate_cost,
)
from .transport_response import (
    parse_response as parse_response,
)
from .transport_response import (
    usage_counters as usage_counters,
)

type Messages = Sequence[Mapping[str, object]]
type ActiveCheck = Callable[[], bool]
type EgressCallback = Callable[[JsonObject], None]

# The untyped journal and transport share the integration's cancellation marker.
_Inactive = cast(type[Exception], vars(engine)["_Inactive"])
_check_active = cast(Callable[[ActiveCheck | None], None], vars(engine)["_check_active"])

ALLOWED_MODELS = ("gpt-6-astra", "gpt-5.6-terra", "gpt-6.1-sol", "gpt-6.2-sol")
COMPACTION_MODEL = "gpt-6-luna"
# Deliberately conservative subset of the official supported-country list.
SUPPORTED_COUNTRIES = frozenset(("PL", "DE", "NL", "FI", "US", "GB", "UA"))


@dataclass(frozen=True)
class ClientConfig:
    key_file: str
    proxy_host: str
    proxy_port: int
    expected_country: str
    model: str | None = None
    reasoning_effort: str = "low"
    proxy_username: str | None = field(default=None, repr=False)
    proxy_password: str | None = field(default=None, repr=False)
    timeout: float = 120
    max_output_tokens: int = 4096
    geo_host: str = "ipapi.co"
    expected_region: str | None = None
    key_field: str | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> Self:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            return cls.from_mapping(data)
        except Exception:
            raise TranslationError(
                "configuration", "Invalid external translation configuration."
            ) from None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        try:
            proxy: JsonObject = data["proxy"]
            config = cls(
                key_file=data["key_file"],
                proxy_host=proxy["host"],
                proxy_port=proxy["port"],
                expected_country=data["expected_country"],
                model=data.get("model"),
                reasoning_effort=data.get("reasoning_effort", "low"),
                proxy_username=proxy.get("username"),
                proxy_password=proxy.get("password"),
                timeout=data.get("timeout", 120),
                max_output_tokens=data.get("max_output_tokens", 4096),
                geo_host=data.get("geo_host", "ipapi.co"),
                expected_region=data.get("expected_region"),
                key_field=data.get("key_field"),
            )
            config.validate()
            return config
        except Exception:
            raise TranslationError(
                "configuration", "Invalid external translation configuration."
            ) from None

    def validate(self, compaction: bool = False) -> None:
        if self.model not in ALLOWED_MODELS and not (compaction and self.model == COMPACTION_MODEL):
            raise TranslationError(
                "configuration", "Choose a supported translation model before translating."
            )
        if self.reasoning_effort not in ("low", "medium", "high"):
            raise TranslationError("configuration", "Reasoning effort must be low, medium or high.")
        if (
            not isinstance(cast(object, self.proxy_host), str)
            or not self.proxy_host
            or any(c in self.proxy_host for c in "\r\n/ @")
            or not isinstance(cast(object, self.proxy_port), int)
            or isinstance(self.proxy_port, bool)
            or not 1 <= self.proxy_port <= 65535
        ):
            raise TranslationError(
                "configuration", "An explicit HTTP proxy host and port are required."
            )
        if self.expected_country not in SUPPORTED_COUNTRIES:
            raise TranslationError(
                "configuration", "Configure an allowed non-Russian egress country."
            )
        # Ukraine has regional exceptions. This deployment permits only the
        # explicitly observed Odessa region, and refuses missing region data.
        if self.expected_country == "UA" and self.expected_region != "Odessa":
            raise TranslationError(
                "configuration", "Ukrainian egress requires the verified Odessa region."
            )
        if self.geo_host not in ("ipapi.co", "ipinfo.io", "ifconfig.co"):
            raise TranslationError("configuration", "Configure a vetted HTTPS geo endpoint.")
        if (
            not isinstance(cast(object, self.key_file), str)
            or not Path(self.key_file).is_absolute()
        ):
            raise TranslationError(
                "configuration", "API key file must be an absolute external path."
            )
        if self.key_field is not None and self.key_field not in (
            "OPENAI_API_KEY_WITH_SHARING",
            "OPENAI_API_KEY_WITHOUT_SHARING",
        ):
            raise TranslationError("configuration", "Select an explicit OpenAI credential field.")
        if (
            not isinstance(cast(object, self.timeout), (float, int))
            or isinstance(self.timeout, bool)
            or not 1 <= self.timeout <= 600
            or not isinstance(cast(object, self.max_output_tokens), int)
            or isinstance(self.max_output_tokens, bool)
            or self.max_output_tokens < 1
        ):
            raise TranslationError("configuration")
        if (self.proxy_username is None) != (self.proxy_password is None):
            raise TranslationError(
                "configuration", "Both proxy credential fields must be supplied together."
            )
        if self.proxy_username is not None and (
            not all(
                isinstance(value, str)
                for value in cast(tuple[object, object], (self.proxy_username, self.proxy_password))
            )
        ):
            raise TranslationError("configuration")


def build_payload(
    messages: Messages, config: ClientConfig, cache_key: str, compaction: bool = False
) -> JsonObject:
    config.validate(compaction=compaction)
    return {
        "model": config.model,
        "reasoning": {"effort": config.reasoning_effort},
        "input": messages,
        "truncation": "disabled",
        "store": False,
        "max_output_tokens": config.max_output_tokens,
        "service_tier": "default",
        "prompt_cache_key": cache_key,
        "prompt_cache_options": {"mode": "implicit"},
    }


class ResponsesClient:
    compact_every = 100

    def __init__(
        self,
        config: ClientConfig,
        on_egress: EgressCallback | None = None,
        should_continue: ActiveCheck | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self._on_egress = on_egress
        self._should_continue = should_continue
        self._egress: JsonObject | None = None
        self._mutex = threading.Lock()
        self._context = ssl.create_default_context()

    def _connection(self, target: str, timeout: float | None = None) -> http.client.HTTPSConnection:
        if target not in ("api.openai.com", "ipapi.co", "ipinfo.io", "ifconfig.co"):
            raise TranslationError("configuration")
        cfg = self.config
        headers: dict[str, str] = {}
        if cfg.proxy_username is not None and cfg.proxy_password is not None:
            token = base64.b64encode(
                (cfg.proxy_username + ":" + cfg.proxy_password).encode("utf-8")
            ).decode("ascii")
            headers["Proxy-Authorization"] = "Basic " + token
        connection = http.client.HTTPSConnection(
            cfg.proxy_host,
            cfg.proxy_port,
            timeout=cfg.timeout if timeout is None else timeout,
            context=self._context,
        )
        # HTTPSConnection connects plaintext to the configured HTTP proxy,
        # performs CONNECT, then wraps the target socket with target SNI/TLS.
        connection.set_tunnel(target, 443, headers=headers)
        return connection

    def _request(
        self,
        target: str,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, JsonObject]:
        connection = self._connection(target, timeout=timeout)
        try:
            if target == "api.openai.com" and method == "POST":
                # HTTPSConnection normally connects lazily in request(); check
                # again after CONNECT/TLS before sending the paid request.
                connection.connect()
                _check_active(self._should_continue)
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
            return response.status, cast(JsonObject, data)
        finally:
            connection.close()

    def _preflight(self) -> JsonObject:
        if self._egress is not None:
            return dict(self._egress)
        try:
            host = self.config.geo_host
            path = "/json/" if host == "ipapi.co" else "/json"
            status, data = self._request(host, "GET", path, headers={"Accept": "application/json"})
            country = data.get(
                {"ipapi.co": "country_code", "ipinfo.io": "country", "ifconfig.co": "country_iso"}[
                    host
                ]
            )
            ip = ipaddress.ip_address(data["ip"])
            region = data.get("region_name", data.get("region"))
            if (
                status != 200
                or country not in SUPPORTED_COUNTRIES
                or country != self.config.expected_country
                or not ip.is_global
                or (country == "UA" and region != self.config.expected_region)
            ):
                raise ValueError("Invalid egress")
            public: JsonObject = {
                "ip": str(ip),
                "country": country,
                "source": "https://" + host + path,
            }
            if country == "UA":
                public["region"] = region
            # No raw city/org field is echoed: only validated public fields.
            if self._on_egress:
                self._on_egress(dict(public))
            self._egress = public
            return dict(public)
        except Exception:
            raise TranslationError(
                "egress_failed", "Proxy egress verification failed; no OpenAI request was sent."
            ) from None

    def preflight(self) -> JsonObject:
        with self._mutex:
            return self._preflight()

    def _read_key(self) -> str:
        try:
            raw = Path(self.config.key_file).read_text(encoding="utf-8-sig")
            key = json.loads(raw)[self.config.key_field] if self.config.key_field else raw.strip()
            if not isinstance(key, str) or not key or any(c.isspace() for c in key):
                raise ValueError("Invalid credential")
            return key
        except Exception:
            raise TranslationError(
                "configuration", "Selected API credential is unavailable."
            ) from None

    def translate(
        self,
        messages: Messages,
        cache_key: str,
        *,
        response_format: Mapping[str, object] | None = None,
        service_tier: str = "default",
    ) -> TranslationResult:
        return self._respond(
            messages,
            cache_key,
            self.config,
            response_format=response_format,
            service_tier=service_tier,
        )

    def compact(self, messages: Messages, cache_key: str) -> TranslationResult:
        config = replace(
            self.config,
            model=COMPACTION_MODEL,
            reasoning_effort="high",
            max_output_tokens=32768,
            timeout=max(self.config.timeout, 300),
        )
        return self._respond(
            messages,
            cache_key + "-context-v2",
            config,
            response_format=CONTEXT_FORMAT,
            service_tier="fast",
            compaction=True,
        )

    def _respond(
        self,
        messages: Messages,
        cache_key: str,
        config: ClientConfig,
        *,
        response_format: Mapping[str, object] | None = None,
        service_tier: str = "default",
        compaction: bool = False,
    ) -> TranslationResult:
        with self._mutex:
            self._preflight()
            _check_active(self._should_continue)
            started = time.monotonic()
            try:
                key = self._read_key()
                payload = build_payload(messages, config, cache_key, compaction=compaction)
                if response_format is not None:
                    payload["text"] = {"format": response_format}
                payload["service_tier"] = service_tier
                body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
                _check_active(self._should_continue)
                status, data = self._request(
                    "api.openai.com",
                    "POST",
                    "/v1/responses",
                    body,
                    {
                        "Content-Type": "application/json",
                        "Authorization": "Bearer " + key,
                        "Accept": "application/json",
                    },
                    timeout=config.timeout,
                )
                if status != 200:
                    error = data.get("error")
                    code = cast(JsonObject, error).get("code") if isinstance(error, dict) else None
                    if code in ("context_length_exceeded", "context_window_exceeded"):
                        raise TranslationError("context_overflow")
                    raise TranslationError("request_failed")
                return parse_response(
                    data,
                    cast(str, config.model),
                    time.monotonic() - started,
                    requested_service_tier=service_tier,
                )
            except (TranslationError, _Inactive):
                raise
            except Exception:
                # Do not surface OS paths, raw headers, reflected API errors or
                # proxy credentials from ssl/http/client exceptions.
                raise TranslationError("request_failed") from None
