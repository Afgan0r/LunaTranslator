"""Compare four model settings on identical, bounded, private opening context."""

import argparse
import hashlib
import json
import statistics
import sys
import uuid
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "LunaTranslator"))
from translator.grisaia.engine import TranslationError, _WorkerLock
from translator.grisaia.prompt import DEVELOPER_PROMPT, run_message, text_message
from translator.grisaia.transport import ClientConfig, ResponsesClient
from install_grisaia_patches import save_json

VARIANTS = [(model, effort) for model in ("gpt-6-astra", "gpt-5.6-terra")
            for effort in ("low", "medium")]


def window_text(window):
    speaker = window["speaker"]
    return (speaker + ":\n" if speaker else "") + window["text"]


def common_messages(sample, position):
    windows = sample["prior_context"] + sample["sample"][:position + 1]
    return [text_message("developer", DEVELOPER_PROMPT, breakpoint=True), run_message(1)] + [
        text_message("user", window_text(window)) for window in windows]


def summarize(state):
    summary = []
    for model, effort in VARIANTS:
        rows = [r for r in state["requests"] if r["model"] == model and
                r["effort"] == effort and r["state"] == "completed"]
        usages = [r["metadata"]["usage"] for r in rows]
        def total(name):
            values = [u.get(name) for u in usages]
            return sum(values) if values and all(v is not None for v in values) else None
        summary.append({"model": model, "effort": effort, "completed": len(rows),
                        "median_seconds": statistics.median([r["metadata"]["latency_seconds"] for r in rows]) if rows else None,
                        "input_tokens": total("input_tokens"), "cached_tokens": total("cached_tokens"),
                        "output_tokens": total("output_tokens"), "reasoning_tokens": total("reasoning_tokens"),
                        "cache_write_tokens": total("cache_write_tokens"),
                        "estimated_usd": sum(r["metadata"]["cost_estimate"]["usd"] for r in rows),
                        "cost_provisional": any(r["metadata"]["cost_estimate"]["provisional"] for r in rows)})
    return summary


def write_report(home, sample, state):
    inputs = [r["metadata"]["usage"]["input_tokens"] for r in state["requests"]
              if r["state"] == "completed"]
    lines = ["Grisaia opening translation comparison", "",
             "15 consecutive windows; identical instructions and preceding original context.",
             "Candidate translations are excluded from context to keep every comparison identical.",
             "Latency is measured end-to-end by the client, excluding its prior egress check.",
             "USD figures are calculated from measured usage at standard API rates; credits/invoice may differ.",
             "Measured input range: %s..%s tokens. Prompt caching starts at 1024 tokens; this sample is below that threshold." % (min(inputs), max(inputs)),
             "Prompt caching: https://developers.openai.com/api/docs/guides/prompt-caching",
             "Sources: https://developers.openai.com/api/docs/models/gpt-6-astra",
             "https://developers.openai.com/api/docs/models/gpt-5.6-terra", "",
             "Model | Effort | Median seconds | Input | Cached | Cache writes | Output | Reasoning | Estimated USD"]
    for row in summarize(state):
        lines.append("%s | %s | %.3f | %s | %s | %s | %s | %s | %.6f" % (
            row["model"], row["effort"], row["median_seconds"], row["input_tokens"],
            row["cached_tokens"], row["cache_write_tokens"], row["output_tokens"],
            row["reasoning_tokens"], row["estimated_usd"]))
    for window in sample["sample"]:
        lines.extend(["", "=" * 72, "Window %s (zero-based)" % window["window_index"],
                      "", "ENGLISH ORIGINAL", window_text(window)])
        for request in state["requests"]:
            if request["window_index"] != window["window_index"]:
                continue
            metadata = request["metadata"]
            usage = metadata["usage"]
            lines.extend(["", "%s / %s | %.3f s | USD %.6f" % (
                request["model"], request["effort"], metadata["latency_seconds"], metadata["cost_estimate"]["usd"]),
                "Tokens: input=%s, cached=%s, cache_write=%s, output=%s, reasoning=%s" % (
                    usage["input_tokens"], usage["cached_tokens"], usage["cache_write_tokens"],
                    usage["output_tokens"], usage["reasoning_tokens"]), request["translation"]])
    (home / "comparison.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--retry", action="store_true", help="Manually retry the failed/uncertain request; it may already have been charged")
    args = parser.parse_args()
    sample_bytes = args.sample.read_bytes()
    sample = json.loads(sample_bytes)
    if not 10 <= len(sample["sample"]) <= 15 or not sample["opening_selector"]["selected_scene_matches"]:
        raise ValueError("Expected 10..15 startup-confirmed consecutive opening windows.")
    windows = sample["prior_context"] + sample["sample"]
    if [w["window_index"] for w in windows] != list(range(len(windows))):
        raise ValueError("The bounded sample must include all preceding context.")
    if args.home.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError("Benchmark data must remain outside Git.")
    args.home.mkdir(parents=True, exist_ok=True)
    path = args.home / "benchmark.json"
    lock = _WorkerLock(str(path) + ".lock")
    try:
        sample_hash = hashlib.sha256(sample_bytes).hexdigest()
        prompt_hash = hashlib.sha256(DEVELOPER_PROMPT.encode("utf-8")).hexdigest()
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
            if state["sample_sha256"] != sample_hash or state["prompt_sha256"] != prompt_hash:
                raise ValueError("Existing benchmark input is immutable. Use a separate private home for a new comparison.")
        else:
            state = {"schema": 1, "sample_sha256": sample_hash, "prompt_sha256": prompt_hash,
                     "context_mode": "identical_prior_original_windows_no_candidate_translations",
                     "cache_key": "grisaia-benchmark-" + uuid.uuid4().hex, "egress_checks": [],
                     "requests": [{"position": p, "window_index": w["window_index"],
                                   "model": m, "effort": e, "state": "pending"}
                                  for p, w in enumerate(sample["sample"]) for m, e in VARIANTS]}
            save_json(path, state)
        head = next((r for r in state["requests"] if r["state"] != "completed"), None)
        if head and head["state"] != "pending":
            if not args.retry:
                print("Benchmark paused. Explicit --retry is required; an interrupted request may have been charged.", flush=True)
                return
            head["state"] = "pending"
            save_json(path, state)
        data = json.loads((args.home / "settings.json").read_text(encoding="utf-8-sig"))
        proxy = data["proxy"]
        base = ClientConfig(key_file=data["key_file"], proxy_host=proxy["host"],
                            proxy_port=proxy["port"], expected_country=data["expected_country"],
                            model="gpt-5.6-terra", geo_host=data.get("geo_host", "ipapi.co"),
                            expected_region=data.get("expected_region"),
                            proxy_username=proxy.get("username"), proxy_password=proxy.get("password"),
                            timeout=data.get("timeout", 120), max_output_tokens=data.get("max_output_tokens", 4096))
        clients = {}
        for request in state["requests"]:
            if request["state"] == "completed":
                continue
            pair = (request["model"], request["effort"])
            if pair not in clients:
                client = ResponsesClient(replace(base, model=pair[0], reasoning_effort=pair[1]))
                # The very same client/transport is used for the subsequent API call.
                egress = client.preflight()
                state["egress_checks"].append({"model": pair[0], "effort": pair[1], **egress})
                save_json(path, state)
                print("Egress verified:", pair[0], pair[1], json.dumps(egress), flush=True)
                clients[pair] = client
            messages = common_messages(sample, request["position"])
            request["messages_sha256"] = hashlib.sha256(json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
            request["state"] = "inflight"
            save_json(path, state)
            try:
                result = clients[pair].translate(messages, state["cache_key"])
            except TranslationError as error:
                request.update(state="failed", error_code=error.code)
                save_json(path, state)
                print("Benchmark stopped:", error.code, str(error), flush=True)
                return
            request.update(state="completed", translation=result.text, metadata=result.metadata)
            state["summary"] = summarize(state)
            save_json(path, state)
            print("Completed:", request["window_index"], *pair,
                  round(result.metadata["latency_seconds"], 3), "seconds", flush=True)
        state["summary"] = summarize(state)
        save_json(path, state)
        write_report(args.home, sample, state)
        print(json.dumps(state["summary"], ensure_ascii=False, indent=2), flush=True)
    finally:
        lock.close()


if __name__ == "__main__":
    main()
